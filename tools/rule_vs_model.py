"""Is the LLM earning its 7.5 MB?

The training labels came from pocket_pet/rubric.py, so the fair baseline is that
rubric run on the SAME held-out, human-labelled rows. If a twenty-line rule matches
the model, the model is decoration and the project should keep the rule.

    uv run python tools/rule_vs_model.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from pocket_pet import rubric

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


KEYS = ["hunger", "energy", "bored", "clingy", "litter", "curiosity", "bold", "lazy",
        "scruff", "food", "toy", "owner", "litter_box", "window", "stage", "last", "time"]


def parse_line(line: str) -> dict:
    """Parse the canonical state line.

    Values are not always one token: the WHERE fields are `food near 10`, so a plain
    pair split drops the last field (it did, and rubric.label then wanted `time`)."""
    parts = line.split()
    out, i = {}, 0
    while i < len(parts):
        k = parts[i]
        if k not in KEYS:
            i += 1
            continue
        i += 1
        val = []
        while i < len(parts) and parts[i] not in KEYS:
            val.append(parts[i])
            i += 1
        v = " ".join(val)
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = val[0] if len(val) == 1 else v
    return out


def main() -> int:
    rows = load(ROOT / "data" / "eval_hand.jsonl")
    print(f"{len(rows)} human-labelled rows; keys: {sorted(rows[0].keys())}")

    pairs = []
    skipped = 0
    for r in rows:
        st = r.get("state")
        if isinstance(st, str):
            st = parse_line(st)
        if not isinstance(st, dict):
            skipped += 1
            continue
        got, _urgency, _why = rubric.label(st, None)
        pairs.append((got, r["goal"]))
    print(f"scored {len(pairs)}, skipped {skipped}")

    rule_acc = float(np.mean([a == b for a, b in zip([p[0] for p in pairs], [p[1] for p in pairs])]))
    human = [p[1] for p in pairs]
    maj, n_maj = Counter(human).most_common(1)[0]
    print(f"rubric (the rule)            : {rule_acc * 100:.1f}%")
    print(f"majority class ({maj})     : {n_maj / len(human) * 100:.1f}%")

    per_goal = defaultdict(lambda: [0, 0])
    for g, h in pairs:
        per_goal[h][0] += 1
        per_goal[h][1] += int(g == h)
    print("\ngoal            n   rule")
    for g, (n, rr) in sorted(per_goal.items(), key=lambda kv: -kv[1][0]):
        print(f"{g:14s} {n:4d}  {rr / n * 100:5.1f}%")

    # note the model number is what earlier work reported (77.4%); the point of this
    # script is the rule's number on the same rows
    print("\nfor reference, the trained model scored 77.4% on these rows (docs/plan/v1-report.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
