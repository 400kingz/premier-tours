from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.db import TourDB
from app.models import RenderJob, Tour
from app.routers.deps import get_db

router = APIRouter(prefix="/api/tours", tags=["tours"])


@router.get("", response_model=list[Tour])
async def list_tours(db: TourDB = Depends(get_db)) -> list[Tour]:
    return await db.list_tours()


@router.get("/{tour_id}", response_model=Tour)
async def get_tour(tour_id: str, db: TourDB = Depends(get_db)) -> Tour:
    tour = await db.get_tour(tour_id)
    if tour is None:
        raise HTTPException(404, "Tour not found")
    return tour


@router.get("/{tour_id}/job", response_model=RenderJob | None)
async def latest_job(tour_id: str, db: TourDB = Depends(get_db)) -> RenderJob | None:
    return await db.latest_job_for_tour(tour_id)
