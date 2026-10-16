# 猫的状态行（v1，冻结）

> 唯一权威是 `include/pet_state.h`；本文件由 `pocket_pet.check_schema` 与它逐名比对，
> 两处不一致就判 fail（REQ-0001-001）。

## 格式

一行，空格分隔的 `名字 值` 序列，数值字段是裸整数，方位字段是 `none` 或 `<桶> <时钟位>`，
META 字段是词。整行不超过 48 token。

```
hunger 6 energy 3 bored 5 clingy 7 litter 2 scruff 1 curiosity 8 bold 4 lazy 5 stage adult food near 3 toy mid 9 owner far 6 litter_box near 12 window none last play time night
```

## 字段表（17 个）

| 字段 | 类型 | 取值 | 含义 |
|---|---|---|---|
| hunger | NUM | 0–9 | 饿（9 = 饿疯） |
| energy | NUM | 0–9 | 精力（0 = 快睡着） |
| bored | NUM | 0–9 | 无聊（这是防止呆滞的关键字段） |
| clingy | NUM | 0–9 | 粘人（0 = 别烦我） |
| litter | NUM | 0–9 | 猫砂盆脏的程度（7+ = 它会犹豫） |
| curiosity | NUM | 0–9 | 好奇 |
| bold | NUM | 0–9 | 胆大（与 hide 负相关） |
| lazy | NUM | 0–9 | 懒 |
| scruff | NUM | 0–9 | 毛乱的程度（它自己会理毛） |
| food | WHERE | none / near·mid·far 1–12 | 食盆相对它自己的方位（时钟位） |
| toy | WHERE | 同上 | 玩具 |
| owner | WHERE | 同上 | 人 |
| litter_box | WHERE | 同上 | 猫砂盆 |
| window | WHERE | 同上 | 窗台 |
| stage | META | kitten / adult / elder | 年龄阶段 |
| last | META | 任一目标名 | 上一个目标（防抖 + 让模型懂"刚做完"） |
| time | META | dawn / day / dusk / night | 一天里的时段 |

## 注意事项

- `last` 与当前欲望冲突是有意保留的边界族（例如刚睡醒又饿疯了），见 `families.py`。
- 方位用"时钟位"而不是坐标：与 pocket-tank 的既有写法一致，模型见到的仍是离散词。
