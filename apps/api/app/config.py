"""Central configuration — everything secret comes from the environment.

Loads `.env` from the monorepo root. Fail-fast `require()` mirrors the v1
pipeline so misconfiguration surfaces at startup, not mid-render.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── GCP core ──────────────────────────────────────────────────────────
    gcp_project_id: str = Field(alias="GCP_PROJECT_ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION")
    gcs_bucket: str = Field(default="premier-tours-media", alias="GCS_BUCKET")

    # ── AI ────────────────────────────────────────────────────────────────
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    # Video engine. Higgsfield DoP is the default (better photoreal drone
    # motion + native start/end-frame chaining); "veo" is kept only as an
    # opt-in fallback.
    render_engine: str = Field(default="higgsfield", alias="RENDER_ENGINE")

    # ── Veo (fallback engine only) ────────────────────────────────────────
    veo_credentials_path: str = Field(default="", alias="VEO_CREDENTIALS_PATH")
    veo_model: str = Field(default="veo-3.1-generate-preview", alias="VEO_MODEL")

    # ── Higgsfield DoP (primary engine) ───────────────────────────────────
    # provider: "higgsfield" (api.higgsfield.ai) | "wavespeed"
    #           (api.wavespeed.ai reseller). Request/response shapes differ per
    #           provider; both are handled in pipeline/higgsfield.py.
    higgsfield_api_key: str = Field(default="", alias="HIGGSFIELD_API_KEY")
    higgsfield_api_secret: str = Field(default="", alias="HIGGSFIELD_API_SECRET")
    higgsfield_provider: str = Field(default="higgsfield", alias="HIGGSFIELD_PROVIDER")
    higgsfield_base_url: str = Field(default="", alias="HIGGSFIELD_BASE_URL")
    higgsfield_model: str = Field(default="dop", alias="HIGGSFIELD_MODEL")
    higgsfield_model_tier: str = Field(default="standard", alias="HIGGSFIELD_MODEL_TIER")
    # Optional DoP camera-motion preset id (UUID). Empty = let the prompt drive.
    higgsfield_motion_id: str = Field(default="", alias="HIGGSFIELD_MOTION_ID")
    higgsfield_clip_seconds: int = Field(default=5, alias="HIGGSFIELD_CLIP_SECONDS")
    # ~cents per generated clip (DoP is far cheaper than Veo). Drives the
    # print-before-you-spend estimate and the per-run cost cap.
    higgsfield_cost_per_clip_cents: int = Field(
        default=3, alias="HIGGSFIELD_COST_PER_CLIP_CENTS"
    )

    # ── Queue ─────────────────────────────────────────────────────────────
    pubsub_topic: str = Field(default="pht-render-jobs", alias="PUBSUB_TOPIC")
    pubsub_subscription: str = Field(
        default="pht-render-worker", alias="PUBSUB_SUBSCRIPTION"
    )

    # ── Data ──────────────────────────────────────────────────────────────
    firestore_prefix: str = Field(default="pht_", alias="FIRESTORE_PREFIX")
    output_dir: Path = Field(
        default=Path.home() / "premier-home-tours" / "renders", alias="OUTPUT_DIR"
    )
    upload_dir: Path = Field(
        default=Path.home() / "premier-home-tours" / "uploads", alias="UPLOAD_DIR"
    )

    # ── Email ─────────────────────────────────────────────────────────────
    email_provider: str = Field(default="", alias="EMAIL_PROVIDER")
    email_from: str = Field(default="", alias="EMAIL_FROM")
    email_smtp_user: str = Field(default="", alias="EMAIL_SMTP_USER")
    email_smtp_pass: str = Field(default="", alias="EMAIL_SMTP_PASS")
    test_recipient: str = Field(default="", alias="TEST_RECIPIENT")

    # ── Web ───────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        default="http://localhost:3000", alias="CORS_ORIGINS"
    )

    @property
    def veo_enabled(self) -> bool:
        return bool(self.google_api_key) or bool(
            self.veo_credentials_path and self.gcp_project_id
        )

    @property
    def higgsfield_enabled(self) -> bool:
        return bool(self.higgsfield_api_key)

    @property
    def higgsfield_endpoint(self) -> str:
        """Resolved base URL for the configured Higgsfield provider."""
        if self.higgsfield_base_url:
            return self.higgsfield_base_url.rstrip("/")
        return {
            "higgsfield": "https://api.higgsfield.ai",
            "wavespeed": "https://api.wavespeed.ai",
        }.get(self.higgsfield_provider, "https://api.higgsfield.ai")

    def collection(self, name: str) -> str:
        return f"{self.firestore_prefix}{name}"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.output_dir.mkdir(parents=True, exist_ok=True)
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
