"""Pydantic domain models — the single source of truth for API + worker state."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, HttpUrl


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────

class TourStatus(str, Enum):
    draft = "draft"
    intake = "intake"
    rendering = "rendering"
    ready = "ready"
    delivered = "delivered"
    failed = "failed"


class JobStatus(str, Enum):
    queued = "queued"
    screenplay = "screenplay"
    rendering = "rendering"
    compositing = "compositing"
    uploading = "uploading"
    done = "done"
    failed = "failed"


class ShotStatus(str, Enum):
    queued = "queued"
    generating = "generating"
    qa = "qa"
    accepted = "accepted"
    rejected = "rejected"
    failed = "failed"


class IntakeSource(str, Enum):
    upload = "upload"
    listing_url = "listing_url"
    drive_url = "drive_url"


# ── Domain models ──────────────────────────────────────────────────────────

class Shot(BaseModel):
    idx: int
    room_type: str = "unknown"
    prompt: str = ""
    status: ShotStatus = ShotStatus.queued
    motion: float = 0.0
    qa_verdict: Optional[str] = None       # hallucination-gate explanation
    qa_attempts: int = 0
    cost_cents: int = 0
    clip_path: Optional[str] = None        # GCS object path or local path
    source_photo: Optional[str] = None
    error: Optional[str] = None


class RenderJob(BaseModel):
    id: str
    tour_id: str
    status: JobStatus = JobStatus.queued
    stage_detail: str = ""                 # human-readable progress line
    shots_total: int = 0
    shots_done: int = 0
    veo_cost_cents: int = 0
    shots: list[Shot] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)


class Tour(BaseModel):
    id: str
    address: str
    agent_name: str = ""
    agent_email: str = ""
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    price_cents: Optional[int] = None
    status: TourStatus = TourStatus.draft
    source: IntakeSource = IntakeSource.upload
    source_url: Optional[str] = None
    photo_paths: list[str] = Field(default_factory=list)
    master_path: Optional[str] = None      # 16:9 MLS-compliant master
    preview_path: Optional[str] = None     # watermarked preview
    reel_path: Optional[str] = None        # 9:16 social reel
    share_url: Optional[str] = None
    veo_cost_cents: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ── API request/response shapes ────────────────────────────────────────────

class IntakeRequest(BaseModel):
    address: str = Field(min_length=3, max_length=200)
    agent_name: str = ""
    agent_email: str = ""
    source: IntakeSource = IntakeSource.upload
    source_url: Optional[HttpUrl] = None
    beds: Optional[int] = Field(default=None, ge=0, le=50)
    baths: Optional[float] = Field(default=None, ge=0, le=50)
    sqft: Optional[int] = Field(default=None, ge=0)
    price_cents: Optional[int] = Field(default=None, ge=0)


class RenderRequest(BaseModel):
    tour_id: str
    max_shots: int = Field(default=6, ge=1, le=8)
    dry_run: bool = False                  # screenplay only, no Veo spend


class KillswitchRequest(BaseModel):
    locked: bool


class MetricsResponse(BaseModel):
    revenue_cents: int
    tours_delivered: int
    in_queue: int
    veo_spend_cents: int
    avg_cost_per_tour_cents: int
    gross_margin_pct: float
