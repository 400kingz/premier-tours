"""Agent-driven generation via the Higgsfield MCP connector (no API key).

The Higgsfield MCP server is authenticated through the *agent's* session, so it
is reachable from an agent context (a Claude/Hermes run with the connector) —
NOT from a bare headless worker process. This module therefore splits Stage 3
into the two halves that split cleanly along that line:

  • CODE decides WHAT to generate  → `room_jobs()` / `transition_jobs()` emit an
    ordered, idempotent worklist (each item: output path, start frame, optional
    end frame, prompt). Already-generated clips are skipped (cost guardrail).
  • The AGENT generates each item    → upload frame(s) via media_upload, call
    generate_video (Seedance 2.0, roles start_image/end_image), poll job_status,
    download the result to the item's `output` path.
  • CODE ingests the result back     → `ingest_room()` / `ingest_transition()`
    run the same QA gates as the REST path, mark the manifest, and extract the
    room's exit frame so the next transition chains onto it.

Generate ALL rooms first, ingest them, THEN the transitions — a transition's
start frame is the previous room's *exit* frame, which only exists post-ingest.
This is the same frame-chaining contract as stage3_generate.py; only the
`animate` call moves out of process to the MCP tool.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.pipeline import qa
from app.pipeline2.manifest import Manifest
from app.pipeline2.stage3_generate import _extract_last_frame, _qa

# Seedance 2.0 is the only MCP model that takes BOTH start_image and end_image.
# IMPORTANT empirical finding (measured 2026-06-13): Seedance treats start/end as
# *soft reference* images, NOT pinned exact frames — a generated clip's first
# frame only ~0.6 SSIM-matches its start_image. So a naive hard-concat of room
# clips + separate transition clips still shows a visible seam. The way to a
# genuinely seamless tour with a soft-reference model is FEWER, LONGER single
# shots (each covers several rooms in one unbroken take, duration up to 15s),
# joined at as few seams as possible — see `segment_jobs()`.
MCP_MODEL = "seedance_2_0"
MCP_MAX_DURATION = 15


def _clip_dir(work_dir: Path) -> Path:
    d = Path(work_dir) / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _frame_dir(work_dir: Path) -> Path:
    d = Path(work_dir) / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _segment_prompt(room_types: list[str]) -> str:
    """One continuous-flythrough prompt covering several rooms in a single shot."""
    # Collapse consecutive duplicate room types so the path reads naturally.
    seq: list[str] = []
    for rt in room_types:
        label = rt.replace("_", " ")
        if not seq or seq[-1] != label:
            seq.append(label)
    rooms = " then through the ".join(seq)
    return (
        f"One continuous cinematic FPV drone flythrough of a home: glide forward "
        f"through the {rooms}, moving smoothly through doorways without stopping. "
        f"Single unbroken take, steady gimbal, constant slow speed, lateral "
        f"parallax, level stable horizon, no cuts, no people, no text, no "
        f"watermark, photoreal real estate, bright natural clean color grade."
    )


def segment_jobs(
    manifest: Manifest, work_dir: Path, rooms_per_shot: int = 3
) -> list[dict]:
    """PRIMARY MCP strategy — group consecutive rooms into LONG single-shot
    generations so most of the tour is captured with zero concat seams.

    Each segment: start_image = its first room's photo, end_image = its last
    room's photo (so Seedance traverses the whole group in one take), duration
    scaled with the room count up to MCP_MAX_DURATION. The few remaining joins
    are between segments — far fewer than per-room transitions, and each can be
    chained on the previous segment's real exit frame (see `chain_segments`).
    """
    clip_dir = _clip_dir(work_dir)
    clips = sorted(manifest.clips, key=lambda c: c.index)
    jobs: list[dict] = []
    for gi in range(0, len(clips), rooms_per_shot):
        group = clips[gi:gi + rooms_per_shot]
        out = clip_dir / f"segment{gi // rooms_per_shot}.mp4"
        if out.exists():
            continue
        dur = min(MCP_MAX_DURATION, 4 + 3 * (len(group) - 1))  # ~one beat/room
        job = {
            "kind": "segment",
            "segment_index": gi // rooms_per_shot,
            "room_indices": [c.index for c in group],
            "room_types": [c.room_type for c in group],
            "output": str(out),
            "start_frame": group[0].photo,
            "end_frame": group[-1].photo if len(group) > 1 else None,
            "prompt": _segment_prompt([c.room_type for c in group]),
            "duration": dur,
            "model": MCP_MODEL,
        }
        jobs.append(job)
    return jobs


def room_jobs(
    manifest: Manifest, work_dir: Path, only_indices: Optional[list[int]] = None
) -> list[dict]:
    """Worklist of room clips still to generate (idempotent: skips ones on disk)."""
    clip_dir = _clip_dir(work_dir)
    jobs: list[dict] = []
    for c in manifest.clips:
        if only_indices is not None and c.index not in only_indices:
            continue
        out = clip_dir / f"room{c.index}.mp4"
        if out.exists() and c.accepted:
            continue
        jobs.append({
            "kind": "room",
            "index": c.index,
            "room_type": c.room_type,
            "output": str(out),
            "start_frame": c.photo,        # normalized photo == entry frame
            "end_frame": None,
            "prompt": c.prompt,
            "model": MCP_MODEL,
        })
    return jobs


def ingest_room(manifest: Manifest, work_dir: Path, index: int) -> qa.QAResult:
    """QA a downloaded room clip; on pass mark accepted + extract its exit frame."""
    clip = next(c for c in manifest.clips if c.index == index)
    out = _clip_dir(work_dir) / f"room{index}.mp4"
    if not out.exists():
        clip.qa_verdict = "clip not downloaded"
        return qa.QAResult(False, "clip not downloaded")
    prior = [Path(c.generated_clip) for c in manifest.clips
             if c.accepted and c.generated_clip and c.index != index]
    res = _qa(out, Path(clip.photo), prior)
    clip.motion = res.score
    clip.qa_verdict = res.reason
    if res.passed:
        clip.accepted = True
        clip.generated_clip = str(out)
        clip.exit_frame = str(
            _extract_last_frame(out, _frame_dir(work_dir) / f"exit{index}.jpg")
        )
    else:
        out.unlink(missing_ok=True)
    manifest.save(work_dir)
    return res


def transition_jobs(manifest: Manifest, work_dir: Path) -> list[dict]:
    """Worklist of frame-chained transition clips between adjacent accepted rooms.

    Sets each transition's first frame (= room A exit) and last frame (= room B
    entry) so the agent can pass them straight through as start/end images.
    """
    clip_dir = _clip_dir(work_dir)
    jobs: list[dict] = []
    for t in manifest.transitions:
        a = next((c for c in manifest.clips if c.index == t.from_index), None)
        b = next((c for c in manifest.clips if c.index == t.to_index), None)
        if not a or not b or not a.accepted or not b.accepted:
            continue
        out = clip_dir / f"trans{t.from_index}_{t.to_index}.mp4"
        if out.exists() and t.accepted:
            continue
        t.first_frame = a.exit_frame or ""
        t.last_frame = b.entry_frame or b.photo
        jobs.append({
            "kind": "transition",
            "from_index": t.from_index,
            "to_index": t.to_index,
            "output": str(out),
            "start_frame": t.first_frame,
            "end_frame": t.last_frame,
            "prompt": t.prompt,
            "model": MCP_MODEL,
        })
    manifest.save(work_dir)
    return jobs


def ingest_transition(
    manifest: Manifest, work_dir: Path, from_index: int, to_index: int
) -> qa.QAResult:
    """Mechanical QA a downloaded transition clip; mark accepted on pass."""
    t = manifest.transition_between(from_index, to_index)
    out = _clip_dir(work_dir) / f"trans{from_index}_{to_index}.mp4"
    if t is None or not out.exists():
        return qa.QAResult(False, "transition clip not downloaded")
    res = qa.check_clip_mechanical(out)
    if res.passed:
        t.accepted = True
        t.generated_clip = str(out)
    else:
        out.unlink(missing_ok=True)
    manifest.save(work_dir)
    return res
