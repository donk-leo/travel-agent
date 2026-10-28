# 项目 2 · 游览步骤的实体识别

> 负责人：**T0coke**｜复核：HappinessJo
> 交接卡：`standards/handover/p02_entities.yaml`｜输出 schema：`standards/schema_entities.json`

## 目标

从三景区的 `clean_content` 中识别三类实体——**景点 POI、交通方式、时间节点**，
输出带字符位置的 `entities.jsonl`，并给出实体定义规范、词频图与停用词迭代记录。

## 输入（只读，禁止修改）

| 文件 | 列 | 来源 tag |
|---|---|---|
| `scenic/changlong/data/processed/changlong_guides.csv` | `clean_content` | v0.1-p01 |
| `scenic/baiyunshan/data/processed/baiyunshan_guides.csv` | `clean_content` | v0.1-p01 |
| `scenic/wugongshan/data/processed/wugongshan_guides.csv` | `clean_content` | v0.1-p01 |

## 产出（文件名写死）

```
analysis/p02_entities/outputs/
├─ entities.jsonl            # 一行一个实体，字段见 schema_entities.json
├─ entity_type_spec.md       # 定义/边界/示例/易混说明
├─ stopwords_iteration.md    # 停用词调整前后对比
└─ figures/wordfreq_*.png    # 词云或柱状图
```

## 运行

```powershell
python analysis/p02_entities/src/run_all.py       # 一键跑三景区
python checks/check_entities.py                   # 自检（必须退出码 0）
```

## 关键约束

- `entity_text` 必须等于 `clean_content[char_start:char_end]`（check 会逐条核验）；
- 类型枚举固定为 `POI / TRANSPORT / TIME`，跨景区一致；
- 多景区批量处理要能单景区失败重试，不中断全批；
- 停用词迭代必须留前后对比图，不能只交最终图。

## 验收（对应任务书 100 分）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 实体类型定义与规范 | 15 | `entity_type_spec.md` |
| 识别方法实现 | 35 | `src/` + 参数/Prompt 说明 |
| 结果与质量检查 | 20 | `entities.jsonl` + 抽查记录（≥20 条） |
| 词频可视化与迭代 | 20 | `figures/*.png` + `stopwords_iteration.md` |
| 报告与可复现 | 10 | `report/` + README |

## 状态

`planned` —— 未开始。开工前先确认 `v0.1-p01` tag 存在。
