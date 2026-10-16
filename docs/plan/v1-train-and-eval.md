# v1-train-and-eval — M4：训练 14M 学生 + 一致率评测

- **Goal**：把标注变成一只"会挑事做"的小脑：14M 参数、词表 ≤64、与我的手标在留出集上一致率 ≥60%。
- **PRD Trace**：REQ-0001-007
- **Scope**
  - 做：`pocket_pet/train.py`（PyTorch，同 seed 可复现）、`eval.py`（一致率 + 混淆矩阵 +
    分歧案例导出）、`configs/v1.yaml`。
  - 不做：不改架构（dim 384/8L/8H 固定）；不做超参大搜索（v1 只要"能过线"）。
- **Acceptance**
  1. `uv run python -m pocket_pet.train --config configs/v1.yaml` 两次（同 seed），
     最终 loss 差异 ≤1%，checkpoint 可加载。
  2. `uv run python -m pocket_pet.eval --ckpt runs/v1/best.pt --eval data/eval_hand.jsonl`
     → 打印 `AGREEMENT=<x>%`（**≥60%**）+ 混淆矩阵 + 导出 ≥20 条分歧到 `runs/v1/disagreements.jsonl`。
  3. 反作弊：跑一次"全押 seek_food"的基线，其一致率必须**明显低于**学生（证明指标不是被单一类刷出来的）。
- **Files**
  - `pocket_pet/{train,eval,model}.py`、`configs/v1.yaml`
  - `runs/v1/`（不入库，`.gitignore`）、`runs/v1/disagreements.jsonl`（入库，作为下一轮种子）
  - `tests/unit/test_model_shapes.py`（断言参数量 ≈14M、词表 ≤64、seq 64）
- **Steps**
  1. **红**：`test_model_shapes.py`（参数量、词表、seq 三条断言）+ `eval.py` 的指标单测（构造完美/随机两个假预测，断言 100%/接近基线）。
  2. **跑到红**：`uv run pytest tests/unit -q` → 预期失败。
  3. **绿**：写模型（与 pocket-tank 同构：RMSNorm + RoPE + SwiGLU，word-level 词表 ≤64）+ 训练循环 + 评测。
  4. **跑到绿**：`uv run pytest tests/unit -q` 全绿；训练一次并把 `AGREEMENT` 写进 `v1-index` 的追溯矩阵证据列。
  5. **重构**：从 `disagreements.jsonl` 里挑 30 条补进种子（走 ECN 记录），再训一次看是否提升。
- **Risks**
  - 一致率上不去（<60%）→ 三个可查方向：标注噪声（看分歧）、状态行信息不足（加字段要走 ECN）、
    模型太小（v1 不扩，记录差异进 v2）。
  - 词表泄漏（测试集出现训练集没有的词）→ 词表在 M1 的 schema 里就已封闭，且 `check_schema` 兜住。

## 成本档位：strict（这是本轮的成败点）
