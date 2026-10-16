"""The 12 boundary families (REQ-0001-003).

Each family is a pure predicate over a decoded state, so `sample.report` can
recompute every count from the artifact alone - the generator's own bookkeeping
is never trusted.
"""
from __future__ import annotations

from .state import State

# name -> (predicate, human description)
FAMILIES = {
    "extreme_hunger":  (lambda s: s["hunger"] >= 8, "hunger >= 8"),
    "extreme_tired":   (lambda s: s["energy"] <= 1, "energy <= 1"),
    "just_woke":       (lambda s: s["energy"] >= 8 and s["last"] == "sleep", "energy >= 8 and last == sleep"),
    "deep_night":      (lambda s: s["time"] == "night", "time == night"),
    "dirty_box":       (lambda s: s["litter"] >= 7, "litter >= 7 (box is dirty)"),
    "owner_far_but_clingy_0": (lambda s: s["clingy"] == 0 and str(s["owner"]).startswith(("near", "mid")),
                               "clingy == 0 and the owner is near"),
    "clingy_max":      (lambda s: s["clingy"] >= 9, "clingy >= 9"),
    "curious_max":     (lambda s: s["curiosity"] >= 9, "curiosity >= 9"),
    "lazy_max":        (lambda s: s["lazy"] >= 9, "lazy >= 9"),
    "food_at_paw":     (lambda s: str(s["food"]).startswith("near"), "food within near"),
    "toy_diagonal":    (lambda s: str(s["toy"]).startswith("far"), "toy far away"),
    "conflicting_last": (lambda s: s["last"] == "sleep" and s["hunger"] >= 7, "just slept and now starving"),
}


def names() -> list[str]:
    return list(FAMILIES)


def which(state: State) -> list[str]:
    """Every family this state belongs to (a state may satisfy several)."""
    return [n for n, (pred, _) in FAMILIES.items() if pred(state)]
