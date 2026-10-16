"""REQ-0001-005: the labeler's accounting and its resume behaviour.

Both are cost gates, so they are tested without touching the network: a mocked
API payload drives the accounting, and a pre-populated output file proves that a
second run makes zero requests.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from pocket_pet import label as L


def test_cost_uses_offpeak_and_peak_prices():
    """Same tokens, different windows: peak costs exactly double."""
    off = L.cost_cny(1_000_000, 0, 0, peak=False)
    peak = L.cost_cny(1_000_000, 0, 0, peak=True)
    assert off == pytest.approx(0.02)
    assert peak == pytest.approx(0.04)


def test_cost_mixes_the_three_buckets():
    c = L.cost_cny(prompt_hit=500_000, prompt_miss=500_000, completion=250_000, peak=False)
    assert c == pytest.approx(0.5 * 0.02 + 0.5 * 1.0 + 0.25 * 4.0)


def test_peak_window_is_beijing_business_hours():
    assert L.is_peak(datetime(2026, 10, 19, 10, 0, tzinfo=L.BEIJING))       # Monday 10:00
    assert not L.is_peak(datetime(2026, 10, 19, 13, 0, tzinfo=L.BEIJING))   # lunch
    assert L.is_peak(datetime(2026, 10, 19, 15, 0, tzinfo=L.BEIJING))       # afternoon
    assert not L.is_peak(datetime(2026, 10, 17, 3, 0, tzinfo=L.BEIJING))    # small hours
    assert not L.is_peak(datetime(2026, 10, 18, 10, 0, tzinfo=L.BEIJING))   # Sunday


def test_parse_labels_accepts_good_and_rejects_bad():
    batch = [{"id": "a", "state": "hunger 8 energy 1"}, {"id": "b", "state": "hunger 1 energy 8"}]
    payload = {"choices": [{"message": {"content": json.dumps({"labels": [
        {"id": "a", "goal": "seek_food", "urgency": 3, "reason": "hunger 8"},
        {"id": "b", "goal": "nap", "urgency": 1, "reason": "tired"},        # not a goal
        {"id": "zz", "goal": "sleep", "urgency": 1, "reason": "energy 8"},  # unknown id
    ]})}}]}
    good, bad = L.parse_labels(payload, batch)
    assert [g["id"] for g in good] == ["a"]
    assert good[0]["source"] == "api"
    assert len(bad) == 2


def test_second_run_makes_no_requests(tmp_path, monkeypatch, capsys):
    """Resume: everything already labelled -> nothing to do."""
    monkeypatch.setattr(L, "SITUATIONS", tmp_path / "situations.jsonl")
    monkeypatch.setattr(L, "OUT", tmp_path / "labeled.jsonl")
    monkeypatch.setattr(L, "COST", tmp_path / "label_cost.json")
    monkeypatch.setattr(L, "BAD", tmp_path / "labeled.bad.jsonl")
    rows = [{"id": f"sit-{i:06d}", "state": "hunger 2 energy 5"} for i in range(3)]
    (tmp_path / "situations.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (tmp_path / "labeled.jsonl").write_text(
        "\n".join(json.dumps({**r, "goal": "explore"}) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-used")
    rc = L.run(limit=None, all_rows=False)
    out = capsys.readouterr().out
    assert rc == 0 and "0 requests" in out


def test_system_prompt_carries_the_rubric_and_is_stable():
    a = L.system_prompt()
    b = L.system_prompt()
    assert a == b, "the prefix must be byte-stable or the prompt cache never hits"
    assert "rubric" in a.lower() and "seek_food" in a
    assert len(a) > 500


def test_build_user_msg_has_one_line_per_situation():
    rows = [{"id": "x1", "state": "hunger 1 energy 1"}, {"id": "x2", "state": "hunger 2 energy 2"}]
    msg = L.build_user_msg(rows)
    assert msg.count("\n") == 2 and "x1\thunger 1 energy 1" in msg
