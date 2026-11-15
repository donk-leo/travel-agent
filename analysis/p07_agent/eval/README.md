# P7 评测 runner / golden set（T4.1：30 条，20 dev / 10 held-out）

> 配套：[03_EVAL_SPEC.md](../../../../travel-agent-run/optimization/03_EVAL_SPEC.md) §2/§3/§8、
> [01_TASK_BOARD.md](../../../../travel-agent-run/optimization/01_TASK_BOARD.md) 的 T4.1 / T4.2、
> [PRODUCT_SPEC.md](../../../docs/optimization/PRODUCT_SPEC.md) §5（四状态语义）。
>
> 本目录只做**评测**：读 golden set → 调真实 `run_agent` → 记录原始结果 → 由 cases 计算指标。
> 不改 `src/` 任何代码，不手写任何成功率/延迟/证据覆盖率。

---

## 1. 范围与现状（T4.1）

- golden set：**30 条**（`golden_set.jsonl`），严格按 `03_EVAL_SPEC.md` §2.2 的 30 行、顺序一致，
  `query` 逐字照抄；**20 dev + 10 held-out**；
- 分层（§2.1）：长隆 10（8 dev / 2 held-out）、白云山 8（5 / 3）、武功山 8（5 / 3）、
  边界 4（2 / 2）；合计 20 / 10；
- **边界场景 17 条**（`boundary=true`，要求 ≥8）：CL-FRD-01、CL-SUB-01、CL-SUB-02、CL-SUB-03、
  CL-2D-01、CL-INFO-01、BYS-SOLO-01、BYS-2D-01、BYS-INFO-01、BYS-CONFLICT-01、WGS-3D-01、
  WGS-INFO-01、WGS-BUDGET-01、EDGE-MISS-01、EDGE-FOLLOW-01、EDGE-UNSUP-01、EDGE-NOMATCH-01；
  分类计数：`info_only` 3、`budget_constraint` 2、`sub_area_scope` 2、`multi_day_fallback` 2，
  `single_destination` / `time_budget` / `missing_feature_data` / `constraint_conflict` /
  `missing_slot` / `multi_turn` / `unsupported_area` / `no_match` 各 1；
- T4.1 **只补数据集与口径，不跑真实模型**（无模型调用）；`results/dev-real-01.json` 是 T2.1 前
  的历史证据，只作存档，不得当作 30 条结论引用；
- 真实模型全量 30 条（含 held-out）由 **T4.2** 执行；held-out **不参与调参**，开发期只看聚合；
- 每条查询超时 **180s**、失败重试 **1 次**；超时/异常/partial 都保留，不删难样本；
- 输出 JSON 只由脚本生成，`eval/results/*.json` 不得手改。

---

## 2. 三步跑起来

工作目录为仓库根，解释器用仓库内 venv：

```powershell
# 第 1 步：只校验 golden set schema，不调用模型（秒级，退出码应为 0）
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split dev --dry-run
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split heldout --dry-run
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split all --dry-run

# 第 2 步：真实跑（T4.2；本次 T4.1 未执行）
$env:P07_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"   # 见 §7 排错
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split dev --out analysis\p07_agent\eval\results\dev-real-02.json

# 第 3 步：跑 schema 单测（标准库 unittest，不装新依赖）
.\.venv\Scripts\python.exe -m unittest analysis.p07_agent.eval.tests.test_eval_schema -q
```

参数：

| 参数 | 说明 |
|---|---|
| `--split dev\|heldout\|all` | 默认 `dev`；当前 dev 选中 20 条、heldout 选中 10 条、all 选中 30 条 |
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
| `raw_status` | agent 原始状态（T2.1 后只会是 `verified/partial/clarify/error`） |
| `status` | 规范四值；无法归一时为 `null`（T4.1 起**没有** `complete` 别名） |
| `status_correct` | `status ∈ expected.status`；未执行或状态为 null 时为 `null` |
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
| `status_counts` | — | 四值计数；`status_other` 统计无法归一的原始状态（T4.1 起不再映射旧值） |
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

## 5. 状态归一（T4.1 起无别名）

T2.1 已落地：`run_agent` 只返回 `verified/partial/clarify/error` 四个值
（`PRODUCT_SPEC.md` §5.1，`src/status.py`）。T4.1 因此**删除**了评测侧临时的
`complete → verified` 别名，只做“四值原样通过、其他一律 None”。

| agent 原始值 | 评测 `status` | `summary` 计数 |
|---|---|---|
| `verified` / `partial` / `clarify` / `error` | 原样保留 | 对应四值计数 +1 |
| `complete`（T2.1 前的旧值） | `null` | `status_other` +1 |
| `reply` / `success` / `working` / 其他未定义值 | `null` | `status_other` +1 |

**四值之外的返回值一律记 `None` / `status_other`，不猜、不映射、不改 agent。**
`normalize_status("complete") is None` 与 `normalize_status("reply") is None`
已写进 `tests/test_eval_schema.py`。别在评测侧恢复任何别名：状态只由后端判定
（`PRODUCT_SPEC.md` §5.5），评测侧只记录。

---

## 6. 如何维护查询

1. golden set 已按 `03_EVAL_SPEC.md` §2.2 定稿 **30 条**；**改 query、改 split、增删条目
   都必须先改 §2.2 并取得人类确认**，不得只改 JSONL；
2. 文件格式：UTF-8 无 BOM，`\n` 换行，**一行一个 JSON 对象**；
3. 必填字段：`id`、`area`、`days`、`persona`、`preferences`、`constraints`、`query`、
   `split`、`expected`（`status/must_include/must_not/evidence_required/max_stops`）、`notes`，
   以及边界字段 `boundary`（bool）/ `boundary_kind`（字符串，非边界为 `""`）；
4. `split` 只能是 `dev` 或 `heldout`，当前必须保持 **20 / 10**；
   `expected.status` 只能取 `verified/partial/clarify/error`；`id` 全局唯一；
5. `max_stops` 口径（Q4 已签字）：带 0–6 岁儿童/老人单日 **≤6**，普通成人单日 **≤8**，
   多日按天数折算；纯信息/澄清类可为 `null`；`CL-FAM-02` 是 D0 冻结种子，保留 8，
   是否收紧见 `REVIEW_T4.1.md` 待确认项；
6. 多轮查询加 `turns`（≥2 条非空字符串，按顺序提交；`query` 保留规范原文）；
7. 加完先跑 `--dry-run`：schema 有错会打印行号与原因并以退出码 2 结束；
8. **held-out 与 dev 严格分开**：开发期不得查看 held-out 明细，T4.2 只在 G4/G5 打开。

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

## 9. 裁定与已知偏差（待人类确认项见 `REVIEW_T4.1.md`）

1. **CL-INFO-01 的 split 裁定（T4.1，2026-11-15，父 Agent）**
   `03_EVAL_SPEC.md` §2.2 原就标 `held-out`；D0 的 10 条种子是全 dev 的阶段性产物。
   30 条按 §2.2 铺开后，只有把该条放 held-out 才能同时满足「§2.2 逐条」与「20/10」，
   因此 `split` 由 `dev` 改为 `heldout`（`query` 未改），裁定与日期已写进该条 `notes`。
   **本条仍列在 `REVIEW_T4.1.md` 请人类最终确认**；开发期不得查看其明细。
2. **held-out 未参与调参**：T4.1 无任何模型调用、无调参；held-out 10 条只构造、不运行。
   T4.2 打开 held-out 前不得用它改 prompt/阈值/规则。
3. **CL-FAM-02 的 `max_stops`**：`03_EVAL_SPEC.md` §2.3 示例写 8，D0 冻结种子保留 8；
   Q4 签字口径是“带 0–6 岁儿童/老人单日 ≤6”。本轮**未静默改**，列为待人类确认是否收紧到 6。
4. **状态别名已删除**：T2.1 落地后评测侧不再有 `complete → verified`；见 §5。
5. **多轮 `query` 含 `→`**：`EDGE-FOLLOW-01` 的 `query` 保留规范原文记号，
   实际提交由 `turns` 累积拼接，见 §3。
6. **半日上限未定义**：Q4 只写“单日”，`BYS-SOLO-01`（0.5 天 / 3 小时）暂按成人单日 8 点，
   已在 `notes` 与 `REVIEW_T4.1.md` 标为待确认口径。
7. **`CL-SUB-02` 孩子年龄未写**：按亲子从严取 6 点（不编造年龄）。
8. **`EDGE-NOMATCH-01` 的期望状态**：按 §2.2「verified/无匹配」记为 `["verified"]`；
   与 `PRODUCT_SPEC.md` §8 的 S2「无匹配 → clarify 或 partial」不同，列为待人类确认项。

---

## 10. 历史真实运行记录（T2.1 前，仅存档）

> 下表是 T0.3 在 **T2.1 落地前**跑的 2 条，当时 agent 返回 `complete`、评测侧用临时别名
> 映射成 `verified`。T4.1 删除别名后该映射不可复现；`results/dev-real-01.json` 原样保留，
> **不得引用为新结论**，30 条真实运行见 T4.2。

命令（退出码 0）：

```powershell
$env:P07_OLLAMA_URL='http://127.0.0.1:11434/api/chat'
.\.venv\Scripts\python.exe analysis\p07_agent\eval\run_eval.py --split dev --limit 2 --out analysis\p07_agent\eval\results\dev-real-01.json
```

- commit：`29d0943`（运行时有未提交的评测目录改动，`meta.git_dirty=true`）
- 模型：`qwen3:8b`；`meta.duration_s=43.672`；结果文件：`results/dev-real-01.json`
- golden set 当时只有 10 条 seed，只跑了前 2 条，剩余 8 条**未跑**（T0.3 时间盒内不跑全量）。

| id | raw_status → status（旧映射） | 耗时 s | 节点 | 段证据 | 结果 |
|---|---|---:|---:|---|---|
| CL-FAM-02 | `complete` → `verified` | 31.797 | 12 | 11/11（100%） | `schema_pass=true`，`status_correct=true`；12 点超过 `max_stops=8` |
| CL-SUB-03 | `partial` → `partial` | 11.797 | 1 | 0 段（单点，coverage=null） | `status_correct=true`；原因 `single_destination`、`sub_area_not_applied` |

summary（由 cases 计算）：`status_correct=2/2`、`schema_pass=2/2`、
`evidence_coverage=11/11`、`route_valid=1/2`、`stop_cap_ok=1/2`、
`partial_rate=1/2`、`latency p50=11.797s / p95=31.797s`。

观察（只记录，不改 agent）：CL-FAM-02 的 `run_agent` 返回 `message` 为空字符串，
但路线/校验正常；另 12 个停留点超过 Q4 人群上限，属 T2.2 要修的问题。

---

## 11. 目录结构

```
analysis/p07_agent/eval/
├─ golden_set.jsonl          # 30 条（20 dev / 10 held-out），query 逐字照抄 03_EVAL_SPEC.md §2.2
├─ run_eval.py               # runner：dry-run / 真实跑 / 指标聚合（T4.1 起无状态别名）
├─ README.md                 # 本文件
├─ REVIEW_T4.1.md            # 30 条逐条人工复核清单 + 机器校验结果 + 待确认项
├─ results/
│  ├─ .gitignore             # 忽略 sessions/ 与 dry-run 骨架
│  └─ dev-real-01.json       # T0.3 历史证据（T2.1 前，脚本生成，勿手改）
└─ tests/
   └─ test_eval_schema.py    # schema/四值/边界/多轮/汇总复算（17 个用例）
```

---

## 12. 禁止

- 手改 `eval/results/*.json` 或 `summary` 数字；
- 改 `golden_set.jsonl` 里的 `query` 文本（一字一句照抄 §2.2）；
- 在评测侧恢复 `complete → verified` 等状态别名；
- 开发期跑或查看 held-out 明细，或拿 held-out 调参；
- 因指标不好看删除查询或把失败改成成功；
- 在 `eval/` 外新增/修改文件（评测只读 `src/`）。
