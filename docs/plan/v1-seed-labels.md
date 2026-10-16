# v1-seed-labels — M2：种子标注（我逐条推理）

- **Goal**：产出 ≥300 条**高质量、带理由**的标注，既是训练数据的第一块，
  也是 M3 里 API 标注器的 few-shot 范例（它决定 API 标注的"猫味"基线）。
- **PRD Trace**：REQ-0001-004
- **Scope**
  - 做：从 M1 的采样器里取 350 条（覆盖全部 12 个边界族），由我逐条给
    `goal + urgency(0-3) + reason(≤40 字)`，落 `data/seed.jsonl`。
  - 不做：不做规模扩张（那是 M3）；不训练模型。
- **Acceptance**
  1. `uv run python -m pocket_pet.check_dataset --seed-only` → `SEED_OK n>=300 goals=8 min_goal>=20 families=12 min_family>=10`。
  2. 每条 `reason` 与该行 `state` 有实质关联（脚本抽查字段名/值出现，失败即 fail）。
  3. 目标分布**不塌陷**：任一目标占比 ≤ 40%（防止"全押 seek_food"）。
- **Files**
  - `data/seed.jsonl`（产物）
  - `pocket_pet/check_dataset.py`（与 M3 共用）
  - `tests/unit/test_check_dataset.py`
- **Steps**
  1. **红**：写 `test_check_dataset.py`（断言 seed-only 的六项门槛 + reason 关联 + 占比上限）。
  2. **跑到红**：`uv run pytest tests/unit/test_check_dataset.py -q` → 预期 `data/seed.jsonl` 不存在。
  3. **绿**：我按族逐条标注（每族 ≥10 条，8 个目标各 ≥20 条），写入 `data/seed.jsonl`。
  4. **跑到绿**：`uv run pytest tests/unit/test_check_dataset.py -q` 全绿 + 贴 `check_dataset --seed-only` 输出。
  5. **重构**：把 reason 的写法规范（"先看哪个字段 → 为什么是这个目标"）写进
     `docs/pet/labeling_rubric.md`，供 M3 的 API 提示复用。
- **Risks**
  - 我把"人的理性"标进去，猫反而不像猫 → 在 rubric 里显式写"猫的优先级"：
    饿 > 困 > 猫砂 > 粘人 > 玩 > 理毛 > 探索 > 躲，并允许 10% 的"没道理"（随机偏好）作为性格噪声。
  - 种子太少导致 M3 的 few-shot 偏 → 族覆盖 + 目标分布两条门槛兜住。

## 标注格式

```json
{"id":"sit-000123","state":"hunger 8 energy 3 ...","goal":"seek_food","urgency":3,"reason":"hunger 8 且 food near，先吃"}
```
