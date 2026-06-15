"""Premier Home Tours — local MVP (Phase 1, agent-assisted, no GCP).

Upload listing photos → plan (Stage 0-2, Gemini, zero video spend) → the AGENT
generates each segment via the Higgsfield MCP → finish (QA + stitch + render) →
master + reel previewed in the browser.

Reuses the PROVEN pipeline (app.pipeline2.agent_runner.plan_mcp / finish_mcp).
No Firestore / Pub-Sub / GCS — local JSON job store + local file serving.

Run (from repo root, using the api venv):
  apps/api/.venv/bin/uvicorn apps.mvp.server:app --port 8090
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "api"))          # import the `app` package

from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings                      # noqa: E402
from app.pipeline2.agent_runner import plan_mcp, finish_mcp, work_dir  # noqa: E402

settings = get_settings()
STATIC = Path(__file__).parent / "static"
JOBS_FILE = settings.output_dir / "mvp_jobs.json"
_lock = threading.Lock()

app = FastAPI(title="Premier Home Tours — MVP")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── tiny JSON job store ───────────────────────────────────────────────────────
def _load() -> dict:
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text())
    return {}


def _save(jobs: dict) -> None:
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(jobs, indent=2))


def _update(job_id: str, **fields) -> dict:
    with _lock:
        jobs = _load()
        jobs.setdefault(job_id, {})["id"] = job_id
        jobs[job_id].update(fields, updated=time.time())
        _save(jobs)
        return jobs[job_id]


def _media_url(p: str | None) -> str | None:
    if not p:
        return None
    p = Path(p)
    for root, prefix in ((settings.output_dir, "/media/renders"),
                         (settings.upload_dir, "/media/uploads")):
        try:
            return prefix + "/" + str(p.relative_to(root))
        except ValueError:
            continue
    return None


# ── background work ───────────────────────────────────────────────────────────
def _run_plan(job_id: str, address: str, photos: list[Path], rooms_per_shot: int):
    try:
        _update(job_id, status="planning", stage="Stage 0-2: normalize · classify · author")
        jobs = plan_mcp(job_id, address, photos, rooms_per_shot=rooms_per_shot)
        est_clips = len(jobs)
        cents = est_clips * settings.higgsfield_cost_per_clip_cents
        _update(job_id, status="ready", stage="Planned — awaiting generation",
                worklist=jobs, n_shots=est_clips,
                est_spend_usd=round(cents / 100, 2))
    except Exception as e:  # surface the failure to the UI
        _update(job_id, status="error", stage=f"plan failed: {e}")


def _run_finish(job_id: str, rooms_per_shot: int):
    try:
        _update(job_id, status="stitching", stage="Stage 4-5: QA · stitch · render")
        m = finish_mcp(job_id, rooms_per_shot=rooms_per_shot)
        _update(job_id, status="done", stage="Done",
                master_url=_media_url(str(m.master_path)),
                reel_url=_media_url(str(m.reel_path)))
    except Exception as e:
        _update(job_id, status="error", stage=f"finish failed: {e}")


def _generated_count(job: dict) -> int:
    return sum(1 for j in job.get("worklist", []) if Path(j["output"]).exists())


# ── API ───────────────────────────────────────────────────────────────────────
@app.post("/api/jobs")
async def create_job(address: str = Form("Untitled listing"),
                     rooms_per_shot: int = Form(3),
                     files: list[UploadFile] = None):
    if not files:
        raise HTTPException(422, "Upload at least 3 photos")
    job_id = "mvp-" + uuid.uuid4().hex[:8]
    dest = settings.upload_dir / job_id
    dest.mkdir(parents=True, exist_ok=True)
    photos = []
    for i, f in enumerate(files):
        out = dest / f"{i:02d}{Path(f.filename or '.jpg').suffix or '.jpg'}"
        out.write_bytes(await f.read())
        photos.append(out)
    _update(job_id, status="uploaded", stage="Photos received",
            address=address, n_photos=len(photos),
            photo_urls=[_media_url(str(p)) for p in photos],
            rooms_per_shot=rooms_per_shot, created=time.time())
    threading.Thread(target=_run_plan, args=(job_id, address, photos, rooms_per_shot),
                     daemon=True).start()
    return {"id": job_id}


@app.post("/api/jobs/{job_id}/finish")
async def finish(job_id: str):
    jobs = _load()
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    threading.Thread(target=_run_finish, args=(job_id, jobs[job_id].get("rooms_per_shot", 3)),
                     daemon=True).start()
    return {"ok": True}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    jobs = _load()
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    job = dict(job)
    job["generated"] = _generated_count(job)
    return job


@app.get("/api/jobs")
async def list_jobs():
    jobs = _load()
    out = sorted(jobs.values(), key=lambda j: j.get("created", 0), reverse=True)
    for j in out:
        j["generated"] = _generated_count(j)
    return out[:25]


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/media/renders", StaticFiles(directory=str(settings.output_dir)), name="renders")
app.mount("/media/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")
app.mount("/", StaticFiles(directory=str(STATIC)), name="static")
