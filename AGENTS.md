# AGENTS.md — how the drone-tour pipeline works (read before any render)

This is the operating manual for any agent (Claude/Hermes) that runs Premier
Home Tours generation. It consolidates `PIPELINE_BRIEF.md` plus the hard-won
empirical findings. **The deterministic stages are code; only classify /
sequence / prompt-author / generate use a model. Never improvise the code stages.**

## What we make
A folder of listing photos → one continuous-feeling FPV drone flythrough, as:
- **16:9 master** — unbranded, MLS-compliant (canonical)
- **9:16 reel** — derived from the master (saliency crop + music + captions)

## The one big lesson (why the architecture is what it is)
We tried per-room clips + separate transition clips chained on exit frames.
**Seedance 2.0 treats start/end frames as _soft references_, not pinned frames**
(a clip's first frame only ~0.6 SSIM-matches its start_image), so hard-concat of
many short clips shows visible seams. **The fix that works: fewer, LONGER single
shots** — each segment is one unbroken take covering ~3 rooms (up to 15s),
joined at as few seams as possible. This is `mcp_engine.segment_jobs()`.

## The proven generation flow (3 steps; agent in the middle)
The Higgsfield MCP is authenticated through the **agent's** session, so generation
cannot run in a headless worker. Run it as:

1. **`plan-mcp`** (CODE, no spend):
   `python -m app.pipeline2.agent_runner plan-mcp <id> "<address>" "<glob>" [rooms_per_shot=3]`
   Runs Stage 0 normalize → Stage 1 sequence (Gemini classify+order) → Stage 2
   author → `segment_jobs()` → writes `renders/<id>-mcp/worklist.json`.

2. **AGENT generates each worklist item** via Higgsfield MCP tools:
   - `media_upload` (or `media_upload_widget`) the `start_frame` → PUT bytes → `media_confirm`. Same for `end_frame` if present.
   - `generate_video` model **`seedance_2_0`**, role `start_image` (+ `end_image` if present), the item's `prompt`, duration ≤ 15s.
   - `job_status` poll until done → download `rawUrl` to the item's `output` path.
   - **NSFW retry policy:** `job_status` returns `nsfw` as a frequent FALSE positive on real-estate prompts (~2/4 in testing). Treat `nsfw`/`failed` as failure and re-submit the SAME shot **up to 2×**, lightly rephrasing: drop trigger words like "luxury" / "front door opens"; keep plain "continuous real-estate drone flythrough" language. **Never loop more than 2 retries per shot.**

3. **`finish-mcp`** (CODE):
   `python -m app.pipeline2.agent_runner finish-mcp <id> [rooms_per_shot]`
   QA each downloaded segment → Stage 4 stitch (concat + `vidstab` + shared LUT)
   → Stage 5 render → **master.mp4 + reel.mp4**.

## Worklist schema (the agent's contract)
`renders/<id>-mcp/worklist.json` = list of segment jobs:
```json
{ "output": "…/clips/seg_00.mp4", "start_frame": "…/normalized/0.jpg",
  "end_frame": "…/normalized/2.jpg | null", "room_types": ["foyer","living","kitchen"],
  "prompt": "One continuous cinematic FPV drone flythrough …" }
```
A clip already on disk is **skipped** (idempotent cost guard). Never regenerate.

## Camera vocabulary (fixed — no free-form motion)
Continuous forward glide through doorways, steady gimbal, constant slow speed,
lateral parallax, level/stable horizon. **No deep push-ins** (they hallucinate
geometry), no rotation-heavy moves, no people, no text/watermark. Bright, natural,
clean real-estate color grade.

## Tour grammar (Stage 1 ordering)
approach → front exterior → foyer → main living → kitchen → bedrooms → baths →
outdoor/backyard. Deterministic: same inputs → same sequence.

## Cost & safety guardrails (you have live keys)
- **Print the spend estimate BEFORE generating** (`stage2_author.estimate_spend`).
- Higgsfield DoP/Seedance ≈ a few ¢/clip — far cheaper than Veo (~$3.20/clip).
- NEVER regenerate an existing clip. HARD CAP generations per run; pause for
  approval beyond it. Max 2 retries per shot — never loop.
- Master first, reel derived — never generate the two independently.

## Map of the code
- `apps/api/app/pipeline2/` — stages 0-5, `manifest.py` (source of truth),
  `mcp_engine.py` (segment_jobs + QA ingest), `agent_runner.py` (plan/finish).
- `apps/api/app/pipeline/` — `higgsfield.py` (headless HTTP client, Phase-2),
  `gemini.py` (classify/QA vision), `qa.py` (mechanical + hallucination gates).
- `apps/mvp/` — the local upload→video dashboard (Phase-1 wrapper, no GCP).
- `apps/api` + `apps/web` — the GCP production stack (Firestore/PubSub/GCS).
