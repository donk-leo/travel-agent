# 项目 7 · 旅游规划 Agent

> 负责人：**HappinessJo**｜复核：T0coke
> 交接卡：`standards/handover/p07_agent.yaml`｜工具 Schema：`standards/schema_tools.json`

## 目标

基于项目 6 的知识图谱，做一个能“理解约束 → 查图谱 → 生成行程”的 Agent：
意图解析（景区/人群/时长）、图谱查询工具、ReAct 闭环、回退与追问。

## 输入（只读）

`analysis/p06_graph/outputs/graph_nodes.csv` 与 `graph_edges.csv`（tag `v0.6-p06`）。
**不允许把整张图塞进 Prompt 代替工具调用**——这是本项目的核心失分点。

## 产出

```
analysis/p07_agent/
├─ src/agent.py                 # ReAct 主循环
├─ src/tools.py                 # 4 个图谱查询工具（见 schema_tools.json）
├─ outputs/sessions/*.jsonl     # 每次运行的思考-调用-观察轨迹
├─ outputs/tests.md             # ≥3 类场景测试（老人/亲子/情侣 × 一天/两天）
├─ outputs/demo.md              # 一条完整示范
└─ .env.example                 # LLM 配置占位（密钥不入库）
```

## 运行

```powershell
copy analysis\p07_agent\.env.example analysis\p07_agent\.env   # 填 key
python analysis/p07_agent/src/agent.py --query "带老人玩一天长隆，怎么安排？"
python checks/check_agent.py
```

## 关键约束

- 每条回答必须能追到 `tool_call` + `observation`（轨迹落盘）；
- 无匹配/信息不足/冲突约束要有回退或追问，不能硬编；
- 模型与密钥走 `.env`；仓库只留 `.env.example`；
- 至少 3 类场景 + 1 个失败案例分析（失败案例同时进总结反思）。

## 验收（对应任务书 100 分）

| 考核项 | 分值 | 证据 |
|---|---|---|
| 架构与 LLM 集成 | 20 | `agent.py` + `config/` |
| 图谱查询工具封装 | 20 | `tools.py` + Schema |
| 推理编排 | 20 | `outputs/sessions/*.jsonl` |
| 测试与鲁棒性 | 20 | `tests.md` |
| 示范用例 | 10 | `demo.md` |
| 交互与可复现 | 10 | CLI/Web 入口 + `.env.example` |

## 状态

`planned` —— 依赖 P6 交付。
