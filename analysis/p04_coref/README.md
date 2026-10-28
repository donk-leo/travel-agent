# 项目 4 · 程序性知识的共指消解

> 负责人：**成员3（待填）**｜复核：T0coke
> 交接卡：`standards/handover/p04_coref.yaml`｜输出 schema：`standards/schema_coref.json`

## 目标

检测游记/路线文本中的代词（它、这、那里、他们等），把指代不明的代词解到具体景点/交通/时间实体，
并用人工标注评估准确率与覆盖率。

## 输入

三景区 `*_guides.csv` 的 `clean_content`（tag `v0.1-p01`）。优先用**游记**（第一人称、代词密集）；
官方文本代词少，可作为对照。

## 产出

```
analysis/p04_coref/outputs/
├─ coref.jsonl        # 一行一个代词消解结果
├─ annotations.csv    # ≥5 条人工标注（含 gold_antecedent、gold_type、note）
└─ eval.md            # 准确率/覆盖率计算过程（可复算）
```

## 运行

```powershell
python analysis/p04_coref/src/detect_pronouns.py
python analysis/p04_coref/src/resolve_coref.py
python checks/check_coref.py
```

## 关键约束

- 同句多个相同代词必须分别定位，不能串号（用 `pronoun_start/pronoun_end` 区分）；
- 无明确先行词时 `gold_antecedent` 留空并在 `note` 写原因，不能硬凑；
- 消解规则要贴合旅游文本（POI 优先、距离/类型约束），并写清边界。

## 验收（对应任务书 100 分）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 代词检测与样本构建 | 20 | `detect_pronouns.py` + 位置字段 |
| 人工标注 | 20 | `annotations.csv` ≥5 条 |
| 消解方法实现 | 30 | `resolve_coref.py` + 规则说明 |
| 效果评估 | 20 | `eval.md`（准确率/覆盖率） |
| 报告与可复现 | 10 | `report/` + README |

## 状态

`planned` —— 未开始（本目录负责人待确认后填入 `AGENTS.md` 第 4 节）。
