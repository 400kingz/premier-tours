"""Feedback memory — learn which prompts produce good clips, per room type.

Every generated clip already gets a mechanical motion score and a Gemini
hallucination verdict. We persist each outcome as a feedback record keyed by
(room_type, camera_move), then let Stage 2 bias toward the prompt fragments
that have historically scored well — epsilon-greedy: usually exploit the best
known fragment, occasionally explore a new one.

This is a contextual bandit over prompt fragments, not model training. It needs
no GPUs and improves monotonically as real renders accumulate.

Storage: Firestore collection `<prefix>clip_feedback`.
"""
from __future__ import annotations

from dataclasses import dataclass

from google.cloud import firestore

from app.config import Settings, get_settings
from app.models import utcnow


@dataclass
class PromptStat:
    room_type: str
    move: str
    prompt_fragment: str
    trials: int
    reward_sum: float       # sum of per-clip rewards in [0,1]

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.trials if self.trials else 0.0


def _reward(accepted: bool, motion: float, vision_score: float) -> float:
    """Collapse a clip's QA outcome into a single reward in [0,1].

    Acceptance dominates; motion and the hallucination-gate confidence refine it.
    """
    if not accepted:
        return 0.0
    # Accepted clips: 0.6 floor + up to 0.2 motion + up to 0.2 vision confidence.
    return round(0.6 + 0.2 * min(motion, 1.0) + 0.2 * min(vision_score, 1.0), 4)


class FeedbackMemory:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = firestore.Client(project=self.settings.gcp_project_id)

    def _col(self):
        return self._client.collection(self.settings.collection("clip_feedback"))

    @staticmethod
    def _key(room_type: str, move: str) -> str:
        return f"{room_type}::{move}".replace("/", "_")

    def record(
        self,
        room_type: str,
        move: str,
        prompt_fragment: str,
        accepted: bool,
        motion: float = 0.0,
        vision_score: float = 0.0,
    ) -> None:
        """Persist one clip outcome (atomic increment on the room/move doc)."""
        reward = _reward(accepted, motion, vision_score)
        doc = self._col().document(self._key(room_type, move))
        snap = doc.get()
        if snap.exists:
            doc.update({
                "trials": firestore.Increment(1),
                "reward_sum": firestore.Increment(reward),
                "prompt_fragment": prompt_fragment,
                "updated_at": utcnow().isoformat(),
            })
        else:
            doc.set({
                "room_type": room_type,
                "move": move,
                "prompt_fragment": prompt_fragment,
                "trials": 1,
                "reward_sum": reward,
                "updated_at": utcnow().isoformat(),
            })

    def best_for_room(self, room_type: str, min_trials: int = 2) -> PromptStat | None:
        """Highest mean-reward fragment for a room, once it has enough trials."""
        return self._best(room_type, move=None, min_trials=min_trials)

    def best_for_move(self, room_type: str, move: str, min_trials: int = 2) -> PromptStat | None:
        """Best fragment for a SPECIFIC (room_type, camera_move).

        Scoping to the move prevents an unrelated phrasing recorded under a
        different move from hijacking this room's prompt.
        """
        return self._best(room_type, move=move, min_trials=min_trials)

    def _best(self, room_type: str, move: str | None, min_trials: int) -> PromptStat | None:
        best: PromptStat | None = None
        for d in self._col().where("room_type", "==", room_type).stream():
            r = d.to_dict()
            if move is not None and r.get("move") != move:
                continue
            stat = PromptStat(
                room_type=r["room_type"], move=r["move"],
                prompt_fragment=r.get("prompt_fragment", ""),
                trials=r.get("trials", 0), reward_sum=r.get("reward_sum", 0.0),
            )
            if stat.trials < min_trials:
                continue
            if best is None or stat.mean_reward > best.mean_reward:
                best = stat
        return best

    def clear(self) -> int:
        """Delete all feedback docs. Returns count removed."""
        n = 0
        for d in self._col().stream():
            d.reference.delete()
            n += 1
        return n

    def summary(self) -> list[PromptStat]:
        out = []
        for d in self._col().stream():
            r = d.to_dict()
            out.append(PromptStat(
                room_type=r["room_type"], move=r["move"],
                prompt_fragment=r.get("prompt_fragment", ""),
                trials=r.get("trials", 0), reward_sum=r.get("reward_sum", 0.0),
            ))
        return sorted(out, key=lambda s: -s.mean_reward)


if __name__ == "__main__":
    fm = FeedbackMemory()
    print(f"{'room::move':40} {'trials':>6} {'mean_reward':>12}")
    for s in fm.summary():
        print(f"{s.room_type + '::' + s.move:40} {s.trials:>6} {s.mean_reward:>12.3f}")
