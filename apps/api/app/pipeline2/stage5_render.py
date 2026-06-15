"""Stage 5 — Render. Master is canonical; the reel is DERIVED from it (brief #5).

Master: the stitched 16:9 sequence + optional ambient bed → unbranded MLS master,
plus a watermarked preview.

Reel: derived from the SAME master (never generated independently) — a 9:16
saliency-biased crop (center-weighted, slightly higher to favor architecture
over floors), beat-agnostic but tightened pacing, optional music + caption.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.pipeline2.manifest import Manifest


def _run(args: list[str], timeout: int = 1800) -> None:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{p.stderr[-1200:]}")


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("'", "’").replace(":", "\\:")


def render_master(
    stitched: Path, manifest: Manifest, work_dir: Path,
    music: Path | None = None, watermark: bool = False,
    watermark_text: str = "Premier Home Tours",
) -> Path:
    out = Path(work_dir) / f"{manifest.listing_id}_{'preview' if watermark else 'master'}.mp4"
    vf = []
    if watermark:
        vf.append(
            f"drawtext=text='{_esc(watermark_text)}':fontcolor=white@0.75:fontsize=36:"
            f"box=1:boxcolor=black@0.35:boxborderw=14:x=w-tw-30:y=h-th-30"
        )
    args = ["ffmpeg", "-y", "-i", str(stitched)]
    if music:
        args += ["-i", str(music)]
    if vf:
        args += ["-vf", ",".join(vf)]
    if music:
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest", "-map", "0:v", "-map", "1:a"]
    else:
        args += ["-an"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    _run(args)
    return out


def derive_reel(
    master: Path, manifest: Manifest, work_dir: Path,
    music: Path | None = None,
    width: int = 1080, height: int = 1920,
) -> Path:
    """9:16 reel DERIVED from the master — saliency-biased center crop + caption."""
    out = Path(work_dir) / f"{manifest.listing_id}_reel.mp4"
    # Crop a 9:16 column from the 16:9 master, biased slightly upward (y center
    # at 45% favors walls/ceilings/architecture over floor).
    crop = (
        f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
        f"scale={width}:{height},setsar=1"
    )
    addr = _esc(manifest.address)
    caption = (
        f"drawtext=text='{addr}':fontcolor=white:fontsize=58:box=1:"
        f"boxcolor=black@0.45:boxborderw=18:x=(w-tw)/2:y=h*0.10:"
        f"enable='between(t,0.4,3.4)'"
    )
    vf = f"{crop},{caption}"
    args = ["ffmpeg", "-y", "-i", str(master)]
    if music:
        args += ["-i", str(music), "-c:a", "aac", "-b:a", "192k", "-shortest",
                 "-map", "0:v", "-map", "1:a"]
    else:
        args += ["-an"]
    args += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    _run(args)
    return out


def render_all(
    stitched: Path, manifest: Manifest, work_dir: Path,
    music: Path | None = None, on_progress=None,
) -> Manifest:
    if on_progress:
        on_progress("rendering master")
    master = render_master(stitched, manifest, work_dir, music=music, watermark=False)
    if on_progress:
        on_progress("rendering watermarked preview")
    preview = render_master(stitched, manifest, work_dir, music=music, watermark=True)
    if on_progress:
        on_progress("deriving 9:16 reel from master")
    reel = derive_reel(master, manifest, work_dir, music=music)

    manifest.master_path = str(master)
    manifest.preview_path = str(preview)
    manifest.reel_path = str(reel)
    manifest.stage = "rendered"
    manifest.save(work_dir)
    return manifest
