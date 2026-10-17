"""Export the cat's PyTorch checkpoint in pocket-tank's Q4 ("version 3") format,
so the tank's existing on-device engine reads it with no code changes.

Format (model/export_q4.py in pocket-tank):
    256-byte header: magic "ak42" (0x616B3432), i32 version=3,
        i32 x7 dim, hidden, n_layers, n_heads, n_kv_heads, vocab_size, max_seq_len,
        u8 shared_classifier, i32 group_size, zero padding
    fp32 norms: per-layer attention_norm, per-layer ffn_norm, final norm
    weights in this order, each as nibbles[numel/2] then fp16 scales[numel/gs]:
        tok_embeddings, [wq x L], [wk x L], [wv x L], [wo x L], [w1 x L], [w2 x L],
        [w3 x L], and output.weight if the classifier is not shared
    symmetric 4-bit per group: scale = max|w| / 7, q = clamp(round(w/scale), -8, 7),
    stored as q + 8 in a nibble (even weight low nibble, odd weight high nibble).

    uv run python tools/export_cat_q4.py --ckpt runs/v1/best.pt --out build/cat_q4.bin
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
GROUP_SIZE = 64
MAGIC = 0x616B3432


def quantize_q4(w: torch.Tensor, gs: int):
    w = w.float().reshape(-1, gs)
    wmax = torch.abs(w).max(dim=1).values
    scale = torch.where(wmax > 0, wmax / 7.0, torch.ones_like(wmax))
    q = torch.clamp(torch.round(w / scale[:, None]), -8, 7).to(torch.int8)
    err = float((q.float() * scale[:, None] - w).abs().max())
    return q.reshape(-1), scale, err


def pack_nibbles(q: torch.Tensor) -> bytes:
    u = (q.to(torch.int16) + 8).to(torch.uint8).numpy()
    return (u[0::2] | (u[1::2] << 4)).astype(np.uint8).tobytes()


def serialise_fp32(fh, t: torch.Tensor) -> None:
    fh.write(np.asarray(t.detach().float().numpy(), dtype="<f4").tobytes())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="export_cat_q4")
    ap.add_argument("--ckpt", type=Path, default=ROOT / "runs" / "v1" / "best.pt")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "cat_q4.bin")
    ap.add_argument("--group-size", type=int, default=GROUP_SIZE)
    a = ap.parse_args(argv)

    blob = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    sd = blob["model"]
    cfg = blob["cfg"]
    gs = a.group_size

    def attn(name: str) -> torch.Tensor:
        return sd[name]

    n_layers = cfg["n_layers"]
    hidden = sd["blocks.0.w1.weight"].shape[0]
    n_heads = cfg["n_heads"]
    seq = cfg["seq_len"]
    dim = cfg["dim"]
    # the trainer left Config.vocab_size at its default; the real vocabulary is in
    # the checkpoint's own vocab list. Row-slice the embedding and the head to it:
    # the extra rows were never trained, and the header must match the tokenizer
    # the device builds from tokenizer.bin.
    vocab = len(blob["vocab"])

    weights = [sd["tok.weight"][:vocab]]
    for suffix in ("wq", "wk", "wv", "wo"):
        for i in range(n_layers):
            weights.append(sd[f"blocks.{i}.attn.{suffix}.weight"])
    for suffix in ("w1", "w3", "w2"):
        for i in range(n_layers):
            weights.append(sd[f"blocks.{i}.{suffix}.weight"])
    shared = False                      # the cat has its own head, like llama2.c
    if not shared:
        weights.append(sd["head.weight"][:vocab])

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("wb") as fh:
        fh.write(struct.pack("I", MAGIC))
        fh.write(struct.pack("i", 3))
        fh.write(struct.pack("iiiiiii", dim, hidden, n_layers, n_heads, n_heads, vocab, seq))
        fh.write(struct.pack("B", int(shared)))
        fh.write(struct.pack("i", gs))
        fh.write(b"\0" * (256 - fh.tell()))
        for i in range(n_layers):
            serialise_fp32(fh, sd[f"blocks.{i}.attn_norm.weight"])
        for i in range(n_layers):
            serialise_fp32(fh, sd[f"blocks.{i}.ffn_norm.weight"])
        serialise_fp32(fh, sd["norm.weight"])
        worst = 0.0
        for w in weights:
            q, s, err = quantize_q4(w.detach(), gs)
            fh.write(pack_nibbles(q))
            fh.write(s.to(torch.float16).numpy().astype("<f2").tobytes())
            worst = max(worst, err)

    size = a.out.stat().st_size
    print(f"Q4 {a.out.relative_to(ROOT)}: {size / 1e6:.2f} MB "
          f"(dim {dim} hidden {hidden} layers {n_layers} heads {n_heads} vocab {vocab} seq {seq} gs {gs} "
          f"shared {shared}) max group abs error {worst:.4f}")
    print(f"GATE size<=8MB: {'PASS' if size <= 8_000_000 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
