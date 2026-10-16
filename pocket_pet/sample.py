"""Situation sampler + report (REQ-0001-003).

Two sources of situations:
  * natural (65%): random states with mild correlations, the "everyday" distribution;
  * families (35%): one generator per boundary family, drawn round-robin so that
    every family is guaranteed coverage at any --n.

`report()` never trusts the generator: it re-reads the artifact and recomputes
every family count with the predicates in families.py.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path

from . import families
from .state import BUCKETS, FIELD_NAMES, GOALS, META, NUMERIC, STAGES, TIMES, WHERE, State

NATURAL_SHARE = 0.65


def _where(rng: random.Random) -> str:
    if rng.random() < 0.25:
        return "none"
    return f"{rng.choice(BUCKETS)} {rng.randint(1, 12)}"


@dataclass
class Sampler:
    rng: random.Random

    def natural(self) -> State:
        """An everyday cat, not a uniformly random one.

        Drives are drawn from a triangular distribution peaking at 4: a real cat
        spends most of its time neither starving nor exhausted. Uniform 0..9 was
        the first version, and it made the rubric's hard needs fire so often that
        the labels collapsed onto seek_food/sleep (found while building the seed
        set - see ECN-0002's notes and the M2 commit).
        """
        r = self.rng
        time = r.choices(TIMES, weights=[2, 5, 2, 3])[0]
        vals: dict = {}
        for name, span in NUMERIC.items():
            mode = {"bored": 5.0, "energy": 5.0, "clingy": 4.0, "curiosity": 4.0}.get(name, 3.5)
            vals[name] = int(r.triangular(0, span - 1, mode))
        if time == "night":
            vals["energy"] = min(vals["energy"], 3)
            vals["bored"] = min(vals["bored"], 4)
        if time == "dawn":
            vals["hunger"] = max(vals["hunger"], 5)
        vals["stage"] = r.choices(STAGES, weights=[2, 6, 2])[0]
        vals["last"] = r.choice(GOALS)
        vals["time"] = time
        for name in WHERE:
            vals[name] = _where(r)
        return State(vals)

    # -- one generator per family, each guaranteed to satisfy its predicate ----
    def extreme_hunger(self) -> State:
        s = self.natural().values; s["hunger"] = self.rng.randint(8, 9); s["food"] = _where(self.rng); return State(s)

    def extreme_tired(self) -> State:
        s = self.natural().values; s["energy"] = self.rng.randint(0, 1); return State(s)

    def just_woke(self) -> State:
        s = self.natural().values; s["energy"] = self.rng.randint(8, 9); s["last"] = "sleep"; return State(s)

    def deep_night(self) -> State:
        s = self.natural().values; s["time"] = "night"; s["energy"] = min(s["energy"], 3); return State(s)

    def dirty_box(self) -> State:
        s = self.natural().values; s["litter"] = self.rng.randint(7, 9); return State(s)

    def owner_far_but_clingy_0(self) -> State:
        s = self.natural().values; s["clingy"] = 0; s["owner"] = f"{self.rng.choice(('near', 'mid'))} {self.rng.randint(1, 12)}"; return State(s)

    def clingy_max(self) -> State:
        s = self.natural().values; s["clingy"] = 9; s["owner"] = f"near {self.rng.randint(1, 12)}"; return State(s)

    def curious_max(self) -> State:
        s = self.natural().values; s["curiosity"] = 9; return State(s)

    def lazy_max(self) -> State:
        s = self.natural().values; s["lazy"] = 9; return State(s)

    def food_at_paw(self) -> State:
        s = self.natural().values; s["food"] = f"near {self.rng.randint(1, 12)}"; s["hunger"] = self.rng.randint(5, 9); return State(s)

    def toy_diagonal(self) -> State:
        s = self.natural().values; s["toy"] = f"far {self.rng.randint(1, 12)}"; s["bored"] = self.rng.randint(6, 9); return State(s)

    def conflicting_last(self) -> State:
        s = self.natural().values; s["last"] = "sleep"; s["hunger"] = self.rng.randint(7, 9); return State(s)

    def _calm(self) -> dict:
        """A cat with no hard need: hunger 2..4, energy 5..7, litter/scruff low."""
        s = self.natural().values
        s["hunger"] = self.rng.randint(2, 4)
        s["energy"] = self.rng.randint(5, 7)
        s["litter"] = self.rng.randint(0, 3)
        s["scruff"] = self.rng.randint(0, 3)
        return s

    def timid_with_owner(self) -> State:
        s = self._calm()
        s["bold"] = self.rng.randint(0, 2)
        s["owner"] = f"{self.rng.choice(('near', 'mid'))} {self.rng.randint(1, 12)}"
        return State(s)

    def clingy_with_owner(self) -> State:
        s = self._calm()
        s["clingy"] = self.rng.randint(7, 9)
        s["owner"] = f"{self.rng.choice(('near', 'mid'))} {self.rng.randint(1, 12)}"
        return State(s)

    def scruffy(self) -> State:
        s = self._calm()
        s["scruff"] = self.rng.randint(6, 9)
        return State(s)


def generate(n: int, seed: int, out: Path) -> int:
    """Write n situations to `out` as JSONL. Deterministic in (n, seed)."""
    rng = random.Random(seed)
    smp = Sampler(rng)
    gens = [(name, getattr(smp, name)) for name in families.names()]
    nl = int(n * NATURAL_SHARE)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        idx = 0
        for _ in range(nl):
            fh.write(json.dumps({"id": f"sit-{idx:06d}", "state": smp.natural().line()},
                                ensure_ascii=False, sort_keys=True) + "\n")
            idx += 1
        fi = 0
        while idx < n:
            name, gen = gens[fi % len(gens)]
            fh.write(json.dumps({"id": f"sit-{idx:06d}", "state": gen().line(), "family": name},
                                ensure_ascii=False, sort_keys=True) + "\n")
            idx += 1
            fi += 1
    return n


def report(path: Path) -> dict:
    """Recompute every family count from the artifact (predicates only)."""
    counts = {name: 0 for name in families.names()}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            st = State.parse(json.loads(line)["state"])
            for name in families.which(st):
                counts[name] += 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pocket_pet.sample")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("data/situations.jsonl"))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--in", dest="src", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.report:
        src = a.src or a.out
        counts = report(src)
        print(f"REPORT {src} families={len(counts)}")
        for name, c in counts.items():
            print(f"  {name:26s} {c}")
        return 0 if all(c >= 100 for c in counts.values()) else 1
    n = generate(a.n, a.seed, a.out)
    print(f"SAMPLED {n} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
