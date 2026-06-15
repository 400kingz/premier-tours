"""Stage 1 — Classify + sequence. Vision model tags each normalized photo and
orders them into tour grammar. Writes room_type + order into the manifest.

Only the classification and ordering use a model; everything downstream of the
room_type is deterministic.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from google.genai import types

from app.config import get_settings
from app.pipeline.gemini import gemini_client
from app.pipeline2.manifest import Manifest

# Tour grammar: approach → entry → main living → kitchen/dining → bedrooms →
# baths → bonus rooms → outdoor. Lower index = earlier in the walkthrough.
TOUR_ORDER = [
    "front_exterior", "aerial", "entryway", "hallway", "living_room",
    "dining_room", "kitchen", "office", "primary_bedroom", "bedroom",
    "bathroom", "laundry_room", "recreation_room", "gym", "wine_cellar",
    "patio", "backyard", "pool",
]

_CLASSIFY_PROMPT = (
    "Classify this real-estate photo. Output ONLY JSON: "
    "{\"room_type\": one of " + json.dumps(TOUR_ORDER) + " (or \"unknown\"), "
    "\"hero_score\": 0-10 how striking this is as an opening video frame, "
    "\"features\": [up to 3 key features]}."
)


def _classify(photo: Path, max_retries: int = 4) -> dict:
    client = gemini_client()
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=get_settings().gemini_model,
                contents=types.Content(role="user", parts=[
                    types.Part.from_bytes(data=photo.read_bytes(), mime_type="image/jpeg"),
                    types.Part(text=_CLASSIFY_PROMPT),
                ]),
                config=types.GenerateContentConfig(
                    temperature=0.1, response_mime_type="application/json"
                ),
            )
            return json.loads(resp.text)
        except Exception as e:
            msg = str(e)
            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and attempt < max_retries - 1:
                time.sleep(20 * (attempt + 1))  # backoff for Vertex rate limit
                continue
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return {"room_type": "unknown", "hero_score": 5, "features": []}
    return {"room_type": "unknown", "hero_score": 5, "features": []}


def _order_key(room_type: str) -> int:
    try:
        return TOUR_ORDER.index(room_type)
    except ValueError:
        return len(TOUR_ORDER)


def sequence(manifest: Manifest, work_dir: Path, on_progress=None) -> Manifest:
    if not manifest.clips:
        raise RuntimeError("Stage 1: manifest has no normalized clips (run Stage 0)")

    for i, clip in enumerate(manifest.clips):
        clip.entry_frame = clip.photo   # the normalized photo IS the entry frame
        if clip.room_type and clip.room_type != "unknown":
            continue                    # idempotent: don't reclassify
        if on_progress:
            on_progress(f"classifying {i + 1}/{len(manifest.clips)}")
        info = _classify(Path(clip.photo))
        clip.room_type = info.get("room_type", "unknown")

    # Deterministic tour order; ties broken by original index for stability.
    manifest.clips.sort(key=lambda c: (_order_key(c.room_type), c.index))
    # Re-index so 0..n-1 reflect final walkthrough order.
    for new_idx, clip in enumerate(manifest.clips):
        clip.index = new_idx

    manifest.stage = "sequenced"
    manifest.save(work_dir)
    if on_progress:
        on_progress("order: " + " → ".join(c.room_type for c in manifest.clips))
    return manifest
