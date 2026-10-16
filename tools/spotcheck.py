"""Print one row per family (plus a few natural ones) so a human - or I - can
check the rubric's judgement by eye. This is the spot-check ECN-0002 promised.

    uv run python tools/spotcheck.py [--file data/seed.jsonl] [--per-family 1]
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

SHORT = {"hunger": "h", "energy": "e", "curiosity": "cur", "litter_box": "lbox", "scruff": "sc"}


def shorten(state: str) -> str:
    for k, v in SHORT.items():
        state = state.replace(k, v)
    return state


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=Path("data/seed.jsonl"))
    ap.add_argument("--per-family", type=int, default=1)
    a = ap.parse_args(argv)
    rows = [json.loads(l) for l in a.file.read_text(encoding="utf-8").splitlines() if l.strip()]
    random.Random(4).shuffle(rows)
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        key = r.get("family") or "natural"
        if len(groups[key]) < a.per_family:
            groups[key].append(r)
    n = 0
    for fam in sorted(groups):
        for r in groups[fam]:
            print(f"[{fam:24s}] {r['goal']:12s} u{r['urgency']}  {r['reason']}")
            print(f"    {shorten(r['state'])}")
            n += 1
    print(f"rows shown: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
