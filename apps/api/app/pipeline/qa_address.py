"""Address verification — the final, listing-level QA gate.

After a tour is fully stitched + rendered, this layer answers the question the
mechanical and per-clip gates can't: *is this video actually of the property we
were hired to film?* It scrapes real listing photos from Redfin, Zillow, and
Realtor.com (in priority order for best resolution), samples frames from the
finished master, and asks Gemini Vision to score how confidently the two depict
the same property.

Like every other vision-backed gate in this pipeline, it is advisory-by-default:
a scrape failure, a missing session, or a Gemini outage downgrades the verdict
to "indeterminate" and NEVER blocks delivery. A tour only earns a hard
"mismatch" when Gemini is confident the video is of a different property.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from google.genai import types

from app.config import get_settings
from app.pipeline import qa
from app.pipeline.gemini import gemini_client
from app.pipeline.multi_scraper import scrape_best_photos

_VERIFY_PROMPT = (
    "You are verifying that an AI-generated real-estate tour depicts the correct "
    "property. The FIRST set of images are REAL listing photos of the property we "
    "were hired to film (ground truth). The REMAINING images are frames sampled "
    "from the finished AI-generated video.\n\n"
    "Do these frames from the AI-generated video match this actual property? "
    "Compare against these real listing photos — judge the architecture, layout, "
    "finishes, fixtures and overall style, NOT lighting, grade, or camera motion "
    "(those are expected to differ). Minor AI embellishment is fine; a clearly "
    "DIFFERENT house, different floor plan, or rooms that don't exist in the "
    "listing is a mismatch.\n\n"
    "Score 0-100 on property match confidence. Output ONLY JSON: "
    '{"match_confidence": 0-100, "verdict": "match"|"mismatch", '
    '"reasons": ["short specific observations, 1-4 items"]}'
)

# Gemini match_confidence at/above this is treated as a confirmed match; a
# confident "mismatch" verdict below the low watermark is the only hard failure.
_MATCH_THRESHOLD = 60.0
_MISMATCH_THRESHOLD = 40.0


@dataclass
class AddressVerdict:
    """Result of the listing-level property-match check."""
    passed: bool                 # False ONLY on a confident mismatch
    verdict: str                 # "match" | "mismatch" | "indeterminate"
    confidence: float            # 0-100 property-match confidence
    reasons: list[str] = field(default_factory=list)
    scraped_photos: int = 0      # real listing photos compared against
    frames_compared: int = 0     # master frames sampled
    sources_used: list[str] = field(default_factory=list)  # which platforms contributed
    best_resolution: str = ""    # e.g. "2K", "4K+", "1024px"

    def to_dict(self) -> dict:
        return asdict(self)


# ── Verdict ────────────────────────────────────────────────────────────────

def verify_address(
    master_path: Path | str,
    address: str,
    work_dir: Path | str | None = None,
    max_photos: int = 10,
    frame_count: int = 5,
) -> AddressVerdict:
    """Compare the finished master against real listing photos for `address`.

    Scrapes Redfin → Zillow → Realtor.com in priority order for the highest
    available resolution. Falls back between sources gracefully. Deduplicates
    across platforms and upscales low-res photos via AI.

    Never raises and never hard-fails on infrastructure problems: missing
    credentials, a failed scrape, or a Gemini outage all resolve to an
    "indeterminate" verdict with ``passed=True``.
    """
    master_path = Path(master_path)

    def _indeterminate(reason: str) -> AddressVerdict:
        return AddressVerdict(
            passed=True, verdict="indeterminate", confidence=0.0,
            reasons=[reason],
        )

    cfg = get_settings()
    if not cfg.veo_enabled:
        return _indeterminate("address QA skipped (no Gemini credentials)")
    if not master_path.exists():
        return _indeterminate("master video not found")
    if not address.strip():
        return _indeterminate("no listing address provided")

    scratch = Path(work_dir) / "qa_address" if work_dir else Path(
        tempfile.mkdtemp(prefix="pht_addr_")
    )
    scratch.mkdir(parents=True, exist_ok=True)

    # ── Multi-source scrape (Redfin → Zillow → Realtor.com) ──────────────
    photos = scrape_best_photos(address, min_photos=4, max_photos=max_photos)

    if not photos:
        return _indeterminate("could not retrieve listing photos from any source (Redfin, Zillow, or Realtor.com)")

    # Save photos to disk for Gemini
    saved: list[Path] = []
    for i, p in enumerate(photos):
        out = scratch / f"listing_{i}.jpg"
        out.write_bytes(p.bytes)
        if out.stat().st_size > 1024:
            saved.append(out)

    if not saved:
        return _indeterminate("downloaded photos were too small or corrupt")

    sources = list(dict.fromkeys(p.source for p in photos))
    best = photos[0]
    best_res = best.quality_label if best.pixels > 0 else "unknown"

    # ── Frame extraction ─────────────────────────────────────────────────
    frames = qa.extract_frames(master_path, count=frame_count)
    if not frames:
        return _indeterminate("could not extract master frames")

    parts: list = [types.Part.from_bytes(data=p.read_bytes(), mime_type="image/jpeg") for p in saved]
    parts += [types.Part.from_bytes(data=f.read_bytes(), mime_type="image/jpeg") for f in frames]
    parts.append(_VERIFY_PROMPT)

    try:
        client = gemini_client()
        resp = client.models.generate_content(
            model=cfg.gemini_model,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.0, response_mime_type="application/json"
            ),
        )
        data = json.loads(resp.text)
        confidence = float(data.get("match_confidence", 0.0))
        verdict = str(data.get("verdict", "")).strip().lower()
        reasons = [str(r) for r in data.get("reasons", []) if r]

        # Hard-fail ONLY on a confident mismatch; otherwise the tour passes,
        # flagged "match" when confident and "indeterminate" when unsure.
        if verdict == "mismatch" and confidence <= _MISMATCH_THRESHOLD:
            final, passed = "mismatch", False
        elif confidence >= _MATCH_THRESHOLD:
            final, passed = "match", True
        else:
            final, passed = "indeterminate", True

        return AddressVerdict(
            passed=passed, verdict=final, confidence=confidence,
            reasons=reasons or ["no specific observations returned"],
            scraped_photos=len(saved), frames_compared=len(frames),
            sources_used=sources, best_resolution=best_res,
        )
    except Exception as e:
        return _indeterminate(f"address QA unavailable ({str(e)[:80]})")
    finally:
        for f in frames:
            f.unlink(missing_ok=True)
