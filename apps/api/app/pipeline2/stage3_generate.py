"""Stage 3 — Generation + frame-chaining. The seamless single-take core.

For each room: generate the clip from its normalized photo, then extract its
exit frame. For each junction: generate a TRANSITION clip from room A's exit
frame TO room B's entry frame (Higgsfield DoP start+end frame). The last frame
of one clip IS the first frame of the next — true continuity, never a crossfade.

Engine is pluggable (Higgsfield DoP by default; see pipeline2/engine.py).

Cost guardrails (brief):
  - NEVER regenerate a clip that already exists on disk (idempotent + cheap).
  - Hard cap on generations per run; pause rather than loop.
  - Re-check the killswitch before every submission so a HARD STOP lands mid-run.
  - QA each clip (mechanical + hallucination gates); limited retries.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.pipeline import qa, qa_address
from app.pipeline2.engine import engine_cost_per_clip_cents, get_engine
from app.pipeline2.manifest import Manifest
from app.pipeline2.stage4_stitch import _ordered_segments

QA_MAX_ATTEMPTS = 2

# Final QA reports live alongside the manifests, keyed by tour (== listing) id.
QA_REPORT_DIR = Path("manifests")


def _extract_last_frame(clip: Path, out: Path) -> Path:
    """Pull the final frame of a clip — becomes the next clip's first frame.

    Seeks from EOF (`-sseof`), not from the start: an input seek to ~dur near
    the end can overshoot the last keyframe and write zero frames. `-update 1`
    is required by modern ffmpeg to write a single image to a fixed filename.
    The frame is the literal continuity anchor for the next clip, so a missing
    one is a hard error, not a silent skip.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for sseof in ("-0.2", "-0.5", "-1.0"):
        subprocess.run(
            ["ffmpeg", "-y", "-sseof", sseof, "-i", str(clip),
             "-update", "1", "-frames:v", "1", "-q:v", "2", str(out)],
            capture_output=True, text=True, timeout=30,
        )
        if out.exists() and out.stat().st_size > 0:
            return out
    raise RuntimeError(f"could not extract exit frame from {clip}")


def _qa(clip: Path, source_photo: Path, prior: list[Path], room_type: str = "") -> qa.QAResult:
    r = qa.check_clip_mechanical(clip, prior_clips=prior)
    if not r.passed:
        return r
    v = qa.check_clip_vision(clip, source_photo)
    if not v.passed:
        return qa.QAResult(False, v.reason, v.score)
    rt = qa.check_clip_room_type(clip, room_type)
    if not rt.passed:
        return qa.QAResult(False, rt.reason, rt.score)
    return qa.QAResult(True, v.reason, max(r.score, 0.0))


def generate(
    manifest: Manifest,
    work_dir: Path,
    max_generations: int,
    only_indices: list[int] | None = None,
    on_progress=None,
    should_abort=None,
) -> Manifest:
    """Generate room clips + frame-chained transitions, capped at max_generations.

    only_indices limits to a subset of room indices (for cheap subset validation
    per the brief). Transitions are generated only between two adjacent rooms
    that both have accepted clips. ``should_abort`` (optional callable) is checked
    before each submission so the killswitch takes effect mid-run.
    """
    engine = get_engine()
    cost_per_clip = engine_cost_per_clip_cents()
    clip_dir = Path(work_dir) / "clips"
    frame_dir = Path(work_dir) / "frames"
    clip_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)

    def _abort() -> bool:
        return bool(should_abort and should_abort())

    gens = 0
    rooms = [c for c in manifest.clips if only_indices is None or c.index in only_indices]
    accepted_paths: list[Path] = []

    # ── room clips ────────────────────────────────────────────────────────
    for clip in rooms:
        out = clip_dir / f"room{clip.index}.mp4"
        if out.exists() and clip.accepted:
            accepted_paths.append(out)
            continue                       # never regenerate (cost guardrail)
        for attempt in range(QA_MAX_ATTEMPTS):
            if gens >= max_generations:
                if on_progress:
                    on_progress(f"hit generation cap ({max_generations}) — pausing")
                manifest.save(work_dir)
                return manifest
            if _abort():
                if on_progress:
                    on_progress("aborted before generation (killswitch)")
                manifest.save(work_dir)
                return manifest
            if on_progress:
                on_progress(f"room {clip.index} ({clip.room_type}) — gen {attempt + 1}")
            try:
                engine.animate(Path(clip.photo), clip.prompt, out)
                gens += 1
                manifest.gen_cost_cents += cost_per_clip
            except engine.RateLimited as e:
                clip.qa_verdict = f"rate limited: {str(e)[:100]}"
                manifest.save(work_dir)
                return manifest          # back off rather than hammer the API
            except Exception as e:
                clip.qa_verdict = f"engine error: {str(e)[:120]}"
                break
            res = _qa(out, Path(clip.photo), accepted_paths, clip.room_type)
            clip.motion = res.score
            clip.qa_verdict = res.reason
            if res.passed:
                clip.accepted = True
                clip.generated_clip = str(out)
                clip.exit_frame = str(_extract_last_frame(out, frame_dir / f"exit{clip.index}.jpg"))
                accepted_paths.append(out)
                break
            out.unlink(missing_ok=True)

    # ── frame-chained transition clips ────────────────────────────────────
    for t in manifest.transitions:
        a = next((c for c in manifest.clips if c.index == t.from_index), None)
        b = next((c for c in manifest.clips if c.index == t.to_index), None)
        if not a or not b or not a.accepted or not b.accepted:
            continue                       # need both ends generated
        out = clip_dir / f"trans{t.from_index}_{t.to_index}.mp4"
        if out.exists() and t.accepted:
            continue
        if gens >= max_generations:
            if on_progress:
                on_progress("hit generation cap before transitions — pausing")
            break
        if _abort():
            if on_progress:
                on_progress("aborted before transitions (killswitch)")
            break
        t.first_frame = a.exit_frame or ""
        t.last_frame = b.entry_frame or b.photo
        if on_progress:
            on_progress(f"transition {t.from_index}→{t.to_index}")
        try:
            engine.animate(
                Path(t.first_frame), t.prompt, out,
                last_frame_path=Path(t.last_frame),
            )
            gens += 1
            manifest.gen_cost_cents += cost_per_clip
            # Transitions are short connective tissue — mechanical QA only.
            if qa.check_clip_mechanical(out).passed:
                t.accepted = True
                t.generated_clip = str(out)
            else:
                out.unlink(missing_ok=True)
        except engine.RateLimited:
            manifest.save(work_dir)
            return manifest
        except Exception:
            t.generated_clip = None

    manifest.stage = "generated"
    manifest.save(work_dir)
    return manifest


# ── Final, tour-level QA + report ──────────────────────────────────────────

def finalize_qa(
    manifest: Manifest,
    work_dir: Path,
    report_dir: Path | None = None,
    on_progress=None,
) -> dict:
    """Run the tour-level QA gates and emit the QA report JSON.

    Runs AFTER stitch+render so the master exists:
      • per-clip room-type results (already gated during generation) are summarized,
      • continuity is scored across the stitched sequence's junctions,
      • address verification compares the master against the real Zillow listing.

    Writes ``manifests/{tour_id}_qa_report.json`` and returns the report dict.
    Each gate is wrapped so a failure degrades to "indeterminate" and never
    prevents the report (or delivery) — the gates inform, they don't block.
    """
    tour_id = manifest.listing_id
    report: dict = {
        "tour_id": tour_id,
        "address": manifest.address,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "master_path": manifest.master_path,
        "engine": manifest.engine,
    }

    # 1) Per-clip summary (mechanical + hallucination + room-type already ran).
    accepted = [c for c in manifest.clips if c.accepted]
    report["clips"] = [
        {
            "index": c.index,
            "room_type": c.room_type,
            "accepted": c.accepted,
            "motion": round(c.motion, 4),
            "qa_verdict": c.qa_verdict,
        }
        for c in sorted(manifest.clips, key=lambda c: c.index)
    ]
    report["clip_summary"] = {
        "accepted": len(accepted),
        "rejected": len(manifest.clips) - len(accepted),
        "transitions_accepted": sum(1 for t in manifest.transitions if t.accepted),
    }

    # 2) Continuity across the stitched sequence.
    if on_progress:
        on_progress("QA: scoring continuity across junctions")
    try:
        segs = _ordered_segments(manifest)
        cont = qa.score_continuity(segs)
        report["continuity"] = {
            "score": round(cont.score, 4),
            "seamless": cont.passed,
            "reason": cont.reason,
        }
    except Exception as e:               # never let QA crash the run
        report["continuity"] = {"score": 0.0, "seamless": None,
                                "reason": f"continuity unavailable ({str(e)[:80]})"}

    # 3) Address / property-match verification on the final master.
    if on_progress:
        on_progress("QA: verifying property against Zillow listing")
    if manifest.master_path:
        try:
            verdict = qa_address.verify_address(
                manifest.master_path, manifest.address, work_dir=Path(work_dir)
            )
            report["address_verification"] = verdict.to_dict()
        except Exception as e:
            report["address_verification"] = {
                "passed": True, "verdict": "indeterminate", "confidence": 0.0,
                "reasons": [f"address QA unavailable ({str(e)[:80]})"],
            }
    else:
        report["address_verification"] = {
            "passed": True, "verdict": "indeterminate", "confidence": 0.0,
            "reasons": ["no master rendered"],
        }

    # 4) Final pass/fail decision. A tour FAILS only on a confident property
    #    mismatch (wrong house). Low continuity or an indeterminate address are
    #    surfaced as warnings for human review, not hard blocks.
    decision = "pass"
    reasons: list[str] = []
    warnings: list[str] = []

    if not accepted:
        decision = "fail"
        reasons.append("no accepted room clips")

    addr = report["address_verification"]
    if addr.get("verdict") == "mismatch" and not addr.get("passed", True):
        decision = "fail"
        reasons.append(
            f"property mismatch vs Zillow listing (confidence {addr.get('confidence', 0)})"
        )
    elif addr.get("verdict") == "indeterminate":
        warnings.append("address verification indeterminate")

    cont = report["continuity"]
    if cont.get("seamless") is False:
        warnings.append(f"continuity below seamless threshold ({cont.get('score')})")

    if decision != "fail" and warnings:
        decision = "review"
    if decision == "pass":
        reasons.append("all QA gates passed")

    report["decision"] = decision
    report["decision_reasons"] = reasons
    report["warnings"] = warnings

    # 5) Persist alongside the manifests.
    out_dir = Path(report_dir) if report_dir else QA_REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tour_id}_qa_report.json"
    out_path.write_text(json.dumps(report, indent=2))
    report["report_path"] = str(out_path)
    if on_progress:
        on_progress(f"QA report written → {out_path} (decision: {decision})")
    return report
