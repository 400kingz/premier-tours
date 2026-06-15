"""QA gates for generated clips.

Four layers:
1. Mechanical (ported from v1): size, duration, motion, SSIM-vs-prior-clips.
2. Hallucination-aware: Gemini Vision compares clip frames against the
   source listing photo and rejects architectural mutations — extra doorways,
   warped staircases, furniture that morphs, rooms that aren't in the photo.
3. Room-type (new): per-clip Gemini check that the rendered room matches the
   room_type the manifest claims (a "kitchen" clip must read as a kitchen).
4. Continuity (new): SSIM across every junction of the stitched sequence —
   the last frame of clip A vs the first frame of clip B — to confirm the
   frame-chaining produced a genuinely seamless single take.

Every vision-backed gate (2–4) is advisory-by-default: if Gemini or ffmpeg is
unavailable it downgrades to a pass rather than blocking the pipeline.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from google.genai import types

from app.config import get_settings
from app.pipeline.gemini import gemini_client


# ── Helpers ────────────────────────────────────────────────────────────────

def _ffprobe(path: Path, show: str = "format") -> dict:
    # `-show_entries <section>` (NOT `<section>=*`). The `=*` wildcard returns an
    # empty section on newer ffmpeg builds (Lavf62+), which silently zeroed every
    # duration and made QA reject every good clip as "too short".
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", show, "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:200]}")
    return json.loads(result.stdout)


def get_duration(path: Path) -> float:
    return float(_ffprobe(path, "format").get("format", {}).get("duration", 0))


def _motion_score(path: Path) -> float:
    """0.0 (static) → 1.0 (lots of motion), via frame-size variation (v1-proven)."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_frames", "-select_streams", "v:0",
             "-show_entries", "frame=pts_time,pkt_size", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        sizes = [
            int(parts[1])
            for line in result.stdout.splitlines()
            if (parts := line.strip().split(",")) and len(parts) >= 2 and parts[1].isdigit()
        ]
        if len(sizes) < 5:
            return 0.0
        mean = sum(sizes) / len(sizes)
        if mean == 0:
            return 0.0
        cv = math.sqrt(sum((s - mean) ** 2 for s in sizes) / len(sizes)) / mean
        return min(cv * 5, 1.0)
    except (subprocess.TimeoutExpired, RuntimeError, ValueError, ZeroDivisionError):
        return 0.0


def _ssim_vs_reference(candidate: Path, reference: Path) -> float:
    """SSIM of middle frames, 0.0 (different) → 1.0 (identical). Ported from v1."""
    try:
        mid = get_duration(candidate) / 2
        cand_frame = candidate.with_suffix(".tmp_cand.png")
        ref_frame = reference.with_suffix(".tmp_ref.png")
        for vid, out in [(candidate, cand_frame), (reference, ref_frame)]:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(mid), "-i", str(vid),
                 "-vframes", "1", "-q:v", "2", str(out)],
                capture_output=True, text=True, timeout=30,
            )
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(cand_frame), "-i", str(ref_frame),
             "-filter_complex", "ssim=stats_file=/dev/null", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        cand_frame.unlink(missing_ok=True)
        ref_frame.unlink(missing_ok=True)
        for line in result.stderr.splitlines():
            if "SSIM" in line and "All:" in line:
                m = re.search(r"All:\s*([\d.]+)", line)
                if m:
                    return float(m.group(1))
        return 0.5
    except (subprocess.TimeoutExpired, RuntimeError, FileNotFoundError):
        return 0.5


def extract_frames(clip: Path, count: int = 3) -> list[Path]:
    """Extract `count` evenly-spaced frames as JPEGs in a temp dir."""
    dur = get_duration(clip)
    tmp = Path(tempfile.mkdtemp(prefix="pht_qa_"))
    frames: list[Path] = []
    for i in range(count):
        t = dur * (i + 0.5) / count
        out = tmp / f"frame{i}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(clip),
             "-vframes", "1", "-q:v", "3", str(out)],
            capture_output=True, text=True, timeout=30,
        )
        if out.exists():
            frames.append(out)
    return frames


# ── Results ────────────────────────────────────────────────────────────────

@dataclass
class QAResult:
    passed: bool
    reason: str = ""
    score: float = 0.0

    def __bool__(self) -> bool:
        return self.passed


# ── Layer 1: mechanical ────────────────────────────────────────────────────

def check_clip_mechanical(
    clip_path: Path,
    prior_clips: list[Path] | None = None,
    min_size_bytes: int = 100_000,
    min_duration: float = 3.0,
    min_motion: float = 0.15,
    ssim_threshold: float = 0.90,
) -> QAResult:
    if not clip_path.exists():
        return QAResult(False, "file not found")

    size = clip_path.stat().st_size
    if size < min_size_bytes:
        return QAResult(False, f"too small: {size / 1024:.0f}KB")

    try:
        dur = get_duration(clip_path)
        if dur < min_duration:
            return QAResult(False, f"too short: {dur:.1f}s < {min_duration:.0f}s")
    except (RuntimeError, ValueError, KeyError):
        return QAResult(False, "could not probe duration")

    motion = _motion_score(clip_path)
    if motion < min_motion:
        return QAResult(
            False,
            f"static clip (motion={motion:.3f}) — likely a still image",
            score=motion,
        )

    for prior in prior_clips or []:
        try:
            sim = _ssim_vs_reference(clip_path, prior)
            if sim >= ssim_threshold:
                return QAResult(False, f"duplicate of {prior.name} (SSIM={sim:.3f})", score=sim)
        except (RuntimeError, FileNotFoundError):
            continue

    return QAResult(True, "passed", score=motion)


# ── Layer 2: hallucination-aware vision gate ───────────────────────────────

_VISION_QA_PROMPT = (
    "You are a strict architectural QA inspector for AI-generated real estate "
    "video. The FIRST image is the real listing photo (ground truth). The "
    "remaining images are frames sampled from an AI-generated video clip that "
    "is supposed to fly through THIS exact space.\n\n"
    "Reject the clip if the frames show architectural mutations relative to "
    "the real photo: walls/doorways/windows that appear or vanish, staircases "
    "that warp, ceilings/floors that bend, furniture that morphs or duplicates, "
    "rooms that are clearly a different property, melted or smeared geometry, "
    "or text/watermark artifacts. Normal camera movement revealing adjacent "
    "areas, perspective change, and mild motion blur are ACCEPTABLE.\n\n"
    "Output ONLY JSON: {\"verdict\": \"pass\"|\"fail\", \"confidence\": 0-1, "
    "\"reason\": \"one short sentence\"}"
)


def check_clip_vision(clip_path: Path, source_photo: Path) -> QAResult:
    """Gemini Vision compares sampled clip frames against the source photo."""
    cfg = get_settings()
    if not cfg.veo_enabled:
        return QAResult(True, "vision QA skipped (no credentials)", score=0.5)

    frames = extract_frames(clip_path, count=3)
    if not frames:
        return QAResult(False, "could not extract frames for vision QA")

    client = gemini_client()
    parts = [
        types.Part.from_bytes(data=Path(source_photo).read_bytes(), mime_type="image/jpeg")
        if source_photo.suffix.lower() in (".jpg", ".jpeg")
        else types.Part.from_bytes(data=Path(source_photo).read_bytes(), mime_type="image/png")
    ]
    parts += [
        types.Part.from_bytes(data=f.read_bytes(), mime_type="image/jpeg") for f in frames
    ]
    parts.append(_VISION_QA_PROMPT)

    try:
        resp = client.models.generate_content(
            model=cfg.gemini_model,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.0, response_mime_type="application/json"
            ),
        )
        data = json.loads(resp.text)
        verdict = data.get("verdict", "fail")
        confidence = float(data.get("confidence", 0))
        reason = data.get("reason", "")
        # Only reject on a confident failure — vision QA is advisory otherwise.
        if verdict == "fail" and confidence >= 0.6:
            return QAResult(False, f"hallucination: {reason}", score=confidence)
        return QAResult(True, reason or "consistent with source photo", score=confidence)
    except Exception as e:
        # The vision gate must never block the pipeline on its own failure.
        return QAResult(True, f"vision QA unavailable ({str(e)[:80]})", score=0.5)
    finally:
        for f in frames:
            f.unlink(missing_ok=True)


def generate_adjusted_prompt(original_prompt: str, issue: str) -> str:
    """Adjust a Veo prompt based on why QA failed (ported from v1, extended)."""
    adjustments = {
        "static": " with MORE CAMERA MOTION, dramatic dolly movement, active camera glide",
        "duplicate": " from a COMPLETELY DIFFERENT ANGLE, shift perspective significantly",
        "too short": " extended duration, slower reveal of the space",
        "too small": " higher quality, detailed rendering",
        "hallucination": (
            " — CRITICAL: preserve the exact architecture, layout, walls, windows "
            "and furniture of the source photo; do not invent, remove, or warp any "
            "structural element; slower, gentler camera move"
        ),
    }
    suffix = next(
        (fix for key, fix in adjustments.items() if key in issue.lower()),
        " with different camera movement and perspective",
    )
    return original_prompt.rstrip(".") + suffix + "."


# ── Frame helpers for the continuity gate ──────────────────────────────────

def _frame_at_offset(clip: Path, out: Path, *, from_end: bool) -> Path | None:
    """Grab the first or last decodable frame of a clip as a PNG.

    The last frame is seeked from EOF (`-sseof`) and retried at growing
    offsets, mirroring stage3's exit-frame extractor: an EOF seek can land
    past the final keyframe and write zero frames on the first try.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    seeks = ["-0.2", "-0.5", "-1.0"] if from_end else ["0"]
    flag = "-sseof" if from_end else "-ss"
    for s in seeks:
        subprocess.run(
            ["ffmpeg", "-y", flag, s, "-i", str(clip),
             "-update", "1", "-frames:v", "1", "-q:v", "2", str(out)],
            capture_output=True, text=True, timeout=30,
        )
        if out.exists() and out.stat().st_size > 0:
            return out
    return None


def _ssim_image_pair(a: Path, b: Path) -> float:
    """SSIM between two still images, 0.0 (different) → 1.0 (identical)."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(a), "-i", str(b),
         "-filter_complex", "ssim=stats_file=/dev/null", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    for line in result.stderr.splitlines():
        if "SSIM" in line and "All:" in line:
            m = re.search(r"All:\s*([\d.]+)", line)
            if m:
                return float(m.group(1))
    return 0.5


# ── Layer 3: room-type verification ────────────────────────────────────────

_ROOM_TYPE_PROMPT = (
    "You are verifying a real-estate video clip. Does this frame primarily show "
    "a {room_type}? Judge by the room's function and fixtures (e.g. a kitchen has "
    "counters/appliances, a bathroom has a sink/toilet/shower, a bedroom has a "
    "bed). Answer with ONLY JSON: "
    '{{"room_type_match": true|false, "confidence": 0.0-1.0, '
    '"observed": "what the frame actually depicts, 3 words max"}}'
)


def check_clip_room_type(clip_path: Path, room_type: str) -> QAResult:
    """Confirm a generated clip actually depicts the manifest's room_type.

    Fails the clip only on a CONFIDENT mismatch (room_type_match is false with
    confidence ≥ 0.7) so an uncertain model never rejects a good clip. Skips
    cleanly when credentials are missing or the room_type is unknown.
    """
    cfg = get_settings()
    if not cfg.veo_enabled:
        return QAResult(True, "room-type QA skipped (no credentials)", score=0.5)
    if not room_type or room_type.strip().lower() in ("", "unknown"):
        return QAResult(True, "room-type unknown — skipped", score=0.5)

    frames = extract_frames(clip_path, count=1)   # the middle frame
    if not frames:
        return QAResult(True, "room-type QA skipped (no frame)", score=0.5)

    try:
        client = gemini_client()
        resp = client.models.generate_content(
            model=cfg.gemini_model,
            contents=[
                types.Part.from_bytes(data=frames[0].read_bytes(), mime_type="image/jpeg"),
                _ROOM_TYPE_PROMPT.format(room_type=room_type),
            ],
            config=types.GenerateContentConfig(
                temperature=0.0, response_mime_type="application/json"
            ),
        )
        data = json.loads(resp.text)
        match = bool(data.get("room_type_match", True))
        confidence = float(data.get("confidence", 0.0))
        observed = str(data.get("observed", "")).strip()
        if not match and confidence >= 0.7:
            detail = f" (looks like {observed})" if observed else ""
            return QAResult(
                False,
                f"room-type mismatch: expected {room_type}{detail} (conf={confidence:.2f})",
                score=confidence,
            )
        return QAResult(True, f"room-type ok: {room_type} (conf={confidence:.2f})", score=confidence)
    except Exception as e:
        # Advisory gate — never block the pipeline on its own failure.
        return QAResult(True, f"room-type QA unavailable ({str(e)[:80]})", score=0.5)
    finally:
        for f in frames:
            f.unlink(missing_ok=True)


# ── Layer 4: continuity score ──────────────────────────────────────────────

def score_continuity(segments: list[Path], seamless_threshold: float = 0.85) -> QAResult:
    """Average junction SSIM across the stitched sequence.

    `segments` is the ordered list of clips that make up the master (room and
    transition clips interleaved). For each adjacent pair we compare the last
    frame of A against the first frame of B; with frame-chaining these should
    be near-identical. The continuity score is the mean of those SSIMs:
    > seamless_threshold (default 0.85) reads as a seamless single take.

    Returns a score in [0, 1]. `passed` reflects the threshold but this gate is
    informational — the report aggregator decides what to do with a low score.
    """
    segments = [Path(s) for s in segments if s and Path(s).exists()]
    if len(segments) < 2:
        return QAResult(True, "single segment — continuity N/A", score=1.0)

    tmp = Path(tempfile.mkdtemp(prefix="pht_continuity_"))
    sims: list[float] = []
    try:
        for i, (a, b) in enumerate(zip(segments, segments[1:])):
            last = _frame_at_offset(a, tmp / f"j{i}_a.png", from_end=True)
            first = _frame_at_offset(b, tmp / f"j{i}_b.png", from_end=False)
            if not last or not first:
                continue
            try:
                sims.append(_ssim_image_pair(last, first))
            except (subprocess.TimeoutExpired, RuntimeError, ValueError):
                continue
    finally:
        for f in tmp.glob("*.png"):
            f.unlink(missing_ok=True)
        if not any(tmp.iterdir()):
            tmp.rmdir()

    if not sims:
        return QAResult(True, "continuity indeterminate (no junctions measured)", score=0.5)

    score = sum(sims) / len(sims)
    passed = score > seamless_threshold
    label = "seamless" if passed else "visible seams"
    return QAResult(passed, f"continuity {score:.3f} over {len(sims)} junction(s) — {label}", score=score)
