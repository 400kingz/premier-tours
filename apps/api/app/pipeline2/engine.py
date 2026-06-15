"""Video engine selection — Higgsfield DoP by default, Veo only as a fallback.

Both clients expose the same duck-typed interface so the pipeline never branches
on which one is active:

    engine.animate(image_path, prompt, out_path, last_frame_path=None) -> Path
    engine.RateLimited   # exception type to back off on

Switch with RENDER_ENGINE=higgsfield|veo in the environment.
"""
from __future__ import annotations

from app.config import Settings, get_settings


def get_engine(settings: Settings | None = None):
    cfg = settings or get_settings()
    if cfg.render_engine == "veo":
        from app.pipeline.veo import RateLimited, VeoClient
        client = VeoClient(cfg)
        client.RateLimited = RateLimited
        return client

    from app.pipeline.higgsfield import HiggsfieldClient, RateLimited
    client = HiggsfieldClient(cfg)
    client.RateLimited = RateLimited
    return client


def engine_cost_per_clip_cents(settings: Settings | None = None) -> int:
    """Per-generated-clip cost estimate for the active engine (cents)."""
    cfg = settings or get_settings()
    if cfg.render_engine == "veo":
        return 8 * 40  # ~8s @ ~$0.40/s
    return cfg.higgsfield_cost_per_clip_cents
