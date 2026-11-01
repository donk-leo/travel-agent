# P6 实验报告：多源程序性知识融合与图谱可视化

> 项目：P6 知识图谱｜负责人：HappinessJo｜复核：T0coke（待复核）
> 交付 tag：`v0.6-p06`｜自检：`python checks/check_graph.py analysis/p06_graph/outputs`（exit 0）
> 复现：`python analysis/p06_graph/src/run_all.py`

---

## 1. 任务与输入

把项目 2 的实体、项目 3 的路线步骤、项目 5 的条件建议融合成一张可查询的知识图谱，
支撑项目 7 的旅游规划 Agent。输入全部来自已冻结的 tag，只读：

| 输入 | tag | 规模 | 本项用到的字段 |
|---|---|---|---|
| `analysis/p02_entities/outputs/entities.jsonl` | `v0.2-p02` | 1006 条 / 29 篇 | `doc_id, scenic_area, normalized_name, entity_type, sentence` |
| `analysis/p03_routes/outputs/routes.jsonl` | `v0.3-p03` | 226 步 / 35 路线 / 122 个 POI | `doc_id, route_id, step_no, poi, activity, time_norm, time_source, time_period` |
| `analysis/p05_conditions/outputs/conditions.jsonl` + `p6_condition_poi.csv` | `v0.5-p05` | 36 条 / 建议入图 33 条 | `cond_id, condition_text, suggestion_text, target_key, anchor_confidence` |

三景区文档数：长隆 8、广州白云山 7、武功山 14（合计 29），与 P1/P2/P3 一致。

---

## 2. 方法

### 2.1 节点与边的 Schema

节点 6 类、边 6 类，与 `standards/schema_graph.json` 的枚举完全一致：

| 节点类型 | `node_id` 模板 | 数量 | 说明 |
|---|---|---|---|
| `SCENIC_AREA` | `SCENIC_AREA|<景区>` | 3 | 长隆 / 广州白云山 / 武功山 |
| `POI` | `POI|<景区>|<标准名>` | 141 | 与 P5 桥接键 `POI|<景区>|<标准名>` 一致 |
| `TRANSPORT` | `TRANSPORT|<方式>` | 8 | 按“方式”跨景区共享，如 `TRANSPORT|索道` |
| `ACTIVITY` | `ACTIVITY|<活动名>` | 12 | 路线里只有活动、没有 POI 的步骤 |
| `TIME` | `TIME|<time_norm>` | 32 | 只来自 P3 的 `time_source=explicit` |
| `CONDITION` | `CONDITION|<cond_id>` | 33 | P5 建议入图的 33 条 |

| 边类型 | 方向 | 语义与生成规则 | 数量 |
|---|---|---|---|
| `CONTAINS` | 景区 → POI/活动 | 归属关系 | 153 |
| `NEXT` | POI/活动 → POI/活动 | 同 `route_id` 内相邻 `step_no`；`weight` = 跨文档出现次数 | 165 |
| `BY_TRANSPORT` | POI → 交通 | P2 中**同一句**共现；`weight` = 共现次数 | 118 |
| `AT_TIME` | POI/活动 → 时间 | P3 `time_source=explicit`；`weight=1` | 47 |
| `HAS_CONDITION` | POI/景区 → 条件 | P5 桥接 `recommended_for_graph=True`；`weight=anchor_confidence` | 33 |
| `SIMILAR_TO` | POI → POI | 未合并的父子/层级写法 | 7 |

> 注：P5 桥接表里的 `AREA|<景区>` 在 P6 建图时映射为 `SCENIC_AREA|<景区>`，映射关系写在 `graph_qa.md`；
> P5 文件未做任何修改。

### 2.2 融合与去重（为什么合并 / 为什么保留）

| 规则 | 做法 | 命中 |
|---|---|---|
| R1 同名合并 | 同景区内 P2 `normalized_name` 与 P3 `poi` 完全相同 → 一个节点 | 54 对 |
| R2 别名表 | 先按 P3 `config/alias.csv`（160 行）归一再比 | **0 对** |
| R3 交通归一 | `游览观光车→观光车`、`免费巴士/大巴/公交→巴士`、`地铁N号线→地铁`（线路号存 `properties.lines`） | 15 个写法 → 8 个节点 |
| R4 父子/层级不合并 | `摩星岭` vs `摩星岭景区` 等保留双节点，用 `SIMILAR_TO` 记录“疑似同一对象” | 7 对 |
| 保留 | P2 独有 28 个（只挂 `CONTAINS`）、P3 独有 59 个 | — |

**R2 为什么是 0**：P2 的 `normalized_name` 已是规范写法，P3 的 `poi` 也已按同一张别名表归一，
两侧没有“只靠别名才能对上”的名字。规则保留在代码里，命中数如实记 0，不硬凑。

**R4 为什么不合并**：`摩星岭景区` 是片区、`摩星岭` 是主峰，合并会丢掉层级；交接卡冻结项要求
“父子关系保留”。7 对明细全部列在 `graph_qa.md` 第 3 节，便于人工复核。

**P3 伪 POI 15 条**（不是规范地名）的处置：

- 过滤 4 条（句子片段/动作）：`南门下山`、`完玻璃栈道就可以下山了`、
  `此次我们挑战经典的武功山沈明线`、`明月山景区大门终点`；
- 转 `ACTIVITY` 5 条（本质是活动/时段，且各自带显式时间，删掉会丢 6 个时间锚点）：
  `刺激项目黄金时段→刺激项目`、`错峰午餐`、`沉浸体验`、`午餐休息区→午餐休息`、`夜场演出`；
- 保留 6 条（设施/地名/区域）：`安检入口`、`明月山6281梯`、`羊狮慕小火车站`、
  `家庭亲子区`、`巡游主街段`、`欢乐主街区`。

### 2.3 连通性设计

`check_graph.py` 按**全图**计算最大连通分量，要求 ≥50%。三个景区天然是三块，POI 又按景区分 ID，
如果各景区独立建图，最大分量只有 **103/229（45.0%）**（去掉共享交通节点后的实测值），会直接 error。

方案：`TRANSPORT` 节点按**交通方式**跨景区共享。依据是 P2 中 `步行` 与三个景区的 POI 都同句共现：

- 长隆：北门、垂直过山车、长隆欢乐世界、长隆熊猫酒店；
- 广州白云山：34 个 POI（世纪圆梦石、摩星岭、鸣春谷……）；
- 武功山：武功山神、福星谷、紫极宫、许愿桥、金顶。

于是 长隆 —步行— 白云山 —索道— 武功山 连成一张网，最大分量 **229/229（100%）**。
这是**概念层共享**（“到该景点可以步行/坐索道”），**不代表景区之间可以步行互通**；
图谱是知识网络，不是路网。这一点在 `graph_qa.md` 第 2 节明确写出，避免被读成“连通性作弊”。

### 2.4 可视化

- 三个景区各一张完整网络图，节点按类型着色、边按关系用线型区分，红色高亮该景区**步数最多的路线**：
  长隆 `CL-T-03-r1`（17 步）、白云山 `BYS-O-01-r1`（23 步）、武功山 `WGS-O-04-r1`（18 步）；
- 一张三景区总览，按景区着色，共享交通节点（紫色）连接三块；
- 中文显式加载 `C:\Windows\Fonts\msyh.ttc`（否则方块）；图内不写标题，标题由图题承担。

---

## 3. 结果

### 3.1 总体规模

- **节点 229**：`SCENIC_AREA` 3、`POI` 141、`TRANSPORT` 8、`ACTIVITY` 12、`TIME` 32、`CONDITION` 33
- **边 523**：`CONTAINS` 153、`NEXT` 165、`BY_TRANSPORT` 118、`AT_TIME` 47、
  `HAS_CONDITION` 33、`SIMILAR_TO` 7

### 3.2 三景区覆盖

| 景区 | POI | 活动 | 条件 | 景区节点 | 交通（独占） | 时间 |
|---|---|---|---|---|---|---|
| 长隆 | 49 | 8 | 12 | 1 | 1（小火车） | 32（全部时间值都来自长隆文档） |
| 广州白云山 | 42 | 3 | 8 | 1 | 0 | 0 |
| 武功山 | 50 | 1 | 13 | 1 | 0 | 0 |
| 跨景区共享 | — | — | — | — | 7（步行/索道/缆车/徒步/观光车/地铁/巴士） | — |

三景区的 POI 合计 141 个，每景区都有独立子图（内部最大分量 71 / 54 / 65），不是“只有一个景区能看”。

### 3.3 核心节点（按无向度）

| 节点 | 类型 | 度 |
|---|---|---|
| `SCENIC_AREA|长隆` | 景区 | 64 |
| `SCENIC_AREA|武功山` | 景区 | 62 |
| `SCENIC_AREA|广州白云山` | 景区 | 52 |
| `TRANSPORT|步行` | 交通 | 45 |
| `TRANSPORT|索道` | 交通 | 21 |
| `TRANSPORT|观光车` | 交通 | 21 |
| `POI|广州白云山|摩星岭` | POI | 14 |
| `TRANSPORT|徒步` | 交通 | 14 |
| `POI|武功山|金顶` | POI | 13 |
| `POI|武功山|金顶索道` | POI | 11 |

度最高的三个是景区节点（`CONTAINS` 的必然结果），说明“核心”要分两层看：
**景区层**是三个 hub，**方式层**是 `步行/索道/观光车`——它们也是跨景区连通的关键。

### 3.4 查询验证（可执行，来自 `graph_qa.md` 第 6 节）

```python
import pandas as pd, networkx as nx
nodes = pd.read_csv('analysis/p06_graph/outputs/graph_nodes.csv', encoding='utf-8-sig')
edges = pd.read_csv('analysis/p06_graph/outputs/graph_edges.csv', encoding='utf-8-sig')
G = nx.from_pandas_edgelist(edges, 'src', 'dst', edge_attr=['rel','weight'],
                            create_using=nx.MultiDiGraph)
```

| 查询 | 实测结果 |
|---|---|
| Q1 长隆有哪些 POI | 49 个（4D影院、U型滑板、亚洲象园、动物幼儿园、北门……） |
| Q2 从长隆北门出发的下一步 | `POI|长隆|小火车游览区`，weight 1 |
| Q3 哪些景点可以坐索道 | 21 个，横跨白云山（九龙泉、摩星岭、鸣春谷……）与武功山（中庵、金顶……） |
| Q4 武功山有哪些条件建议 | 11 条挂景区节点（另有 2 条挂到石鼓寺、观音宕） |

Q3 正是跨景区共享交通节点的价值：一条查询能同时拿到两个景区的索道可达点。

### 3.5 连通性与自检

```
=== p06_graph · 节点 229 · 边 523 —— 通过 ===
节点类型 {'SCENIC_AREA': 3, 'POI': 141, 'TRANSPORT': 8, 'ACTIVITY': 12, 'TIME': 32, 'CONDITION': 33}
边类型 {'AT_TIME': 47, 'BY_TRANSPORT': 118, 'CONTAINS': 153, 'HAS_CONDITION': 33, 'NEXT': 165, 'SIMILAR_TO': 7}
最大连通分量 229/229（100%）
检查通过，可用于交接。（exit 0）
```

---

## 4. 质量验证与问题分析

### 4.1 缺失的关系（缺失 ≠ 没有）

1. **时间只有长隆**：P3 显式时间 47 步、32 个值，**全部集中在长隆文档**；白云山、武功山没有
   显式时间。本项不推断、不补，`AT_TIME` 为 0 的两景区如实呈现。
2. **P2/P3 对齐约一半**：P3 的 122 个 POI 中 54 个与 P2 同名（44.3%）；扣掉 9 条伪 POI
   （4 条过滤 + 5 条转活动）后，合法 POI 的对齐率 54/113 ≈ 47.8%，其余保留为独立节点并标
   `origins=P3`，不硬合并。
3. **条件覆盖稀疏**：36 条条件只来自 13/28 篇文档，没有条件边的景区/POI **不代表“无条件”**。
4. **交通只认同句**：`BY_TRANSPORT` 要求 POI 与交通方式出现在同一句，避免把“全文提到索道”
   错误挂到每个 POI 上；代价是部分真实关系会漏（已在 QA 记录）。
5. **活动名粒度不统一**：`错峰午餐`（转写）与 `错峰休整+特色午餐`（原生活动）未合并，
   属于两种来源的命名差异，保留原样。

### 4.2 已知数据质量问题

- P3 伪 POI 15 条（处置见 2.2）；12 条“整篇路线概述（未结构化）”散文路线没有可用步骤，
  直接跳过（不生成 NEXT）；7 个只有活动的步骤建成 ACTIVITY 节点，避免丢信息；
- 条件重复 3 条（`CND-0014/0015/0022`）按 P5 建议默认过滤；
- 输出 CSV 统一 UTF-8-SIG + `lineterminator="\n"`，JSONL/GraphML 为 UTF-8，无 CRLF。

### 4.3 设计取舍

- **为什么不用“三景区汇总节点”**：`docs/01` §8 的“汇总层”是 `scenic/summary` 数据层，
  不是图谱节点；凭空造一个 `SCENIC_AREA|三景区` 没有文本证据，评审会问“这条边从哪来”。
- **为什么共享交通而不是合并 POI**：交通方式是**类型概念**，可以合法地跨景区共享；
  POI 是**具体地点**，跨景区同名（实测 0 例）才可合并。
- **100% 连通的含义**：是“概念层可达”，不是“地理连通”；去掉共享交通后 45.0%，
  这个反证数字写在 `graph_qa.md` 里，供复核判断设计是否过度。

---

## 5. 可复现性

```powershell
# 一条命令：重建 → 出图 → QA → 自检
python analysis/p06_graph/src/run_all.py

# 或分开跑
python analysis/p06_graph/src/build_graph.py
python checks/check_graph.py analysis/p06_graph/outputs
```

- 无随机数据；布局仅用于出图（`spring_layout(seed=42/7)`），不影响 CSV/GraphML；
- 所有统计量由 `build_graph.py` 写入 `outputs/graph_stats.json`，报告数字均可用它复算；
- 输入版本由 tag 固定（`v0.2-p02` / `v0.3-p03` / `v0.5-p05`），不读上游中间文件。

---

## 6. 评分对照（任务书 100 分）

| 考核项 | 分值 | 本项证据 |
|---|---|---|
| 多源读取与融合策略 | 30 | 三源读取（P2/P3/P5）；R1–R4 规则 + 命中数（54/0/8/7）；伪 POI 15 条逐条处置 |
| Schema 与构建 | 30 | 6 类节点 / 6 类边全部使用；`graph_nodes.csv` 229 行、`graph_edges.csv` 523 行；边端点全部存在；连通 100% |
| 可视化 | 20 | 3 张景区图（含关键路线高亮）+ 1 张总览；类型/关系图例可辨；中文字体显式加载 |
| 质量验证与分析 | 10 | `graph_qa.md` 4 条可执行查询、核心节点、缺失关系、融合明细；check exit 0 |
| 报告与可复现 | 10 | 本报告 + `run_all.py` 一条命令；数字均可由 `graph_stats.json` 复算 |

---

## 7. 遗留问题

1. **T0coke 尚未复核**：本报告与 tag 由 owner 自检后提交，复核意见可能要求调整 R4 的 7 对或
   `BY_TRANSPORT` 的同句规则；如需调整，按仓库规则**升 tag**，不静默改冻结项。
2. **时间覆盖不足**：白云山/武功山没有显式时间，`AT_TIME` 无法覆盖；若后续 P3 升 tag 补时间，
   P6 需重跑（输入 tag 变更）。
3. **P2/P3 对齐率约 50%**：剩余 59 个 P3 独有 POI 只能靠人工/规则继续对齐，当前选择“保留”而非“硬合”。
4. **活动层较薄**：12 个活动节点，命名粒度不一；P7 若要用活动做推荐，建议先用 `NEXT` 序列而不是活动名匹配。
