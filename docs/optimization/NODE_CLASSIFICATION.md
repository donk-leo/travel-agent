# 节点分类与 POI 噪声治理（T1.4）

> **状态**：`done`（本地 commit，未 push；合并权在 owner HappinessJo）
> **任务**：T1.4 · Owner：GRAPH｜基线分支 `agent/d2-graph-evidence @ 6813920`
> **产出**：`analysis/p06_graph/outputs/node_classification.csv`（152 行）、
> `analysis/p06_graph/outputs/classify_nodes.py`（确定性分类器 + `--check` / `--write`）、
> `analysis/p02_entities/outputs/node_noise_sample50.csv`（50 抽样）、本文档
> **只读输入**：`graph_nodes.csv`、`graph_edges.csv`、`entities.jsonl`、32 篇 `clean_content`、
> P6 `README.md` / `graph_qa.md`、`standards/handover/p06_graph.yaml`
> **零改动**：`graph_nodes.csv` / `graph_edges.csv` / `graph_stats.json` / `graph_qa.md` / `graph.graphml`、
> P2 的 `entities.jsonl` / `entity_stats.json`、`analysis/p02_entities/src/**`、`analysis/p06_graph/src/**`、
> `lib/` / `checks/` / `standards/` / `scenic/` **全部未改**（`git diff 6813920..HEAD` 见提交）

---

## 1. 结论先行

| 指标 | 结果 |
|---|---|
| 地点节点分类覆盖 | **152/152（100%）**，`node_class` 空值 **0**，无重复 `node_id` |
| 6 值枚举 | `attraction` 90、`area` 32、`transport` 15、`facility` 11、`food` 3、`shop` 1（合计 152） |
| 非地点节点 | **77** 个按 `node_type` 显式排除并计数（TIME 32 / ACTIVITY 12 / CONDITION 33） |
| POI 噪声率（50 抽样） | **0/50 = 0%**（< 10% 门槛）；但 95% 置信上限约 **6%**，且 2 条已知可疑节点未被抽中，**不能声称“POI 零噪声”**，见 §6.4 |
| 难样本 | **29 条**（19.1%）保留并写 `quality_flags`，逐条列于 §7 |
| 确定性 | `--write` 重跑后 `node_classification.csv` sha256 不变：`82d70e36…59f28b` |
| 未做 | 未删任何节点、未改任何冻结项、未新增第 7 个枚举值、未联网/装包 |

---

## 2. 范围规则：152 + 77 = 229

`graph_nodes.csv` 共 **229** 个节点。本任务**只分类「地点节点」**，非地点节点按 `node_type` 显式排除并计数，
**不静默丢弃**（`--check` 逐项核对下表数字）：

| `node_type` | 节点数 | 是否分类 | 归入 / 排除 | 说明 |
|---|---:|---|---|---|
| `SCENIC_AREA` | 3 | ✅ 分类 | `area`（3/3，`node_type` 直判） | 长隆 / 广州白云山 / 武功山 |
| `POI` | 141 | ✅ 分类 | 按名称 + 原文证据细分（§3） | 长隆 49 / 白云山 42 / 武功山 50 |
| `TRANSPORT` | 8 | ✅ 分类 | `transport`（8/8，`node_type` 直判） | 跨景区共享交通方式 |
| **地点小计** | **152** | — | — | — |
| `TIME` | 32 | ❌ 排除 | 时间节点（`TIME\|<time_norm>`） | 时间是值，不是地点 |
| `ACTIVITY` | 12 | ❌ 排除 | 活动节点（`ACTIVITY\|<活动名>`） | 活动已在 P6 单独建模 |
| `CONDITION` | 33 | ❌ 排除 | 条件节点（`CONDITION\|<cond_id>`） | 条件建议，不是地点 |
| **非地点小计** | **77** | — | — | — |
| **合计** | **229** | — | — | **152 + 77 = 229** |

- **覆盖率**：152 / 229 = **66.4%**；分类只覆盖地点，P7 若按 `node_class` 过滤必须保留 TIME/ACTIVITY/CONDITION。
- **排除是可验证的**：`classify_nodes.py --check` 断言 `len(rows) + len(excluded) == len(nodes)`，
  并逐个核对 TIME=32 / ACTIVITY=12 / CONDITION=33（`BASELINE` 常量），任何一类数量变化都会非 0 退出。
- **`node_class` 不是 `node_type` 的替代**：`node_type` 是 P6 冻结枚举（6 类，含非地点），
  `node_class` 是 P7 语义层（6 值，仅地点），两者并存、不互相覆盖。

---

## 3. 6 值枚举定义与判据

枚举**固定 6 值**，本任务不新增第 7 值（要加先提案，见 §8.6）。

| `node_class` | 定义 | 判据（可复算） | 典型节点 |
|---|---|---|---|
| `attraction` | 可游览/可参观的具体景点、展馆、表演、游乐项目 | 名称含景点/设施词（楼阁塔桥瀑泉潭石寺宫馆台园广场栈道峰岩坡顶村林坛廊温室中心），且不是片区、不是食宿 | 摩星岭、金顶、垂直过山车、能仁寺、玻璃栈道 |
| `food` | 餐饮点 | 名称含餐饮词（餐厅/茶餐厅/咖啡/小吃/美食/饭店/酒楼/餐饮/烧烤/糖水/豆腐花/面馆/火锅/餐吧/食堂/快餐） | 南国茶餐厅、椰林餐厅、熊猫餐厅 |
| `transport` | 交通方式 / 交通设施（乘车点、索道站、缆车站、车站、码头、停车场） | `node_type=TRANSPORT` 直接定死；POI 名称含索道/缆车/车站/码头/停车场/摆渡/接驳/乘车点，或以「站」结尾 | 中庵索道、金顶索道、天鹅湖站、萍乡车站 |
| `shop` | 购物点 | 名称含商店/商场/超市/购物/纪念品/便利店/市集/文创/专卖店 | 南门纪念品商店 |
| `facility` | 服务设施与出入口：大门/闸口/游客中心/厕所/医疗/酒店住宿/观景平台/休息区 | 名称含入口/大门/闸口/游客中心/服务中心/厕所/医疗/酒店/宾馆/客栈/旅舍/别墅/民宿/观景台/眺台/休息区/驿站/售票处，或以「门」结尾 | 北门、南门、安检入口、长隆熊猫酒店、九龙客栈、玻璃眺台 |
| `area` | 大范围空间单元：景区/园区/片区/街区/游览区/度假区/湖/谷/岛/山/岭/水库/界 | 名称含景区/度假区/园区/片区/区域/地带/天地/街区/街段/游览区/乐园/世界/王国/公园，或以「区」结尾；或纯自然地理通名结尾（湖/水库/谷/岛/岭/山/界/宕） | 长隆欢乐世界、云台景区、巡游主街段、发云界、天鹅湖 |

**两条硬约束**（`--check` 强制）：

1. `node_type = SCENIC_AREA` **必须**是 `area`；`node_type = TRANSPORT` **必须**是 `transport`（各 3 / 8 条）。
2. 每类至少 1 个节点；`transport` / `area` 不允许只靠 POI 撑起来（有 SCENIC_AREA / TRANSPORT 来源）。

**为什么 `area` 会包含谷/湖/山**：parent 口径是「园区/片区/度假区/岛/谷/山/湖等**大范围** → area」。
本任务把「自然地理通名结尾」当作大范围的默认信号（`name_rule:area_geo`，confidence 0.70 起步），
凡原文能证明只是一个小点位或单一展区的，用人工覆盖改判并标 `scope_ambiguous`（如 `百虎山`→`attraction`、
`猴谷`→`attraction`）。这条边界与代价写进 §8.3。

---

## 4. 分类方法与优先级

分类器 `analysis/p06_graph/outputs/classify_nodes.py` 是**纯规则 + 显式人工覆盖**，无随机、无时间戳、无网络；
输出顺序 = `graph_nodes.csv` 行序（SCENIC_AREA → POI → TRANSPORT），`confidence` 固定两位小数。

### 4.1 规则顺序（先命中先用）

| 序号 | 规则 | 作用范围 | `method` | confidence |
|---:|---|---|---|---:|
| 0 | `node_type = SCENIC_AREA` → `area` | 3 | `node_type:SCENIC_AREA` | 1.00 |
| 0 | `node_type = TRANSPORT` → `transport` | 8 | `node_type:TRANSPORT` | 1.00 |
| 0′ | **人工覆盖表 `OVERRIDES`**（23 条，逐条写理由） | POI | `manual_review` | 0.55–0.90 |
| 1 | 餐饮词 → `food` | POI | `name_rule:food` | 0.90 |
| 2 | 购物词 → `shop` | POI | `name_rule:shop` | 0.90 |
| 3 | 交通词 / 以「站」结尾 → `transport` | POI | `name_rule:transport` | 0.90 |
| 4 | 设施词 → `facility` | POI | `name_rule:facility` | 0.90 |
| 5 | 以「门」结尾 → `facility`（出入口/闸口语义） | POI | `name_rule:gate` | 0.90 |
| 6 | 同景区存在 `X景区` 时，`X` → `attraction` | POI | `name_rule:paired_spot` | 0.85 |
| 7 | 片区/园区容器词 / 以「区」结尾 → `area` | POI | `name_rule:area` | 0.90 |
| 8 | 自然地理通名结尾 → `area`（有争议的加 `scope_ambiguous`） | POI | `name_rule:area_geo` | 0.70 |
| 9 | 景点/展演/游乐词 → `attraction` | POI | `name_rule:attraction` | 0.85 |
| 10 | 兜底 → `attraction`（名称无任何类别信号） | POI | `fallback:attraction` | 0.70 |

> **规则 6（成对景点）** 是 P6 `SIMILAR_PAIRS` 的直接推论：`摩星岭` / `明珠楼` / `鸣春谷` 各有一个
> `X景区` 节点（P6 刻意保留双节点、不合并），因此 `X` 是具体点位（`attraction`）、`X景区` 才是片区（`area`）。
> 这条规则把「层级写法」翻译成了分类差异，而不是靠人工逐条指定。
>
> 两个「规则已判对、只做确认」的例子（**不进人工覆盖表**，`method` 保持规则来源）：
> `明珠楼` 除了是楼阁景点，还是白云山观光车「热门上车点」，P7 需结合 `BY_TRANSPORT` 边；
> `长隆国际大马戏` 是独立马戏场馆，按「表演」归 `attraction`。

### 4.2 词表（正则，全部在脚本顶部）

- `FOOD_RE` / `SHOP_RE` / `TRANSPORT_RE` / `FACILITY_RE` / `AREA_RE` / `GEO_AREA_RE` / `ATTRACTION_RE`
- `GEO_AREA_RE = (湖|水库|谷|岛|岭|山|界|宕)$`（**只匹配结尾**，避免「三县界**碑**」被当成「界」）
- 词表顺序即优先级；同一名称命中多类时，靠前的规则生效，并在 `quality_flags` 记 `multi_class_name`。

### 4.3 人工覆盖（`manual_review`，23 条）

覆盖只用于「规则会判错 / 必须降置信 / 必须加标记」的节点，每条在脚本 `OVERRIDES` 字典里带 `reason`，逐条列在 §7。
其中 **3 条是改类**：`金猴王国`（王国→attraction）、`百虎山`（山→attraction）、`猴谷`（谷→attraction）；
其余 **20 条同类别，但调整置信或补标记**（如 `明珠楼` 类由规则 6 处理、`观音宕` 0.70→0.85、`松涛别院` 0.70→0.55）。

### 4.4 其它标记来源

- `EXTRA_FLAGS`：规则判类正确但需补标记（P3 伪 POI 保留 6 条、P3 内车站 1 条、活动 1 条、别名 2 条、景区外 4 条）。
- `GEO_SCOPE_FLAG`：被规则 8 判成 `area` 但范围存疑的谷（`蒲谷`/`梅花谷`/`回音谷`）补 `scope_ambiguous`。

### 4.5 方法分布（152 行）

| method | 行数 | 占比（四舍五入） |
|---|---:|---:|
| `name_rule:*` | 111 | 73.0% |
| `manual_review` | 23 | 15.1% |
| `node_type:SCENIC_AREA` / `node_type:TRANSPORT` | 11 | 7.2% |
| `fallback:attraction` | 7 | 4.6% |

细分：`attraction` 69、`area` 17、`gate` 5、`transport` 7、`facility` 3、`food` 3、`shop` 1、`area_geo` 3、`paired_spot` 3（合计 111）。

### 4.6 `confidence` 口径（**分类置信度 ≠ 节点重要度**）

| 值 | 含义 | 例 |
|---:|---|---|
| 1.00 | `node_type` 直判，无解释空间 | 3 个 SCENIC_AREA、8 个 TRANSPORT |
| 0.90 | 名称词表直命中，无歧义 | 长隆欢乐世界→area、南国茶餐厅→food、北门→facility |
| 0.80–0.85 | 词表命中 + 原文证据确认，或成对规则 | 摩星岭→attraction、金顶→0.65（见下） |
| 0.70 | 只有名称信号 + 地名通名，或多解但取了保守值 | 发云界→area、吊马桩→attraction |
| 0.55–0.65 | 证据不足/两种解释都成立，必须人看 | 松涛别院 0.55、双溪别墅 0.60、玻璃眺台 0.65 |

- `confidence` 均值 **0.848**，最小 **0.55**，最大 **1.00**；**< 0.70 共 5 条**，**< 0.80 共 21 条**。
- 低置信**不隐藏**：全部落进 §7 难样本清单，`quality_flags` 非空。

---

## 5. 分类结果统计

### 5.1 按 `node_class`

| `node_class` | 行数 | 其中来自 `node_type` | 其中来自 POI |
|---|---:|---:|---:|
| `attraction` | 90 | 0 | 90 |
| `area` | 32 | 3（SCENIC_AREA） | 29 |
| `transport` | 15 | 8（TRANSPORT） | 7 |
| `facility` | 11 | 0 | 11 |
| `food` | 3 | 0 | 3 |
| `shop` | 1 | 0 | 1 |
| **合计** | **152** | **11** | **141** |

### 5.2 按景区 × 分类

| 景区 | 行数 | `area` | `attraction` | `facility` | `food` | `shop` | `transport` |
|---|---:|---:|---:|---:|---:|---:|---:|
| 长隆 | 51 | 16 | 23 | 4 | 3 | 1 | 4 |
| 广州白云山 | 43 | 11 | 27 | 5 | 0 | 0 | 0 |
| 武功山 | 51 | 5 | 40 | 2 | 0 | 0 | 4 |
| 跨景区 | 7 | 0 | 0 | 0 | 0 | 0 | 7 |

> 「景区行数」含该景区的 `SCENIC_AREA` 节点本身与共享/跨景区 `TRANSPORT`：长隆 51 = 1 SCENIC_AREA + 49 POI + 1 TRANSPORT（小火车）；
> 白云山 43 = 1 + 42；武功山 51 = 1 + 50；跨景区 7 = 7 个 TRANSPORT。合计 152。

### 5.3 质量标记分布

`quality_flags` 非空 **29/152 = 19.1%**，共 31 个标记（2 行各有 2 个）：

| `quality_flags` | 行数 | 含义 |
|---|---:|---|
| `scope_ambiguous` | 8 | 大范围/小点位判据冲突（金顶、发云界边界、谷/山/岛等） |
| `p3_pseudo_poi_kept` | 6 | P3 曾判伪 POI、按 P6 `KEEP_POI_NOTE` 保留的 6 条 |
| `class_uncertain` | 4 | 类别有 ≥2 种合理解释（住宿 vs 景点、观景台 vs 景点） |
| `off_park_boundary` | 4 | 名称位于景区范围外（萍乡市区/穿越线边界） |
| `low_evidence` | 3 | 只有路线串联、没有描述性语句 |
| `alias_mismatch` | 3 | 节点名与原文写法/同址别名不一致 |
| `multi_class_name` | 1 | 名称同时命中两类词（`小火车游览区`） |
| `name_from_animal` | 1 | 节点名是动物名而非地名（`火烈鸟`） |
| `activity_like` | 1 | 名称是活动/表演而非固定地点（`花车大巡游`） |

---

## 6. 50 抽样：POI 噪声审计

### 6.1 抽样口径（可复算，父 Agent 用同 seed 重抽可直接对比）

```python
# 抽样框 = graph_nodes.csv 中 node_type == "POI" 的 141 个节点
poi_ids = sorted(n["node_id"] for n in nodes if n["node_type"] == "POI")
sample = random.Random(20261115).sample(poi_ids, 50)   # seed = 20261115，50 条
```

- **seed**：`20261115`（与 T1.3 抽样一致，便于复核）。
- **抽样框**：141 个 POI（**不是** 152，也**不是** 229；不含 SCENIC_AREA / TRANSPORT / TIME / ACTIVITY / CONDITION）。
- **`sample_no`** = 上述 `sample` 列表下标 +1（1..50），`node_noise_sample50.csv` 的 `node_id` 顺序必须与之一致。
- `classify_nodes.py --check` 会用同一 seed/框架**重抽并逐条比对**，顺序不符即非 0 退出。

### 6.2 `evidence_sentence` 取值规则（确定性）

1. **证据文档**：优先取 P2 `entities.jsonl` 中同 `(scenic_area, normalized_name)` 的第一条 POI 实体的 `doc_id`；
   没有（P3-only 节点）则取 P3 `routes.jsonl` 中同名 `poi` 的第一条 `source_span` 所在文档。
2. **证据句**：该文档 `clean_content` 中节点名首次出现处所在完整句（含句末标点；句末括号/引号并入；
   括号内出现感叹号导致未闭合时顺延到行尾）。节点名与原文不一致时退回 P2 的 `entity_text`。
3. 逐字校验：`--check` 断言每条 `evidence_sentence` 都是 `entities.jsonl` 某条 `sentence` 或某篇
   `clean_content` 的**子串**（不是改写、不是拼凑）。

### 6.3 噪声定义（本任务口径）

> **噪声 = 节点名不指代任何地点/景点/餐饮/商店/交通/设施**，例如：动作（`南门下山`）、方向、
> 句子片段（`完玻璃栈道就可以下山了`）、纯营销话术（`真的太爽啦`）。

- P6 已用 `DROP_POI`（4 条句子片段/动作）与 `RECLASS_ACTIVITY`（5 条活动/时段）清理过一轮，
  这 9 条**不在** 141 个 POI 中，因此**不在**本抽样框内；本任务不把它们放回，也不重复计入噪声。
- 本任务**不删除**任何噪声节点（若发现），只 `is_noise=1` + `noise_reason` 引原文；分类列照常给值。

### 6.4 噪声率结论

| 指标 | 数值 |
|---|---|
| 抽样数 | 50 / 141 |
| 判为噪声 | **0** |
| 噪声率 | **0/50 = 0%**（门槛 < 10%，**通过**） |
| 95% 置信上限（3/n 经验法则） | 约 **6.0%** |

**必须说清的三件事**（不粉饰）：

1. `0/50` 只说明**抽到的 50 条里没有非地点噪声**，不等于 141 个 POI 零噪声；按 3/n 规则，真实噪声率
   仍可能高到约 6%。
2. 随机抽样**没有抽到**本任务已识别的 2 条最可疑节点：`花车大巡游`（活动，已标 `activity_like`）、
   `途经好汉坡`（名称含动词「途经」，与 `好汉坡` 重复，已标 `alias_mismatch`）。若按「必须是地点名词」的严格口径，
   这两条应计噪声；本任务**没有**为了让噪声率好看而改抽样框或补抽——它们留在节点表里，靠 `quality_flags` 暴露。
3. 边界样本 `火烈鸟`（动物名）判 **0**：原文「进门先打卡火烈鸟」「火烈鸟区域」把它当作展区/打卡点使用，
   与 `考拉园`/`百虎山` 同类；名称本身不规范已标 `name_from_animal`。若评审口径要求「节点名必须是地点名词」，
   本条应改判 1，噪声率变为 1/50 = 2%（仍 < 10%）。

### 6.5 逐条结论（50 条）

| # | 节点（景区） | node_class | is_noise | 判定依据（原文/名称） |
|---:|---|---|---:|---|
| 1 | `绝望坡`（武功山） | attraction | 0 | 山脊坡段名，路线串联出现 |
| 2 | `回归林`（广州白云山） | attraction | 0 | 纪念林（地点），路线串联出现 |
| 3 | `百虎山`（长隆） | attraction | 0 | 动物展区（白虎跳水） |
| 4 | `黄河石广场`（广州白云山） | attraction | 0 | 广场景点，原文列为「等主要景点」 |
| 5 | `飙水岩瀑布`（武功山） | attraction | 0 | 瀑布景点 |
| 6 | `中庵`（武功山） | attraction | 0 | 紫极宫所在山腰地名（与紫极宫同址，见难样本） |
| 7 | `欢乐剧场`（长隆） | attraction | 0 | 演出场馆（表演区） |
| 8 | `古祭坛群`（武功山） | attraction | 0 | 古迹景点（1700 年历史） |
| 9 | `白云仙馆`（广州白云山） | attraction | 0 | 馆/景点，原文「等景点」 |
| 10 | `岩石园`（广州白云山） | attraction | 0 | 专类园，原文「云台花园（含…岩石园…等景点）」 |
| 11 | `武功山神`（武功山） | attraction | 0 | 石景名（地名） |
| 12 | `九龙客栈`（武功山） | facility | 0 | 住宿设施（客栈） |
| 13 | `麓湖公园`（广州白云山） | area | 0 | 公园片区 |
| 14 | `梅花谷`（广州白云山） | area | 0 | 谷地片区（`scope_ambiguous`） |
| 15 | `玻璃栈道`（武功山） | attraction | 0 | 栈道景点 |
| 16 | `熊猫乐园`（长隆） | area | 0 | 园内片区（缆车站以其命名） |
| 17 | `武功神拳`（武功山） | attraction | 0 | 石景名（地名） |
| 18 | `超级海盗船`（长隆） | attraction | 0 | 游乐项目 |
| 19 | `律动天地`（长隆） | area | 0 | 园内主题片区 |
| 20 | `滴水观音`（武功山） | attraction | 0 | 景点名（观音石/滴水） |
| 21 | `安检入口`（长隆） | facility | 0 | 出入口设施 |
| 22 | `南门`（长隆） | facility | 0 | 出入口设施 |
| 23 | `高空栈道`（武功山） | attraction | 0 | 栈道景点 |
| 24 | `熊猫乐园站`（长隆） | transport | 0 | 缆车站（交通设施） |
| 25 | `七仙潭`（武功山） | attraction | 0 | 潭/瀑布群景点 |
| 26 | `火烈鸟`（长隆） | attraction | 0 | **边界**：动物名，原文用作展区（「打卡火烈鸟」），标 `name_from_animal` |
| 27 | `巡游主街段`（长隆） | area | 0 | 街区段（地点） |
| 28 | `南国茶餐厅`（长隆） | food | 0 | 餐饮点 |
| 29 | `星海园`（广州白云山） | attraction | 0 | 纪念园（景点） |
| 30 | `中庵索道`（武功山） | transport | 0 | 索道（交通设施） |
| 31 | `松园`（武功山） | attraction | 0 | 园/景点 |
| 32 | `空中缆车`（长隆） | transport | 0 | 交通方式（缆车） |
| 33 | `草甸之舟`（武功山） | attraction | 0 | 景点名 |
| 34 | `环湖栈道`（广州白云山） | attraction | 0 | 栈道景点 |
| 35 | `超级大摆锤`（长隆） | attraction | 0 | 游乐项目 |
| 36 | `双溪别墅`（广州白云山） | facility | 0 | 建筑/设施，原文列为途经景点（`class_uncertain`） |
| 37 | `羊狮慕小火车站`（武功山） | transport | 0 | 小火车站（交通设施） |
| 38 | `安源路矿工人运动纪念馆`（武功山） | attraction | 0 | 纪念馆（景区外，`off_park_boundary`） |
| 39 | `两江情缘石`（广州白云山） | attraction | 0 | 石景 |
| 40 | `欢乐主街区`（长隆） | area | 0 | 街区（地点） |
| 41 | `石鼓寺`（武功山） | attraction | 0 | 寺庙景点 |
| 42 | `超级激流`（长隆） | attraction | 0 | 游乐项目 |
| 43 | `椰林餐厅`（长隆） | food | 0 | 餐饮点 |
| 44 | `十环过山车`（长隆） | attraction | 0 | 游乐项目 |
| 45 | `长颈鹿广场`（长隆） | attraction | 0 | 广场/投喂点 |
| 46 | `红岩瀑`（武功山） | attraction | 0 | 瀑布景点 |
| 47 | `长隆熊猫酒店`（长隆） | facility | 0 | 住宿设施（酒店） |
| 48 | `发云界`（武功山） | area | 0 | 高山片区（官方四大景区之一） |
| 49 | `北门`（长隆） | facility | 0 | 出入口设施 |
| 50 | `长隆大熊猫中心`（长隆） | attraction | 0 | 展馆/中心（景点） |

> 逐条依据的**原文证据句**在 `node_noise_sample50.csv` 的 `evidence_sentence` 列（逐字来自 `clean_content`/`entities.jsonl`），
> 本文只写结论与一句话理由，不重复抄 50 条长句。

---

## 7. 难样本清单（29 条：保留 + `quality_flags`，一条不删）

> **质量标记（`quality_flags`）受控词表**——只允许下列 9 个值，`;` 分隔，顺序固定：
> `class_uncertain` / `scope_ambiguous` / `multi_class_name` / `alias_mismatch` / `name_from_animal` /
> `activity_like` / `off_park_boundary` / `p3_pseudo_poi_kept` / `low_evidence`。
> 新增标记必须先改脚本 `FLAG_ORDER` 并在此登记；`--check` 会拒绝未登记标记。

| # | 节点（景区） | node_class | confidence | quality_flags | 判定理由（为什么保留、为什么这么标） |
|---:|---|---|---:|---|---|
| 1 | `双溪别墅`（广州白云山） | facility | 0.60 | `class_uncertain` | 「别墅」= 住宿/接待建筑；原文仅列为途经景点，无功能描述 |
| 2 | `山庄旅舍`（广州白云山） | facility | 0.70 | `class_uncertain` | 「旅舍」= 住宿设施；但原文把它列入「途经游览…等景点」 |
| 3 | `山顶公园`（广州白云山） | area | 0.75 | `scope_ambiguous` | 「公园」为片区，但原文又把它与山顶广场并列为「主要景点」 |
| 4 | `松涛别院`（广州白云山） | attraction | 0.55 | `class_uncertain;low_evidence` | 原文只有路线串联「西门→黄婆洞水库→梅花谷→松涛别院→摩星岭」；「别院」也可能是住宿/餐饮建筑，无法判定 |
| 5 | `梅花谷`（广州白云山） | area | 0.70 | `scope_ambiguous` | 原文只作景点/路线串联；「谷」按片区规则归 area |
| 6 | `白云松涛`（广州白云山） | attraction | 0.70 | `low_evidence` | 原文只作路线串联「经过『白云松涛』」；按景名归 attraction |
| 7 | `蒲谷`（广州白云山） | area | 0.70 | `scope_ambiguous` | 原文「蒲谷溪流：热带雨林既视感」= 溪谷点位；「谷」按片区规则归 area |
| 8 | `三县界碑`（武功山） | attraction | 0.85 | `off_park_boundary` | 位于武功山—明月山穿越线边界，非武功山景区内部点位；保留 |
| 9 | `中庵`（武功山） | attraction | 0.70 | `alias_mismatch` | 原文「紫极宫（中庵）」= 与紫极宫同址的别名；P6 未合并，保留双节点 |
| 10 | `回音谷`（武功山） | area | 0.70 | `scope_ambiguous` | 原文只作路线串联；「谷」按片区规则归 area |
| 11 | `安源路矿工人运动纪念馆`（武功山） | attraction | 0.85 | `off_park_boundary` | 位于萍乡安源（独立景点），不在武功山景区内；保留为 POI 节点 |
| 12 | `明月山6281梯`（武功山） | attraction | 0.60 | `p3_pseudo_poi_kept;low_evidence` | 6281 级阶梯段，原文只作路线终点前的串联；P6 已按 KEEP_POI_NOTE 保留 |
| 13 | `玻璃眺台`（武功山） | facility | 0.65 | `class_uncertain` | 「眺台」= 观景平台（设施）；但它同时是武功山核心打卡点，下游若按「景点」取用可并入 attraction |
| 14 | `秋收起义广场`（武功山） | attraction | 0.85 | `off_park_boundary` | 位于萍乡市区（江南第一大广场），不在武功山景区内；保留 |
| 15 | `羊狮慕小火车站`（武功山） | transport | 0.90 | `p3_pseudo_poi_kept` | P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「…→羊狮慕小火车站→…」 |
| 16 | `萍乡车站`（武功山） | transport | 0.90 | `off_park_boundary` | 位于萍乡市区、不在武功山景区范围内；作为行程起点的交通设施保留 |
| 17 | `途经好汉坡`（武功山） | attraction | 0.70 | `alias_mismatch` | 节点名含动词「途经」，与「好汉坡」重复（原文「途经好汉坡」）；保留节点不删 |
| 18 | `金顶`（武功山） | attraction | 0.65 | `scope_ambiguous` | 官方 WGS-O-03 把它列为「四大景区」之一；但它同时是海拔 1918 米主峰/登顶目的地（freq=13，无下级 POI），按具体目的地归 attraction，争议保留 |
| 19 | `奇妙岛`（长隆） | area | 0.70 | `scope_ambiguous` | 原文「饭后逛『奇妙岛』拍照打卡」= 园内打卡片区；范围介于点位与片区 |
| 20 | `安检入口`（长隆） | facility | 0.90 | `p3_pseudo_poi_kept` | P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「09:00 入园 / 安检入口」 |
| 21 | `家庭亲子区`（长隆） | area | 0.90 | `p3_pseudo_poi_kept` | P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「13:10 家庭亲子区 / 飞马家庭过山车」 |
| 22 | `小火车游览区`（长隆） | area | 0.90 | `multi_class_name` | 「小火车」是交通词、「游览区」是片区词，按片区归类（不是 P3 伪 POI 保留项） |
| 23 | `巡游主街段`（长隆） | area | 0.90 | `p3_pseudo_poi_kept` | P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「15:30 巡游主街段 / 主题街区」 |
| 24 | `欢乐主街区`（长隆） | area | 0.90 | `p3_pseudo_poi_kept` | P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「进入主街，两边是各种商店和餐厅」 |
| 25 | `火烈鸟`（长隆） | attraction | 0.80 | `name_from_animal` | 节点名是动物名，原文以「火烈鸟区域」「看火烈鸟」指代展区 |
| 26 | `花果山`（长隆） | area | 0.70 | `scope_ambiguous` | 原文只给「花果山是花车巡游起点」「花果山道路两边占位置」= 园内片区；无独立景点描述 |
| 27 | `花车大巡游`（长隆） | attraction | 0.85 | `activity_like` | 原文「15:30 花车大巡游（花果山始发）」= 巡游活动，不是固定地点；保留节点归 attraction |
| 28 | `金猴王国`（长隆） | attraction | 0.80 | `scope_ambiguous` | 原文「金猴王国猴子种类超多，上午最活泼」= 可参观动物展区；不是独立售票园区，故不按「王国」归 area |
| 29 | `长隆旅游度假区`（长隆） | area | 0.90 | `alias_mismatch` | 原文写「广州长隆度假区」，节点名加了「旅游」二字 |

### 7.1 与 P6 既有规则的关系（不推翻、不重跑）

| P6 规则 | 本任务处理 |
|---|---|
| `DROP_POI`（4 条句子片段/动作） | 这 4 条不在 141 POI 中，**不恢复、不重判**；它们属于 P6 已处理项 |
| `RECLASS_ACTIVITY`（5 条活动/时段） | 同上，已转 ACTIVITY 节点，**不在**分类范围（ACTIVITY 12 之一部分） |
| `KEEP_POI_NOTE`（6 条） | **全部保留**，6 条都标 `p3_pseudo_poi_kept`，逐条见 §7 第 12/15/20/21/23/24 行 |
| `SIMILAR_PAIRS`（7 对） | **不合并**；分类上用 `paired_spot` 规则把 `X` 与 `X景区` 区分成 `attraction` / `area`（摩星岭、明珠楼、鸣春谷） |

---

## 8. 已知局限（不掩盖）

1. **餐饮/购物覆盖极低**：141 个 POI 里 `food` 只有 3 个、`shop` 只有 1 个，且全部在长隆。
   这不是分类器漏判，而是上游 P2/P3 本来就没有把「鸣春谷豆腐花」「山间亭子」「补给点」这类写成 POI 节点。
   本任务**不补造节点**，只如实反映缺口 → 若 T2/T3 要做「吃什么/买什么」，需回 P2 补抽或新建属性表（T1.3 的 `meal_spot` 已覆盖部分）。
2. **`area` 含自然地理单元**：`天鹅湖` / `黄婆洞水库` / `发云界` / `福星谷` / `蒲谷` / `梅花谷` / `回音谷` /
   `奇妙岛` / `百虎山`（已改判 attraction）/ `花果山` 等按 parent 口径归 `area`。若下游只要「可玩景点」，
   应取 `attraction` ∪ `area`，或按 `confidence` 排序取高分。
3. **`area` 与「点位」的边界靠规则 + 26 条人工覆盖**：`谷/山/湖/岛` 既可能是片区也可能是单点，
   本任务用「原文是否把它当区域/容器」判，证据不足的标 `scope_ambiguous` 并降置信（0.70），**没有硬猜成 attraction**。
4. **P2 只覆盖 29 篇文档**：`entities.jsonl` 停在 `v0.2-p02`（T1.2 新增的 `WGS-O-07/08/09` 未重跑 P2），
   因此 59 个 P3-only POI 的原文证据只能从 `routes.jsonl` 的 `source_span` 回 `clean_content` 取句；
   本任务只读、不重跑 P2，也不改 P2 产物。
5. **分类只对「地点」负责**：TIME / ACTIVITY / CONDITION 共 77 个节点没有分类值，P7 若按 `node_class` 过滤
   必须显式保留这三类，否则会丢时间、活动与条件建议。
6. **不新增第 7 枚举**：`花车大巡游`（活动）、`玉龙雪山式` 的表演类、住宿类都只能塞进现有 6 值。
   若评审认为需要 `activity` / `lodging` 子类，必须先在 `docs/optimization/` 提案并过审，本任务不实施。
7. **抽样 0% 不等于零噪声**：见 §6.4，真实噪声率 95% 置信上限约 6%，且 2 条可疑节点未被抽中。

---

## 9. T1.5 重跑后的重建命令

P6 重跑（T1.5）后，`graph_nodes.csv` 若节点集合变化，按下面顺序重建：

```powershell
Set-Location E:\ProgramProject\travel-agent
$env:PYTHONIOENCODING='utf-8'
$py = ".\.venv\Scripts\python.exe"

# 1) 重建分类表（确定性：同输入必得同字节输出）
& $py analysis\p06_graph\outputs\classify_nodes.py --write

# 2) 全量校验（行数/集合/枚举/空值/置信度/确定性/抽样表/docs）
& $py analysis\p06_graph\outputs\classify_nodes.py --check

# 3) 图自检仍须绿
& $py checks\check_graph.py analysis\p06_graph\outputs
```

- **`--write` 幂等**：同一 `graph_nodes.csv` 输入重复跑，`node_classification.csv` 的 sha256 不变
  （本基线：`82d70e36eefaa8567d9ab61476ab719212f8fe53ca0e06fab7ff30bd1059f28b`）。
- **节点集合变了怎么办**：`--check` 会报「当前地点节点 N ≠ 基线 152」。
  此时需要（a）更新本文 §2 的 152 / 77 / 229 口径与 §5 统计；
  （b）按 §6.1 的 seed/框架**重做 50 抽样**并重新人工判定 `is_noise`（抽样表不能复用旧节点集）；
  （c）若新节点无名称信号，`fallback:attraction` 会给 0.70 并把不确定性留给人工。
- **不要手改 CSV**：`--check` 会用规则重算并逐行比对，手改任何 `node_class`/`confidence`/`method` 都会非 0 退出。

---

## 10. 文件清单与只读输入

### 10.1 本任务产出

| 文件 | 行数 | 编码 | 说明 |
|---|---:|---|---|
| `analysis/p06_graph/outputs/node_classification.csv` | 152（+表头） | UTF-8-SIG | 列固定：`node_id,node_type,name,scenic_area,node_class,confidence,method,quality_flags` |
| `analysis/p06_graph/outputs/classify_nodes.py` | — | UTF-8 | 规则分类器 + `--check` / `--write` |
| `analysis/p02_entities/outputs/node_noise_sample50.csv` | 50（+表头） | UTF-8-SIG | 列固定：`sample_no,node_id,name,scenic_area,evidence_sentence,node_class,is_noise,noise_reason,quality_flags` |
| `docs/optimization/NODE_CLASSIFICATION.md` | — | UTF-8 | 本文档 |

### 10.2 只读输入（一字未改）

| 文件 | 用途 |
|---|---|
| `analysis/p06_graph/outputs/graph_nodes.csv` | 152 个地点节点的来源（229 行全量） |
| `analysis/p06_graph/outputs/graph_edges.csv` | 只用于判断节点在路线中的角色（如 `明珠楼` 是观光车上车点） |
| `analysis/p06_graph/outputs/graph_qa.md` | P6 既有 `DROP_POI` / `RECLASS_ACTIVITY` / `KEEP_POI_NOTE` / `SIMILAR_PAIRS` 口径 |
| `analysis/p02_entities/outputs/entities.jsonl` | P2 原文句子（`sentence`）证据 |
| `scenic/{changlong,baiyunshan,wugongshan}/data/processed/*_guides.csv` | 32 篇 `clean_content` 冻结原文（取句、核证据） |
| `standards/handover/p06_graph.yaml` | 冻结项：节点/边类型枚举、融合去重规则 |

---

## 11. `--check` 到底校验什么（DoD 的机器化）

`classify_nodes.py --check` 只读不写，任何一条不满足即打印原因并非 0 退出：

1. `node_classification.csv` **表头与列序** = 本文 §10.1；
2. **行数** = 地点节点数（当前 152），且当前基线必须仍是 152（否则提示 T1.5 需同步 docs/抽样）；
3. `node_id` 集合 **完全等于** `graph_nodes.csv` 中 `node_type ∈ {SCENIC_AREA, POI, TRANSPORT}` 的集合，
   **无重复、无缺失、无多余**；
4. `node_class` **无空值**、只允许 6 值、**6 值均有节点**；`SCENIC_AREA`→`area`、`TRANSPORT`→`transport`；
5. `confidence` 可解析且 ∈ [0,1]；`quality_flags` 全部在受控词表内、无重复、顺序固定；
6. `name` / `node_type` / `scenic_area` 与 `graph_nodes.csv` 逐行一致（防手改漂移）；
7. **确定性**：用规则重算 152 行，与磁盘 CSV 逐行逐字段比对；
8. **范围口径**：`152 + 77 = 229`，且 TIME=32 / ACTIVITY=12 / CONDITION=33 与基线一致；
9. **50 抽样表**：50 行、表头正确、`sample_no` 1..50、`node_id` 序列 = `random.Random(20261115).sample(141 POI, 50)`、
   `node_class` 与分类表一致、`is_noise ∈ {0,1}`、噪声行必须有 `noise_reason`、
   `evidence_sentence` 必须是 `entities.jsonl`/`clean_content` 的原文子串；
10. **噪声率** < 10%（当前 0/50）；
11. **本文档**存在且含范围口径（`152 + 77 = 229`）、seed（`random.Random(20261115)`）、重建命令（`classify_nodes.py --write`）、
    6 值枚举与噪声率结论。

> 通过时输出：`rows=152  attraction=90 food=3 transport=15 shop=1 facility=11 area=32`，`[OK] … 全部满足 DoD`。
