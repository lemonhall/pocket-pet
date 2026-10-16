# v1-schema-and-sampler — M1：状态行 schema、目标集、情境采样器

- **Goal**：把"猫的状态"与"猫的目标"冻结成可复现的 schema，并能批量生成多样情境。
  这是后面所有标注/训练/评测的地基（愿景的"它像一只猫"从这里开始）。
- **PRD Trace**：REQ-0001-001、REQ-0001-002、REQ-0001-003
- **Scope**
  - 做：`state_line.md`（人读）、`include/pet_state.h`（C，字段表 + 目标枚举）、
    `pocket_pet/state.py`（编解码）、`pocket_pet/sample.py`（采样器 + 报告）、
    `pocket_pet/check_schema.py`（三方一致性校验）。
  - 不做：数值标定、多只猫、任何模型相关代码。
- **Acceptance**
  1. `uv run python -m pocket_pet.check_schema` → `SCHEMA_OK fields=17 goals=8`（字段表从 C 头解析）。
  2. `uv run python -m pocket_pet.sample --n 50000 --seed 7 --out data/situations.jsonl`
     连跑两次，产物 sha256 相同。
  3. `uv run python -m pocket_pet.sample --report --in data/situations.jsonl`
     打印 12 个边界族的计数，**每族 ≥100**。
- **Files**（创建）
  - `docs/pet/state_line.md`、`docs/pet/goals.md`
  - `include/pet_state.h`
  - `pocket_pet/{__init__,state,sample,check_schema}.py`
  - `tests/unit/test_state.py`、`tests/unit/test_sample.py`、`tests/unit/test_check_schema.py`
- **Steps**（严格按序）
  1. **红**：写 `tests/unit/test_check_schema.py`（断言 `SCHEMA_OK`、断言删一个字段就 fail）
     与 `test_sample.py`（断言幂等、断言族计数 ≥100）。
  2. **跑到红**：`uv run pytest tests/unit -q` → 预期 `ModuleNotFoundError: pocket_pet.check_schema`。
  3. **绿**：写 schema 三件套 + 采样器。
  4. **跑到绿**：`uv run pytest tests/unit -q` 全绿；再跑 Acceptance 的 1–3 条命令并贴输出。
  5. **重构**：把采样分布抽成 `configs/sampler-v1.json`（仍绿 + 幂等不变）。
- **Risks**
  - 三处 schema 漂移 → 由 `check_schema` 从 C 头解析来消除（反作弊条款）。
  - 采样器"看起来多样其实扎堆" → 用族计数 + 每字段分布报告兜住。

## 状态行（v1 草案，Step 3 冻结）

```
hunger 6 energy 3 bored 5 clingy 7 litter 2 curiosity 8 bold 4 lazy 5 stage adult
food near 3 toy mid 9 owner far 6 litter_box near 12 window none last play time night
```

- 数值字段 0–9；方位字段 `none` / `near|mid|far <时钟位>`（时钟位 = 1..12，跟鱼缸版一致）。
- 目标枚举：`seek_food sleep play groom follow_owner scratch explore hide`。
