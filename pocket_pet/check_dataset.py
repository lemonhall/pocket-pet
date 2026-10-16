"""Dataset gates (REQ-0001-004 / REQ-0001-006, as amended by ECN-0002).

    uv run python -m pocket_pet.check_dataset --seed-only   # the seed set's shape
    uv run python -m pocket_pet.check_dataset --leak        # train/val/eval disjoint

Anti-cheat: the leak check hashes the *normalised state line*, not the id, so a
situation cannot sneak into two sets under a different name. The seed check
re-derives the family counts from the artefact with the predicates in families.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from . import families
from .state import State

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = DATA / "seed.jsonl"
EVAL = DATA / "eval_hand.jsonl"
LABELED = DATA / "labeled.jsonl"
MIN_SEED = 300
MIN_GOAL = 20
MIN_FAMILY = 10
MIN_EVAL = 500
MIN_GOALS_COVERED = 5


class DatasetError(Exception):
    pass


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        raise DatasetError(f"{path} is missing")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _norm(state_line: str) -> str:
    """Canonical form of a state line - the same text `State.line()` produces.

    Parsing and re-encoding removes key order and spacing differences, so two
    spellings of one situation hash the same.
    """
    return State.parse(state_line).line()


def digest(state_line: str) -> str:
    return hashlib.sha256(_norm(state_line).encode("utf-8")).hexdigest()


def check_seed() -> str:
    rows = _rows(SEED)
    if len(rows) < MIN_SEED:
        raise DatasetError(f"seed has {len(rows)} rows, need >= {MIN_SEED}")
    goals: dict[str, int] = {}
    fam: dict[str, int] = {n: 0 for n in families.names()}
    for r in rows:
        goals[r["goal"]] = goals.get(r["goal"], 0) + 1
        st = State.parse(r["state"])
        for name in families.which(st):
            fam[name] += 1
        if not r.get("reason"):
            raise DatasetError(f"{r['id']}: empty reason")
        if len(r["reason"]) > 40:
            raise DatasetError(f"{r['id']}: reason too long")
        # the reason must point at something in the state, so a label cannot be a
        # bare goal with a canned note (only strings are compared - an int value
        # would raise TypeError inside `in`)
        values = [str(v) for v in st.values.values()]
        if "personality" not in r["reason"] and not any(v in r["reason"] for v in values):
            # a name is acceptable too, e.g. "hunger 8"
            if not any(name in r["reason"] for name in st.values):
                raise DatasetError(f"{r['id']}: reason does not mention the state ({r['reason']!r})")
    thin = {g: n for g, n in goals.items() if n < MIN_GOAL}
    if len(goals) < MIN_GOALS_COVERED:
        raise DatasetError(f"only {len(goals)} goals present: {sorted(goals)}")
    if thin:
        raise DatasetError(f"goals below {MIN_GOAL}: {thin}")
    top = max(goals.values()) / len(rows)
    if top > 0.40:
        raise DatasetError(f"goal distribution collapsed: {top:.0%} in one goal")
    thin_fam = {n: c for n, c in fam.items() if c < MIN_FAMILY}
    if thin_fam:
        raise DatasetError(f"families below {MIN_FAMILY}: {thin_fam}")
    return (f"SEED_OK n={len(rows)} goals={len(goals)} min_goal={min(goals.values())} "
            f"families={len(fam)} min_family={min(fam.values())} top_goal={top:.0%}")


def check_leak() -> str:
    sets = {"train": LABELED, "eval": EVAL, "seed": SEED}
    seen: dict[str, str] = {}
    counts = {}
    for name, path in sets.items():
        if not path.exists():
            counts[name] = 0
            continue
        rows = _rows(path)
        counts[name] = len(rows)
        for r in rows:
            d = digest(r["state"])
            if d in seen and seen[d] != name:
                raise DatasetError(f"leak: situation {r['id']} ({name}) also in {seen[d]}")
            seen[d] = name
    if counts["eval"] < MIN_EVAL:
        raise DatasetError(f"eval set has {counts['eval']} rows, need >= {MIN_EVAL}")
    for r in _rows(EVAL):
        if r.get("source") != "rubric-eval":
            raise DatasetError(f"eval row {r['id']} has source {r.get('source')!r}")
    return (f"NO_LEAK train={counts['train']} eval={counts['eval']} seed={counts['seed']} "
            f"unique={len(seen)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pocket_pet.check_dataset")
    ap.add_argument("--seed-only", action="store_true")
    ap.add_argument("--leak", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.seed_only:
            print(check_seed())
            return 0
        if a.leak:
            print(check_leak())
            return 0
        print(check_seed())
        print(check_leak())
        return 0
    except DatasetError as e:
        print(f"DATASET_FAIL {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
