"""The rubric as code - my judgement, made explicit (docs/pet/labeling_rubric.md).

`label()` returns (goal, urgency, reason). The seed set and the held-out eval set
are both derived from this function (ECN-0002), and the API teacher is prompted
with it, so there is exactly one definition of "what a cat should do here".
"""
from __future__ import annotations

import random

GOALS = ("seek_food", "sleep", "play", "groom", "follow_owner", "scratch", "explore", "hide")
NOISE_P = 0.10          # personality noise, only when urgency <= 1


def _where(s: dict, name: str) -> tuple[str, int | None]:
    v = s.get(name, "none")
    if v == "none" or " " not in v:
        return ("none", None) if v == "none" else (v, None)
    bucket, clock = v.split()
    return bucket, int(clock)


def label(s: dict, rng: random.Random | None = None) -> tuple[str, int, str]:
    """Apply the rubric to a state dict (the fields of the state line)."""
    rng = rng or random.Random(0)
    h, e = s["hunger"], s["energy"]
    food_b, _ = _where(s, "food")
    owner_b, _ = _where(s, "owner")

    if h >= 7:
        return "seek_food", 3, f"hunger {h}"
    if e <= 1:
        return "sleep", 3, f"energy {e}"
    if s["litter"] >= 7:
        return "scratch", 3, f"litter {s['litter']}"
    if h >= 5 and food_b == "near":
        return "seek_food", 2, f"hunger {h} + food near"
    if e <= 3:
        return "sleep", 2, f"energy {e}"
    if s["time"] == "night" and e <= 5:
        return "sleep", 2, f"night + energy {e}"
    if s["clingy"] >= 7 and owner_b in ("near", "mid"):
        return "follow_owner", 2, f"clingy {s['clingy']} + owner {owner_b}"
    if s["bold"] <= 2 and owner_b == "near":
        return "hide", 2, f"bold {s['bold']} + owner near"
    if s["scruff"] >= 6:
        return "groom", 1, f"scruff {s['scruff']}"
    if s["bored"] >= 6 and s["lazy"] <= 6:
        return "play", 1, f"bored {s['bored']} + lazy {s['lazy']}"
    if s["curiosity"] >= 8:
        return "explore", 1, f"curiosity {s['curiosity']}"
    if s["bored"] >= 4 and s["lazy"] <= 7:
        return "play", 1, f"bored {s['bored']}"
    goal, urg, why = "explore", 0, f"nothing pressing (bored {s['bored']}, curiosity {s['curiosity']})"
    if rng.random() < NOISE_P:                          # the deliberate nonsense
        return rng.choice(GOALS), urg, f"no reason (personality, bored {s['bored']})"
    return goal, urg, why
