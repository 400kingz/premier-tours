"""Render orchestrator (pipeline v2) — executed by the Pub/Sub worker.

This is THE bot: a manifest-driven, frame-chained, continuous drone flythrough.
There is no crossfade and no slideshow path anymore — clips hand off on identical
frames (room exit frame == transition first frame == next room entry frame), so
the result reads as one unbroken take.

Stage 0 normalize → Stage 1 classify+sequence → Stage 2 author moves+prompts →
Stage 3 generate room clips + frame-chained transitions (Higgsfield DoP) →
Stage 4 stitch (hard concat + vidstab + one LUT) → Stage 5 render master, then
derive the 9:16 reel → GCS upload → tour finalize.

Progress is written to Firestore after every state change (the API's SSE
endpoint streams it). The killswitch is re-checked before every generation so a
HARD STOP lands mid-job. Spend is printed BEFORE any generation (brief guardrail)
and generations are hard-capped per run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import get_settings
from app.db import WorkerDB
from app.learning.feedback import FeedbackMemory
from app.models import JobStatus, RenderJob, Shot, ShotStatus, TourStatus
from app.pipeline2.manifest import Manifest
from app.pipeline2.stage0_normalize import color_consistency_report, normalize
from app.pipeline2.stage1_sequence import sequence
from app.pipeline2.stage2_author import author, estimate_spend
from app.pipeline2.stage3_generate import generate
from app.pipeline2.stage4_stitch import stitch
from app.pipeline2.stage5_render import render_all
from app.services.storage import MediaStore

_feedback = FeedbackMemory()


class KillswitchEngaged(RuntimeError):
    pass


def _save(db: WorkerDB, job: RenderJob, detail: str | None = None) -> None:
    if detail is not None:
        job.stage_detail = detail
    db.save_job(job)


def _work_dir(tour_id: str) -> Path:
    return get_settings().output_dir / f"{tour_id}-v2"


def _seed_shots(job: RenderJob, manifest: Manifest) -> None:
    """Mirror the manifest's room clips onto the job so the dashboard shows the
    full plan + exact prompts before any generation."""
    job.shots = [
        Shot(idx=c.index, room_type=c.room_type, prompt=c.prompt,
             source_photo=c.raw_photo, status=ShotStatus.queued)
        for c in manifest.clips
    ]
    job.shots_total = len(job.shots)


def _sync_shot_outcomes(job: RenderJob, manifest: Manifest) -> int:
    """Reflect Stage 3 results back onto the job shots; return accepted count."""
    by_idx = {c.index: c for c in manifest.clips}
    accepted = 0
    for shot in job.shots:
        c = by_idx.get(shot.idx)
        if not c:
            continue
        shot.motion = c.motion
        shot.qa_verdict = c.qa_verdict
        if c.accepted:
            shot.status = ShotStatus.accepted
            shot.clip_path = c.generated_clip
            accepted += 1
        else:
            shot.status = ShotStatus.failed
            shot.error = c.qa_verdict or "not accepted"
    job.shots_done = accepted
    return accepted


def _record_feedback(manifest: Manifest) -> None:
    """Persist clip outcomes to the bandit memory. Never breaks a render."""
    for c in manifest.clips:
        try:
            _feedback.record(
                room_type=c.room_type,
                move=c.camera_move or c.room_type,
                prompt_fragment=(c.prompt or "")[:300],
                accepted=c.accepted,
                motion=c.motion,
                vision_score=c.motion if c.accepted else 0.0,
            )
        except Exception as e:
            print(f"[feedback] skipped {c.index}: {e}")


def run_render_job(job_id: str, tour_id: str, max_shots: int, dry_run: bool) -> None:
    settings = get_settings()
    db = WorkerDB(settings)
    store = MediaStore(settings)

    tour = db.get_tour(tour_id)
    if tour is None:
        return

    job = RenderJob(id=job_id, tour_id=tour_id, status=JobStatus.screenplay)
    _save(db, job, "Normalizing photos")
    db.update_tour(tour_id, status=TourStatus.rendering.value)
    db.log_activity("info", "Render started (continuous drone tour)", tour.address, tour_id)

    def killcheck() -> None:
        if db.killswitch_locked():
            raise KillswitchEngaged("Generation is HARD STOPPED")

    work = _work_dir(tour_id)
    cost_cents = settings.higgsfield_cost_per_clip_cents if settings.render_engine != "veo" else 8 * 40

    try:
        killcheck()
        photos = [Path(p) for p in tour.photo_paths if Path(p).exists()]
        if not photos:
            raise RuntimeError("no local photos available for this tour")

        # ── Stage 0–2: plan (deterministic, no generation) ─────────────────
        manifest = Manifest(listing_id=tour_id, address=tour.address)
        manifest = normalize(photos, manifest, work,
                             on_progress=lambda m: _save(db, job, f"normalize: {m}"))
        report = color_consistency_report(work)
        _save(db, job, f"normalized — color spread {report}")

        manifest = sequence(manifest, work,
                            on_progress=lambda m: _save(db, job, f"sequence: {m}"))
        # Cap to the requested number of rooms, keeping tour order.
        if len(manifest.clips) > max_shots:
            manifest.clips = manifest.clips[:max_shots]
            for i, c in enumerate(manifest.clips):
                c.index = i

        manifest = author(manifest, work,
                         on_progress=lambda m: _save(db, job, f"author: {m}"))
        _seed_shots(job, manifest)
        spend = estimate_spend(manifest, cost_per_clip_cents=cost_cents)
        _save(db, job, f"plan ready — {len(manifest.clips)} rooms, "
                       f"est ${spend['est_cost_usd']:.2f}")
        print("SPEND ESTIMATE:", json.dumps(spend, indent=2), flush=True)

        if dry_run:
            job.status = JobStatus.done
            job.finished_at = job.updated_at
            _save(db, job, "Dry run complete (plan only, no generation)")
            db.update_tour(tour_id, status=TourStatus.intake.value)
            return

        # ── Stage 3: generate room clips + frame-chained transitions ───────
        job.status = JobStatus.rendering
        _save(db, job, "Generating continuous flythrough")
        # Hard cap: one full pass (rooms + transitions) plus ~1 retry/room.
        n = len(manifest.clips)
        cap = max(1, 3 * n - 1)
        manifest = generate(
            manifest, work, max_generations=cap,
            on_progress=lambda m: _save(db, job, f"generate: {m}"),
            should_abort=db.killswitch_locked,
        )
        job.veo_cost_cents = manifest.gen_cost_cents       # DB spend field (generic)
        accepted = _sync_shot_outcomes(job, manifest)
        _record_feedback(manifest)
        _save(db, job, f"generated — {accepted}/{n} rooms accepted")
        killcheck()

        if accepted == 0:
            raise RuntimeError("no clips passed QA")

        # ── Stage 4–5: stitch + render (PURE ffmpeg, no model) ─────────────
        job.status = JobStatus.compositing
        _save(db, job, "Stitching continuous take")
        music_env = os.environ.get("MUSIC_PATH", "")
        music = Path(music_env) if music_env and Path(music_env).exists() else None

        stitched = stitch(manifest, work,
                          on_progress=lambda m: _save(db, job, f"stitch: {m}"))
        manifest = render_all(stitched, manifest, work, music=music,
                              on_progress=lambda m: _save(db, job, f"render: {m}"))

        # ── upload + finalize ──────────────────────────────────────────────
        job.status = JobStatus.uploading
        _save(db, job, "Uploading to Cloud Storage")
        master_obj = store.upload_final(Path(manifest.master_path), tour_id, "master")
        preview_obj = store.upload_final(Path(manifest.preview_path), tour_id, "preview")
        reel_obj = store.upload_final(Path(manifest.reel_path), tour_id, "reel")

        job.status = JobStatus.done
        job.finished_at = job.updated_at
        _save(db, job, "Complete")
        db.update_tour(
            tour_id,
            status=TourStatus.ready.value,
            master_path=master_obj,
            preview_path=preview_obj,
            reel_path=reel_obj,
            share_url=store.public_url(preview_obj),
            veo_cost_cents=manifest.gen_cost_cents,
        )
        db.log_activity(
            "success", "Tour rendered",
            f"{tour.address} — {accepted} rooms, ${manifest.gen_cost_cents / 100:.2f}",
            tour_id,
        )

    except KillswitchEngaged:
        job.status = JobStatus.failed
        job.error = "HARD STOP engaged"
        job.finished_at = job.updated_at
        _save(db, job, "Stopped by killswitch")
        db.update_tour(tour_id, status=TourStatus.failed.value)
        db.log_activity("danger", "Render stopped", "Killswitch engaged", tour_id)
    except Exception as e:
        job.status = JobStatus.failed
        job.error = str(e)[:300]
        job.finished_at = job.updated_at
        _save(db, job, "Failed")
        db.update_tour(tour_id, status=TourStatus.failed.value)
        db.log_activity("danger", "Render failed", str(e)[:200], tour_id)
