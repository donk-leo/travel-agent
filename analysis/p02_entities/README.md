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

## 产出

```
analysis/p02_entities/outputs/
├─ entities.jsonl                    # 一行一个实体，字段见 schema_entities.json
├─ entity_stats.json                  # 总数、类型分布、景区分布
├─ entity_type_spec.md                # 定义/边界/示例/易混说明
├─ manual_review_samples.csv          # 30 条分层抽检样本与原文配对
├─ manual_review_report.md            # 人工抽检结论
├─ stopwords_iteration.md             # 词典/停用词迭代记录
├─ entity_frequency_poi.png           # POI 词频柱状图
├─ entity_frequency_transport.png     # 交通方式词频柱状图
├─ entity_frequency_time.png          # 时间节点词频柱状图
├─ entity_count_before_after.png      # 词典优化前后对比图
└─ entity_frequency_summary.json      # 图表的可复核统计数据

analysis/p02_entities/report/
└─ p02_experiment_report.md           # 实验报告与复现说明
```

## 运行

```bash
python3 -m pip install jieba                        # 首次运行时安装
python3 analysis/p02_entities/src/run_all.py       # 一键跑三景区
python3 checks/check_entities.py analysis/p02_entities/outputs/entities.jsonl
python3 analysis/p02_entities/src/visualize_entities.py
```

## 关键约束

- `entity_text` 必须等于 `clean_content[char_start:char_end]`（check 会逐条核验）；
- 类型枚举固定为 `POI / TRANSPORT / TIME`，跨景区一致；
- 多景区批量处理要能单景区失败重试，不中断全批；
- 停用词迭代必须留前后对比图，不能只交最终图。

## 验收（对应任务书 100 分）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 实体类型定义与规范 | 15 | `outputs/entity_type_spec.md` |
| 识别方法实现 | 35 | `src/run_all.py` + `config/` |
| 结果与质量检查 | 20 | `outputs/entities.jsonl` + 30 条抽查记录 |
| 词频可视化与迭代 | 20 | `outputs/entity_frequency_*.png` + `outputs/stopwords_iteration.md` |
| 报告与可复现 | 10 | `report/p02_experiment_report.md` + 本 README |

## 状态

`completed` —— 已完成三景区 29 篇文本的实体识别、人工抽检、词典迭代、词频可视化与复现说明。

最终输出共 1006 条实体：POI 573、TRANSPORT 185、TIME 248。实体位置检查已通过。
