# Premier Home Tours — Flythrough Pipeline: Implementation Brief

> Task spec for the implementing agent. Read this fully before writing code.
> Build against ONE real test listing end-to-end before generalizing.

## Objective
Turn a folder of real-estate listing photos into a single continuous-feeling FPV
drone flythrough. Produce two renders:
- a 16:9 **unbranded, MLS-compliant master** (canonical)
- a 9:16 **music-cut social reel**, derived from the master

## Definition of done (acceptance criteria)
- One command: `folder of photos in → both videos out`.
- The flythrough reads as one continuous shot — no visible crossfade-style room cuts.
- Color and exposure are consistent across the entire video.
- Ordering is deterministic: same inputs → same sequence every run.
- The single real test listing passes end-to-end before any generalization.

## Hard architectural rules — DO NOT deviate
1. **Split deterministic work from judgment work.** Frame extraction, color
   normalization, stitching, stabilization, and encoding are PURE CODE
   (FFmpeg / OpenCV). They are never model-driven and never improvised. Only
   scene classification, tour sequencing, and prompt authoring use a model.
2. **The manifest JSON is the single source of truth.** Every stage reads it and
   writes it. No state passed implicitly between stages. Schema below.
3. **Continuity comes from frame-chaining, NOT crossfades.** For each room:
   generate the clip, extract its final frame, then use **Veo 3.1 first-last-frame
   mode** to interpolate a transition clip from room A's exit frame to room B's
   entry frame. The last frame of one clip MUST be the first frame of the next.
   Never crossfade independent clips.
4. **Constrained camera vocabulary.** A fixed move set assigned by room type, with
   identical lens/motion language in every prompt. No free-form motion. Prefer
   lateral parallax / shallow orbit over deep push-ins (deep push-ins cause
   geometry hallucination).
5. **Master first, reel derived.** Render the clean 16:9 master as canonical, then
   derive the 9:16 reel from it (saliency crop + beat-synced cuts + music +
   captions). Never generate the two independently.

## Build order — STOP after each stage, show me the output, then proceed
1. **Stage 0 — Intake + normalization.** Dedupe, drop blurry/low-res, histogram-
   match exposure/white balance to a reference photo, de-warp ultra-wides, crop to
   a consistent virtual lens, upscale to clean 1080p+. *Verify: stills are color-
   consistent.*
2. **Stage 1 — Classify + sequence.** Vision model tags each photo (exterior-front,
   foyer, living, kitchen, primary-bed, bath, backyard…) and orders into tour
   grammar: approach → front door → foyer → main living → kitchen → bedrooms →
   baths → outdoor. Write manifest. *Verify: order is sane.*
3. **Stage 2 — Assign moves + author prompts.** Per room_type, assign a move from
   the fixed vocabulary and write the full prompt into the manifest. *Verify:
   prompts read consistently.*
4. **Stage 3 — Generation + frame-chaining.** Generate room clips, extract exit
   frames, generate first-last-frame transition clips. **Start with the fast/720p
   Veo variant on a 2–3 clip subset.** *Verify: seams are invisible.*
5. **Stage 4 — Stitch.** FFmpeg concat, cut on dark/doorway frames, one
   stabilization pass (`vidstab`), one shared LUT across the whole sequence.
6. **Stage 5 — Render.** 16:9 master, then derive 9:16 reel.

## Manifest schema (the contract between stages)
```json
{
  "listing_id": "string",
  "reference_photo": "path",
  "render": { "master": {"aspect": "16:9", "branded": false},
              "reel":   {"aspect": "9:16", "music": "path", "captions": true} },
  "clips": [
    {
      "index": 0,
      "photo": "path/to/normalized.jpg",
      "room_type": "foyer",
      "camera_move": "forward_dolly_to_doorway",
      "prompt": "slow cinematic forward dolly, smooth gimbal, steady constant speed, no rotation, no warping, no people, no text",
      "generated_clip": "path | null",
      "exit_frame": "path | null"
    }
  ],
  "transitions": [
    { "from_index": 0, "to_index": 1,
      "first_frame": "path", "last_frame": "path",
      "generated_clip": "path | null" }
  ]
}
```

## Non-goals / don'ts
- No 3D reconstruction from sparse photos (not enough overlap in listing photos).
- No deep push-ins into rooms — lateral parallax / shallow orbit only.
- No branding, contact info, or lyric music on the master.
- Do not run the full generation loop unattended (see guardrails).

## Cost & safety guardrails — IMPORTANT (you have my live API keys)
- Veo bills per second (~$0.20–0.60/sec). During development, stub or cache the
  generation calls. NEVER regenerate a clip that already exists on disk.
- Use the fast / 720p variant until the full pipeline is validated end-to-end.
- HARD CAP: no more than **[N]** Veo generations per run without pausing for my
  approval. On generation failure, retry at most **[N]** times — never loop.
- Print estimated spend for a run BEFORE executing any generation.
- Work on a branch and commit each working stage. Do not push to main without my
  review.
