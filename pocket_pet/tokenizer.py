"""The word-level tokenizer for the cat: 60 tokens, closed vocabulary.

The vocabulary is *derived* from include/pet_state.h (field names, digit values,
the WHERE words, the clock positions, stages, times and goals), so it can never
drift from the schema. Training sequence:

    <s> hunger 6 energy 3 ... time night <goal> </s>

and the model is asked for the token after `time <value>` - which is exactly how
the tank's engine already works (state text in, one token out).
"""
from __future__ import annotations

from . import header
from .state import BUCKETS, GOALS, NUMERIC, STAGES, TIMES

SPECIALS = ["<pad>", "<s>", "</s>", "<unk>"]


def build_vocab() -> list[str]:
    fields, goals, stages, times = header.parse()
    toks = list(SPECIALS)
    toks += [f[0] for f in fields]                       # field names
    toks += [str(d) for d in range(max(NUMERIC.values()))]   # digit values 0..9
    toks += ["none"] + list(BUCKETS) + [str(c) for c in range(1, 13)]
    toks += list(stages or STAGES) + list(times or TIMES)
    toks += list(goals or GOALS)
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


VOCAB = build_vocab()
STOI = {t: i for i, t in enumerate(VOCAB)}
UNK = STOI["<unk>"]


def encode(text: str, bos: bool = True, eos: bool = False) -> list[int]:
    ids = [STOI["<s>"]] if bos else []
    ids += [STOI.get(t, UNK) for t in text.split()]
    if eos:
        ids.append(STOI["</s>"])
    return ids


def decode(ids: list[int]) -> str:
    return " ".join(VOCAB[i] for i in ids if i >= len(SPECIALS))


def sample_text(state_line: str, goal: str) -> str:
    """The training string: the state, then the goal, then the terminator."""
    return f"<s> {state_line} {goal} </s>"


def prompt(state_line: str) -> str:
    return f"<s> {state_line}"
