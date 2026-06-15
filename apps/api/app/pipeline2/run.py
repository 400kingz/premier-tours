"""Pipeline v2 orchestrator — manifest-driven, idempotent, cost-guarded.

Runs Stage 0→5 against a folder of photos. Prints the spend estimate BEFORE any
generation (brief guardrail) and never exceeds max_generations without stopping.

CLI:
  # plan only (no generation): normalize + sequence + author, print spend
  python -m app.pipeline2.run plan <listing_id> "<address>" <photos_glob>

  # generate a subset to validate seams (e.g. 2 rooms + 1 transition)
  python -m app.pipeline2.run subset <listing_id> "<address>" <photos_glob> <idx> <idx>

  # full run, capped
  python -m app.pipeline2.run full <listing_id> "<address>" <photos_glob> <cap>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.pipeline2.manifest import Manifest
from app.pipeline2.stage0_normalize import normalize, color_consistency_report
from app.pipeline2.stage1_sequence import sequence
from app.pipeline2.stage2_author import author, estimate_spend
from app.pipeline2.stage3_generate import finalize_qa, generate
from app.pipeline2.stage4_stitch import stitch
from app.pipeline2.stage5_render import render_all


def _work_dir(listing_id: str) -> Path:
    return Path.home() / "premier-home-tours" / "renders" / f"{listing_id}-v2"


def _log(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def plan(listing_id: str, address: str, photos: list[Path]) -> Manifest:
    work = _work_dir(listing_id)
    m = Manifest(listing_id=listing_id, address=address)
    print("Stage 0 — normalize")
    m = normalize(photos, m, work, on_progress=_log)
    print("  color consistency:", color_consistency_report(work))
    print("Stage 1 — sequence")
    m = sequence(m, work, on_progress=_log)
    print("Stage 2 — author")
    m = author(m, work, on_progress=_log)
    print("\nSPEND ESTIMATE:", json.dumps(estimate_spend(m), indent=2))
    return m


def _finish(m: Manifest, work: Path) -> Manifest:
    print("Stage 4 — stitch")
    stitched = stitch(m, work, on_progress=_log)
    print("Stage 5 — render")
    m = render_all(stitched, m, work, on_progress=_log)
    print("Final QA — continuity + property verification")
    report = finalize_qa(m, work, on_progress=_log)
    print(f"  QA decision: {report['decision'].upper()}", flush=True)
    print("\nDONE:", m.master_path)
    return m


def main() -> None:
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)
    mode, listing_id, address, glob = sys.argv[1:5]
    photos = sorted(Path(glob).parent.glob(Path(glob).name))
    if not photos:
        print(f"no photos match {glob}")
        sys.exit(1)
    work = _work_dir(listing_id)

    m = plan(listing_id, address, photos)
    if mode == "plan":
        return

    if mode == "subset":
        idxs = [int(x) for x in sys.argv[5:]]
        print(f"\nGenerating SUBSET rooms {idxs} (+ transitions between them)")
        m = generate(m, work, max_generations=len(idxs) + 2,
                     only_indices=idxs, on_progress=_log)
    elif mode == "full":
        cap = int(sys.argv[5]) if len(sys.argv) > 5 else 12
        print(f"\nGenerating FULL run, cap={cap}")
        m = generate(m, work, max_generations=cap, on_progress=_log)
    else:
        print(f"unknown mode {mode}")
        sys.exit(1)

    accepted = [c for c in m.clips if c.accepted]
    print(f"\naccepted {len(accepted)} room clips, "
          f"{sum(1 for t in m.transitions if t.accepted)} transitions, "
          f"spent ${m.gen_cost_cents/100:.2f}")
    if accepted:
        _finish(m, work)


if __name__ == "__main__":
    main()
