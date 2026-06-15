from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.db import TourDB
from app.models import IntakeRequest, IntakeSource, Tour, TourStatus
from app.routers.deps import get_db, get_store
from app.services.intake_sources import (
    IntakeError,
    fetch_photos_from_url,
    save_uploaded_photo,
)
from app.services.storage import MediaStore

router = APIRouter(prefix="/api/intake", tags=["intake"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _new_tour_id() -> str:
    return f"T-{secrets.token_hex(3).upper()}"


@router.post("", response_model=Tour)
async def create_tour(req: IntakeRequest, db: TourDB = Depends(get_db)) -> Tour:
    tour = Tour(
        id=_new_tour_id(),
        address=req.address,
        agent_name=req.agent_name,
        agent_email=req.agent_email,
        beds=req.beds,
        baths=req.baths,
        sqft=req.sqft,
        price_cents=req.price_cents,
        source=req.source,
        source_url=str(req.source_url) if req.source_url else None,
        status=TourStatus.draft,
    )
    await db.create_tour(tour)

    # Zero-touch path: pull photos from the listing / Drive URL immediately.
    if req.source in (IntakeSource.listing_url, IntakeSource.drive_url) and req.source_url:
        try:
            photos = await fetch_photos_from_url(str(req.source_url), tour.id)
        except IntakeError as e:
            await db.update_tour(tour.id, status=TourStatus.failed.value)
            raise HTTPException(422, str(e)) from None
        await db.update_tour(
            tour.id,
            photo_paths=[str(p) for p in photos],
            status=TourStatus.intake.value,
        )
        tour.photo_paths = [str(p) for p in photos]
        tour.status = TourStatus.intake

    await db.log_activity("info", "Tour created", tour.address, tour.id)
    return tour


@router.post("/{tour_id}/photos", response_model=Tour)
async def upload_photos(
    tour_id: str,
    files: list[UploadFile],
    db: TourDB = Depends(get_db),
    store: MediaStore = Depends(get_store),
) -> Tour:
    tour = await db.get_tour(tour_id)
    if tour is None:
        raise HTTPException(404, "Tour not found")
    if not files:
        raise HTTPException(422, "No files provided")

    paths = list(tour.photo_paths)
    for f in files:
        content = await f.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(422, f"{f.filename} exceeds 25MB")
        try:
            local = save_uploaded_photo(tour_id, f.filename or "photo.jpg", content)
        except IntakeError as e:
            raise HTTPException(422, str(e)) from None
        store.upload_photo(local, tour_id, len(paths))
        paths.append(str(local))

    await db.update_tour(tour_id, photo_paths=paths, status=TourStatus.intake.value)
    tour.photo_paths = paths
    tour.status = TourStatus.intake
    return tour
