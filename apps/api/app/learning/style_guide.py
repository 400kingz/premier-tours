"""Learn drone-tour grammar from reference YouTube videos.

Gemini (via Vertex) ingests YouTube URLs directly — no download — and returns a
structured read of each video: per-room camera moves, pacing, transitions, and
color. We aggregate those observations into one canonical `style_guide.json`
that the prompt-authoring stage (Stage 2) consumes as its *constrained camera
vocabulary*. This is retrieval / in-context learning, not model training: the
guide is data the pipeline reads, and it improves as you add reference videos.

CLI:
  python -m app.learning.style_guide analyze <url> [<url> ...]
  python -m app.learning.style_guide show
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from google.genai import types

from app.config import get_settings
from app.pipeline.gemini import gemini_client
from app.services.storage import MediaStore

STYLE_DIR = Path.home() / "premier-home-tours" / "data" / "style"
STYLE_DIR.mkdir(parents=True, exist_ok=True)
OBSERVATIONS = STYLE_DIR / "observations.jsonl"
GUIDE = STYLE_DIR / "style_guide.json"

# Room types the rest of the pipeline already uses — keep them aligned.
ROOM_TYPES = [
    "front_exterior", "entryway", "living_room", "dining_room", "kitchen",
    "primary_bedroom", "bedroom", "bathroom", "backyard", "pool", "patio",
]

# Per-video extraction schema. Strict so aggregation is mechanical.
_OBS_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_pacing": {"type": "string"},
        "avg_seconds_per_room": {"type": "number"},
        "transition_style": {"type": "string"},
        "color_grade": {"type": "string"},
        "camera_moves": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "room_type": {"type": "string", "enum": ROOM_TYPES + ["unknown"]},
                    "move": {"type": "string"},
                    "speed": {"type": "string", "enum": ["very_slow", "slow", "medium", "fast"]},
                    "notes": {"type": "string"},
                },
                "required": ["room_type", "move", "speed"],
            },
        },
        "do": {"type": "array", "items": {"type": "string"}},
        "dont": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overall_pacing", "transition_style", "camera_moves"],
}

_EXTRACT_PROMPT = (
    "You are a cinematographer analyzing a real-estate drone/FPV flythrough so we "
    "can reproduce its style with an image-to-video model. Watch the whole video. "
    "For each distinct room or area shown, report the camera MOVE in plain, "
    "reproducible language (e.g. 'slow lateral truck left revealing the island', "
    "'shallow orbit around the bed', 'forward dolly through the doorway'), the "
    "relative SPEED, and the room_type. Also report overall pacing, average "
    "seconds per room, how rooms TRANSITION into each other (cuts vs continuous "
    "flythrough vs frame-matched doorway passes), and the color grade. Finally "
    "list concrete DO and DON'T rules a generator should follow to match this "
    "look. Favor what makes it feel like ONE continuous real drone take. "
    "Output strictly the requested JSON."
)

# Synthesis: merge many observations into one canonical guide.
_GUIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "camera_vocabulary": {
            "type": "object",
            "description": "One canonical move per room_type",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "move": {"type": "string"},
                    "speed": {"type": "string"},
                    "prompt_fragment": {"type": "string"},
                },
                "required": ["move", "speed", "prompt_fragment"],
            },
        },
        "pacing": {
            "type": "object",
            "properties": {
                "seconds_per_room": {"type": "number"},
                "total_target_seconds": {"type": "number"},
            },
            "required": ["seconds_per_room"],
        },
        "transition_style": {"type": "string"},
        "color_grade": {"type": "string"},
        "global_do": {"type": "array", "items": {"type": "string"}},
        "global_dont": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["camera_vocabulary", "pacing", "transition_style", "global_do", "global_dont"],
}

_SYNTH_PROMPT = (
    "You are distilling several analyses of professional real-estate drone tours "
    "into ONE reusable style guide for an image-to-video generator. Below is a "
    "JSON array of per-video observations. Produce a single canonical guide:\n"
    "- camera_vocabulary: for EACH room_type that appears, pick the single most "
    "common/effective camera move and write a ready-to-paste prompt_fragment in "
    "consistent lens/motion language.\n"
    "- IMPORTANT constraints to bake in: prefer lateral parallax and shallow "
    "orbits over deep push-ins (deep push-ins cause geometry hallucination); "
    "constant speed, steady gimbal, no rotation/warping, no people, no text.\n"
    "- pacing: consensus seconds per room and a total target length.\n"
    "- transition_style: describe the seamless continuous-take approach.\n"
    "- global_do / global_dont: merge and dedupe the rules.\n"
    "Output strictly the requested JSON.\n\nOBSERVATIONS:\n"
)


def _video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([\w-]{6,})", url)
    return m.group(1) if m else re.sub(r"\W+", "", url)[-11:]


def _download_to_gcs(url: str) -> str:
    """yt-dlp the first ~90s at <=720p, upload to GCS, return the gs:// URI.

    Used when Vertex rejects a direct YouTube URL ('not owned by the user').
    Capping length/resolution keeps the download small and the token cost low.
    """
    vid = _video_id(url)
    tmp = Path(tempfile.gettempdir()) / f"ref_{vid}.mp4"
    if not tmp.exists():
        subprocess.run(
            ["yt-dlp", "-f", "mp4[height<=720]/best[height<=720]/best",
             "--download-sections", "*0-90", "--force-keyframes-at-cuts",
             "-o", str(tmp), url],
            check=True, capture_output=True, text=True, timeout=300,
        )
    store = MediaStore()
    obj = store.upload(tmp, f"refs/{vid}.mp4", content_type="video/mp4")
    return f"gs://{store.settings.gcs_bucket}/{obj}"


def _gemini_video_obs(file_uri: str, mime: str = "video/*") -> dict:
    client = gemini_client()
    resp = client.models.generate_content(
        model=get_settings().gemini_model,
        contents=types.Content(
            role="user",
            parts=[
                types.Part(file_data=types.FileData(file_uri=file_uri, mime_type=mime)),
                types.Part(text=_EXTRACT_PROMPT),
            ],
        ),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=_OBS_SCHEMA,
        ),
    )
    return json.loads(resp.text)


def analyze_video(url: str) -> dict:
    """Gemini video understanding on one URL → structured observation.

    Tries the YouTube URL directly first (free, no download); on Vertex's
    ownership restriction, falls back to yt-dlp → GCS → gs:// URI.
    """
    try:
        obs = _gemini_video_obs(url, "video/*")
    except Exception as e:
        msg = str(e)
        if "not owned" in msg or "PERMISSION_DENIED" in msg or "INVALID_ARGUMENT" in msg:
            print(f"    direct URL rejected, downloading via yt-dlp → GCS…")
            gs_uri = _download_to_gcs(url)
            obs = _gemini_video_obs(gs_uri, "video/mp4")
        else:
            raise
    obs["source_url"] = url
    return obs


def synthesize(observations: list[dict]) -> dict:
    """Merge per-video observations into the canonical style guide."""
    client = gemini_client()
    payload = json.dumps(observations, indent=2)
    resp = client.models.generate_content(
        model=get_settings().gemini_model,
        contents=_SYNTH_PROMPT + payload,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=_GUIDE_SCHEMA,
        ),
    )
    guide = json.loads(resp.text)
    guide["sources"] = [o.get("source_url") for o in observations]
    guide["n_videos"] = len(observations)
    return guide


def _append_observation(obs: dict) -> None:
    with OBSERVATIONS.open("a") as f:
        f.write(json.dumps(obs) + "\n")


def _all_observations() -> list[dict]:
    if not OBSERVATIONS.exists():
        return []
    return [json.loads(l) for l in OBSERVATIONS.read_text().splitlines() if l.strip()]


def learn(urls: list[str]) -> dict:
    """Analyze new URLs (skipping already-seen ones), then rebuild the guide."""
    seen = {o.get("source_url") for o in _all_observations()}
    for url in urls:
        if url in seen:
            print(f"  skip (already analyzed): {url}")
            continue
        print(f"  analyzing: {url}")
        try:
            obs = analyze_video(url)
        except Exception as e:
            # One bad reference must not abort the batch.
            print(f"    ✗ skipped ({type(e).__name__}: {str(e)[:80]})")
            continue
        _append_observation(obs)
        print(f"    → {len(obs.get('camera_moves', []))} room moves, "
              f"pacing: {obs.get('overall_pacing', '?')[:50]}")
    all_obs = _all_observations()
    if not all_obs:
        raise RuntimeError("no observations to synthesize")
    guide = synthesize(all_obs)
    GUIDE.write_text(json.dumps(guide, indent=2))
    return guide


def load_guide() -> dict | None:
    """Read the current style guide, or None if not built yet."""
    return json.loads(GUIDE.read_text()) if GUIDE.exists() else None


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "analyze":
        urls = sys.argv[2:]
        if not urls:
            print("usage: ... analyze <url> [<url> ...]")
            sys.exit(1)
        g = learn(urls)
        print(f"\nStyle guide rebuilt from {g['n_videos']} videos → {GUIDE}")
        print(f"rooms: {', '.join(g['camera_vocabulary'].keys())}")
        print(f"pacing: {g['pacing']}")
    elif len(sys.argv) >= 2 and sys.argv[1] == "show":
        g = load_guide()
        print(json.dumps(g, indent=2) if g else "No style guide yet.")
    else:
        print(__doc__)
