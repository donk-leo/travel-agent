# 项目 5 · 条件性游览建议的抽取

> 负责人：**T0coke**｜复核：成员3
> 交接卡：`standards/handover/p05_conditions.yaml`｜输出 schema：`standards/schema_conditions.json`

## 目标

识别“如果下雨就……”“带老人建议……”“夜爬要……”这类**条件 → 建议**结构，
整理成可直接查询的映射表（条件类型 / 条件描述 / 建议内容 / 来源景区）。

## 输入

三景区 `*_guides.csv` 的 `clean_content`（tag `v0.1-p01`）。

## 产出

```
analysis/p05_conditions/
├─ config/triggers.csv                 # 触发词表（如果/假如/若/建议/可以…）
├─ outputs/conditions.jsonl            # 一行一条条件-建议
├─ outputs/映射表.xlsx                  # 条件类型/条件/建议/来源
└─ outputs/figures/condition_stats.png  # 按游客类型（人群）分组统计
```

## 运行

```powershell
python analysis/p05_conditions/src/extract_conditions.py
python checks/check_conditions.py
```

## 关键约束

- 条件与建议**必须是原文片段**（check 会验证是 `source_sentence` 的子串），不得改写；
- 同句多建议拆成多条，共享同一 `source_sentence`；
- 去重要有前后统计（同句重复 / 近重复 / 前后缀重复），不能只交去重后结果；
- 样本稀疏要如实说明（官方文本条件句密度低，游记更高）。

## 验收（对应任务书 100 分）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 触发词与规则设计 | 30 | `config/triggers.csv` + 优先级/边界说明 |
| 条件-建议抽取 | 35 | `conditions.jsonl` + 人工抽查记录 |
| 映射表、分类与去重 | 25 | `映射表.xlsx` + 去重前后统计 |
| 报告与可复现 | 10 | `report/` + README |

## 状态

`planned` —— 未开始。
