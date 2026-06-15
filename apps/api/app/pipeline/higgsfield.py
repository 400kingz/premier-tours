"""Higgsfield DoP image-to-video — the primary render engine.

Why Higgsfield over Veo: the DoP (Director-of-Photography) model produces more
convincing photoreal real-estate camera motion at a fraction of Veo's per-second
cost, and it natively accepts a START frame and an END frame. That start/end
pair is exactly what the seamless single-take flythrough needs — a transition
clip can be generated FROM room A's exit frame TO room B's entry frame, so the
last frame of one clip is literally the first frame of the next. No crossfade,
no slideshow: one continuous drone move (see pipeline2/stage3_generate.py).

Drop-in for the old VeoClient: same `.animate(image, prompt, out, last_frame_path=...)`
signature, same `HiggsfieldError` / `RateLimited` exceptions, so the rest of the
pipeline doesn't care which engine is wired in.

DoP fetches its input frames by URL, so each local frame is uploaded to GCS and
passed as a short-lived signed URL. Providers (api.higgsfield.ai vs the
WaveSpeed reseller) differ only in endpoint paths + field names; both are
described in `_PROVIDERS` and the response readers are tolerant of either shape.
"""
from __future__ import annotations

import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from app.config import Settings, get_settings


class HiggsfieldError(RuntimeError):
    pass


class RateLimited(HiggsfieldError):
    pass


_DEFAULT_PROMPT = (
    "cinematic FPV real-estate drone flythrough, smooth gimbal, steady constant "
    "speed, lateral parallax, stable horizon, photoreal, bright natural color, "
    "no people, no text, no watermark"
)

# Per-provider wire format. The pipeline only ever calls submit/poll through the
# generic code below; everything provider-specific lives here.
_PROVIDERS: dict[str, dict[str, Any]] = {
    "higgsfield": {
        "submit_path": "/v1/generations",
        "poll_path": "/v1/generations/{id}",   # GET by id
        "poll_query": None,
        "start_field": "input_image",
        "end_field": "end_image",
        "id_keys": ["id", "generation_id", ["data", "id"], ["job", "id"]],
    },
    "wavespeed": {
        "submit_path": "/submit",
        "poll_path": "/result",
        "poll_query": "task_id",                # GET /result?task_id=<id>
        "start_field": "start_image_url",
        "end_field": "end_image_url",
        "id_keys": ["task_id", "id", ["data", "task_id"]],
    },
}

_DONE = {"completed", "succeeded", "success", "done", "finished", "ready"}
# "nsfw"/content flags are FREQUENT false positives on real-estate prompts
# (measured ~2/4 in testing) — treat as failure so the caller retries/rephrases.
_FAILED = {"failed", "error", "errored", "canceled", "cancelled", "rejected",
           "nsfw", "content_violation", "flagged", "blocked"}
_VIDEO_KEYS = [
    "video_url", "output_url", "url",
    ["output", "video_url"], ["output", "url"], ["result", "url"],
    ["result", "video_url"], ["video", "url"], ["assets", 0, "url"],
    ["outputs", 0, "url"], ["data", "video_url"], ["data", "url"],
]
_STATUS_KEYS = ["status", "state", ["data", "status"], ["job", "status"]]


def _dig(obj: Any, path: Any) -> Any:
    """Read a value by a key, an index, or a list-path (e.g. ['data','id'])."""
    keys = path if isinstance(path, list) else [path]
    cur = obj
    for k in keys:
        try:
            cur = cur[k]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _first(obj: Any, paths: list) -> Optional[Any]:
    for p in paths:
        v = _dig(obj, p)
        if v not in (None, ""):
            return v
    return None


class HiggsfieldClient:
    """Image→video via Higgsfield DoP. ``image_uploader`` turns a local frame
    into a URL the API can fetch; defaults to a GCS signed-URL uploader."""

    def __init__(
        self,
        settings: Settings | None = None,
        image_uploader: Callable[[Path], str] | None = None,
    ):
        self.cfg = settings or get_settings()
        if not self.cfg.higgsfield_enabled:
            raise HiggsfieldError(
                "Higgsfield not configured — set HIGGSFIELD_API_KEY "
                "(and HIGGSFIELD_PROVIDER if not the default 'higgsfield')."
            )
        self.provider = _PROVIDERS.get(self.cfg.higgsfield_provider)
        if self.provider is None:
            raise HiggsfieldError(
                f"unknown HIGGSFIELD_PROVIDER={self.cfg.higgsfield_provider!r} "
                f"(expected one of {list(_PROVIDERS)})"
            )
        self._upload = image_uploader or self._default_uploader()

    # ── frame hosting ───────────────────────────────────────────────────────
    def _default_uploader(self) -> Callable[[Path], str]:
        """Upload a frame to GCS and return a short-lived signed URL."""
        from app.services.storage import MediaStore

        store = MediaStore(self.cfg)

        def up(path: Path) -> str:
            obj = f"tours/_frames/{uuid.uuid4().hex}{Path(path).suffix or '.jpg'}"
            store.upload(Path(path), obj, content_type="image/jpeg")
            return store.signed_url(obj)

        return up

    @staticmethod
    def _as_jpeg(path: Path) -> Path:
        """DoP accepts jpg/png/webp; normalize everything to JPEG on disk so the
        uploaded frame is always a clean, API-friendly image."""
        if Path(path).suffix.lower() in (".jpg", ".jpeg"):
            return Path(path)
        from PIL import Image

        img = Image.open(path).convert("RGB")
        out = Path(path).with_suffix(".hf.jpg")
        img.save(out, format="JPEG", quality=95)
        return out

    def _frame_url(self, path: Path) -> str:
        return self._upload(self._as_jpeg(Path(path)))

    # ── HTTP ──────────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.cfg.higgsfield_api_key}",
            "Content-Type": "application/json",
        }
        if self.cfg.higgsfield_api_secret:
            h["hf-secret"] = self.cfg.higgsfield_api_secret
        return h

    def _build_body(self, start_url: str, prompt: str, aspect_ratio: str,
                    end_url: str | None) -> dict[str, Any]:
        p = self.provider
        body: dict[str, Any] = {
            "model": (
                "higgsfield/dop/image-to-video"
                if self.cfg.higgsfield_provider == "wavespeed"
                else self.cfg.higgsfield_model
            ),
            p["start_field"]: start_url,
            "prompt": prompt or _DEFAULT_PROMPT,
            "duration": self.cfg.higgsfield_clip_seconds,
            "aspect_ratio": aspect_ratio,
            "model_tier": self.cfg.higgsfield_model_tier,
        }
        if self.cfg.higgsfield_provider == "wavespeed":
            body["task_type"] = "image_to_video"
        else:
            body["task"] = "image-to-video"
        if end_url:
            body[p["end_field"]] = end_url
        if self.cfg.higgsfield_motion_id:
            body["motion_id"] = self.cfg.higgsfield_motion_id
        return body

    def _submit(self, client: httpx.Client, body: dict[str, Any]) -> str:
        url = self.cfg.higgsfield_endpoint + self.provider["submit_path"]
        r = client.post(url, json=body, headers=self._headers())
        if r.status_code == 429:
            raise RateLimited("Higgsfield 429 rate limited")
        if r.status_code >= 400:
            raise HiggsfieldError(f"submit {r.status_code}: {r.text[:300]}")
        gen_id = _first(r.json(), self.provider["id_keys"])
        if not gen_id:
            raise HiggsfieldError(f"no generation id in response: {r.text[:300]}")
        return str(gen_id)

    def _poll(self, client: httpx.Client, gen_id: str,
              poll_seconds: int, max_polls: int) -> str:
        p = self.provider
        base = self.cfg.higgsfield_endpoint
        if p["poll_query"]:
            url = base + p["poll_path"]
            params = {p["poll_query"]: gen_id}
        else:
            url = base + p["poll_path"].format(id=gen_id)
            params = None
        for _ in range(max_polls):
            time.sleep(poll_seconds)
            r = client.get(url, params=params, headers=self._headers())
            if r.status_code == 429:
                continue
            if r.status_code >= 400:
                raise HiggsfieldError(f"poll {r.status_code}: {r.text[:300]}")
            data = r.json()
            status = str(_first(data, _STATUS_KEYS) or "").lower()
            if status in _FAILED:
                raise HiggsfieldError(f"generation failed: {r.text[:300]}")
            video_url = _first(data, _VIDEO_KEYS)
            if video_url and (status in _DONE or not status):
                return str(video_url)
            if status in _DONE and not video_url:
                raise HiggsfieldError(f"completed but no video url: {r.text[:300]}")
        raise HiggsfieldError(
            f"timed out after {poll_seconds * max_polls}s waiting on {gen_id}"
        )

    @staticmethod
    def _download(video_url: str, out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(video_url, timeout=180) as resp:
            out_path.write_bytes(resp.read())
        if out_path.stat().st_size == 0:
            raise HiggsfieldError("downloaded empty video")

    # ── public API (drop-in for VeoClient.animate) ──────────────────────────
    def animate(
        self,
        image_path: Path,
        prompt: str,
        out_path: Path,
        aspect_ratio: str = "16:9",
        poll_seconds: int = 5,
        max_polls: int = 180,
        last_frame_path: Path | None = None,
    ) -> Path:
        """Generate one clip. With ``last_frame_path`` set, DoP interpolates the
        camera path from the start frame to that end frame — consecutive shots
        hand off on identical frames for a true single-take look."""
        out_path = Path(out_path)
        start_url = self._frame_url(Path(image_path))
        end_url = self._frame_url(Path(last_frame_path)) if last_frame_path else None
        body = self._build_body(start_url, prompt, aspect_ratio, end_url)

        timeout = httpx.Timeout(60.0, read=120.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                gen_id = self._submit(client, body)
                video_url = self._poll(client, gen_id, poll_seconds, max_polls)
        except RateLimited:
            raise
        except HiggsfieldError:
            raise
        except httpx.HTTPError as e:
            raise HiggsfieldError(f"http error: {e}") from None

        self._download(video_url, out_path)
        return out_path
