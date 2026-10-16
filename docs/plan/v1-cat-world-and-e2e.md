# v1-cat-world-and-e2e — M6：猫的世界（反射层）+ 端到端测试

- **Goal**：先让"没有小脑的猫"也能活（反射层 + 世界），再用 E2E 证明整条用户流程跑得通；
  小脑装上之后行为分布发生可量化变化。
- **PRD Trace**：REQ-0001-009、REQ-0001-010
- **Scope**
  - 做：房间世界（分区、食盆、猫砂盆、猫爬架、窗台、玩具、人的位置）、猫的连续行为
    （走动/进食/睡觉/上厕所/理毛/伸爪）、无头模拟器 `sim/`、E2E 测试。
  - 不做：不做美术升级；不做多猫交互；不做声音。
- **Acceptance**
  1. `uv run python -m pocket_pet.sim --no-advisor --minutes 5 --report`
     → 无异常退出，且打印"状态机覆盖 ≥8 个状态"（运行期统计）。
  2. `uv run python -m pocket_pet.sim --advisor --minutes 5 --report`
     → 行为分布与 ① 相比**至少 3 个目标出现次数变化 ≥50%**（证明小脑真的在起作用）。
  3. `uv run pytest tests/e2e/ -q` 全绿：`test_cat_day_flow.py` 覆盖
     `seek_food → eat → play → sleep` 全链路，且**调用真实的 `advisor.choose()`**（不允许绕过）。
- **Files**
  - `pocket_pet/{world,cat,reflex,sim,advisor}.py`
  - `tests/e2e/test_cat_day_flow.py`、`tests/e2e/test_sim_no_advisor.py`
  - `docs/pet/world.md`（房间布局与状态机图）
- **Steps**
  1. **红**：写 `test_sim_no_advisor.py`（断言 5 分钟内无异常 + 覆盖率 ≥8）。
  2. **跑到红**：`uv run pytest tests/e2e -q` → 预期模块缺失。
  3. **绿**：实现世界 + 反射层 + 模拟器（反射层可先用规则挑目标，专门用于 ① 的验证）。
  4. **跑到绿**：`uv run pytest tests/e2e -q` 全绿 + 贴两条 `--report` 输出对比。
  5. **接小脑**：`advisor.choose()` 走 M4 的模型（`--advisor`），跑 ② 的对比。
- **Risks**
  - 反射层被写得太聪明 → 小脑就没存在感（② 的对比就是门禁：分布必须显著变化）。
  - 无头模拟与真机行为不一致 → 用同一份 `reflex.py`/世界参数，真机只是渲染层不同（M5 只换显示）。
  - 5 分钟太短看不出覆盖 → 覆盖率门槛写 8 个状态（不是"越多越好"），可调但要走 ECN。
