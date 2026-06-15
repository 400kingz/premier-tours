"""Agent-driven render — the bot routed THROUGH the agent's MCP connection.

The Higgsfield connector is bound to the agent's session, so generation cannot
run in a bare worker; it runs in an agent (Claude/Hermes) session. This splits
the run into two code commands with the agent's MCP loop in the middle:

  1) plan-mcp   → code: Stage 0–2, then write `worklist.json` (long single-shot
                  segment jobs — the seamless strategy). Prints what to generate.
  2) [AGENT]    → for each worklist item, via the Higgsfield MCP tools:
                  media_upload(start[,end]) → PUT bytes → media_confirm →
                  generate_video(seedance_2_0, start_image[,end_image]) →
                  job_status(poll) → download rawUrl to item["output"].
  3) finish-mcp → code: QA the downloaded segments, Stage 4 stitch + Stage 5
                  render → master + 9:16 reel.

AGENT RETRY POLICY (important): job_status may return status "nsfw" — a frequent
FALSE positive on real-estate prompts (~2/4 in testing). Treat nsfw/failed as a
failure and re-submit the SAME shot up to 2 times, lightly rephrasing the prompt
(drop trigger-prone words like "luxury"/"front door opens"; keep the plain
"continuous real-estate drone flythrough" language, which passed reliably). Never
loop more than 2 retries per shot.

CLI:
  python -m app.pipeline2.agent_runner plan-mcp   <id> "<addr>" "<glob>" [rooms_per_shot]
  python -m app.pipeline2.agent_runner finish-mcp <id> [rooms_per_shot]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.config import get_settings
from app.pipeline import qa
from app.pipeline2.manifest import ClipSpec, Manifest
from app.pipeline2.mcp_engine import segment_jobs
from app.pipeline2.stage0_normalize import normalize
from app.pipeline2.stage1_sequence import sequence
from app.pipeline2.stage2_author import author
from app.pipeline2.stage4_stitch import stitch
from app.pipeline2.stage5_render import render_all


def work_dir(tour_id: str) -> Path:
    return get_settings().output_dir / f"{tour_id}-mcp"


def _worklist_path(work: Path) -> Path:
    return work / "worklist.json"


def plan_mcp(tour_id: str, address: str, photos: list[Path],
             rooms_per_shot: int = 3) -> list[dict]:
    work = work_dir(tour_id)
    m = Manifest(listing_id=tour_id, address=address)
    m = normalize(photos, m, work, on_progress=lambda s: print("  normalize:", s))
    m = sequence(m, work, on_progress=lambda s: print("  sequence:", s))
    m = author(m, work)
    jobs = segment_jobs(m, work, rooms_per_shot=rooms_per_shot)
    _worklist_path(work).write_text(json.dumps(jobs, indent=2))
    print(f"\nWORKLIST ({len(jobs)} segment shots) → {_worklist_path(work)}")
    print(json.dumps(jobs, indent=2))
    return jobs


def finish_mcp(tour_id: str, rooms_per_shot: int = 3) -> Manifest:
    """Assemble downloaded segment clips into the seamless master + reel."""
    work = work_dir(tour_id)
    src = Manifest.load(work)
    jobs = json.loads(_worklist_path(work).read_text())

    # Represent each generated segment as one "clip"; no transitions to stitch
    # (each segment is already a continuous multi-room take).
    seg_clips: list[ClipSpec] = []
    for j in jobs:
        out = Path(j["output"])
        if not out.exists():
            print(f"  ! missing segment clip {out.name} — skipping")
            continue
        res = qa.check_clip_mechanical(out)
        if not res.passed:
            print(f"  ! segment {out.name} failed QA: {res.reason} — skipping")
            continue
        idx = len(seg_clips)
        seg_clips.append(ClipSpec(
            index=idx,
            photo=j["start_frame"],
            raw_photo=j["start_frame"],
            room_type="+".join(j["room_types"]),
            generated_clip=str(out),
            accepted=True,
            motion=res.score,
        ))
    if not seg_clips:
        raise RuntimeError("no usable segment clips to stitch")

    m = Manifest(listing_id=tour_id, address=src.address, engine="mcp:seedance_2_0")
    m.clips = seg_clips
    m.transitions = []
    m.save(work)

    stitched = stitch(m, work, on_progress=lambda s: print("  stitch:", s))
    m = render_all(stitched, m, work, on_progress=lambda s: print("  render:", s))
    print("\nMASTER:", m.master_path)
    print("REEL  :", m.reel_path)
    return m


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1]
    tour_id = sys.argv[2]
    if mode == "plan-mcp":
        address, glob = sys.argv[3], sys.argv[4]
        rps = int(sys.argv[5]) if len(sys.argv) > 5 else 3
        photos = sorted(Path(glob).parent.glob(Path(glob).name))
        if not photos:
            print(f"no photos match {glob}")
            sys.exit(1)
        plan_mcp(tour_id, address, photos, rooms_per_shot=rps)
    elif mode == "finish-mcp":
        rps = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        finish_mcp(tour_id, rooms_per_shot=rps)
    else:
        print(f"unknown mode {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
