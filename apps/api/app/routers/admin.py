from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db import TourDB
from app.models import (
    JobStatus,
    KillswitchRequest,
    MetricsResponse,
    TourStatus,
)
from app.routers.deps import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])

PRICE_PER_TOUR_CENTS = 12_400  # $124 blended average of the $99–199 range


@router.get("/killswitch")
async def get_killswitch(db: TourDB = Depends(get_db)) -> dict:
    return {"locked": await db.killswitch_locked()}


@router.post("/killswitch")
async def set_killswitch(req: KillswitchRequest, db: TourDB = Depends(get_db)) -> dict:
    await db.set_killswitch(req.locked)
    await db.log_activity(
        "danger" if req.locked else "success",
        "HARD STOP engaged" if req.locked else "Generation resumed",
    )
    return {"locked": req.locked}


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(db: TourDB = Depends(get_db)) -> MetricsResponse:
    tours = await db.list_tours(limit=500)
    delivered = [t for t in tours if t.status == TourStatus.delivered]
    active = await db.active_jobs()
    veo_spend = sum(t.veo_cost_cents for t in tours)
    revenue = len(delivered) * PRICE_PER_TOUR_CENTS
    rendered = [t for t in tours if t.veo_cost_cents > 0]
    avg_cost = veo_spend // len(rendered) if rendered else 0
    margin = (1 - (avg_cost / PRICE_PER_TOUR_CENTS)) * 100 if avg_cost else 0.0
    return MetricsResponse(
        revenue_cents=revenue,
        tours_delivered=len(delivered),
        in_queue=len(active),
        veo_spend_cents=veo_spend,
        avg_cost_per_tour_cents=avg_cost,
        gross_margin_pct=round(margin, 1),
    )


@router.get("/queue")
async def render_queue(db: TourDB = Depends(get_db)) -> list[dict]:
    jobs = await db.recent_jobs(limit=20)
    return [j.model_dump(mode="json", exclude={"shots"}) for j in jobs]


@router.get("/activity")
async def activity(db: TourDB = Depends(get_db)) -> list[dict]:
    return await db.recent_activity()
