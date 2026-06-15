"""Shared Gemini client — Vertex AI (SA key, billed) first, AI Studio fallback.

The AI Studio key is prepaid and can run dry mid-pipeline; the Vertex path
bills the project and matches how Veo is already authenticated.
"""
from __future__ import annotations

from pathlib import Path

from google import genai

from app.config import get_settings

_client: genai.Client | None = None


def gemini_client() -> genai.Client:
    global _client
    if _client is None:
        cfg = get_settings()
        if cfg.veo_credentials_path and Path(cfg.veo_credentials_path).exists():
            # Explicit SA credentials — do NOT touch GOOGLE_APPLICATION_CREDENTIALS.
            # Mutating it process-wide would make later Firestore/Storage clients
            # authenticate as this Veo-only SA (no Firestore perms) → 403.
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                str(Path(cfg.veo_credentials_path).resolve()),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            _client = genai.Client(
                vertexai=True,
                project=cfg.gcp_project_id,
                location=cfg.gcp_location,
                credentials=creds,
            )
        else:
            _client = genai.Client(api_key=cfg.google_api_key)
    return _client
