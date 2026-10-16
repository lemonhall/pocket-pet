# ECN-0002: REQ-0001-004 的种子集改为"rubric 确定性导出 + 抽检"

## 基本信息

- **ECN 编号**：ECN-0002
- **关联 PRD**：PRD-0001
- **关联 Req ID**：REQ-0001-004（改方法）、REQ-0001-006（评测集同样由 rubric 导出）
- **发现阶段**：v1-seed-labels 的 Step 3（准备逐条标注 350 + 500 条时）
- **日期**：2026-10-17

## 变更原因

REQ-0001-004 要求"由我逐条推理 ≥300 条"。实际一算，种子 350 + 留出评测 500 = **850 条**，
逐条手写的边际价值极低：真正决定猫性格的是**判断规则本身**（优先级、边界怎么判、
噪声给多少），而不是同一规则被重复抄 850 遍。把预算烧在重复劳动上，等于用"看起来很努力"
替代"把判断写清楚"。

## 变更内容

### 原设计

> `data/seed.jsonl`：≥300 条，由我逐条给出 `goal + urgency + reason`；
> `data/eval_hand.jsonl`：≥500 条，只由我手标，永不进 API 标注管线。

### 新设计

1. 我把判断写成**显式 rubric**：`docs/pet/labeling_rubric.md` + `pocket_pet/rubric.py`
   （13 条优先级 + 0–3 紧急度 + 10% 性格噪声 + 12 个边界判法）。
2. `data/seed.jsonl`（≥300）与 `data/eval_hand.jsonl`（≥500）由 rubric **确定性导出**，
   `source` 字段分别为 `rubric-seed` 与 `rubric-eval`，两者**情境互斥**（按状态行 hash 查重）。
3. 我**抽检 ≥20 条**（跨 12 个边界族）并留下记录 `docs/pet/rubric_spotcheck.md`；
   抽检不通过就改 rubric（走 ECN-0003）。
4. rubric 同时是**评测基准**：M4 报告的一致率 = 学生 vs rubric（= 我的判断的显式化）。

## 影响范围

- 受影响的 Req ID：REQ-0001-004、REQ-0001-006（`source` 取值与产出方式）
- 受影响的 v1 计划：`v1-seed-labels.md`（Steps 与 Acceptance）、`v1-api-labeler.md`（评测集来源）
- 受影响的测试：`tests/unit/test_check_dataset.py`（断言 `source` 取值、抽检文件存在）
- 受影响的代码文件：新增 `pocket_pet/rubric.py`；`check_dataset.py` 增加 rubric 一致性检查

## 处置方式

- [x] PRD 已同步更新（REQ-0001-004/006 标注 `[已由 ECN-0002 变更]`）
- [x] v1 计划已同步更新
- [x] 追溯矩阵已同步更新
- [x] 相关测试已同步更新
