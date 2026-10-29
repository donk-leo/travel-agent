# 实验项目 2：游览步骤的实体识别实验报告

## 一、实验目标

从长隆、广州白云山、武功山三个景区的攻略文本中，识别以下三类游览要素：

1. 景点 POI；
2. 交通方式；
3. 时间节点。

实验输出带原文字符位置的 JSON Lines 实体文件、实体定义规范表、词频可视化图和迭代记录，
使识别过程可检查、可复现。

## 二、数据与方法

### 2.1 输入数据

输入为项目 1 已清洗的 `clean_content` 字段，共 29 篇文本：长隆 8 篇、广州白云山 7 篇、
武功山 14 篇。输入文件位于：

- `scenic/changlong/data/processed/changlong_guides.csv`
- `scenic/baiyunshan/data/processed/baiyunshan_guides.csv`
- `scenic/wugongshan/data/processed/wugongshan_guides.csv`

### 2.2 技术路线

采用 **Jieba 分词 + 自定义词典 + 时间正则规则** 的混合规则方法，不调用 LLM，也不需要本地部署模型。

1. 使用 Jieba 默认精确模式（`mode=default`）切分文本；
2. 加载 `jieba_userdict.txt`，使景区专名、交通表达和时间词优先作为完整词切分；
3. 使用 `entity_lexicon.csv` 将词语映射为 `POI`、`TRANSPORT`、`TIME` 三类，并统一别名的标准名称；
4. 使用正则补充具体时刻、时长、行程天数、日期范围、节假日等未必能稳定分词的时间表达；
5. 对重叠候选保留更完整的实体，例如保留“地铁3号线”而非其中的“地铁”；
6. 为每个实体写入字符起止位置，保证可从原文精确回取。

### 2.3 主要参数与资源

| 项目 | 设置 |
|---|---|
| 分词工具 | Jieba 默认精确模式 |
| 自定义词典 | 127 条：POI 99 条、TRANSPORT 18 条、TIME 10 条 |
| 停用词 | 19 条泛化 POI 候选词，如“景区、园区、路线、攻略、这里” |
| 时间规则 | 时刻、时间范围、天/夜行程、时长、月份范围、节假日等 6 类正则 |
| 实体类型 | `POI`、`TRANSPORT`、`TIME` |
| 位置口径 | 基于 `clean_content`，从 0 开始计数，结束位置不包含在实体内 |

实体类别定义、边界和易混淆情况见 `../outputs/entity_type_spec.md`。

## 三、运行与复现

### 3.1 环境准备

```bash
python3 -m pip install jieba
```

本实验的图表生成使用本机已有的 Pillow；不需要 Excel、Matplotlib 或付费软件。

### 3.2 一键运行

在仓库根目录执行：

```bash
python3 analysis/p02_entities/src/run_all.py
python3 checks/check_entities.py analysis/p02_entities/outputs/entities.jsonl
python3 analysis/p02_entities/src/visualize_entities.py
```

只重跑一个景区时，可使用：

```bash
python3 analysis/p02_entities/src/run_all.py --areas wugongshan
```

### 3.3 输入与输出

| 输出文件 | 内容 |
|---|---|
| `../outputs/entities.jsonl` | 每行一个实体，包含原文、标准名称、类型、景区、文档编号、字符位置、所在句、方法和置信度。 |
| `../outputs/entity_stats.json` | 总数、按类型统计、按景区统计和失败记录。 |
| `../outputs/entity_type_spec.md` | 三类实体的定义、边界、正反例与一致性规则。 |
| `../outputs/manual_review_samples.csv` | 30 条分层人工抽检样本及其原文配对。 |
| `../outputs/manual_review_report.md` | 抽检结论和边界问题。 |
| `../outputs/entity_frequency_*.png` | 三类实体词频柱状图。 |
| `../outputs/entity_count_before_after.png` | 词典优化前后数量对比图。 |
| `../outputs/stopwords_iteration.md` | 词典/停用词处理与优化前后结果说明。 |

## 四、实验结果

最终共识别 1006 条实体，三个景区均处理成功：

| 景区 | POI | TRANSPORT | TIME | 合计 |
|---|---:|---:|---:|---:|
| 长隆 | 133 | 35 | 98 | 266 |
| 广州白云山 | 134 | 65 | 33 | 232 |
| 武功山 | 306 | 85 | 117 | 508 |
| **合计** | **573** | **185** | **248** | **1006** |

代表性结果：

- POI：`观音宕`、`长隆欢乐世界`、`摩星岭`、`金顶`；
- TRANSPORT：`地铁3号线`、`索道`、`观光车`、`徒步`；
- TIME：`12:10`、`第二天`、`15分钟`、`日出`。

实体文件已运行检查脚本，检查通过：实体类型合法、文档编号存在，且每条实体均满足
`clean_content[char_start:char_end] == entity_text`。

## 五、人工检查与迭代优化

从三类实体、三个景区中分层抽取 30 条样本（每类 10 条、每景区 10 条），逐条核验原文位置、
实体类型和语义。已抽取实体的样本正确数为 30/30，样本误识别率为 0.00%。该结果仅表示抽检
样本正确，不代表语料不存在漏识别。

抽检发现武功山的 `观音宕、好汉坡、滴水观音、飚水瀑布、尽心瀑` 未被初版词典覆盖；
还发现长隆文本中的 `地铁3号线、地铁5号线` 可由泛化“地铁”细化为具体线路。补充后重跑：

| 类型 | 优化前 | 优化后 | 变化 |
|---|---:|---:|---:|
| POI | 532 | 573 | +41 |
| TRANSPORT | 185 | 185 | 0 |
| TIME | 248 | 248 | 0 |
| **合计** | **965** | **1006** | **+41** |

交通实体总量不变，是因为新词条替代了原先较短的“地铁”匹配；结果的改善体现在实体粒度而非数量。
本轮词频分析未发现进入结果的明显泛化高频 POI 噪声，因此保留原停用词表，不额外删除实体。

## 六、结论与局限

本实验完成了三景区文本的批量实体识别、结构化 JSON 输出、字符位置记录、人工抽检、词频可视化
和词典迭代。方法无需模型部署，适合课程实验中的本地复现和规则解释。

局限是词典法仍可能漏掉未收入词典的新景点、别名或口语表达；“徒步训练”等与景区游览关系较弱的
表达也需要结合上下文进行人工判断。后续可增加更细的“行程相关性”字段，或以 LLM 复核边界样本。
