from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException

from app.db import TourDB
from app.models import JobStatus, RenderJob, RenderRequest
from app.queue import RenderQueue
from app.routers.deps import get_db, get_queue

router = APIRouter(prefix="/api/render", tags=["render"])


@router.post("", response_model=RenderJob)
async def start_render(
    req: RenderRequest,
    db: TourDB = Depends(get_db),
    queue: RenderQueue = Depends(get_queue),
) -> RenderJob:
    if await db.killswitch_locked():
        raise HTTPException(423, "Generation is HARD STOPPED")

    tour = await db.get_tour(req.tour_id)
    if tour is None:
        raise HTTPException(404, "Tour not found")
    if not tour.photo_paths:
        raise HTTPException(422, "Tour has no photos — upload or intake first")

    job = RenderJob(
        id=f"{req.tour_id}_{secrets.token_hex(4)}",
        tour_id=req.tour_id,
        status=JobStatus.queued,
        stage_detail="Queued",
    )
    await db.create_job(job)
    queue.publish_render(job.id, req.tour_id, req.max_shots, req.dry_run)
    await db.log_activity("info", "Render queued", tour.address, tour.id)
    return job
