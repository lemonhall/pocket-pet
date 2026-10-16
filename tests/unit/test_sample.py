"""M1 / REQ-0001-003: the sampler is reproducible and covers the boundary families.

Anti-cheat: the family counts in the report are recomputed from the artifact by
predicate, never read back from the generator's own bookkeeping.
"""
import hashlib
import json
from pathlib import Path

from pocket_pet import families, sample

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_seed_same_bytes(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    sample.generate(2000, seed=7, out=a)
    sample.generate(2000, seed=7, out=b)
    assert _sha(a) == _sha(b)


def test_different_seed_differs(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    sample.generate(2000, seed=7, out=a)
    sample.generate(2000, seed=8, out=b)
    assert _sha(a) != _sha(b)


def test_report_counts_come_from_the_file(tmp_path):
    out = tmp_path / "s.jsonl"
    sample.generate(4000, seed=7, out=out)
    report = sample.report(out)
    assert set(report) == set(families.names()), "every family must be reported"
    for name, n in report.items():
        assert n >= 100, f"family {name} has only {n}"


def test_report_recomputes_by_predicate(tmp_path):
    """Hand-write one situation that satisfies exactly one family and check the count."""
    out = tmp_path / "tiny.jsonl"
    state = "hunger 9 energy 3 bored 5 clingy 5 litter 2 scruff 1 curiosity 5 bold 5 lazy 5 stage adult " \
            "food near 3 toy mid 9 owner far 6 litter_box near 12 window none last play time day"
    out.write_text(json.dumps({"id": "x", "state": state}) + "\n", encoding="utf-8")
    report = sample.report(out)
    assert report["extreme_hunger"] == 1
    assert report["deep_night"] == 0
