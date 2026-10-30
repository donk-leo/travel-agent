# 项目 4 · 程序性知识的共指消解

> 负责人：成员3（本实现由 T0coke 代为完成，待负责人/复核确认）
> 复核：T0coke（自检已通过）｜交接卡：`standards/handover/p04_coref.yaml`
> 输出 schema：`standards/schema_coref.json`

## 目标

检测游记/路线文本中的代词（它、这、那里、他们等），把指代不明的代词解到具体景点/交通/时间实体，
并用人工标注评估准确率与覆盖率。

## 输入

三景区 `*_guides.csv` 的 `clean_content`（tag `v0.1-p01`）。优先用**游记**（第一人称、代词密集）；
官方文本代词少，可作为对照。上游只读：

- P2 `analysis/p02_entities/outputs/entities.jsonl`（tag `v0.2-p02`）
- P3 `analysis/p03_routes/outputs/routes.jsonl`（tag `v0.3-p03`）

## 产出

```
analysis/p04_coref/
├─ config/
│  ├─ pronouns.txt              # 23 个代词形式（最长优先）
│  └─ annotations_gold.csv      # 20 条人工 gold（16 有先行词 + 4 空）
├─ outputs/
│  ├─ pronoun_candidates.jsonl  # 140 条候选（位置/句/上下文）
│  ├─ coref.jsonl               # 140 条消解结果（28 消解 / 112 留空）
│  ├─ annotations.csv           # 与 coref 对齐的标注（评估输入）
│  ├─ eval.md                   # 准确率/覆盖率计算与逐条核对
│  └─ eval_stats.json           # 机读指标
└─ report/
   ├─ 项目4_程序性知识的共指消解_实验报告.docx
   ├─ 项目4_程序性知识的共指消解_实验报告.pdf
   └─ figures/                  # 流程图、分布图、消解率、指标
```

## 运行

推荐一键：

```powershell
python analysis/p04_coref/src/run_all.py
```

等价分步：

```powershell
python analysis/p04_coref/src/detect_pronouns.py
python analysis/p04_coref/src/resolve_coref.py
python analysis/p04_coref/src/build_annotations.py
python analysis/p04_coref/src/eval_coref.py
python analysis/p04_coref/src/make_figures.py
python analysis/p04_coref/src/build_report.py
python checks/check_coref.py
```

## 方法摘要

1. **检测**：`pronouns.txt` 按长度降序做最长优先匹配；分句正则 `[。！？!?；;\n]+`；记录
   `sentence_start/end` 与绝对 `pronoun_start/end`（0 起、结束不含）。
2. **候选**：P2 实体为主，P3 路线步骤补 P2 漏标的 POI（P3 的 span 先按名称回找真实位置）；
   同文档按 `(start,end,name)` 去重，只保留代词前的候选，最大距离 100 字。
3. **规则**：代词类 → 允许类型白名单（处所/指示→POI，对象→POI/TRANSPORT，时间→TIME）；
   打分 `0.55*类型 + 0.25*邻近 + 0.15*同句 + 0.05*路线命中`，阈值 0.60；
   低于 0.70 标 `needs_review`。无合适候选时留空并写 `reason`，不硬凑。
4. **评估**：20 条人工标注（三景区、两类文本、成功/失败/空 gold），按
   `(doc_id, pronoun_start)` 对齐；空 gold + 空预测判对。

## 主要结果

| 指标 | 数值 |
|---|---|
| 候选 / 文档 | 140 / 21 |
| 已消解 / 留空 | 28 / 112 |
| 标注数（有 gold + 空） | 20（16 + 4） |
| 准确率 | 80.00%（16/20） |
| 精确率 | 75.00%（12/16） |
| 召回率 | 75.00%（12/16） |
| 标注覆盖率 | 80.00%（16/20） |
| 全量消解率 | 20.00%（28/140） |

主要错误来自 P2 漏标（尖叫地带/吊马桩/几字湾栈道未识别，规则退到父区域）和后置指代；
人物/动物/事件/路线因 P4 schema 无对应类型，规则主动留空，属预期行为。

## 关键约束

- 同句多个相同代词必须分别定位，不能串号（用 `pronoun_start/pronoun_end` 区分）；
- 无明确先行词时 `gold_antecedent` 留空并在 `note` 写原因，不能硬凑；
- 消解规则要贴合旅游文本（POI 优先、距离/类型约束），并写清边界；
- 不改 `scenic/` 冻结数据；P4 只读 P1/P2/P3 产出。

## 验收（对应任务书 100 分）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 代词检测与样本构建 | 20 | `detect_pronouns.py`、`pronoun_candidates.jsonl`、位置字段 |
| 人工标注 | 20 | `config/annotations_gold.csv` + `outputs/annotations.csv`（20 条） |
| 消解方法实现 | 30 | `resolve_coref.py`、类/距离/阈值规则、`coref.jsonl` |
| 效果评估 | 20 | `eval.md`、`eval_stats.json`（准确率/覆盖率/精确率/召回率） |
| 报告与可复现 | 10 | `report/*.docx/pdf`、`run_all.py`、本 README |

## 状态

`implemented` —— 本地实现、评估、报告与自检均完成（`checks/check_coref.py` 通过）；
已合并到 `main`（合并提交 `4702304`），**未打 tag**，待成员3/组长复核后转 `done` 并打 `v0.4-p04`。
