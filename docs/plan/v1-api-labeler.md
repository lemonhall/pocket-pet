# v1-api-labeler — M3：deepseek-flash 批量标注 + 数据集纪律

- **Goal**：用最便宜的方式把 5 万条情境标注完（目标 ≤¥40，实测记账），
  并保证训练/校验/留出三集互斥、留出集只由人手标。
- **PRD Trace**：REQ-0001-005、REQ-0001-006
- **Scope**
  - 做：`pocket_pet/label.py`（批量、非思考模式、JSON 输出、缓存前缀、断点续跑、
    **逐请求记账**）、`check_dataset.py --leak`（按状态行规范化文本 hash 查交集）。
  - 不做：不做多轮自我批评（贵）；不做自动重试超 3 次；不动 M1 的采样器。
- **Acceptance**
  1. `uv run python -m pocket_pet.label --limit 100` → 100 条落 `data/labeled.jsonl`，
     schema 校验通过率 ≥99%，`data/label_cost.json` 记录花费 **≤ ¥0.10**。
  2. 再跑一次 `--limit 100` → **0 次请求**（断点续跑证据）。
  3. 全量跑完：`uv run python -m pocket_pet.label --all` → `labeled.jsonl` ≥ 50000 行，
     **实测总花费 ≤ ¥40**（`label_cost.json` 与行数自洽）。
  4. `uv run python -m pocket_pet.check_dataset --leak` →
     `NO_LEAK train=N val=N eval=N`，且 `data/eval_hand.jsonl` 每行 `source=="hand"`（≥500 条）。
- **Files**
  - `pocket_pet/label.py`、`pocket_pet/check_dataset.py`（扩展）
  - `configs/labeler-v1.json`（模型名、并发、批量、温度、max_tokens、前缀 hash）
  - `data/labeled.jsonl`、`data/label_cost.json`、`data/eval_hand.jsonl`
  - `tests/unit/test_label_cost.py`（用 mock 响应断言记账口径）、`tests/unit/test_no_leak.py`
- **Steps**
  1. **红**：`test_label_cost.py`（mock 一个返回 `usage` 的响应，断言费用 = input×单价 + output×单价，
     且**按空闲/高峰时段取价**）；`test_no_leak.py`（构造一条同时出现在两集的样本，断言脚本报错）。
  2. **跑到红**：`uv run pytest tests/unit -q` → 预期模块缺失/断言失败。
  3. **绿**：实现标注器（含 5 条种子范例作为前缀、`response_format={"type":"json_object"}`、
     `thinking` 关闭、并发 8、指数退避重试 ≤3）。
  4. **跑到绿**：`uv run pytest tests/unit -q` 全绿；跑 `--limit 100` 并贴记账输出（≤¥0.10）。
  5. **全量**：`--all`（预计 2000 请求 / 约 ¥5–15），跑完贴实测花费。
  6. **重构**：把"每请求 25 条"的批量大小抽成配置，并记录一次 A/B（批量 10 vs 40 的花费/质量对比）。
- **Risks**
  - **思考模式没关** → 输出 token 暴涨（贵 5–10×）：Step 4 的记账就是门禁（≤¥0.10 反推）。
  - 前缀没命中缓存 → 花费上升：`label_cost.json` 里分别记 `cache_hit` / `cache_miss` token 数。
  - 泄漏 → `test_no_leak.py` + 规范化 hash 兜住。
  - 5 万条里出现格式坏行 → 校验通过率 ≥99% 是硬门禁，坏行单独落 `data/labeled.bad.jsonl` 并人工看 ≥10 条。
