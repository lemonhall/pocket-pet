"""M1 / REQ-0001-001 + REQ-0001-002: the schema has one source of truth.

Anti-cheat: the field table must be parsed out of the C header, not copied into
Python by hand. So these tests change the header and expect the checker to notice.
"""
import re
import shutil
from pathlib import Path

import pytest

from pocket_pet import check_schema

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "include" / "pet_state.h"


def test_schema_ok_line():
    """The agreed one-line output, with the agreed field and goal counts."""
    out = check_schema.run()
    assert out.startswith("SCHEMA_OK fields=17 goals=8"), out


def test_fields_come_from_the_header(tmp_path, monkeypatch):
    """Drop a field from the C header -> the checker must fail, not silently pass."""
    text = HEADER.read_text(encoding="utf-8")
    broken = re.sub(r"^\s*PET_FIELD\([^)]*bored[^)]*\).*$", "", text, flags=re.M)
    assert broken != text, "the test needs a PET_FIELD line for `bored`"
    copy = tmp_path / "pet_state.h"
    copy.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(check_schema, "HEADER", copy)
    with pytest.raises(check_schema.SchemaError):
        check_schema.run()


def test_goals_match_the_header(tmp_path, monkeypatch):
    """Drop a goal from the C enum -> the checker must fail."""
    text = HEADER.read_text(encoding="utf-8")
    broken = re.sub(r"^\s*PET_GOAL\([^)]*groom[^)]*\).*$", "", text, flags=re.M)
    assert broken != text, "the test needs a PET_GOAL line for `groom`"
    copy = tmp_path / "pet_state.h"
    copy.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(check_schema, "HEADER", copy)
    with pytest.raises(check_schema.SchemaError):
        check_schema.run()


def test_docs_are_checked_too():
    """The markdown docs must list exactly the same names (no drift)."""
    text = (ROOT / "docs" / "pet" / "state_line.md").read_text(encoding="utf-8")
    for name in check_schema.fields():
        assert name in text, f"{name} missing from docs/pet/state_line.md"
    goals = (ROOT / "docs" / "pet" / "goals.md").read_text(encoding="utf-8")
    for name in check_schema.goals():
        assert name in goals, f"{name} missing from docs/pet/goals.md"
