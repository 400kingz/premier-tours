# Premier Home Tours — v2

Cinematic AI drone flythroughs from listing photos. A listing's photos in, a
~22-second FPV master (16:9, MLS-compliant) plus a 9:16 social reel out.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 14 (App Router), Tailwind, Zustand, framer-motion, cmdk |
| API | FastAPI (async, strict Pydantic) |
| Database | Firestore `(default)` — collections prefixed `pht_` |
| Queue | Cloud Pub/Sub — topic `pht-render-jobs`, sub `pht-render-worker` |
| Media | GCS bucket `premier-tours-media` |
| AI | Gemini 2.5 Flash (screenplay + QA vision), Veo (image→video, Vertex AI) |
| Video | FFmpeg — FPV whip transitions, social reel, watermarking |

## Architecture

```
Next.js (3000)
   │  REST + SSE
   ▼
FastAPI (8000) ──publish──▶ Pub/Sub topic ──pull──▶ Worker (app.worker)
   │                                                  │
   │◀──── poll job doc ── Firestore (pht_*) ◀── write progress
   │                                                  │
   └── SSE → browser              Veo → QA gates → FFmpeg → GCS
```

- **Screenplay**: Gemini Vision classifies each photo (room type, features,
  hero score), curates the top shots, orders them into a walkthrough, and
  chains scenes — each scene's Veo call gets the *next* scene's photo as its
  end frame, so clips hand off as one continuous flight.
- **QA gates**: mechanical (size/duration/motion/SSIM-dedupe) plus a
  hallucination-aware vision gate — Gemini compares sampled clip frames
  against the source photo and rejects architectural mutations. Max 3
  generation attempts per shot with prompt adjustment between attempts.
- **FPV compositing**: no hard cuts. Junctions are whip transitions — last
  0.6s of clip A + first 0.6s of clip B speed-ramped to 300% with directional
  motion blur (`tmix` + horizontal-dominant `gblur`).
- **Killswitch**: `POST /api/admin/killswitch {locked}` — new renders return
  HTTP 423; in-flight jobs halt before their next Veo call. State lives in
  Firestore `pht_config/generation`.

## Run locally

```bash
make install   # one-time: venv + npm install
make dev       # API :8000 + worker + web :3000 in one terminal
make seed      # demo data (idempotent)
```

Or individually: `make api`, `make worker`, `make web`.

- Web: http://localhost:3000 (⌘K command palette)
- API docs: http://localhost:8000/docs

## Configuration

All secrets in `.env` at the repo root (see `app/config.py` for every knob).
Local auth uses gcloud ADC for Firestore/Pub/Sub/GCS and the Vertex SA key
(`VEO_CREDENTIALS_PATH`) for Veo.

`MUSIC_PATH=/path/to/ambient.mp3` (optional) adds a loudness-normalized audio
bed to masters and reels; without it output is silent-ambient.

## Cost controls

- `dry_run: true` on `POST /api/render` → screenplay only, zero Veo spend.
- Veo ≈ $3.20/clip (8s × $0.40/s); a 5-shot tour ≈ $16 + retries.
- The killswitch is checked before *every* Veo submission.

## v1

The proven MVP lives at `~/realestate-tours` (FastAPI + Jinja2 admin,
deployed on Cloud Run as `premier-tours`). Its pipeline modules were ported
here; v1 remains untouched and live.
