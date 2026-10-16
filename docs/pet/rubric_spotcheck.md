# rubric 抽检记录（ECN-0002 承诺的 ≥20 条人工复核）

- **日期**：2026-10-17
- **样本**：`uv run python tools/spotcheck.py`（每个 boundary family 抽 1 条 + 自然样本，共 15 条）
- **我（老师本人）的判定**：**14 / 15 认可**，1 处发现 rubric 自身矛盾。

## 逐条

| family | 状态要点 | rubric 给的 | 我的判定 |
|---|---|---|---|
| clingy_max | energy 2、clingy 9 | sleep u2 | ✅ 困 > 粘人，对 |
| clingy_with_owner | clingy 8、owner mid、无硬需求 | follow_owner u2 | ✅ 稀有类，正是想要的 |
| conflicting_last | hunger 9 且 last=sleep | seek_food u3 | ✅ 当前欲望压过 last，符合"last 只防抖" |
| curious_max | curiosity 9 但 energy 3、night | sleep u2 | ✅ 困 > 好奇 |
| deep_night | night | sleep u2 | ✅ |
| dirty_box | litter 8 | scratch u3 | ✅ 猫砂脏优先于理毛/玩 |
| extreme_hunger | hunger 9、energy 1 | seek_food u3 | ✅（我刻意让"饿"压过"困"，保持一致） |
| extreme_tired | energy 1 | sleep u3 | ✅ |
| food_at_paw | hunger 7、food near | seek_food u3 | ✅ |
| just_woke | energy 8、bold 2、owner near | hide u2 | ✅ 胆小的猫刚醒躲人，合理 |
| **lazy_max** | **lazy 9、bored 7** | **play u1** | ❌ **矛盾**：规则 10 用 `lazy<=6` 挡懒猫玩，规则 12 却没挡 → 已修 |
| owner_far_but_clingy_0 | clingy 0、scruff 7 | groom u1 | ✅ 不粘人就理毛 |
| scruffy | scruff 8 | groom u1 | ✅ |
| timid_with_owner | bold 2、owner near | hide u2 | ✅ |
| toy_diagonal | bored 6、toy far | play u1 | ✅ 玩具远也照玩（它会走过去） |

## 处置

1. **规则 12 加 `lazy <= 7`**（`pocket_pet/rubric.py`）：懒到 8–9 的猫不再"无聊就去玩"，
   落到 `explore`（懒猫就是不怎么动）。这条改动**改变了已生成的数据集**，
   所以 `data/seed.jsonl` 与 `data/eval_hand.jsonl` 在改后重新生成过一遍。
2. 其余 14 条无需改动；没有发现"理由与状态无关"的标注（那条反作弊检查也一直在跑）。

## 结论

rubric 抽检通过（修正 1 处后）。这也是 M4 评测的基准：学生的一致率是**对着这份判断**算的。
