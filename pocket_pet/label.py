"""Label situations with deepseek-flash (REQ-0001-005).

Design notes that the cost depends on:
  * `{"thinking": {"type": "disabled"}}` - thinking is ON by default with effort
    high, and its tokens are billed as output. Leaving it on would multiply the
    bill several times over.
  * one request carries BATCH=25 situations, so the rubric prefix (which is
    identical every time and therefore cache-hit) is amortised.
  * the rubric + six seed examples are the fixed prefix; only the situations vary.
  * resume: ids already present in the output are skipped, so a second run makes
    zero requests (that is checked in tests/unit/test_label_cost.py).
  * accounting comes from the API's own `usage` numbers, never from a local guess.

    DEEPSEEK_API_KEY=... uv run python -m pocket_pet.label --limit 100
    DEEPSEEK_API_KEY=... uv run python -m pocket_pet.label --all
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .state import GOALS, State

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SITUATIONS = DATA / "situations.jsonl"
OUT = DATA / "labeled.jsonl"
BAD = DATA / "labeled.bad.jsonl"
COST = DATA / "label_cost.json"
RUBRIC_DOC = ROOT / "docs" / "pet" / "labeling_rubric.md"
SEED = DATA / "seed.jsonl"

API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
BATCH = 25
WORKERS = 8
MAX_RETRY = 3
BEIJING = timezone(timedelta(hours=8))

# CNY per 1M tokens: (off-peak, peak). Off-peak is half price; peak is Mon-Fri
# 09:00-12:00 and 14:00-18:00 Beijing time.
PRICES = {"in_hit": (0.02, 0.04), "in_miss": (1.0, 2.0), "out": (4.0, 8.0)}


def is_peak(now: datetime | None = None) -> bool:
    now = now or datetime.now(BEIJING)
    return now.weekday() < 5 and (9 <= now.hour < 12 or 14 <= now.hour < 18)


def cost_cny(prompt_hit: int, prompt_miss: int, completion: int, peak: bool) -> float:
    i = 1 if peak else 0
    return (prompt_hit * PRICES["in_hit"][i] + prompt_miss * PRICES["in_miss"][i]
            + completion * PRICES["out"][i]) / 1_000_000.0


def system_prompt() -> str:
    """The rubric + a handful of seed examples - the fixed, cacheable prefix."""
    rubric = RUBRIC_DOC.read_text(encoding="utf-8")
    examples = []
    if SEED.exists():
        rows = [json.loads(l) for l in SEED.read_text(encoding="utf-8").splitlines() if l.strip()]
        random.Random(11).shuffle(rows)
        picked = []
        seen_goals = set()
        for r in rows:                       # one example per goal, for balance
            if r["goal"] not in seen_goals:
                picked.append(r); seen_goals.add(r["goal"])
            if len(picked) >= 8:
                break
        for r in picked:
            examples.append(f'{r["state"]} -> {r["goal"]} u{r["urgency"]}  ({r["reason"]})')
    ex = "\n".join(examples)
    return (
        "You label situations for a virtual Siamese cat. Apply the rubric below exactly; "
        "do not invent goals. Reply with JSON only: {\"labels\":[{\"id\":...,\"goal\":...,"
        "\"urgency\":0-3,\"reason\":\"<=40 chars, must mention a field or value from the state\"}]}.\n\n"
        f"# Rubric\n{rubric}\n\n# Examples (state -> goal urgency (reason))\n{ex}\n"
    )


def build_user_msg(rows: list[dict]) -> str:
    lines = [f'{r["id"]}\t{r["state"]}' for r in rows]
    return "Label these situations:\n" + "\n".join(lines)


def call_api(key: str, sys_msg: str, user_msg: str, timeout: int = 180) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": 4000,
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_labels(payload: dict, batch: list[dict]) -> tuple[list[dict], list[str]]:
    """Pull labels out of the reply; return (good rows, complaints)."""
    bad: list[str] = []
    try:
        content = payload["choices"][0]["message"]["content"]
        data = json.loads(content)
        items = data.get("labels", data if isinstance(data, list) else [])
    except Exception as e:                      # noqa: BLE001 - report, do not crash
        return [], [f"unparsable reply: {e}"]
    by_id = {r["id"]: r for r in batch}
    out = []
    for it in items:
        i = it.get("id")
        if i not in by_id:
            bad.append(f"unknown id {i!r}")
            continue
        goal = it.get("goal")
        if goal not in GOALS:
            bad.append(f"{i}: bad goal {goal!r}")
            continue
        reason = str(it.get("reason", ""))[:40]
        if not reason:
            bad.append(f"{i}: empty reason")
            continue
        out.append({"id": i, "state": by_id[i]["state"], "goal": goal,
                    "urgency": int(it.get("urgency", 0)), "reason": reason, "source": "api"})
    return out, bad


def load_done() -> set[str]:
    if not OUT.exists():
        return set()
    return {json.loads(l)["id"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}


def run(limit: int | None, all_rows: bool, dry: bool = False) -> int:
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DSH_DEEPSEEK_API_KEY")
    if not key and not dry:
        print("LABEL_FAIL no DEEPSEEK_API_KEY in the environment")
        return 1
    rows = [json.loads(l) for l in SITUATIONS.read_text(encoding="utf-8").splitlines() if l.strip()]
    if all_rows and len(rows) < 50000:
        print(f"LABEL_WARN situations.jsonl has {len(rows)} rows; run "
              f"`uv run python -m pocket_pet.sample --n 50000 --seed 7 --out data/situations.jsonl`")
    done = load_done()
    todo = [r for r in rows if r["id"] not in done]
    if limit:
        todo = todo[:limit]
    if not todo:
        print(f"LABEL_SKIP nothing to do ({len(done)} already labelled, 0 requests)")
        return 0
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    sys_msg = system_prompt()
    total = {"requests": 0, "in_hit": 0, "in_miss": 0, "out": 0, "cny": 0.0, "bad": 0}

    def work(batch):
        last: Exception | None = None
        for attempt in range(MAX_RETRY):
            try:
                return batch, call_api(key, sys_msg, build_user_msg(batch)), None
            except urllib.error.HTTPError as e:
                last = e
                body = e.read().decode("utf-8", "replace")[:200]
                if e.code in (429, 500, 502, 503):
                    time.sleep(2 ** attempt)
                    continue
                return batch, None, f"HTTP {e.code}: {body}"
            except Exception as e:              # noqa: BLE001
                last = e
                time.sleep(2 ** attempt)
        return batch, None, f"{last}"

    peak = is_peak()
    with OUT.open("a", encoding="utf-8", newline="\n") as fh, \
         BAD.open("a", encoding="utf-8", newline="\n") as bh, \
         ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for batch, payload, err in pool.map(work, batches):
            total["requests"] += 1
            if err:
                bh.write(json.dumps({"batch": [r["id"] for r in batch], "error": err},
                                    ensure_ascii=False) + "\n")
                total["bad"] += len(batch)
                continue
            usage = payload.get("usage", {})
            total["in_hit"] += usage.get("prompt_cache_hit_tokens", 0)
            total["in_miss"] += usage.get("prompt_cache_miss_tokens", usage.get("prompt_tokens", 0))
            total["out"] += usage.get("completion_tokens", 0)
            good, bad = parse_labels(payload, batch)
            for r in good:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            for b in bad:
                bh.write(json.dumps({"id": b}, ensure_ascii=False) + "\n")
            total["bad"] += len(bad) + (len(batch) - len(good) - len(bad))
    total["cny"] = cost_cny(total["in_hit"], total["in_miss"], total["out"], peak)
    total["peak"] = peak
    prev = json.loads(COST.read_text(encoding="utf-8")) if COST.exists() else {"cny": 0.0, "requests": 0}
    merged = {"requests": prev.get("requests", 0) + total["requests"],
              "cny": round(prev.get("cny", 0.0) + total["cny"], 4),
              "in_hit": prev.get("in_hit", 0) + total["in_hit"],
              "in_miss": prev.get("in_miss", 0) + total["in_miss"],
              "out": prev.get("out", 0) + total["out"],
              "last_peak": peak, "last_bad": total["bad"]}
    COST.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"LABEL_OK requests={total['requests']} cost=CNY {total['cny']:.4f} "
          f"(cumulative CNY {merged['cny']:.4f}) in_hit={total['in_hit']} "
          f"in_miss={total['in_miss']} out={total['out']} bad={total['bad']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pocket_pet.label")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if not a.limit and not a.all:
        a.limit = 100
    return run(a.limit, a.all)


if __name__ == "__main__":
    raise SystemExit(main())
