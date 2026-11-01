# 项目 6 · 多源程序性知识融合与图谱可视化

> 负责人：**HappinessJo**｜复核：T0coke（待复核）
> 交接卡：`standards/handover/p06_graph.yaml`｜输出 schema：`standards/schema_graph.json`
> 状态：**已完成并打 tag `v0.6-p06`**（2026-11-01）｜check exit 0

## 目标

把项目 2 的实体、项目 3 的路线（+ 项目 5 的条件建议）融合成知识图谱：
节点（景点/交通/时间/活动/条件/景区）、边（先后 NEXT、包含 CONTAINS、时间 AT_TIME、
交通 BY_TRANSPORT、条件 HAS_CONDITION、相似 SIMILAR_TO），并做可视化与质量验证。

## 输入（只读，来自上游 tag）

| 文件 | 来自 |
|---|---|
| `analysis/p02_entities/outputs/entities.jsonl` | `v0.2-p02` |
| `analysis/p03_routes/outputs/routes.jsonl` | `v0.3-p03` |
| `analysis/p05_conditions/outputs/conditions.jsonl` + `p6_condition_poi.csv` | `v0.5-p05` |

## 结果（2026-11-01，三景区）

- **229 节点 / 523 边**，节点与边类型均只用 schema 枚举；
- 节点：`SCENIC_AREA` 3、`POI` 141（长隆 49 / 白云山 42 / 武功山 50）、`TRANSPORT` 8、
  `ACTIVITY` 12、`TIME` 32、`CONDITION` 33；
- 边：`CONTAINS` 153、`NEXT` 165、`BY_TRANSPORT` 118、`AT_TIME` 47、`HAS_CONDITION` 33、`SIMILAR_TO` 7；
- 最大连通分量 **229/229（100%）**；去掉共享交通节点后 103/229（45.0%，会低于 check 的 50% 门槛）。

## 运行（一条命令）

```powershell
python analysis/p06_graph/src/run_all.py        # 建图 → 出图 → QA → 自检
```

也可分开跑：

```powershell
python analysis/p06_graph/src/build_graph.py                    # 三景区总图
python analysis/p06_graph/src/build_graph.py --areas changlong  # 只跑长隆
python checks/check_graph.py analysis/p06_graph/outputs
```

## 产出

```
analysis/p06_graph/
├─ src/build_graph.py               # 建图（融合规则、边语义、出图、QA 生成）
├─ src/run_all.py                   # 一条命令重建 + 自检
├─ outputs/graph_nodes.csv          # UTF-8-SIG
├─ outputs/graph_edges.csv          # UTF-8-SIG
├─ outputs/graph.graphml            # Gephi / Neo4j 导入
├─ outputs/graph_stats.json         # 全部统计量（报告数字可复算）
├─ outputs/graph_qa.md              # 查询验证、核心节点、缺失关系、融合明细
├─ outputs/figures/graph_*.png      # 3 张景区图（关键路线高亮）+ 总览
└─ report/p06_experiment_report.md  # 实验报告
```

## 关键规则

- 节点 ID：`POI|<景区>|<标准名>`（与 P5 桥接键一致）、`SCENIC_AREA|<景区>`、`TRANSPORT|<方式>`、
  `TIME|<time_norm>`、`ACTIVITY|<活动名>`、`CONDITION|<cond_id>`；
- 融合：同名合并 54 对、别名表 0 对、交通归一 15→8、父子/层级保留 7 对（`SIMILAR_TO`）；
- 连通性靠 `TRANSPORT` 按方式跨景区共享（`步行` 三景区都有、`索道` 白云山+武功山），
  这是概念层共享，不代表景区间可步行互通；
- 时间只来自 P3 显式时间（47 步 / 32 个值，全在长隆），**不推断、不补**；
- P3 的 15 条伪 POI：过滤 4、转 `ACTIVITY` 5、保留 6（明细见 `outputs/graph_qa.md` 第 7 节）。

## 给 P7 的接口

只读 `outputs/graph_nodes.csv` 与 `outputs/graph_edges.csv`（`from_tag: v0.6-p06`）：

- 所有边端点都在节点表；`POI` 的 `node_id` 与 P5 桥接键一致；
- `TRANSPORT` 的 `scenic_area` 可能是 `跨景区`，按景区过滤时要带上；
- `TIME` 没有 `scenic_area`，按边反查所属 POI；
- 条件方向是 `POI/SCENIC_AREA -> CONDITION`；
- `graph_qa.md` 第 6 节有 4 条可直接复制的查询示例。

## 已知限制

- `AT_TIME` 只覆盖长隆（P3 只有长隆有显式时间）；
- P2/P3 的 POI 对齐率约一半，P3 独有 59 个保留为独立节点，不硬合并；
- P5 条件只来自 13/28 篇文档，缺失 ≠ 无条件；
- `BY_TRANSPORT` 只认同句共现，跨句关系会漏。
