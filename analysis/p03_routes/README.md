# 项目 3 · 游览路线的层级结构挖掘

> 负责人：**HappinessJo**｜复核：T0coke
> 交接卡：`standards/handover/p03_routes.yaml`｜输出 schema：`standards/schema_routes.json`

## 目标

把官方攻略与游记中的路线描述解析为统一结构（步骤序号 / 时间 / 景点 / 活动），
再按**上午 / 中午 / 下午**构建时间层级；附加题做**官方 vs 游客**路线对比。

## 输入（只读）

三景区 `*_guides.csv` 的 `clean_content`（tag `v0.1-p01`）。
重点样本：长隆 `CL-O-02`（箭头链路 + `第一站（10:00）` 编号 + 时间）、`CL-O-01`（多日“第一站/第二站”）。

## 产出

```
analysis/p03_routes/
├─ outputs/routes.jsonl                  # 一行一个步骤
├─ outputs/hierarchy.json                # 时间层级（上午/中午/下午）
├─ outputs/figures/route_structure.png
├─ outputs/compare_official_vs_user.csv  # 附加题：景点覆盖度/顺序一致性/时间分配
└─ config/alias.csv                      # 名称归一化表（简称/全称/子景点/父区域）
```

## 运行

```powershell
# 一条命令重跑（解析 → 层级/对比/图 → 自检）
python analysis/p03_routes/src/run_all.py

# 或分步
python analysis/p03_routes/src/parse_routes.py
python analysis/p03_routes/src/build_hierarchy.py
python checks/check_routes.py
```

输出确定（两次重跑 SHA1 相同），无网络、无 LLM 调用。

## 关键约束

- **缺失时间不得伪装成原文事实**：`time_source=absent` 时 `time_norm` 必须为空；
- 同 `route_id` 内 `step_no` 从 1 连续递增（check 会验连续性）；
- 名称归一化要说明过度对齐的风险与局限；
- 官方页里的“关于饮食/住宿/交通”段落不是路线步骤，解析时按小标题切分过滤。

## 验收（对应任务书 100 分 + 附加 20）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 官方路线模式分析与结构化解析 | 40 | `routes.jsonl` + 模式归纳说明 |
| 时间维度层级构建 | 40 | `hierarchy.json` + 结构图 + 缺失时间策略 |
| 官方 vs 游客对比（附加） | 20 | `compare_official_vs_user.csv` + 原因分析 |
| 名称归一化与稳健性 | 10 | `config/alias.csv` + 规则说明 |
| 报告与可复现 | 10 | `report/` + README |

## 状态

`done`（`v0.3-p03`）：35 条路线 / 226 个步骤（长隆 8/52、白云山 11/61、武功山 16/113），
47 步有显式时间（全部在长隆），官方 vs 游客 4 个指标已出（覆盖度 / 顺序 τ / 步数 / 显式时间占比）。
`checks/check_routes.py` 退出码 0。详见 `report/p03_experiment_report.md`。
