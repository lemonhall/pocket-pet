# v1-ship-to-device — M5：量化 + 上板（零改动复用内核）

- **Goal**：把学生装进真板子：Q4 权重 ≤8 MB、现有推理路径与 SIMD 内核**一行不改**跑起来。
- **PRD Trace**：REQ-0001-008
- **Scope**
  - 做：量化导出（fp32 → q4，沿用 pocket-tank 的导出脚本与格式）、写进 flash 分区、
    真机跑一次并抓日志。
  - 不做：不做 OTA、不做多模型切换、不动内核。
- **Acceptance**
  1. `ls -l build/pet-q4.bin` → ≤8 MB（贴数字）。
  2. 真机日志出现：`q4_model_dot_check` 全一致 + 至少一条**模型自己产出的**状态行与目标
     （例如 `hunger 7 ... -> seek_food urgency 3`）。
  3. 实测生成速度 ≥8 tok/s（日志里 `tok/s` 数字）。
- **Files**
  - `tools/export_q4.py`（复用 pocket-tank 的 `model/` 流程）
  - `firmware/`（分叉自 pocket-tank，替换世界与状态行；内核文件不动，diff 必须为空）
  - `docs/pet/on_device.md`（烧写与验证步骤）
- **Steps**
  1. **红**：写一个 `tests/e2e/test_device_log.py`：喂入一段真机日志文本，
     断言四条关键行（版本/自检/状态行/tok/s）都在 → 先拿一段假日志跑到红。
  2. **跑到红**：`uv run pytest tests/e2e/test_device_log.py -q`。
  3. **绿**：导出 + 烧写 + 抓日志（`tools/tab5_boot_log.py`，与 Tab5 档案里的流程一致）。
  4. **跑到绿**：把真机日志喂进同一测试 → 全绿；并在 `v1-index` 证据列填日志路径。
  5. **重构**：把"内核零改动"变成机器可查：`git diff --stat pocket-tank/main/... q4_model.c` 为空。
- **Risks**
  - 量化掉点（一致率从 60% 掉到 <50%）→ 先量化后评测（在主机上比对 q4 vs fp32 的一致率，差值 >5% 就回退到 q8 并走 ECN）。
  - 板上内存不够 → 沿用前作的 mmap 方案（权重不进 RAM）。
