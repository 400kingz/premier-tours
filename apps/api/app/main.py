"""Premier Home Tours API.

Run with:  uvicorn app.main:app --reload --port 8000
Worker:    python -m app.worker
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import admin, events, intake, render, tours

settings = get_settings()

app = FastAPI(
    title="Premier Home Tours",
    version="2.0.0",
    description="Cinematic AI drone flythroughs from listing photos.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tours.router)
app.include_router(intake.router)
app.include_router(render.router)
app.include_router(events.router)
app.include_router(admin.router)

# Local renders + uploads served for dev preview (GCS serves production).
app.mount("/media/renders", StaticFiles(directory=str(settings.output_dir)), name="renders")
app.mount("/media/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
