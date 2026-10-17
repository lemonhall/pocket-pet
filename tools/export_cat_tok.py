"""Export the cat's vocabulary in the format `common/llm/word_tok.c` reads.

Layout (llama2.c's, with the word-tokenizer convention):
    i32 max_token_length
    then vocab_size records: f32 score (unused, 0) + i32 len + len bytes
word_tok_encode() starts matching words at index 3 and requires the stored string
to start with a space, so indices >= 4 (our first real word) carry a leading
space. Indices 0..3 are the specials, and index 1 must stay BOS because the
encoder emits a literal 1 for it.

    uv run python tools/export_cat_tok.py --out build/cat_tok.bin
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from pocket_pet import tokenizer as T

ROOT = Path(__file__).resolve().parents[1]
BOS_INDEX = 1                      # word_tok_encode() hard-codes out[0] = 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="export_cat_tok")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "cat_tok.bin")
    a = ap.parse_args(argv)
    assert T.VOCAB[BOS_INDEX] == "<s>", f"index {BOS_INDEX} must be BOS, got {T.VOCAB[BOS_INDEX]}"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("wb") as fh:
        longest = max(len(t) + 1 for t in T.VOCAB[4:])
        fh.write(struct.pack("i", longest))          # max_token_length
        for i, tok in enumerate(T.VOCAB):
            s = tok if i < 4 else " " + tok          # words are stored space-prefixed
            b = s.encode("utf-8")
            fh.write(struct.pack("f", 0.0))          # score: unused
            fh.write(struct.pack("i", len(b)))
            fh.write(b)
    print(f"TOK {a.out.relative_to(ROOT)}: {a.out.stat().st_size} bytes, vocab {len(T.VOCAB)}, "
          f"max_token_length {longest}, BOS at {BOS_INDEX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
