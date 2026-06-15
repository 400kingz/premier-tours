"""Server-Sent Events — live render progress without page refreshes.

The worker writes job state to Firestore; this endpoint polls the job document
and pushes a `job` event whenever `updated_at` advances. Poll interval is 1s —
imperceptible to the UI, trivial load on Firestore.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.db import TourDB
from app.models import JobStatus
from app.routers.deps import get_db

router = APIRouter(prefix="/api/events", tags=["events"])

POLL_SECONDS = 1.0
TERMINAL = {JobStatus.done, JobStatus.failed}


@router.get("/tours/{tour_id}")
async def tour_events(
    tour_id: str, request: Request, db: TourDB = Depends(get_db)
) -> StreamingResponse:
    async def stream():
        last_stamp: str | None = None
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                return
            job = await db.latest_job_for_tour(tour_id)
            if job is not None:
                stamp = job.updated_at.isoformat()
                if stamp != last_stamp:
                    last_stamp = stamp
                    payload = job.model_dump(mode="json")
                    yield f"event: job\ndata: {json.dumps(payload)}\n\n"
                if job.status in TERMINAL:
                    tour = await db.get_tour(tour_id)
                    if tour:
                        yield f"event: tour\ndata: {tour.model_dump_json()}\n\n"
                    yield "event: end\ndata: {}\n\n"
                    return
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
