# 项目 6 · 多源程序性知识融合与图谱可视化

> 负责人：**T0coke**｜复核：HappinessJo
> 交接卡：`standards/handover/p06_graph.yaml`｜输出 schema：`standards/schema_graph.json`

## 目标

把项目 2 的实体、项目 3 的路线（可选项目 5 的条件建议）融合成知识图谱：
节点（景点/交通/时间/活动/条件/景区）、边（先后 NEXT、包含 CONTAINS、时间 AT_TIME、
交通 BY_TRANSPORT、条件 HAS_CONDITION），并做可视化与质量验证。

## 输入（只读，来自上游 tag）

| 文件 | 来自 |
|---|---|
| `analysis/p02_entities/outputs/entities.jsonl` | v0.2-p02 |
| `analysis/p03_routes/outputs/routes.jsonl` | v0.3-p03 |
| `analysis/p05_conditions/outputs/conditions.jsonl` | v0.5-p05（可选） |

## P5 条件接入（已冻结 v0.5-p05）

P5 已交付，可直接消费，不必再猜锚点：

- 条件：`analysis/p05_conditions/outputs/conditions.jsonl`，36 条 / 33 唯一，13 篇文档；
- 锚点桥接：`analysis/p05_conditions/outputs/p6_condition_poi.csv`（36 行，8 条挂 POI、28 条挂景区）；
- 规则与注意事项：`analysis/p05_conditions/outputs/P6_接入说明.md`；
- 默认过滤 3 条 `is_duplicate=true`：`CND-0014`、`CND-0015`、`CND-0022`；
- 若 P6 暂不做条件节点，可跳过 P5；P6 的必需输入仍只有 P2、P3。

## 产出

```
analysis/p06_graph/outputs/
├─ graph_nodes.csv     # node_id / node_type / name / scenic_area / source_doc_ids / freq
├─ graph_edges.csv     # src / rel / dst / weight / source_doc_ids
├─ graph.graphml       # 或 Neo4j 导入脚本
├─ figures/graph_*.png # 至少一个景区的完整网络，关键路径高亮
└─ graph_qa.md         # 查询验证、核心节点、缺失关系、数据质量问题
```

## 运行

```powershell
python analysis/p06_graph/src/build_graph.py
python checks/check_graph.py analysis/p06_graph/outputs
```

## 关键约束

- 所有边的 `src`/`dst` 必须存在于节点表（check 会逐条验）；
- 最大连通分量 ≥ 50%，否则视为“散点图”不合格；
- 融合策略要写清：什么合并、什么保留、为什么（写进 `graph_qa.md`）；
- 节点数量不是目标，可解释的关系质量才是。

## 验收（对应任务书 100 分）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 多源读取与融合策略 | 30 | `build_graph.py` + 对齐/去重规则说明 |
| Schema 与构建 | 30 | `graph_nodes/edges.csv` + 连通性 |
| 可视化 | 20 | `figures/*.png` |
| 质量验证与分析 | 10 | `graph_qa.md` |
| 报告与可复现 | 10 | `report/` + README |

## 状态

`planned` —— 上游 `v0.2-p02`、`v0.3-p03`、`v0.5-p05` 均已存在；P6 代码尚未开始。
P5 的接入说明与锚点桥接表已就绪，开工时先读 `analysis/p05_conditions/outputs/P6_接入说明.md`。
