"""Media storage — GCS in production, with deterministic object layout.

Layout: tours/{tour_id}/photos/{n}.jpg, tours/{tour_id}/clips/shot{n}.mp4,
tours/{tour_id}/master.mp4 | preview.mp4 | reel.mp4
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from google.cloud import storage

from app.config import Settings, get_settings

PUBLIC_BASE = "https://storage.googleapis.com"


class MediaStore:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = storage.Client(project=self.settings.gcp_project_id)
        self._bucket = self._client.bucket(self.settings.gcs_bucket)

    def upload(self, local: Path, object_path: str, content_type: str | None = None) -> str:
        blob = self._bucket.blob(object_path)
        blob.upload_from_filename(str(local), content_type=content_type)
        return object_path

    def public_url(self, object_path: str) -> str:
        return f"{PUBLIC_BASE}/{self.settings.gcs_bucket}/{object_path}"

    def signed_url(self, object_path: str, minutes: int = 120) -> str:
        """Time-limited read URL — lets an external API (Higgsfield DoP) fetch a
        frame without making the whole bucket public. Falls back to the public
        URL if the credentials can't sign (e.g. ADC without a private key)."""
        try:
            blob = self._bucket.blob(object_path)
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=minutes),
                method="GET",
            )
        except Exception:
            return self.public_url(object_path)

    def upload_photo(self, local: Path, tour_id: str, idx: int) -> str:
        ext = local.suffix.lower() or ".jpg"
        return self.upload(
            local, f"tours/{tour_id}/photos/{idx}{ext}",
            content_type=f"image/{'jpeg' if ext in ('.jpg', '.jpeg') else ext.lstrip('.')}",
        )

    def upload_clip(self, local: Path, tour_id: str, idx: int) -> str:
        return self.upload(
            local, f"tours/{tour_id}/clips/shot{idx}.mp4", content_type="video/mp4"
        )

    def upload_final(self, local: Path, tour_id: str, kind: str) -> str:
        # kind: master | preview | reel
        return self.upload(
            local, f"tours/{tour_id}/{kind}.mp4", content_type="video/mp4"
        )
