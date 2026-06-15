"""Stage 4 — Stitch. PURE FFmpeg. No model, no improvisation.

Assemble the final sequence in walkthrough order, interleaving room clips with
their frame-chained transition clips:

    room0 → trans(0,1) → room1 → trans(1,2) → room2 → …

Because each transition's first frame IS room A's exit frame and its last frame
IS room B's entry frame, this is a hard concat with NO crossfade — yet it reads
as one continuous take. Then: one vidstab two-pass stabilization over the whole
sequence (buttery motion a handheld FPV drone can't match), and one shared
color grade (curves) across everything so exposure/grade are uniform end-to-end.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.pipeline2.manifest import Manifest


def _run(args: list[str], timeout: int = 1800) -> None:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{p.stderr[-1200:]}")


def _ordered_segments(manifest: Manifest) -> list[Path]:
    """room0, trans(0,1), room1, trans(1,2), … — only accepted clips."""
    clips = sorted([c for c in manifest.clips if c.accepted], key=lambda c: c.index)
    segs: list[Path] = []
    for i, clip in enumerate(clips):
        segs.append(Path(clip.generated_clip))
        if i < len(clips) - 1:
            nxt = clips[i + 1]
            t = manifest.transition_between(clip.index, nxt.index)
            if t and t.accepted and t.generated_clip:
                segs.append(Path(t.generated_clip))
    return segs


def stitch(
    manifest: Manifest,
    work_dir: Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    stabilize: bool = False,
    on_progress=None,
) -> Path:
    # NOTE: stabilize defaults OFF. vidstab is for shaky HANDHELD footage; the
    # generated shots are already gimbal-smooth, and running vidstab over them
    # adds warp/wobble + a crop zoom that makes the master visibly LESS smooth
    # than the raw clips (confirmed 2026-06-13). Only enable for real shaky input.
    segs = _ordered_segments(manifest)
    if not segs:
        raise RuntimeError("Stage 4: no accepted clips to stitch")

    out_dir = Path(work_dir)
    norm_dir = out_dir / "stitch"
    norm_dir.mkdir(parents=True, exist_ok=True)

    # 1) Normalize every segment to identical geometry/fps so concat is clean.
    normed: list[Path] = []
    for i, s in enumerate(segs):
        n = norm_dir / f"seg{i:02d}.mp4"
        _run([
            "ffmpeg", "-y", "-i", str(s),
            "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"),
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", str(n),
        ])
        normed.append(n)

    # 2) Concat (no crossfade — frames already match at the seams).
    concat_list = norm_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{p}'\n" for p in normed))
    raw = out_dir / "_stitched_raw.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
          "-c", "copy", str(raw)])

    src = raw
    # 3) vidstab two-pass over the whole sequence.
    if stabilize:
        if on_progress:
            on_progress("stabilizing (vidstab pass 1/2)")
        trf = norm_dir / "transforms.trf"
        _run(["ffmpeg", "-y", "-i", str(raw),
              "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={trf}",
              "-f", "null", "-"])
        stab = out_dir / "_stitched_stab.mp4"
        if on_progress:
            on_progress("stabilizing (vidstab pass 2/2)")
        _run(["ffmpeg", "-y", "-i", str(raw),
              "-vf", (f"vidstabtransform=input={trf}:zoom=1:smoothing=30,"
                      f"unsharp=5:5:0.6:5:5:0.0"),
              "-c:v", "libx264", "-preset", "medium", "-crf", "18",
              "-pix_fmt", "yuv420p", str(stab)])
        src = stab

    # 4) One shared color grade across the entire sequence (consistent look).
    if on_progress:
        on_progress("applying shared color grade")
    out = out_dir / f"{manifest.listing_id}_stitched.mp4"
    # Seedance leaves output slightly cool/dim even from a color-corrected input,
    # so the shared grade also lifts exposure a touch and adds a gentle warm bias
    # (more red, less blue) for a natural, inviting real-estate look.
    grade = (
        "curves=preset=lighter,"
        "colorbalance=rs=0.06:rm=0.04:bs=-0.05:bm=-0.04,"
        "eq=contrast=1.06:saturation=1.07:brightness=0.03,"
        "format=yuv420p"
    )
    _run(["ffmpeg", "-y", "-i", str(src), "-vf", grade,
          "-c:v", "libx264", "-preset", "medium", "-crf", "18",
          "-movflags", "+faststart", str(out)])

    manifest.stage = "stitched"
    manifest.save(work_dir)
    return out
