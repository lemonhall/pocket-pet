"""Parse include/pet_state.h - the only place field and goal names live.

Nothing in this package hard-codes a field list: if it is not in the header, it
does not exist. `check_schema` then compares the header against the markdown
docs, so the two can never drift apart silently.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HEADER = ROOT / "include" / "pet_state.h"

_FIELD = re.compile(r"PET_FIELD\(\s*(\w+)\s*,\s*(\w+)\s*,\s*(\d+)\s*\)")
_GOAL = re.compile(r"PET_GOAL\(\s*(\w+)\s*\)")
_LIST_X = re.compile(r"#define\s+(PET_STAGE_LIST|PET_TIME_LIST)\(X\)\s*(.+)")


def parse(path: Path = DEFAULT_HEADER):
    """-> (fields, goals, stages, times): fields is [(name, kind, span), ...]."""
    text = path.read_text(encoding="utf-8")
    fields = [(m.group(1), m.group(2), int(m.group(3))) for m in _FIELD.finditer(text)]
    goals = [m.group(1) for m in _GOAL.finditer(text)]
    lists = {}
    for line in text.splitlines():
        m = _LIST_X.match(line.strip())
        if m:
            lists[m.group(1)] = re.findall(r"X\((\w+)\)", m.group(2))
    if not fields:
        raise ValueError(f"no PET_FIELD(...) lines found in {path}")
    if not goals:
        raise ValueError(f"no PET_GOAL(...) lines found in {path}")
    return fields, goals, lists.get("PET_STAGE_LIST", []), lists.get("PET_TIME_LIST", [])


def field_names(path: Path = DEFAULT_HEADER) -> list[str]:
    return [f[0] for f in parse(path)[0]]


def numeric_fields(path: Path = DEFAULT_HEADER) -> list[tuple[str, int]]:
    return [(name, span) for name, kind, span in parse(path)[0] if kind == "NUM"]


def where_fields(path: Path = DEFAULT_HEADER) -> list[str]:
    return [name for name, kind, _ in parse(path)[0] if kind == "WHERE"]


def goal_names(path: Path = DEFAULT_HEADER) -> list[str]:
    return parse(path)[1]
