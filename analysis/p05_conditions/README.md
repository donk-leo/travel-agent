# 项目 5 · 条件性游览建议的抽取

> 负责人：**T0coke**｜复核：成员3（本轮由 T0coke 自检后代为交付，独立复核可在后续补充）
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
├─ outputs/manual_review.csv            # 20 条人工抽查明细
├─ outputs/eval_conditions.md           # 抽查评估报告
├─ outputs/rejected.jsonl               # 被过滤候选及原因
├─ outputs/p6_condition_poi.csv         # P6 接入用条件锚点桥接表（派生，非 schema）
├─ outputs/P6_接入说明.md                # 锚点规则、统计与 P6 注意事项
└─ outputs/figures/condition_stats.png  # 类型 / 景区 / 景区×类型 / 抽查结果
```

## 运行

```powershell
# 一键跑完抽取、评估、映射表、图、报告和自检
python analysis/p05_conditions/src/run_all.py

# 或分步运行
python analysis/p05_conditions/src/extract_conditions.py
python analysis/p05_conditions/src/eval_conditions.py
python analysis/p05_conditions/src/build_mapping.py
python analysis/p05_conditions/src/make_figures.py
python analysis/p05_conditions/src/build_report.py
python checks/check_conditions.py
```

> 本机系统 Python 若缺少 openpyxl/Pillow/python-docx，请改用课程环境的 python.exe；
> 本次运行使用的是 `.dsh` 捆绑运行时。

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

## 结果

- 29 条文档 / 28 有效；13 篇有结果，文档覆盖率 46.43%；
- 36 条条件-建议，去重后 33 条（exact 2、prefix_suffix 1、near 0）；
- 类型：交通 4、时间 13、人群 13、体力 2、天气 3、预算 1；
- 景区：长隆 12、白云山 8、武功山 16；显式 10、隐式 26；
- 人工抽查 20 条：正确 14、部分正确 5、错误 1；严格准确率 70.00%、宽松可用率 95.00%。

## 状态

`done` —— 已提交并推送到 `main`，tag `v0.5-p05`；`checks/check_conditions.py` 通过。
本轮由 T0coke 自检后代为交付，成员3的独立复核可在后续补充；P6 可按下表直接消费。

### 给 P6 的接口

- `outputs/conditions.jsonl`：36 条 / 33 唯一，13 篇文档有结果；
- `outputs/p6_condition_poi.csv`：条件 → POI/景区锚点桥接表，36 行；
  其中 8 条挂到具体 POI，28 条退到景区节点；规则见 `outputs/P6_接入说明.md`；
- 3 条 `is_duplicate=true`（CND-0014、CND-0015、CND-0022）默认建议 P6 过滤；
- P3 没有 `scenic_area` 字段，P6 需按 `doc_id` 前缀推断。
