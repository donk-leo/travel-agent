# P7 评测骨架（T0.3）

> 配套：[03_EVAL_SPEC.md](../../../../travel-agent-run/optimization/03_EVAL_SPEC.md) §2/§3/§8、
> [01_TASK_BOARD.md](../../../../travel-agent-run/optimization/01_TASK_BOARD.md) 的 T0.3 / T4.2。
>
> 本目录只做**评测**：读 golden set → 调真实 `run_agent` → 记录原始结果 → 由 cases 计算指标。
> 不改 `src/` 任何代码，不手写任何成功率/延迟/证据覆盖率。

---

## 1. 范围与边界（T0.3）

- golden set：**10 条 seed**（`golden_set.jsonl`），全部 `split=dev`，用于验证骨架可跑；
- 本轮**不跑** held-out，**不跑** 30 条全量（30 条是 T4.1 的产出，全量跑是 T4.2）；
- 真实模型只跑了 `--limit 2`（见 §9），其余 8 条未跑，原因写在 §9，未编造结果；
- 每条查询超时 **180s**、失败重试 **1 次**；超时/异常/partial 都保留，不删难样本；
- 输出 JSON 只由脚本生成，`eval/results/*.json` 不得手改。

---

## 2. 三步跑起来

工作目录为仓库根，解释器用仓库内 venv：

```powershell
# 第 1 步：只校验 golden set schema，不调用模型（秒级，退出码应为 0）
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split dev --limit 1 --dry-run

# 第 2 步：真实跑前 2 条（单条历史耗时 33–158 秒，预留 1–5 分钟）
$env:P07_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"   # 见 §7 排错
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split dev --limit 2 --out analysis\p07_agent\eval\results\dev-real-02.json

# 第 3 步：跑 schema 单测（标准库 unittest，不装新依赖）
.\.venv\Scripts\python.exe analysis\p07_agent\eval\tests\test_eval_schema.py -v
```

参数：

| 参数 | 说明 |
|---|---|
| `--split dev\|heldout\|all` | 默认 `dev`；`heldout` 当前选中 0 条，正常写空骨架；`all` = 10 条 |
| `--limit N` | 在 split 过滤后只跑前 N 条 |
| `--dry-run` | 不 import agent、不调用模型，只校验 schema 并写空骨架 |
| `--out PATH` | 结果 JSON 路径；默认 `eval/results/<split>-<dryrun\|real>-<时间戳>.json` |

`eval/results/sessions/` 是 `run_agent` 的会话轨迹落盘位置（由 runner 用
`P07_SESSION_DIR` 指到白名单目录），含用户原文，**已被 `.gitignore` 忽略，不入库**。
`*-dryrun-*.json` 也是本地校验产物，同样不入库。

---

## 3. 输出 JSON 结构

```json
{
  "meta": {
    "commit": "29d0943", "git_dirty": true, "model": "qwen3:8b",
    "model_url": "http://127.0.0.1:11434/api/chat",
    "run_mode": "real | dry-run", "split": "dev", "limit": 2,
    "started_at": "2026-11-15T15:52:48+08:00", "finished_at": "...", "duration_s": 43.672,
    "timeout_s": 180.0, "max_attempts": 2, "python_version": "3.11.9",
    "agent_imported": true, "model_preflight": {"ok": true, "message": "..."}
  },
  "cases": [ { "...": "单条查询记录" } ],
  "summary": { "...": "全部由 cases 计算" }
}
```

`cases[]` 关键字段：

| 字段 | 含义 |
|---|---|
| `id` / `split` / `query` / `turns` / `expected` | 从 golden set 原样带出（`query` 不重写） |
| `executed` | 是否拿到 `run_agent` 返回值（超时/异常为 false） |
| `model_calls` | 实际调用 `run_agent` 的次数（含重试、多轮） |
| `raw_status` | agent 原始状态（当前可能是 `complete`） |
| `status` | 归一后的四值 `verified/partial/clarify/error`；无法归一为 `null` |
| `status_correct` | `status ∈ expected.status`；未执行为 `null` |
| `schema_pass` | 返回值含契约必需键且 `status` 非空 |
| `route` | `node_count`、`segment_count`、`single_destination`、`validation_valid`、`fully_verified`、`missing_connections`、`cross_doc_transitions`、`route_truncated`、`day_plan_fallback` |
| `evidence` | `segments_total`、`segments_with_source`、`coverage`、逐段 `segments[]`（含 `source_doc_ids`） |
| `route_reasons` | 结构问题的机器标签：`no_route_nodes`、`single_destination`、`missing_connections:N`、`cross_doc_transitions:N`、`route_truncated`、`day_plan_fallback`、`sub_area_not_applied` |
| `partial_reasons` | 仅当 `status=partial` 时，等于 `route_reasons` |
| `latency_s` | 该条所有尝试的墙钟耗时之和（含重试与多轮），单位秒 |
| `timeout` / `error` / `attempts[]` / `turns_run[]` | 失败证据：每轮、每次尝试的耗时/错误；多轮记录当前累积提交文本 |

多轮查询（`EDGE-FOLLOW-01`）由 `turns` 驱动：第 1 轮提交 `我想出去玩一天`，
第 2 轮复用累积文本 `我想出去玩一天，白云山，轻松一点。`（`query` 字段保留规范
原文的 `→` 记号，只作追溯，不用于提交）。

---

## 4. 指标定义（summary 可复算）

所有比例统一为 `{"numerator": n, "denominator": m, "rate": n/m}`；**分母为 0 时
`rate=null`**，不会伪造 0%。`rate` 保留 4 位小数。

| summary 字段 | 分母 | 定义 |
|---|---|---|
| `n_cases` / `split_counts` | — | 本次选中的条数与 split 分布 |
| `n_attempted_cases` / `n_executed_cases` | — | 调用过模型 / 拿到返回值 |
| `n_timeout_cases` / `n_error_cases` | — | 出现超时 / 出现错误的条数 |
| `status_counts` | — | 四值计数；`status_other` 统计无法归一的原始状态 |
| `status_correct` | executed | `status_correct is true` 的比例 |
| `schema_pass` | executed | 返回结构符合契约的比例 |
| `evidence_coverage` | 所有 executed 的 `segments_total` 之和 | 有来源文档的 NEXT 段比例 |
| `route_valid` | `validation_valid` 非 null 的 executed 条数 | `validation_valid is true` 的比例 |
| `stop_cap_ok` | 有 `expected.max_stops` 且 executed 的条数 | `node_count <= max_stops` 的比例 |
| `partial_rate` | executed | `status=partial` 比例 |
| `latency_s` | — | `n`、`p50`、`p95`（nearest-rank，空集为 null） |

注意口径：

- `evidence_coverage` 目前只覆盖 **NEXT 段**；点位级证据（`doc → 标题/URL/摘句`）
  属 T1.6 证据服务，尚未实现。单点子园区（0 段）的 `coverage` 是 `null`，不是 100%；
- `route_valid` 对单点园区会因“至少两个节点才能校验”而计为 false，这是现状，不隐藏；
- 延迟是 runner 实测墙钟，不是模型自报；历史基线 33–158 秒/次（BASELINE §6，非本轮复测）。

---

## 5. 状态映射（临时，T2.1 后删除）

| agent 原始值 | 评测四值 |
|---|---|
| `complete` | `verified` |
| `verified` | `verified` |
| `partial` | `partial` |
| `clarify` | `clarify` |
| `error` | `error` |
| 其他（如 `reply`、`working`） | `null`（`status_other` +1，不猜） |

映射只发生在评测侧，**不改 agent**。T2.1 把 `complete` 改为 `verified` 后，映射表
中的 `complete` 一行即可删除。

---

## 6. 如何加一条查询

1. 在 `golden_set.jsonl` 追加一行 JSON（UTF-8 无 BOM，`\n` 换行），不要把
   一条查询拆成多行；
2. 必填字段：`id`、`area`、`days`、`persona`、`preferences`、`constraints`、
   `query`、`split`、`expected`（`expected` 含 `status/must_include/must_not/
   evidence_required/max_stops`）；
3. `split` 只能是 `dev` 或 `heldout`；`expected.status` 只能取
   `verified/partial/clarify/error`；`id` 全局唯一；
4. 多轮查询加 `turns`（≥2 条非空字符串，按顺序提交；`query` 保留规范原文）；
5. 加完先跑 `--dry-run`：schema 有错会打印行号与原因并以退出码 2 结束；
6. 新增 held-out 查询必须与 dev 分开，且开发期不得查看 held-out 明细。

---

## 7. 排错

| 现象 | 处理 |
|---|---|
| 连接 `localhost:11434` 失败（IPv6 解析） | 用 `127.0.0.1` 覆盖：`$env:P07_OLLAMA_URL="http://127.0.0.1:11434/api/chat"`；`--dry-run` 不受影响 |
| `ollama` 命令找不到 | 本机 CLI 不在 PATH，属正常；runner 只用 HTTP API，不调用 CLI |
| 单条很慢 / 超时 | 历史 33–158 秒/次；本轮超时 180s、重试 1 次。超时线程无法强杀（Python 限制），重试可能与旧调用并行，耗时按实际墙钟记录 |
| 模型没启动 | runner 先探测 `/api/tags` 并打印警告，随后逐条如实记录 error，不伪造成功 |
| 中文在 PowerShell 乱码 | 读文件/数行用 Python，或 `Get-Content -Encoding utf8`；写 JSON 用 UTF-8 无 BOM |
| 想装 pytest / PyYAML | 不要装；本目录只用标准库，单测用 `unittest` |

---

## 8. 如何报告

- **机器指标**：直接引用 `eval/results/*.json` 的 `summary`，报告里写清运行命令、
  split、limit、commit、模型名；数字必须能由 `cases` 复算；
- **人工评分**：另建 CSV（id × 6 维），不写进 `results.json`；
- **失败样本**：保留在 `cases` 里，报告里按 03_EVAL_SPEC §7 的 F1–F13 分类并给
  repro 命令，不删样本；
- **禁止**：手改 `results.json`、把未跑的条数写成已跑、把 `partial` 改写成
  `verified`、因指标难看删查询。

---

## 9. 已知偏差 / 待人类决定

1. **CL-INFO-01 的 split 冲突（已按父 Agent 裁决处理）**
   `03_EVAL_SPEC.md` §2.2 将该条标为 `held-out`，但 T0.3 的 10 条 seed 列表包含它，
   且 T0.3 的 DoD 要求 `split=dev`。当前处理：`query` **逐字照抄规范**，该条写
   `"split": "dev"`，并在 `notes` 与本节标注冲突；须在 **T4.1 由人类重新分类**。
   **当前 10 条均为 dev，held-out 集为空（0 条），30 条全集待 T4.1。**
2. **held-out 为空**：`--split heldout` 选中 0 条时**不报错**，正常写 `cases=[]`
   的合法骨架并在 stdout 说明；`--split all` 当前等于 10 条。
3. **CL-FAM-02 的 `max_stops`**：`03_EVAL_SPEC.md` §2.3 示例写 8，T2.2 计划把带
   0–6 岁儿童/老人的单日上限收紧到 6。当前沿用规范示例值 **8**，待 T4.2 人类裁决；
   本轮真实跑该条返回 12 个节点，`stop_cap_ok` 因此为 false（见 §10）。
4. **状态映射是临时的**：当前 agent 返回 `complete`，评测映射为 `verified`；
   T2.1 改完后应删除映射（见 §5）。
5. **多轮 `query` 含 `→`**：`EDGE-FOLLOW-01` 的 `query` 保留规范原文记号，
   实际提交由 `turns` 累积拼接，见 §3。

---

## 10. 本轮真实运行记录（2026-11-15）

命令（退出码 0）：

```powershell
$env:P07_OLLAMA_URL='http://127.0.0.1:11434/api/chat'
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split dev --limit 2 --out analysis\p07_agent\eval\results\dev-real-01.json
```

- commit：`29d0943`（运行时有未提交的评测目录改动，`meta.git_dirty=true`）
- 模型：`qwen3:8b`；`meta.duration_s=43.672`；结果文件：`results/dev-real-01.json`
- golden set 10 条只跑了前 2 条，剩余 8 条**未跑**（T0.3 时间盒内不跑全量）。

| id | raw_status → status | 耗时 s | 节点 | 段证据 | 结果 |
|---|---|---:|---:|---|---|
| CL-FAM-02 | `complete` → `verified` | 31.797 | 12 | 11/11（100%） | `schema_pass=true`，`status_correct=true`；12 点超过 `max_stops=8` |
| CL-SUB-03 | `partial` → `partial` | 11.797 | 1 | 0 段（单点，coverage=null） | `status_correct=true`；原因 `single_destination`、`sub_area_not_applied` |

summary（由 cases 计算）：`status_correct=2/2`、`schema_pass=2/2`、
`evidence_coverage=11/11`、`route_valid=1/2`、`stop_cap_ok=1/2`、
`partial_rate=1/2`、`latency p50=11.797s / p95=31.797s`。

观察（只记录，不改 agent）：CL-FAM-02 的 `run_agent` 返回 `message` 为空字符串，
但路线/校验正常；另 12 个停留点超过 T2.2 计划的人群上限，属 T2.2 要修的问题。

---

## 11. 目录结构

```
analysis/p07_agent/eval/
├─ golden_set.jsonl          # 10 条 dev seed（query 逐字照抄 03_EVAL_SPEC.md）
├─ run_eval.py               # runner：dry-run / 真实跑 / 指标聚合
├─ README.md                 # 本文件
├─ results/
│  ├─ .gitignore             # 忽略 sessions/ 与 dry-run 骨架
│  └─ dev-real-01.json       # 本轮真实运行证据（脚本生成，勿手改）
└─ tests/
   └─ test_eval_schema.py    # schema/映射/多轮/汇总复算（12 个用例）
```

---

## 12. 禁止

- 手改 `eval/results/*.json` 或 `summary` 数字；
- 改 `golden_set.jsonl` 里的 `query` 文本（只允许按 §6 追加/补充元数据）；
- 开发期跑或查看 held-out 明细；
- 因指标不好看删除查询或把失败改成成功；
- 在 `eval/` 外新增/修改文件（评测只读 `src/`）。
