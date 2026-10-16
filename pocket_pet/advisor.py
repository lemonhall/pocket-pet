"""Choosing the next goal. Two implementations live here:

* `reflex_goal` - threshold reflexes only. No model, no policy: if it is hungry it
  eats, if it is tired it sleeps, otherwise it drifts between toys and windows.
  This is what REQ-0001-009 requires to keep the cat alive on its own.
* `policy_goal` - the "little brain" slot. Until the distilled 14M model lands
  (M4), this is a small hand-written policy so the rest of the pipeline has a
  real, deterministic chooser to compare against; `--model runs/v1/best.pt`
  swaps in the trained student and this function is bypassed.

Both take a state dict (the same fields as the state line) and return a goal name
from pocket_pet.state.GOALS.
"""
from __future__ import annotations

import random

GOALS = ("seek_food", "sleep", "play", "groom", "follow_owner", "scratch", "explore", "hide")


def reflex_goal(s: dict, rng: random.Random | None = None) -> str:
    """Thresholds only - the cat survives on this alone."""
    if s["hunger"] >= 7:
        return "seek_food"
    if s["energy"] <= 2:
        return "sleep"
    if s["litter"] >= 7:
        return "scratch"
    if s["scruff"] >= 6:
        return "groom"
    if s["bored"] >= 7:
        return "play"
    return "explore"


def policy_goal(s: dict, rng: random.Random | None = None) -> str:
    """A hand-written stand-in for the model: same priorities, plus personality.

    This is deliberately *not* the model - it exists so M6 can measure "does the
    advisor change behaviour at all?" before M4 finishes, and so training has a
    baseline to beat.
    """
    rng = rng or random.Random(0)
    # hard needs first, but personality decides the ties and the noise
    if s["hunger"] >= 6:
        return "seek_food"
    if s["energy"] <= 3:
        return "sleep"
    # a clingy cat seeks its human before tidying itself up (ECN-0001 keeps this
    # in the policy layer, never in the reflex layer)
    if s["owner"] != "none" and s["clingy"] >= 6 and rng.random() < 0.55:
        return "follow_owner"
    if s["litter"] >= 6:
        return "scratch"
    if s["scruff"] >= 5:
        return "groom"
    if s["bold"] <= 2 and str(s["owner"]).split()[0] == "near" and rng.random() < 0.4:
        return "hide"
    if s["bored"] >= 5 and s["lazy"] <= 5:
        return "play"
    if s["curiosity"] >= 7:
        return "explore"
    if rng.random() < 0.1:                 # the deliberate 10% of nonsense
        return rng.choice(GOALS)
    return "explore"
