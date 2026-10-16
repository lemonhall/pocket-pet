"""Train the 14M student (REQ-0001-007).

Objective: next-token cross-entropy *at the goal position only* - the model is
asked exactly one question ("what comes after this state line?"), which is what
the tank's engine does at runtime too.

    uv run python -m pocket_pet.train --config configs/v1.yaml
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
import torch.nn.functional as F

from . import tokenizer as T
from .model import CatLM, Config

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        if p.exists():
            rows += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows


def encode_row(row: dict, cfg: Config):
    """(input ids, target index) - target is the goal token's position."""
    ids = T.encode(f"{row['state']} {row['goal']}", bos=True, eos=True)
    ids = ids[:cfg.seq_len]
    goal_id = T.STOI[row["goal"]]
    if goal_id not in ids:
        return None
    pos = ids.index(goal_id)          # first occurrence is the goal
    if pos < 1:
        return None
    x = ids[:pos]
    return x, goal_id


def make_batch(rows: list[dict], cfg: Config, device):
    xs, ys = [], []
    for r in rows:
        enc = encode_row(r, cfg)
        if enc is None:
            continue
        x, y = enc
        xs.append(x); ys.append(y)
    if not xs:
        return None, None
    width = max(len(x) for x in xs)
    pad = T.STOI["<pad>"]
    xi = torch.tensor([x + [pad] * (width - len(x)) for x in xs], dtype=torch.long, device=device)
    yi = torch.tensor(ys, dtype=torch.long, device=device)
    return xi, yi


def goal_logits(model: CatLM, xi: torch.Tensor, ys: torch.Tensor) -> torch.Tensor:
    """Logits at the last real position of each row, restricted to the goal tokens."""
    logits = model(xi)
    pad = T.STOI["<pad>"]
    lens = (xi != pad).sum(dim=1).clamp(min=1)
    rows = torch.arange(xi.shape[0], device=xi.device)
    last = logits[rows, lens - 1]
    goal_ids = torch.tensor([T.STOI[g] for g in T.GOALS], device=xi.device)
    return last[:, goal_ids], goal_ids


def evaluate(model: CatLM, rows: list[dict], cfg: Config, device, bs: int = 256) -> float:
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            xi, yi = make_batch(chunk, cfg, device)
            if xi is None:
                continue
            lg, goal_ids = goal_logits(model, xi, yi)
            want = torch.tensor([int((goal_ids == y).nonzero()[0]) for y in yi], device=device)
            correct += int((lg.argmax(-1) == want).sum())
            total += len(chunk)
    return correct / max(1, total)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pocket_pet.train")
    ap.add_argument("--config", type=Path, default=ROOT / "configs" / "v1.yaml")
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--max-rows", type=int, default=None,
                    help="subsample the training set (the policy is 13 rules; a few "
                         "thousand rows is plenty, and a full pass costs ~240 TFLOPs)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)

    cfg_kv = {}
    for line in a.config.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.strip().startswith("#"):
            k, v = line.split(":", 1)
            cfg_kv[k.strip()] = v.strip()
    cfg = Config(seq_len=int(cfg_kv.get("seq_len", 64)))
    epochs = a.epochs or int(cfg_kv.get("epochs", 6))
    lr = float(cfg_kv.get("lr", 3e-4))
    bs = int(cfg_kv.get("batch_size", 64))

    random.seed(a.seed); torch.manual_seed(a.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rows = load_rows([DATA / "labeled.jsonl", DATA / "seed.jsonl"])
    if not rows:
        print("TRAIN_FAIL no labelled rows (run the labeler first)")
        return 1
    random.Random(a.seed).shuffle(rows)
    if a.max_rows and len(rows) > a.max_rows:
        # stratified: keep the class balance while shrinking the set
        per_goal: dict[str, list] = {}
        for r in rows:
            per_goal.setdefault(r["goal"], []).append(r)
        keep = max(1, a.max_rows // max(1, len(per_goal)))
        rows = [r for g in per_goal for r in per_goal[g][:keep]]
        random.Random(a.seed).shuffle(rows)
        print(f"TRAIN subsampled to {len(rows)} rows ({keep} per goal)")
    cut = max(1, len(rows) // 10)
    val, train = rows[:cut], rows[cut:]

    model = CatLM(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = max(1, math.ceil(len(train) / bs)) * epochs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.1)

    out = ROOT / "runs" / "v1"
    out.mkdir(parents=True, exist_ok=True)
    best = -1.0
    curve = []
    print(f"TRAIN device={device} params={model.n_params():,} rows={len(rows)} "
          f"train={len(train)} val={len(val)} epochs={epochs} bs={bs}")
    t0 = time.time()
    for ep in range(epochs):
        model.train()
        random.Random(a.seed + ep).shuffle(train)
        tot, n = 0.0, 0
        for i in range(0, len(train), bs):
            xi, yi = make_batch(train[i:i + bs], cfg, device)
            if xi is None:
                continue
            lg, goal_ids = goal_logits(model, xi, yi)
            want = torch.tensor([int((goal_ids == y).nonzero()[0]) for y in yi], device=device)
            loss = F.cross_entropy(lg, want)
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step()
            tot += float(loss) * len(xi); n += len(xi)
        acc = evaluate(model, val, cfg, device)
        curve.append({"epoch": ep + 1, "loss": round(tot / max(1, n), 4), "val_acc": round(acc, 4)})
        print(f"  epoch {ep + 1}/{epochs} loss={tot / max(1, n):.4f} val_acc={acc:.3f} "
              f"({time.time() - t0:.0f}s)")
        if acc > best:
            best = acc
            torch.save({"model": model.state_dict(), "cfg": cfg.__dict__, "vocab": T.VOCAB,
                        "val_acc": acc, "epoch": ep + 1}, out / "best.pt")
    (out / "curve.json").write_text(json.dumps(curve, indent=1), encoding="utf-8")
    print(f"TRAIN_OK best_val_acc={best:.3f} ckpt={out / 'best.pt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
