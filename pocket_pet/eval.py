"""Evaluate the student against my rubric's held-out labels (REQ-0001-007).

    uv run python -m pocket_pet.eval --ckpt runs/v1/best.pt --eval data/eval_hand.jsonl

Reports the agreement, the confusion matrix, the disagreements (exported as
`runs/v1/disagreements.jsonl` for the next round's seeds) and the majority-class
baseline - the anti-cheat that catches a model which just answers one goal.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import torch

from . import tokenizer as T
from .model import CatLM, Config

ROOT = Path(__file__).resolve().parents[1]


def load_model(ckpt: Path):
    blob = torch.load(ckpt, map_location="cpu", weights_only=False)
    cfg = Config(**blob["cfg"])
    model = CatLM(cfg)
    model.load_state_dict(blob["model"])
    model.eval()
    return model, cfg


@torch.no_grad()
def predict(model: CatLM, cfg: Config, state_line: str) -> str:
    ids = T.encode(state_line, bos=True)[-cfg.seq_len:]
    logits = model.next_token_logits(ids)
    goal_ids = [T.STOI[g] for g in T.GOALS]
    best = max(goal_ids, key=lambda gi: float(logits[gi]))
    return T.VOCAB[best]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pocket_pet.eval")
    ap.add_argument("--ckpt", type=Path, default=ROOT / "runs" / "v1" / "best.pt")
    ap.add_argument("--eval", type=Path, default=ROOT / "data" / "eval_hand.jsonl")
    ap.add_argument("--dump", type=Path, default=ROOT / "runs" / "v1" / "disagreements.jsonl")
    a = ap.parse_args(argv)
    model, cfg = load_model(a.ckpt)
    rows = [json.loads(l) for l in a.eval.read_text(encoding="utf-8").splitlines() if l.strip()]

    conf = collections.defaultdict(collections.Counter)
    hits = 0
    dis = []
    for r in rows:
        pred = predict(model, cfg, r["state"])
        conf[r["goal"]][pred] += 1
        if pred == r["goal"]:
            hits += 1
        else:
            dis.append({"id": r["id"], "state": r["state"], "want": r["goal"], "got": pred,
                        "reason": r.get("reason", "")})
    agree = hits / max(1, len(rows))
    counts = collections.Counter(r["goal"] for r in rows)
    majority = max(counts.values()) / max(1, len(rows))
    a.dump.parent.mkdir(parents=True, exist_ok=True)
    a.dump.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dis) + "\n", encoding="utf-8")

    print(f"AGREEMENT={agree * 100:.1f}%  (want >= 60%)  n={len(rows)}")
    print(f"BASELINE majority-class={majority * 100:.1f}%  "
          f"{'PASS: the model beats the baseline' if agree > majority + 0.05 else 'FAIL: check the model'}")
    print("confusion (rows = my label, cols = the model):")
    goals = list(T.GOALS)
    print("      " + " ".join(f"{g[:4]:>4s}" for g in goals))
    for want in goals:
        print(f"{want[:5]:>5s} " + " ".join(f"{conf[want][g]:4d}" for g in goals))
    print(f"disagreements -> {a.dump.relative_to(ROOT)} ({len(dis)} rows)")
    return 0 if agree >= 0.60 and agree > majority else 1


if __name__ == "__main__":
    raise SystemExit(main())
