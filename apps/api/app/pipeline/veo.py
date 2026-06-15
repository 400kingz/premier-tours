"""Veo image-to-video — Vertex AI (SA key, billed) with AI Studio fallback.

Ported from v1 (proven working, including first+last frame interpolation on
veo-3.1 and graceful degradation when a model rejects last_frame).
"""
from __future__ import annotations

import io
import os
import time
from pathlib import Path

from app.config import Settings, get_settings

_DEFAULT_PROMPT = (
    "Smooth cinematic drone shot of this property, gentle aerial push-in, "
    "camera glides forward slowly revealing the space, stable horizon, "
    "natural daylight, golden hour warm lighting, photoreal real estate video, "
    "24fps, professional quality, no text overlay, no watermarks"
)


class VeoError(RuntimeError):
    pass


class RateLimited(VeoError):
    pass


class VeoClient:
    def __init__(self, settings: Settings | None = None):
        self.cfg = settings or get_settings()
        if not self.cfg.veo_enabled:
            raise VeoError(
                "Veo not configured — set GOOGLE_API_KEY or "
                "VEO_CREDENTIALS_PATH + GCP_PROJECT_ID"
            )
        self._use_vertex = bool(self.cfg.veo_credentials_path)
        self._client = None
        self._types = None

    def _genai(self):
        if self._client is None:
            import google.genai as genai
            from google.genai import types

            self._types = types
            if self._use_vertex:
                # Pass SA credentials explicitly — NEVER mutate the process-wide
                # GOOGLE_APPLICATION_CREDENTIALS env var. The worker is long-lived
                # and Firestore/Storage clients created later would otherwise
                # inherit this Veo-only SA (no Firestore perms) → 403.
                from google.oauth2 import service_account

                creds = service_account.Credentials.from_service_account_file(
                    str(Path(self.cfg.veo_credentials_path).resolve()),
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                self._client = genai.Client(
                    vertexai=True,
                    project=self.cfg.gcp_project_id,
                    location=self.cfg.gcp_location,
                    credentials=creds,
                )
            else:
                self._client = genai.Client(api_key=self.cfg.google_api_key)
        return self._client

    @staticmethod
    def _jpeg_bytes(image_path: Path) -> bytes:
        # Veo only accepts JPEG/PNG (not WebP) — normalize everything to JPEG.
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()

    def animate(
        self,
        image_path: Path,
        prompt: str,
        out_path: Path,
        aspect_ratio: str = "16:9",
        poll_seconds: int = 5,
        max_polls: int = 120,
        last_frame_path: Path | None = None,
    ) -> Path:
        """Generate one clip. With last_frame_path, Veo interpolates the camera
        path from first frame to final frame — consecutive shots hand off
        seamlessly (requires veo-3.1 / veo-2.0)."""
        client = self._genai()
        types = self._types
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        base_config: dict = {"aspect_ratio": aspect_ratio, "number_of_videos": 1}
        last_frame = (
            types.Image(
                image_bytes=self._jpeg_bytes(Path(last_frame_path)),
                mime_type="image/jpeg",
            )
            if last_frame_path is not None
            else None
        )
        source = types.GenerateVideosSource(
            prompt=prompt or _DEFAULT_PROMPT,
            image=types.Image(
                image_bytes=self._jpeg_bytes(Path(image_path)), mime_type="image/jpeg"
            ),
        )

        def submit_and_poll(with_last_frame: bool):
            config = dict(base_config)
            if with_last_frame and last_frame is not None:
                config["last_frame"] = last_frame
            op = client.models.generate_videos(
                model=self.cfg.veo_model,
                source=source,
                config=types.GenerateVideosConfig(**config),
            )
            for _ in range(max_polls):
                time.sleep(poll_seconds)
                op = client.operations.get(op)
                if op.done:
                    break
            else:
                raise VeoError(f"Timed out after {poll_seconds * max_polls}s")
            return op

        def is_interp_unsupported(msg: str) -> bool:
            m = msg.lower()
            return any(
                t in m
                for t in ("last_frame", "lastframe", "invalid_argument",
                          "not supported by this model", "failed_precondition")
            )

        try:
            operation = submit_and_poll(with_last_frame=True)
            if operation.error:
                # Some models reject interpolation only at poll time
                # (FAILED_PRECONDITION). Retry once as single-image.
                if last_frame is not None and is_interp_unsupported(str(operation.error)):
                    operation = submit_and_poll(with_last_frame=False)
                else:
                    raise VeoError(str(operation.error))
        except VeoError:
            raise
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise RateLimited(msg) from None
            if last_frame is not None and is_interp_unsupported(msg):
                operation = submit_and_poll(with_last_frame=False)
            else:
                raise VeoError(msg) from None

        if operation.error:
            raise VeoError(str(operation.error))

        result = operation.result
        if not result or not result.generated_videos:
            raise VeoError("No videos in response")

        video = result.generated_videos[0].video
        if video.video_bytes:
            out_path.write_bytes(video.video_bytes)
        elif video.uri:
            import urllib.request

            with urllib.request.urlopen(video.uri, timeout=120) as dr:
                out_path.write_bytes(dr.read())
        else:
            raise VeoError("No video bytes or URI in response")

        if out_path.stat().st_size == 0:
            raise VeoError("Downloaded empty video")
        return out_path
