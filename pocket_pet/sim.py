"""The headless simulator (REQ-0001-009 / REQ-0001-010).

One step is: drift the drives, ask the chooser for a goal (unless --no-advisor),
walk toward whatever that goal needs, and do the thing on arrival. Rendering is
optional and lives in render.py, so the same loop drives the GIF and the tests.

    uv run python -m pocket_pet.sim --minutes 5 --report
    uv run python -m pocket_pet.sim --minutes 5 --no-advisor --report
"""
from __future__ import annotations

import argparse
import math
import random
from collections import Counter
from dataclasses import dataclass

from . import advisor, world

FPS = 10                      # sim steps per second
SPEED = 34.0                  # pixels per second


@dataclass
class Stats:
    goals: Counter
    states_seen: set
    steps: int = 0

    def as_dict(self) -> dict:
        return {
            "steps": self.steps,
            "goals": dict(self.goals),
            "states_seen": len(self.states_seen),
        }


def _state(cat: world.Cat) -> dict:
    """What the chooser sees: the five WHERE fields of the state line, rounded."""
    s = {k: int(round(v)) for k, v in cat.drives.items()}
    for name in STATE_ANCHORS:
        ax, ay = world.ANCHORS[name]
        s[name] = bucket_str(cat, ax, ay)
    s["stage"] = cat.stage
    s["last"] = cat.last
    return s


STATE_ANCHORS = ("food", "toy", "owner", "litter_box", "window")


def bucket_str(cat: world.Cat, ax: float, ay: float) -> str:
    b = world.bucket(cat.x, cat.y, ax, ay)
    if b == "far" or (abs(cat.x - ax) < 8 and abs(cat.y - ay) < 8):
        return b if b != "far" else "far"
    return f"{b} {world.clock_dir(cat.x, cat.y, ax, ay)}"


TARGET = {
    "seek_food": "food",
    "play": "toy",
    "scratch": "tree",
    "sleep": "bed",
    "follow_owner": None,          # the owner follows the cat in v1: stay put and meow
    "groom": None,
    "explore": None,
    "hide": None,
}


def _pick_target(goal: str, rng: random.Random):
    if goal == "explore" or goal == "hide":
        return (rng.uniform(20, world.W - 20), rng.uniform(world.WALL_H + 12, world.H - 10))
    name = TARGET.get(goal)
    return world.ANCHORS.get(name) if name else (160.0, 130.0)


def step(cat: world.Cat, target, dt: float, rng: random.Random) -> str | None:
    """Move toward `target`; return the goal when the cat arrives (and acts)."""
    tx, ty = target
    dx, dy = tx - cat.x, ty - cat.y
    dist = math.hypot(dx, dy)
    if dist < 6.0:
        cat.moving = False
        return cat.goal
    cat.moving = True
    cat.heading = math.degrees(math.atan2(dx, -dy)) % 360
    cat.frame += 1
    step_len = min(SPEED * dt, dist)
    cat.x += dx / dist * step_len
    cat.y += dy / dist * step_len
    return None


def act(cat: world.Cat, goal: str) -> None:
    """What the cat does on arrival - the only place drives change."""
    if goal == "seek_food":
        cat.drives["hunger"] = max(0, cat.drives["hunger"] - 4)
        cat.drives["energy"] = min(9, cat.drives["energy"] + 1)
        cat.asleep = False
    elif goal == "sleep":
        cat.asleep = True
        cat.drives["energy"] = min(9, cat.drives["energy"] + 3)
    elif goal == "play":
        cat.drives["bored"] = max(0, cat.drives["bored"] - 3)
        cat.drives["energy"] = max(0, cat.drives["energy"] - 1)
        cat.asleep = False
    elif goal == "groom":
        cat.drives["scruff"] = max(0, cat.drives["scruff"] - 4)
    elif goal == "scratch":
        cat.drives["litter"] = max(0, cat.drives["litter"] - 5)
        cat.drives["bored"] = max(0, cat.drives["bored"] - 1)
    elif goal == "follow_owner":
        cat.drives["clingy"] = max(0, cat.drives["clingy"] - 2)
        cat.drives["bored"] = max(0, cat.drives["bored"] - 1)
    cat.last = goal


def drift(cat: world.Cat, dt: float) -> None:
    """The world moves on. Rates are per second of sim time; a sim minute is
    roughly a cat-hour, which is what makes a 5-minute run show every goal."""
    k = dt
    cat.drives["hunger"] = min(9, cat.drives["hunger"] + 0.10 * k)
    cat.drives["bored"] = min(9, cat.drives["bored"] + (0.04 if cat.asleep else 0.22) * k)
    if cat.asleep:
        cat.drives["energy"] = min(9, cat.drives["energy"] + 0.55 * k)
    else:
        cat.drives["energy"] = max(0, cat.drives["energy"] - 0.14 * k)
    cat.drives["litter"] = min(9, cat.drives["litter"] + 0.05 * k)
    cat.drives["scruff"] = min(9, cat.drives["scruff"] + 0.06 * k)
    # being alone makes a cat clingier; that is the only source of `clingy`, so
    # without it follow_owner fires once and then never again
    cat.drives["clingy"] = min(9, cat.drives["clingy"] + 0.09 * k)


# Things that happen to a cat. Deterministic per seed, and they are what makes
# `hide` reachable without hand-forcing the state.
EVENTS = (
    ("human_stands", 0.012),   # the human gets up: a timid cat hides
    ("bird_at_window", 0.010),  # something moved outside: curiosity spikes
    ("toy_rolls", 0.010),       # the toy rolls: boredom relief appears
)


def fire_events(cat: world.Cat, rng: random.Random) -> str | None:
    for name, p in EVENTS:
        if rng.random() < p:
            if name == "human_stands":
                cat.drives["bold"] = max(0, cat.drives["bold"] - 3)
                if cat.drives["bold"] <= 2:
                    return "hide"
            elif name == "bird_at_window":
                cat.drives["curiosity"] = min(9, cat.drives["curiosity"] + 3)
            elif name == "toy_rolls":
                cat.drives["bored"] = min(9, cat.drives["bored"] + 2)
    return None


def run(minutes: float = 5.0, seed: int = 7, use_advisor: bool = True, on_frame=None):
    """Run the sim. `on_frame(cat, t, stats)` is called after every step."""
    rng = random.Random(seed)
    cat = world.Cat()
    stats = Stats(Counter(), set())
    dt = 1.0 / FPS
    total = int(minutes * 60 * FPS)
    target = _pick_target(cat.goal, rng)
    for t in range(total):
        s = _state(cat)
        stats.states_seen.add(cat.goal)
        stats.goals[cat.goal] += 1
        stats.steps += 1
        choose = advisor.policy_goal if use_advisor else advisor.reflex_goal
        new_goal = choose(s, rng)
        forced = fire_events(cat, rng)
        if forced:
            new_goal = forced
        # a cat does not re-choose a hard need it is already acting on
        if new_goal != cat.goal:
            cat.goal = new_goal
            cat.asleep = (new_goal == "sleep")
            target = _pick_target(new_goal, rng)
        arrived = step(cat, target, dt, rng)
        if arrived:
            act(cat, arrived)
            # stay a moment on the spot, then choose again next tick
            target = _pick_target(cat.goal, rng)
        drift(cat, dt)
        if on_frame:
            on_frame(cat, t, stats)
    return cat, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pocket_pet.sim")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-advisor", action="store_true", help="reflexes only (REQ-0001-009)")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    cat, stats = run(a.minutes, a.seed, use_advisor=not a.no_advisor)
    if a.report:
        d = stats.as_dict()
        mode = "reflex-only" if a.no_advisor else "advisor"
        print(f"SIM {mode} minutes={a.minutes} steps={d['steps']} states_seen={d['states_seen']}")
        for g, n in sorted(d["goals"].items(), key=lambda kv: -kv[1]):
            print(f"  {g:14s} {n}")
        print(f"final: hunger={int(cat.drives['hunger'])} energy={int(cat.drives['energy'])} "
              f"bored={int(cat.drives['bored'])} litter={int(cat.drives['litter'])} last={cat.last}")
        bounded = all(0.0 <= v <= 9.0 for v in cat.drives.values())
        if not bounded:
            print("FAIL: a drive left 0..9")
            return 1
        # ECN-0001: the reflex run proves liveness, the advisor run proves variety
        need = 8 if not a.no_advisor else 4
        return 0 if d["states_seen"] >= need else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
