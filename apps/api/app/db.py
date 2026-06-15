"""Firestore data layer — async client for the API, sync client for the worker.

Collections are prefixed (`pht_` by default) so dev/prod can share a database
without collisions, mirroring the v1 `TOURS_DB` convention.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from google.cloud import firestore

from app.config import Settings, get_settings
from app.models import JobStatus, RenderJob, Shot, Tour, TourStatus, utcnow


class TourDB:
    """Async Firestore access for the FastAPI layer."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = firestore.AsyncClient(project=self.settings.gcp_project_id)

    def _col(self, name: str):
        return self._client.collection(self.settings.collection(name))

    # ── Tours ─────────────────────────────────────────────────────────────

    async def create_tour(self, tour: Tour) -> Tour:
        await self._col("tours").document(tour.id).set(tour.model_dump(mode="json"))
        return tour

    async def get_tour(self, tour_id: str) -> Optional[Tour]:
        snap = await self._col("tours").document(tour_id).get()
        return Tour(**snap.to_dict()) if snap.exists else None

    async def update_tour(self, tour_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow().isoformat()
        await self._col("tours").document(tour_id).update(fields)

    async def list_tours(self, limit: int = 100) -> list[Tour]:
        q = (
            self._col("tours")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [Tour(**d.to_dict()) async for d in q.stream()]

    # ── Render jobs ───────────────────────────────────────────────────────

    async def get_job(self, job_id: str) -> Optional[RenderJob]:
        snap = await self._col("render_jobs").document(job_id).get()
        return RenderJob(**snap.to_dict()) if snap.exists else None

    async def latest_job_for_tour(self, tour_id: str) -> Optional[RenderJob]:
        # No order_by: avoids a composite-index requirement; a tour only ever
        # has a handful of jobs, so sorting client-side is free.
        q = self._col("render_jobs").where("tour_id", "==", tour_id).limit(20)
        jobs = [RenderJob(**d.to_dict()) async for d in q.stream()]
        return max(jobs, key=lambda j: j.started_at) if jobs else None

    async def create_job(self, job: RenderJob) -> RenderJob:
        await self._col("render_jobs").document(job.id).set(
            job.model_dump(mode="json")
        )
        return job

    async def active_jobs(self) -> list[RenderJob]:
        active = [s.value for s in JobStatus if s not in (JobStatus.done, JobStatus.failed)]
        q = self._col("render_jobs").where("status", "in", active).limit(50)
        return [RenderJob(**d.to_dict()) async for d in q.stream()]

    async def recent_jobs(self, limit: int = 25) -> list[RenderJob]:
        q = (
            self._col("render_jobs")
            .order_by("started_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [RenderJob(**d.to_dict()) async for d in q.stream()]

    # ── Config / killswitch ───────────────────────────────────────────────

    async def killswitch_locked(self) -> bool:
        snap = await self._col("config").document("generation").get()
        return bool(snap.to_dict().get("locked")) if snap.exists else False

    async def set_killswitch(self, locked: bool) -> None:
        await self._col("config").document("generation").set(
            {"locked": locked, "updated_at": utcnow().isoformat()}
        )

    # ── Activity feed ─────────────────────────────────────────────────────

    async def log_activity(
        self, kind: str, title: str, detail: str = "", tour_id: str | None = None
    ) -> None:
        await self._col("activity").add(
            {
                "kind": kind,  # info | success | danger
                "title": title,
                "detail": detail,
                "tour_id": tour_id,
                "at": utcnow().isoformat(),
            }
        )

    async def recent_activity(self, limit: int = 50) -> list[dict]:
        q = (
            self._col("activity")
            .order_by("at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [d.to_dict() async for d in q.stream()]


class WorkerDB:
    """Sync Firestore access for the Pub/Sub worker process."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = firestore.Client(project=self.settings.gcp_project_id)

    def _col(self, name: str):
        return self._client.collection(self.settings.collection(name))

    def killswitch_locked(self) -> bool:
        snap = self._col("config").document("generation").get()
        return bool(snap.to_dict().get("locked")) if snap.exists else False

    def get_tour(self, tour_id: str) -> Optional[Tour]:
        snap = self._col("tours").document(tour_id).get()
        return Tour(**snap.to_dict()) if snap.exists else None

    def update_tour(self, tour_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow().isoformat()
        self._col("tours").document(tour_id).update(fields)

    def save_job(self, job: RenderJob) -> None:
        job.updated_at = utcnow()
        self._col("render_jobs").document(job.id).set(job.model_dump(mode="json"))

    def log_activity(
        self, kind: str, title: str, detail: str = "", tour_id: str | None = None
    ) -> None:
        self._col("activity").add(
            {
                "kind": kind,
                "title": title,
                "detail": detail,
                "tour_id": tour_id,
                "at": utcnow().isoformat(),
            }
        )
