"""Stage 0 — Intake + normalization. PURE CODE (OpenCV / scikit-image). No model.

This is the stage that lets a generated tour beat a real drone shoot: a real
operator can't fix that the kitchen was shot at noon and the bedroom at dusk.
We can. Every photo is brought to one exposure, one white balance, one virtual
lens, and clean 1080p+ before a single frame is generated.

Steps:
  1. Drop unusable photos — too low-res, or too blurry (Laplacian variance).
  2. Dedupe near-identical photos (aHash Hamming distance).
  3. Pick a reference photo (best-exposed, well-balanced) as the color anchor.
  4. Histogram-match every photo's exposure + white balance to the reference.
  5. De-warp ultra-wide barrel distortion.
  6. Center-crop to one consistent virtual lens (16:9), upscale to >=1080p.

Writes normalized JPEGs and records reference_photo + per-clip photo paths in
the manifest. Deterministic: same inputs → same outputs, same order.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.pipeline2.manifest import ClipSpec, Manifest

MIN_DIM = 460                # reject true thumbnails; real listing photos
                             # (often ~960x640) are upscaled to 1080p below
BLUR_FLOOR = 60.0            # Laplacian variance; below = too soft
AHASH_DUPE_BITS = 6          # Hamming distance <= this = duplicate
TARGET_W, TARGET_H = 1920, 1080
BARREL_K1 = -0.06            # mild de-barrel for ultra-wide real-estate lenses


# ── quality gates ───────────────────────────────────────────────────────────

def _read(path: Path) -> np.ndarray | None:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return img


def _blur_score(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _ahash(img: np.ndarray) -> int:
    small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (8, 8))
    avg = small.mean()
    bits = (small > avg).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _exposure_quality(img: np.ndarray) -> float:
    """Higher = better exposed: mid-mean + healthy spread, not clipped."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean = gray.mean()
    std = gray.std()
    clipped = (np.count_nonzero(gray < 4) + np.count_nonzero(gray > 251)) / gray.size
    midness = 1.0 - abs(mean - 128) / 128.0
    return midness * 0.5 + min(std / 64.0, 1.0) * 0.4 - clipped * 0.5


# ── transforms ──────────────────────────────────────────────────────────────

def _luma(img: np.ndarray) -> np.ndarray:
    b, g, r = img[..., 0], img[..., 1], img[..., 2]
    return 0.114 * b + 0.587 * g + 0.299 * r


def _color_normalize(img: np.ndarray, target_luma: float) -> np.ndarray:
    """Gentle, reference-free color/exposure normalization.

    Replaces the old full 3-channel histogram-match-to-a-reference, which forced
    every room toward the reference photo's palette — and when the auto-picked
    reference was a grass-heavy exterior, it dyed interiors green and crushed
    their warmth. Instead:
      1. gray-world white balance (CLAMPED, so genuinely warm/cool rooms keep
         their character but color CASTS are neutralized), and
      2. exposure scaled to a shared target luma so brightness is uniform.
    This keeps each room's true color while making exposure/WB consistent across
    the set — which is what the generator needs to produce a consistent tour.
    """
    b, g, r = cv2.split(img.astype(np.float32))
    mb, mg, mr = b.mean(), g.mean(), r.mean()
    gray = (mb + mg + mr) / 3.0
    b *= np.clip(gray / max(mb, 1e-3), 0.85, 1.18)
    g *= np.clip(gray / max(mg, 1e-3), 0.85, 1.18)
    r *= np.clip(gray / max(mr, 1e-3), 0.85, 1.18)
    luma = (0.114 * b + 0.587 * g + 0.299 * r).mean()
    scale = np.clip(target_luma / max(luma, 1e-3), 0.75, 1.35)
    out = cv2.merge([b * scale, g * scale, r * scale])
    return np.clip(out, 0, 255).astype(np.uint8)


def _debarrel(img: np.ndarray, k1: float = BARREL_K1) -> np.ndarray:
    h, w = img.shape[:2]
    cam = np.array([[w, 0, w / 2], [0, w, h / 2], [0, 0, 1]], dtype=np.float64)
    dist = np.array([k1, 0, 0, 0], dtype=np.float64)
    return cv2.undistort(img, cam, dist)


def _virtual_lens(img: np.ndarray) -> np.ndarray:
    """Center-crop to 16:9, then resize to a consistent 1080p virtual lens."""
    h, w = img.shape[:2]
    target_ar = TARGET_W / TARGET_H
    ar = w / h
    if ar > target_ar:                       # too wide → crop sides
        new_w = int(h * target_ar)
        x0 = (w - new_w) // 2
        img = img[:, x0:x0 + new_w]
    else:                                    # too tall → crop top/bottom
        new_h = int(w / target_ar)
        y0 = (h - new_h) // 2
        img = img[y0:y0 + new_h, :]
    interp = cv2.INTER_LANCZOS4 if img.shape[1] < TARGET_W else cv2.INTER_AREA
    return cv2.resize(img, (TARGET_W, TARGET_H), interpolation=interp)


def normalize(
    photo_paths: list[Path],
    manifest: Manifest,
    work_dir: Path,
    on_progress=None,
) -> Manifest:
    out_dir = Path(work_dir) / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── load + quality gate ───────────────────────────────────────────────
    kept: list[tuple[Path, np.ndarray]] = []
    hashes: list[int] = []
    for p in photo_paths:
        img = _read(p)
        if img is None:
            continue
        h, w = img.shape[:2]
        if min(h, w) < MIN_DIM:
            if on_progress:
                on_progress(f"drop {p.name}: low-res {w}x{h}")
            continue
        if _blur_score(img) < BLUR_FLOOR:
            if on_progress:
                on_progress(f"drop {p.name}: blurry")
            continue
        ah = _ahash(img)
        if any(_hamming(ah, h0) <= AHASH_DUPE_BITS for h0 in hashes):
            if on_progress:
                on_progress(f"drop {p.name}: duplicate")
            continue
        hashes.append(ah)
        kept.append((p, img))

    if not kept:
        raise RuntimeError("Stage 0: no usable photos after quality gate")

    # ── exposure/WB anchor ─────────────────────────────────────────────────
    # Reference photo is recorded for provenance only; color is normalized
    # reference-free (gray-world WB + shared target luma), so a grass-heavy
    # exterior can no longer dye the interiors green.
    ref_idx = max(range(len(kept)), key=lambda i: _exposure_quality(kept[i][1]))
    ref_path = kept[ref_idx][0]
    target_luma = float(np.median([_luma(img).mean() for _, img in kept]))
    if on_progress:
        on_progress(f"reference photo: {ref_path.name}, target luma {target_luma:.0f}")

    # ── normalize every photo (consistent exposure + neutral WB) ───────────
    clips: list[ClipSpec] = []
    for idx, (p, img) in enumerate(kept):
        matched = _color_normalize(img, target_luma)
        deWarped = _debarrel(matched)
        lensed = _virtual_lens(deWarped)
        out = out_dir / f"{idx:02d}.jpg"
        cv2.imwrite(str(out), lensed, [cv2.IMWRITE_JPEG_QUALITY, 95])
        clips.append(ClipSpec(index=idx, photo=str(out), raw_photo=str(p)))
        if on_progress:
            on_progress(f"normalized {idx + 1}/{len(kept)}")

    manifest.reference_photo = str(ref_path)
    manifest.clips = clips
    manifest.stage = "normalized"
    manifest.save(work_dir)
    return manifest


def color_consistency_report(work_dir: Path) -> dict:
    """Verify acceptance criterion: stills are color-consistent.

    Reports per-image mean L*a*b* spread across the normalized set — low spread
    in a*/b* (chroma) means white balance is consistent; low L spread means
    exposure is consistent.
    """
    norm = sorted((Path(work_dir) / "normalized").glob("*.jpg"))
    means = []
    for p in norm:
        lab = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2LAB)
        means.append(lab.reshape(-1, 3).mean(axis=0))
    arr = np.array(means)
    return {
        "n": len(norm),
        "L_spread": round(float(arr[:, 0].std()), 2),
        "a_spread": round(float(arr[:, 1].std()), 2),
        "b_spread": round(float(arr[:, 2].std()), 2),
    }
