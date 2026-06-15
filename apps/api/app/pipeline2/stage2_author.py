"""Stage 2 — Assign camera moves + author prompts. Deterministic given the
manifest + learned style guide + feedback bandit. No video generation.

Each room gets a camera move from the LEARNED vocabulary (style_guide.json),
overridden by the feedback bandit's best-known fragment for that room when one
has proven itself. Prompts share identical lens/motion language and bake in the
global do/don't rules so every clip matches the reference style — and avoid the
deep push-ins that cause geometry hallucination.

Also plans the frame-chained TRANSITION clips (room A exit → room B entry), the
core of the seamless single-take look (brief rule #3 — never crossfade).
"""
from __future__ import annotations

from pathlib import Path

from app.learning.feedback import FeedbackMemory
from app.learning.style_guide import load_guide
from app.pipeline2.engine import engine_cost_per_clip_cents
from app.pipeline2.manifest import Manifest, TransitionSpec

# Shared lens/motion language appended to every room prompt. Tuned for
# Higgsfield DoP: it responds to a single, decisive camera verb plus an explicit
# "no cut / continuous" cue, and degrades into warping on deep push-ins — so we
# keep moves to lateral parallax / shallow orbit and a constant slow speed.
_BASE_STYLE = (
    "shot on a cinema FPV drone, one continuous take, smooth gimbal, steady "
    "constant slow speed, lateral parallax and shallow orbit (NOT a deep "
    "push-in), level stable horizon, no rotation, no warping, no morphing, no "
    "people, no text, no watermark, photoreal real estate, bright natural clean "
    "color grade"
)

_FALLBACK_MOVE = {
    "move": "slow forward dolly then a gentle shallow orbit to reveal the space",
    "speed": "slow",
    "prompt_fragment": "slow forward dolly into the space, then a gentle shallow orbit revealing the room",
}


def _move_for(room_type: str, guide: dict, fm: FeedbackMemory) -> tuple[str, str]:
    """Return (move_label, prompt_fragment) for a room.

    Priority: a feedback-proven winner for this room > the learned vocabulary >
    a safe generic fallback. This is where the bot 'learns from its own renders'.
    """
    vocab = (guide or {}).get("camera_vocabulary", {})
    entry = vocab.get(room_type) or _FALLBACK_MOVE
    move = entry["move"]
    # Refine ONLY with feedback recorded under this exact move — prevents an
    # unrelated phrasing from hijacking the prompt.
    best = fm.best_for_move(room_type, move, min_trials=3)
    if best and best.mean_reward >= 0.85 and best.prompt_fragment:
        return move, best.prompt_fragment
    return move, entry["prompt_fragment"]


def author(manifest: Manifest, work_dir: Path, on_progress=None) -> Manifest:
    if not manifest.clips:
        raise RuntimeError("Stage 2: no clips (run Stages 0–1)")
    from app.config import get_settings
    manifest.engine = get_settings().render_engine
    guide = load_guide()
    fm = FeedbackMemory()

    do_rules = (guide or {}).get("global_do", [])
    grade = (guide or {}).get("color_grade", "")
    manifest.style_guide_version = f"{(guide or {}).get('n_videos', 0)}videos"

    # ── room clips ────────────────────────────────────────────────────────
    n = len(manifest.clips)
    for clip in manifest.clips:
        move, fragment = _move_for(clip.room_type, guide, fm)
        clip.camera_move = move
        clip.prompt = (
            f"{fragment}. {_BASE_STYLE}."
            + (f" Color: {grade}" if grade else "")
        )
        if on_progress:
            on_progress(f"{clip.room_type}: {move[:48]}")

    # ── frame-chained transitions (room i exit → room i+1 entry) ──────────
    # The actual exit/entry frame PATHS are filled by Stage 3 after each room
    # clip exists; here we plan the transition specs and their prompts.
    manifest.transitions = []
    for i in range(n - 1):
        a, b = manifest.clips[i], manifest.clips[i + 1]
        manifest.transitions.append(TransitionSpec(
            from_index=a.index,
            to_index=b.index,
            first_frame="",   # set in Stage 3 (a.exit_frame)
            last_frame=b.entry_frame or b.photo,
            prompt=(
                f"seamless continuous FPV drone move that flies out of the "
                f"{a.room_type.replace('_',' ')} and into the "
                f"{b.room_type.replace('_',' ')} through the doorway, "
                f"frame-matched, no cut, {_BASE_STYLE}."
            ),
        ))

    manifest.stage = "authored"
    manifest.save(work_dir)
    return manifest


def estimate_spend(manifest: Manifest, cost_per_clip_cents: int | None = None) -> dict:
    """Print-before-you-spend estimate (brief guardrail).

    Counts room clips + transition clips, priced at the active engine's
    per-clip cost. Transitions are the +cost for the true single-take seam.
    """
    per_clip = (
        cost_per_clip_cents if cost_per_clip_cents is not None
        else engine_cost_per_clip_cents()
    )
    room_clips = len(manifest.clips)
    transition_clips = len(manifest.transitions)
    total_clips = room_clips + transition_clips
    cents = total_clips * per_clip
    return {
        "engine": manifest.engine,
        "room_clips": room_clips,
        "transition_clips": transition_clips,
        "total_clips": total_clips,
        "cost_per_clip_usd": round(per_clip / 100, 3),
        "est_cost_usd": round(cents / 100, 2),
        "note": "transition clips are the +cost for true seamless single-take",
    }
