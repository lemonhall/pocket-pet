"""Build the labelled datasets from the rubric (ECN-0002).

    uv run python tools/make_seed.py --seed 350 --eval 500

Writes:
    data/seed.jsonl       source="rubric-seed"   (few-shot examples for M3 + training)
    data/eval_hand.jsonl  source="rubric-eval"   (held out, never sent to the API teacher)

The two sets are drawn from disjoint situation pools, and the leak check in
check_dataset.py verifies that on the artefact, not on this script's word.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from pocket_pet import families, rubric, sample
from pocket_pet.state import State

ROOT = Path(__file__).resolve().parents[1]

# Which family generators tend to produce which goal (used to fill quotas).
GOAL_SOURCES = {
    "seek_food": ["extreme_hunger", "food_at_paw"],
    "sleep": ["extreme_tired", "deep_night", "just_woke"],
    "play": ["toy_diagonal", "lazy_max"],
    "groom": ["scruffy", "just_woke"],
    "follow_owner": ["clingy_with_owner", "clingy_max"],
    "scratch": ["dirty_box"],
    "explore": ["curious_max"],
    "hide": ["timid_with_owner", "owner_far_but_clingy_0"],
}


def build_balanced(per_goal: int, per_family: int, seed: int, source: str,
                   start: int = 0) -> tuple[list[dict], dict]:
    """A class-balanced teacher set, drawn with rejection sampling.

    The natural distribution is heavily skewed towards the hard needs (a hungry
    cat is hungry a lot), and training a policy classifier on that teaches it to
    answer "sleep" to everything. So: first guarantee `per_family` rows for each
    boundary family, then top up until every goal has `per_goal` rows.
    """
    rng = random.Random(seed * 7919 + 13)
    smp = sample.Sampler(random.Random(seed))
    rows: list[dict] = []
    seen: set[str] = set()
    fam_count = {n: 0 for n in families.names()}
    goal_count = {g: 0 for g in rubric.GOALS}

    def offer(state, tag: str | None) -> bool:
        line = state.line()
        if line in seen:
            return False
        goal, urg, why = rubric.label(state.values, rng)
        seen.add(line)
        rows.append({
            "id": f"{source}-{start + len(rows):06d}",
            "state": line, "goal": goal, "urgency": urg, "reason": why, "source": source,
            "family": tag,
        })
        goal_count[goal] = goal_count.get(goal, 0) + 1
        for name in families.which(state):
            fam_count[name] = fam_count.get(name, 0) + 1
        return True

    # phase 1: every family gets its quota (the generator is built to satisfy it)
    for _ in range(4000):
        if all(c >= per_family for c in fam_count.values()):
            break
        for name in families.names():
            if fam_count[name] < per_family:
                offer(getattr(smp, name)(), name)
    # phase 2: fill the goal quotas from the families that actually produce them.
    # Only rows whose goal is still short are kept - the first attempt added every
    # row it saw, which blew the set up to 2668 rows with sleep at 1071.
    def offer_if_needed(state, tag=None) -> bool:
        goal, _, _ = rubric.label(state.values, rng)
        if goal_count.get(goal, 0) >= per_goal:
            return False
        return offer(state, tag)

    for _ in range(20000):
        if all(c >= per_goal for c in goal_count.values()):
            break
        for goal, sources in GOAL_SOURCES.items():
            if goal_count.get(goal, 0) >= per_goal:
                continue
            for name in sources:
                if offer_if_needed(getattr(smp, name)(), name):
                    break
    return rows, {"families": fam_count, "goals": goal_count}


def write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-goal", type=int, default=45, help="rows per goal in the seed set")
    ap.add_argument("--eval-per-goal", type=int, default=70, help="rows per goal in the eval set")
    ap.add_argument("--per-family", type=int, default=12)
    a = ap.parse_args(argv)
    seed_rows, seed_stats = build_balanced(a.per_goal, a.per_family, 101, "rubric-seed")
    eval_rows, eval_stats = build_balanced(a.eval_per_goal, a.per_family, 202, "rubric-eval",
                                           start=len(seed_rows))
    # the two pools are drawn from different seeds, but overlap is possible: drop
    # any eval row whose situation already appears in the seed set
    seed_lines = {r["state"] for r in seed_rows}
    eval_rows = [r for r in eval_rows if r["state"] not in seed_lines]
    write(seed_rows, ROOT / "data" / "seed.jsonl")
    write(eval_rows, ROOT / "data" / "eval_hand.jsonl")
    print(f"SEED {len(seed_rows)} -> data/seed.jsonl")
    print("  goals:", ", ".join(f"{g}={n}" for g, n in sorted(seed_stats["goals"].items())))
    print("  families:", ", ".join(f"{n}={c}" for n, c in sorted(seed_stats["families"].items())))
    print(f"EVAL {len(eval_rows)} -> data/eval_hand.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
