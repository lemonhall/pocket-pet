"""REQ-0001-001 / REQ-0001-002: the header and the docs must agree, both ways.

The field table lives in include/pet_state.h and nowhere else: this module reads
it, reads the two markdown docs, and fails unless the names match exactly. That
is what stops a field from being added on one side only (and it is the
anti-cheat clause of REQ-0001-001).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import header

HEADER = header.DEFAULT_HEADER
ROOT = header.ROOT
STATE_DOC = ROOT / "docs" / "pet" / "state_line.md"
GOALS_DOC = ROOT / "docs" / "pet" / "goals.md"


class SchemaError(Exception):
    pass


def fields() -> list[str]:
    return header.field_names(HEADER)


def goals() -> list[str]:
    return header.goal_names(HEADER)


_ROW = re.compile(r"^\|\s*([a-z_][a-z0-9_]*)\s*\|")


def _doc_names(path: Path) -> set[str]:
    """The first column of the markdown table in `path` - an independent list.

    It must be parsed, not derived from the header: if the header loses a field,
    the doc still has it, and that difference is the whole point of this check.
    """
    if not path.exists():
        raise SchemaError(f"{path} is missing")
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line.strip())
        if m:
            names.add(m.group(1))
    if not names:
        raise SchemaError(f"{path} has no table whose first column lists names")
    return names


def run() -> str:
    fs, gs = fields(), goals()
    doc_fields = _doc_names(STATE_DOC)
    doc_goals = _doc_names(GOALS_DOC)
    missing_in_doc = set(fs) - doc_fields
    missing_in_header = doc_fields - set(fs)
    if missing_in_doc:
        raise SchemaError(f"documented nowhere in {STATE_DOC.name}: {sorted(missing_in_doc)}")
    if missing_in_header:
        raise SchemaError(f"{STATE_DOC.name} lists names the header does not have: {sorted(missing_in_header)}")
    missing_goals_in_doc = set(gs) - doc_goals
    unknown_goals_in_doc = doc_goals - set(gs)
    if missing_goals_in_doc:
        raise SchemaError(f"goals missing from {GOALS_DOC.name}: {sorted(missing_goals_in_doc)}")
    if unknown_goals_in_doc:
        raise SchemaError(f"{GOALS_DOC.name} lists goals the header does not have: {sorted(unknown_goals_in_doc)}")
    return f"SCHEMA_OK fields={len(fs)} goals={len(gs)}"


def main(argv=None) -> int:
    try:
        print(run())
        return 0
    except SchemaError as e:
        print(f"SCHEMA_FAIL {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
