"""Seed demo data into the pht_ Firestore collections.

Run:  .venv/bin/python seed_demo.py

Reuses real artifacts where they exist: the CV26126549 Veo master on GCS and
its real listing photos, plus the v1 demo clips under tours/T-*/clips/.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.cloud import firestore

from app.config import get_settings

settings = get_settings()
db = firestore.Client(project=settings.gcp_project_id)

NOW = datetime.now(timezone.utc)
REAL_PHOTOS_SRC = sorted(Path("/home/jarvis/realestate-bot/photos").glob("CV26126549_veo_*.webp"))[:6]


def ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def col(name: str):
    return db.collection(settings.collection(name))


def seed_flagship() -> None:
    """Real tour: actual Veo master on GCS + actual listing photos."""
    tour_id = "T-CV2612"
    photo_dir = settings.upload_dir / tour_id
    photo_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, src in enumerate(REAL_PHOTOS_SRC):
        dest = photo_dir / f"{i}.webp"
        shutil.copy(src, dest)
        paths.append(str(dest))

    col("tours").document(tour_id).set({
        "id": tour_id,
        "address": "27344 Main St",
        "agent_name": "Dana Keller",
        "agent_email": "dana@example.com",
        "beds": 4, "baths": 3.0, "sqft": 2400, "price_cents": 75_000_000,
        "status": "delivered",
        "source": "upload", "source_url": None,
        "photo_paths": paths,
        "master_path": "tours/CV26126549_master.mp4",
        "preview_path": "tours/CV26126549_master.mp4",
        "reel_path": None,
        "share_url": "https://storage.googleapis.com/premier-tours-media/tours/CV26126549_master.mp4",
        "veo_cost_cents": 1920,
        "created_at": ts(30), "updated_at": ts(28),
    })


DEMOS = [
    {
        "id": "T-0912", "address": "912 Marigold Ct", "agent": "Maya Brooks",
        "status": "rendering", "cost": 960, "hours": 2,
        "clips": 5, "done": 3,
    },
    {
        "id": "T-4821", "address": "4821 Pine Ridge Dr", "agent": "Leo Tran",
        "status": "ready", "cost": 1600, "hours": 8,
        "clips": 5, "done": 5,
    },
    {
        "id": "T-0063", "address": "63 Sunset Mesa", "agent": "Ana Reyes",
        "status": "failed", "cost": 320, "hours": 20,
        "clips": 5, "done": 1, "error": "Veo rate limited (429) after retries",
    },
]

ROOMS = ["front_exterior", "living_room", "kitchen", "primary_bedroom", "backyard"]


def seed_demos() -> None:
    for d in DEMOS:
        col("tours").document(d["id"]).set({
            "id": d["id"], "address": d["address"],
            "agent_name": d["agent"], "agent_email": "",
            "beds": 3, "baths": 2.0, "sqft": 1900, "price_cents": 54_900_000,
            "status": d["status"],
            "source": "upload", "source_url": None,
            "photo_paths": [],
            "master_path": None, "preview_path": None, "reel_path": None,
            "share_url": None,
            "veo_cost_cents": d["cost"],
            "created_at": ts(d["hours"] + 1), "updated_at": ts(d["hours"]),
        })

        shots = []
        for i in range(d["clips"]):
            if i < d["done"]:
                status, clip = "accepted", f"tours/{d['id']}/clips/shot{i}.mp4"
            elif d["status"] == "failed":
                status, clip = "failed", None
            elif d["status"] == "rendering" and i == d["done"]:
                status, clip = "generating", None
            else:
                status, clip = "queued", None
            shots.append({
                "idx": i, "room_type": ROOMS[i % len(ROOMS)],
                "prompt": f"Shot {i + 1} of {d['clips']} of ONE continuous, uncut FPV drone tour — "
                          f"smooth glide through {ROOMS[i % len(ROOMS)].replace('_', ' ')}, photoreal.",
                "status": status, "motion": 0.42 if status == "accepted" else 0.0,
                "qa_verdict": "consistent with source photo" if status == "accepted" else None,
                "qa_attempts": 1 if status != "queued" else 0,
                "cost_cents": 320 if status == "accepted" else 0,
                "clip_path": clip, "source_photo": None,
                "error": d.get("error") if status == "failed" else None,
            })

        job_status = {"rendering": "rendering", "ready": "done", "failed": "failed"}[d["status"]]
        col("render_jobs").document(f"{d['id']}_demo").set({
            "id": f"{d['id']}_demo", "tour_id": d["id"],
            "status": job_status,
            "stage_detail": {
                "rendering": f"Shot {d['done'] + 1}/{d['clips']} — Veo attempt 1",
                "done": "Complete", "failed": "Failed",
            }[job_status],
            "shots_total": d["clips"], "shots_done": d["done"],
            "veo_cost_cents": d["cost"], "shots": shots,
            "error": d.get("error"),
            "started_at": ts(d["hours"] + 0.5),
            "finished_at": None if job_status == "rendering" else ts(d["hours"]),
            "updated_at": ts(d["hours"]),
        })


def seed_activity() -> None:
    events = [
        ("success", "Tour delivered", "27344 Main St — 4 shots, $19.20", "T-CV2612", 28),
        ("info", "Render started", "912 Marigold Ct", "T-0912", 2.5),
        ("success", "Tour rendered", "4821 Pine Ridge Dr — 5 shots, $16.00", "T-4821", 8),
        ("danger", "Render failed", "63 Sunset Mesa — Veo rate limited (429)", "T-0063", 20),
    ]
    for kind, title, detail, tour_id, hours in events:
        col("activity").add({
            "kind": kind, "title": title, "detail": detail,
            "tour_id": tour_id, "at": ts(hours),
        })


if __name__ == "__main__":
    seed_flagship()
    seed_demos()
    seed_activity()
    print("Seeded:", settings.collection("tours"), "+ render_jobs + activity")
