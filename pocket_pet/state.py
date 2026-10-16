"""Encode/decode the cat's state line (REQ-0001-001).

Wire format, one line, <= 48 tokens:
    hunger 6 energy 3 bored 5 ... stage adult food near 3 ... time night
Numeric fields render as bare integers (0..span-1); WHERE fields render as
`none` or `<bucket> <clock>`; META fields render as their word.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import header

FIELDS, GOALS, STAGES, TIMES = header.parse()
NUMERIC = {name: span for name, kind, span in FIELDS if kind == "NUM"}
WHERE = [name for name, kind, _ in FIELDS if kind == "WHERE"]
META = [name for name, kind, _ in FIELDS if kind == "META"]
FIELD_NAMES = [name for name, _, _ in FIELDS]
BUCKETS = ("near", "mid", "far")


@dataclass
class State:
    values: dict = field(default_factory=dict)

    # -- encoding ---------------------------------------------------------
    def line(self) -> str:
        """Canonical text form: the exact string the model is trained on."""
        out: list[str] = []
        for name in FIELD_NAMES:
            v = self.values[name]
            if name in NUMERIC:
                out.append(f"{name} {int(v)}")
            elif name in WHERE:
                out.append(f"{name} {v}" if v != "none" else f"{name} none")
            else:
                out.append(f"{name} {v}")
        return " ".join(out)

    # -- decoding ---------------------------------------------------------
    @classmethod
    def parse(cls, line: str) -> "State":
        toks = line.split()
        vals: dict = {}
        i = 0
        while i < len(toks):
            name = toks[i]
            if name not in FIELD_NAMES:
                raise ValueError(f"unknown field {name!r} in state line")
            if name in NUMERIC:
                vals[name] = int(toks[i + 1]); i += 2
            elif name in WHERE:
                # canonical is `name <value>` with value `none` or `<bucket> <clock>`;
                # the bare `name` form is accepted too, for hand-written lines
                if i + 1 < len(toks) and toks[i + 1] == "none":
                    vals[name] = "none"; i += 2
                elif i + 1 < len(toks) and toks[i + 1] in BUCKETS:
                    vals[name] = f"{toks[i + 1]} {toks[i + 2]}"; i += 3
                else:
                    vals[name] = "none"; i += 1
            else:
                vals[name] = toks[i + 1]; i += 2
        missing = [n for n in FIELD_NAMES if n not in vals]
        if missing:
            raise ValueError(f"state line is missing {missing}")
        return cls(vals)

    def __getitem__(self, k):
        return self.values[k]


def validate_line(line: str) -> None:
    """Raise ValueError unless `line` parses and every value is in range."""
    st = State.parse(line)
    for name, span in NUMERIC.items():
        v = st[name]
        if not isinstance(v, int) or not 0 <= v < span:
            raise ValueError(f"{name}={v!r} out of range 0..{span - 1}")
    for name in WHERE:
        v = st[name]
        if v == "none":
            continue
        bucket, clock = v.split()
        if bucket not in BUCKETS or not 1 <= int(clock) <= 12:
            raise ValueError(f"{name}={v!r} is not 'none' or '<near|mid|far> 1..12'")
    if st["stage"] not in STAGES:
        raise ValueError(f"stage={st['stage']!r} not in {STAGES}")
    if st["time"] not in TIMES:
        raise ValueError(f"time={st['time']!r} not in {TIMES}")
    if st["last"] not in GOALS:
        raise ValueError(f"last={st['last']!r} is not a goal")
