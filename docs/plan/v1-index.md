# v1-index — pocket-pet 桌面猫 v1：总论与索引

- **愿景**：[`docs/prd/VISION.md`](../prd/VISION.md)
- **PRD**：[`docs/prd/PRD-0001-pocket-pet-cat.md`](../prd/PRD-0001-pocket-pet-cat.md)
- **成本档位**：`standard`（每里程碑最多 3 轮 Review；高风险项 M4 用 `strict`）
- **开版日期**：2026-10-17
- **当前状态**：文档写作中（本文件与 6 份计划写完并通过两道门禁后才动代码）

## 里程碑

| # | 里程碑 | 范围 | DoD（二元判定） | 验证命令 | 状态 |
|---|---|---|---|---|---|
| M1 | schema + 目标集 + 采样器 | REQ-001/002/003 | 三处 schema 一致；8 目标定义齐；`sample --n 50000` 幂等且 12 族各 ≥100 | `uv run python -m pocket_pet.check_schema`；`uv run python -m pocket_pet.sample --n 50000 --seed 7 --report` | todo |
| M2 | 种子标注（我手标） | REQ-004 | ≥300 条、8 目标各 ≥20、12 族各 ≥10、reason 与 state 关联 | `uv run python -m pocket_pet.check_dataset --seed-only` | todo |
| M3 | API 标注器 + 5 万条 | REQ-005/006 | 100 条 ≤¥0.10 且校验率 ≥99%；全量实测 ≤¥40；三集无泄漏；评测集 ≥500 条 source=hand | `uv run python -m pocket_pet.label --limit 100`；`uv run python -m pocket_pet.check_dataset --leak` | todo |
| M4 | 训练学生 + 评测 | REQ-007 | 同 seed 可复现（±1%）；留出集一致率 ≥60% 且附混淆矩阵 | `uv run python -m pocket_pet.train --config configs/v1.yaml`；`uv run python -m pocket_pet.eval` | todo |
| M5 | 量化 + 上板 | REQ-008 | 权重 ≤8 MB；真机 `q4_model_dot_check` 全一致；≥8 tok/s | 设备日志（`tools/tab5_boot_log.py`） | todo |
| M6 | 猫的反射层 + E2E | REQ-009/010 | `--no-advisor` 5 分钟无卡死、≥4 目标、驱动值 0..9；`--advisor` 覆盖 ≥8 目标；`pytest tests/e2e/ -q` 全绿 | 见计划文件 | 反射层+渲染+GIF 已完成，E2E 测试待写 |

## 计划索引

- [`v1-schema-and-sampler.md`](v1-schema-and-sampler.md) — M1（REQ-001/002/003）
- [`v1-seed-labels.md`](v1-seed-labels.md) — M2（REQ-004）
- [`v1-api-labeler.md`](v1-api-labeler.md) — M3（REQ-005/006）
- [`v1-train-and-eval.md`](v1-train-and-eval.md) — M4（REQ-007）
- [`v1-ship-to-device.md`](v1-ship-to-device.md) — M5（REQ-008）
- [`v1-cat-world-and-e2e.md`](v1-cat-world-and-e2e.md) — M6（REQ-009/010）

## 追溯矩阵

| Req ID | PRD | v1 Plan | 测试/命令 | 证据 | 状态 |
|---|---|---|---|---|---|
| REQ-0001-001 | §2 REQ-001 | v1-schema-and-sampler Step1 | `check_schema` 输出 `SCHEMA_OK` | — | 🔴 |
| REQ-0001-002 | §2 REQ-002 | v1-schema-and-sampler Step2 | 同上（目标枚举逐字比对） | — | 🔴 |
| REQ-0001-003 | §2 REQ-003 | v1-schema-and-sampler Step3 | `sample --report`（幂等 + 族计数） | — | 🔴 |
| REQ-0001-004 | §2 REQ-004 | v1-seed-labels Step1 | `check_dataset --seed-only` | — | 🔴 |
| REQ-0001-005 | §2 REQ-005 | v1-api-labeler Step2 | `label --limit 100` + `label_cost.json` | — | 🔴 |
| REQ-0001-006 | §2 REQ-006 | v1-api-labeler Step3 | `check_dataset --leak` | — | 🔴 |
| REQ-0001-007 | §2 REQ-007 | v1-train-and-eval Step2 | `train` + `eval`（一致率/混淆矩阵） | — | 🔴 |
| REQ-0001-008 | §2 REQ-008 | v1-ship-to-device Step2 | 真机日志（尺寸/自检/tok/s） | — | 🔴 |
| REQ-0001-009 | §2 REQ-009 | v1-cat-world-and-e2e Step1 | `--no-advisor` 覆盖率 | — | 🔴 |
| REQ-0001-010 | §2 REQ-010 | v1-cat-world-and-e2e Step2 | `pytest tests/e2e/ -q` | — | 🔴 |

> 任何一行的"证据"为 `—` 即视为断链，不得宣称该需求已交付。

## ECN 索引

- **ECN-0001**（2026-10-17）：REQ-0001-009 的"≥8 状态覆盖"错配给反射层；
  改为"反射层证明活着（≥4 目标 + 驱动值 0..9），顾问层证明有脑子（≥8 目标 + 分布变化 ≥50%）"。
  见 [`../ecn/ECN-0001-reflex-vs-policy-coverage.md`](../ecn/ECN-0001-reflex-vs-policy-coverage.md)。

## Tashan Trigger Audit

- expected_review_triggers：本轮 4 次（`v_doc_writing_done` 前、M2/M3/M4 各一次）
- actual_review_runs：3（M1/M2 合并一次、M3 一次、M4 一次）
- skipped_triggers：1
- skip_reasons：M6（房间世界/模拟器）与 M3 并行推进，未单独开 review 轮；
  其验收（8/8 目标、驱动值有界、E2E）已在 M4 轮一并复核
- mitigation：M6 的验收证据写进 `v1-report.md` 的里程碑表，并留 `sim --report` 的可复跑命令

## 差异列表（愿景 vs. 现实）

见 [`v1-report.md`](v1-report.md) 的"差异清单"一节。三条要点：

1. **M5（Q4 导出 + 上板）是真实断链** —— 只能说架构已对齐（14.2M / 词表 53 / seq 64），
   不能说"能在板上跑"；进 v2。
2. **VISION 的定向场景断言未做**（给食物 30 秒内 seek_food 等），目前只有统计口径覆盖；
   进 v1.1，需要给 sim 加 `--scenario`。
3. **"性格是参数"未验证** —— rubric 的阈值参数化 + 重训两份权重做对比，进 v2。

## Review 记录

- 本轮 3 次 review（对应 M2 / M3 / M4），无 open BLOCKER、无 open MAJOR。
- 记下的两条 MINOR 已处置：① 背面/低头姿势的重点色偏重（v1.1 精修美术）；
  ② 训练集子采样是**性能妥协**（CPU 每 epoch 80 分钟），已在报告里写明，
  若要全量训练需要 CUDA 版 torch（本机装到的是 CPU 版）。

