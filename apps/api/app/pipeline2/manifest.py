"""The manifest — single source of truth between pipeline stages (per the brief).

Every stage reads the manifest, does its work, and writes the manifest back.
No state is passed implicitly. The manifest lives on disk next to the render
artifacts so a run is fully inspectable and resumable, and each stage is
idempotent: if its output already exists it is not recomputed (this is also the
cost guardrail — we NEVER regenerate a clip that already exists on disk).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ClipSpec:
    index: int
    photo: str                      # normalized photo path (Stage 0 output)
    raw_photo: str                  # original source photo
    room_type: str = "unknown"
    camera_move: str = ""           # assigned from learned vocabulary (Stage 2)
    prompt: str = ""                # full engine prompt (Stage 2)
    generated_clip: Optional[str] = None   # room clip path | None
    exit_frame: Optional[str] = None       # last frame of the room clip
    entry_frame: Optional[str] = None      # first frame (== normalized photo)
    motion: float = 0.0
    qa_verdict: Optional[str] = None
    accepted: bool = False


@dataclass
class TransitionSpec:
    from_index: int
    to_index: int
    first_frame: str                # exit frame of from-clip
    last_frame: str                 # entry frame of to-clip
    prompt: str = ""
    generated_clip: Optional[str] = None
    accepted: bool = False


@dataclass
class RenderSpec:
    master_aspect: str = "16:9"
    master_branded: bool = False
    reel_aspect: str = "9:16"
    reel_music: Optional[str] = None
    reel_captions: bool = True


@dataclass
class Manifest:
    listing_id: str
    address: str
    reference_photo: Optional[str] = None   # the exposure/WB anchor (Stage 0)
    render: RenderSpec = field(default_factory=RenderSpec)
    clips: list[ClipSpec] = field(default_factory=list)
    transitions: list[TransitionSpec] = field(default_factory=list)
    style_guide_version: Optional[str] = None
    engine: str = "higgsfield"      # render engine used for this manifest
    stage: str = "created"          # created→normalized→sequenced→authored→generated→stitched→rendered
    master_path: Optional[str] = None
    preview_path: Optional[str] = None
    reel_path: Optional[str] = None
    gen_cost_cents: int = 0          # total generation spend (any engine)

    # ── persistence ───────────────────────────────────────────────────────
    @staticmethod
    def path_for(work_dir: Path) -> Path:
        return Path(work_dir) / "manifest.json"

    @classmethod
    def load(cls, work_dir: Path) -> "Manifest":
        data = json.loads(cls.path_for(work_dir).read_text())
        # Legacy manifests stored the spend as `veo_cost_cents`.
        if "veo_cost_cents" in data and "gen_cost_cents" not in data:
            data["gen_cost_cents"] = data.pop("veo_cost_cents")
        data.pop("veo_cost_cents", None)
        data["render"] = RenderSpec(**data.get("render", {}))
        data["clips"] = [ClipSpec(**c) for c in data.get("clips", [])]
        data["transitions"] = [TransitionSpec(**t) for t in data.get("transitions", [])]
        return cls(**data)

    def save(self, work_dir: Path) -> None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        self.path_for(work_dir).write_text(json.dumps(asdict(self), indent=2))

    # ── convenience ───────────────────────────────────────────────────────
    def transition_between(self, a: int, b: int) -> Optional[TransitionSpec]:
        for t in self.transitions:
            if t.from_index == a and t.to_index == b:
                return t
        return None
