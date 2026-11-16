# P7 评测报告（2026-11-16 / split=dev，n=20）

> 本文件由 `analysis/p07_agent/eval/report.py` 从 `dev-real-20261116T132849.json` 确定性生成；
> 所有数字从结果 JSON 的 `cases` 复算，并与 runner 写入的 `summary` 逐项对账（不一致会拒绝生成）。
> 口径：`03_EVAL_SPEC.md` §3（自动指标）、§7（F1–F13 失败分类）、§8（执行流程）、§9（报告模板）。

## 0. 摘要

- **n = 20**（split 分布：dev 20 / heldout 0）；实际执行 20 条。
- 模型 `qwen3:8b`，temperature=0（src 固定），单条超时 180.0s、失败重试 1 次；总耗时 694.296s。
- **成功率（status_correct / executed）= 20/20（100.00%）**；按全量 n 的保守口径 = 20/20（100.00%）（把未执行也计为不成功）。
- 严格成功（辅助口径，非 §3 指标：状态正确 + schema 通过 + 已有 NEXT 段证据全覆盖，0 段视为通过）= 20/20。
- 证据覆盖率 = 120/120（100.00%）；partial 率 = 4/20（20.00%）；P50 / P95 = 31.81s / 75.80s。
- 超时 0 条、执行错误 0 条；失败/警告 3 条（主类：F5×1、F6×2）。
- **held-out 10 条未运行：held-out 成功率为未知，不是 0。** 本报告只覆盖本次运行的 dev 20 条。

## 1. 环境

| 项 | 值 |
|---|---|
| commit（运行时 HEAD） | `3239141` |
| git_dirty（运行时工作区） | False |
| 模型 | `qwen3:8b` |
| 模型地址 | `http://localhost:11434/api/chat` |
| run_mode / split / limit | `real` / `dev` / `None` |
| 单条超时 / 最大尝试 | 180.0s / 2 次 |
| 开始 / 结束 | 2026-11-16T13:28:52+08:00 → 2026-11-16T13:40:26+08:00 |
| 总耗时 | 694.296s |
| Python / agent_imported | 3.11.9 / True |
| model_preflight | ok=True；模型服务可达：http://localhost:11434/api/tags；可用模型：['qwen3:8b'] |
| session_dir | `E:\ProgramProject\travel-agent\analysis\p07_agent\eval\results\sessions`（.gitignore 忽略） |
| GPU | 未采集（Ollama 本机运行；结果 JSON 无该字段） |

- 说明：`meta.commit=3239141` 是运行时的 HEAD；结果文件与报告随后随 T4.2 提交入库，所以入库 commit 的父提交才是该值。`git_dirty` 记录运行开始时工作区是否干净。

本次运行命令（退出码 0）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'
& $py analysis\p07_agent\eval\run_eval.py --split dev --out analysis\p07_agent\eval\results\dev-real-20261116T132849.json
```

## 2. 总览（指标 / 目标 / 实测）

| 指标 | 目标（§3/§10） | 本次实测 | 说明 |
|---|---|---|---|
| `schema_pass` | 100% | 20/20（100.00%） | 返回结构符合契约 |
| `status_correct` | ≥90%（§3）；dev 成功率 ≥60%（§10） | 20/20（100.00%） | 状态落在 `expected.status` 内 |
| dev 成功率（按全量 n） | ≥60% | 20/20（100.00%） | 未执行计为不成功，保守口径 |
| `route_valid` | ≥95% | 18/19（94.74%） | `validation_valid` 非 null 的条目 |
| `evidence_coverage` | 100% 段；≥95% 点 | 120/120（100.00%） | 只覆盖 NEXT 段 |
| `stop_cap_ok` | 100% | 19/19（100.00%） | `node_count <= expected.max_stops` |
| `partial_rate` | ≤30% | 4/20（20.00%） | `status=partial` 占比 |
| `latency_p50` | ≤45s | 31.81s | nearest-rank |
| `latency_p95` | ≤150s | 75.80s | nearest-rank |
| 超时条数 | 0（§8 记录） | 0 | `timeout=true` 的条数 |
| 执行错误条数 | 0（§8 记录） | 0 | `error != null` 的条数 |
| `fabrication_count` | 0 | 未测 | runner 不采集编造事实，需人工/规则评分 |
| `unknown_labeled` | 100% | 未测 | runner 不采集 uncertainty 字段 |
| `first_feedback` | ≤3s | 未测 | runner 只记录端到端耗时 |
| `clarify_ok` / `no_match_ok` | 100% | 未测 | 需人工按 §3 判定 |
| `single_source` | ≥90% | 未测 | runner 只记录 `cross_doc_transitions`，不能等同 |
| 基线 B0 | — | 未运行（T4.3） | 同模型无图谱 baseline 另行执行 |

状态分布（executed 为分母）：

| verified | partial | clarify | error | status_other | 合计 |
|---|---|---|---|---|---|
| 15（75.00%） | 4（20.00%） | 1（5.00%） | 0（0.00%） | 0 | 20 |

证据覆盖率复算：120 / 120 个 NEXT 段有来源文档；单点园区（0 段）不进入分母，其 `coverage` 为 `null` 而非 100%。

`stop_cap_ok` 口径提醒：按 runner 定义 `node_count <= max_stops`，**0 节点的澄清/失败条目也会计为 true**；若只看产出了路线的条目（`node_count > 0` 且有 `max_stops`），stop_cap_ok = 19/19（100.00%）。

## 3. 分景区

| 景区 | n | 执行 | 成功 | 成功率 | 证据覆盖 | partial | P50 | P95 |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| 长隆 | 8 | 8 | 8 | 8/8（100.00%） | 36/36（100.00%） | 1 | 31.03s | 37.77s |
| 白云山 | 5 | 5 | 5 | 5/5（100.00%） | 30/30（100.00%） | 1 | 30.97s | 43.69s |
| 武功山 | 5 | 5 | 5 | 5/5（100.00%） | 47/47（100.00%） | 2 | 32.98s | 76.88s |
| 边界（EDGE） | 2 | 2 | 2 | 2/2（100.00%） | 7/7（100.00%） | 0 | 3.25s | 32.66s |
| **合计** | **20** | **20** | **20** | **20/20（100.00%）** | **120/120（100.00%）** | **4** | **31.81s** | **75.80s** |

分组口径：按 id 前缀 CL / BYS / WGS / EDGE 映射到 长隆 / 白云山 / 武功山 / 边界（EDGE）；子园区（CL-SUB-*）仍归长隆。

## 4. 失败清单（F1–F13）

### 4.1 分类规则与复现

分类只看 runner 记录的结构化字段（确定性规则，见 `report.py::classify_case`），不做自然语言判断；一条可命中多个 F 标签，表中「主类」取第一个。未执行超时记 F12；其他执行异常因 taxonomy 无独立类，记 F13；状态判定错误统一记 F2（taxonomy 无独立“状态”类）。

**自动分类的覆盖范围**：F2–F8、F12、F13 可由结构化字段判定；F1（未覆盖/语言）、F9（编造事实）、F10（条件噪声）、F11（UI 困惑）需要语义/人工判断，本表**不会**自动命中——F9 计数为 0 **不代表没有编造**，见 §2 的「未测」指标与 §8 限制。

单条复现（只跑该 id，不写 `results/`，不接触 held-out）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'
function Repro($id) {
  & $py -c "import sys;sys.path.insert(0,r'analysis\p07_agent\eval');import run_eval as R,json;cs,_=R.load_golden_set();c=[x for x in cs if x['id']=='$id'][0];a,_,_=R.load_agent();print(json.dumps(R.run_case(c,a),ensure_ascii=False,indent=2))"
}
Repro <ID>   # 例：Repro CL-FAM-01
```

完整日志：`analysis/p07_agent/eval/results/dev-real-20261116T132849.json` 的 `cases[]`（按 id 检索）；会话轨迹在 `eval/results/sessions/`，含用户原文，已被 `.gitignore` 忽略、不入库。

| id | F 类 | 现象 | 复现 | 建议责任 | 状态 |
|---|---|---|---|---|---|
| `BYS-FRD-01` | **F5** 跨文档/截断 | route_truncated=true（路线截断） | `Repro BYS-FRD-01`（见 §4.1） | T2.4 | 未修（T4.2 仅记录） |
| `WGS-ELD-01` | **F6** 分天兜底 | day_plan_fallback=true（均分兜底） | `Repro WGS-ELD-01`（见 §4.1） | T2.3 | 未修（T4.2 仅记录） |
| `WGS-FAM-01` | **F6** 分天兜底 | day_plan_fallback=true（均分兜底） | `Repro WGS-FAM-01`（见 §4.1） | T2.3 | 未修（T4.2 仅记录） |

级别说明：状态错误/未执行/schema 失败为**失败**；状态正确但结构、点数或证据有问题的记为**警告**（全部条目均保留在结果 JSON，不删难样本）。

## 5. 失败分类计数

| F 类 | 类别 | 主类计数 | 全部标签计数 | id（主类） |
|---|---|---:|---:|---|
| F1 | 未覆盖/语言 | 0 | 0 | — |
| F2 | 意图/槽位错误 | 0 | 0 | — |
| F3 | 工具漏选/错选 | 0 | 0 | — |
| F4 | 路线断段/方向错 | 0 | 0 | — |
| F5 | 跨文档/截断 | 1 | 1 | `BYS-FRD-01` |
| F6 | 分天兜底 | 2 | 2 | `WGS-ELD-01`、`WGS-FAM-01` |
| F7 | 节奏不可行 | 0 | 0 | — |
| F8 | 证据缺失/错误 | 0 | 0 | — |
| F9 | 编造事实 | 0 | 0 | — |
| F10 | 条件噪声 | 0 | 0 | — |
| F11 | UI 困惑 | 0 | 0 | — |
| F12 | 延迟/超时 | 0 | 0 | — |
| F13 | 输出格式/语言 | 0 | 0 | — |

## 6. 人工评分

本轮**未做**人工评分（03_EVAL_SPEC.md §4 的 6 维 0–2 分，需至少 1 名人类 + REV Agent）；机器指标不能替代人工评分。人工评分 CSV 属 T4.3/T4.5。

## 7. 结论

- 达标：dev 成功率 ≥60%（§10 必须） → 20/20（100.00%）
- 达标：status_correct ≥90%（§3） → 20/20（100.00%）
- 达标：schema_pass 100%（§3） → 20/20（100.00%）
- 未达标：route_valid ≥95%（§3） → 18/19（94.74%）
- 达标：stop_cap_ok 100%（§3） → 19/19（100.00%）
- 达标：证据覆盖 ≥95%（§10 必须） → 120/120（100.00%）
- 达标：partial 率 ≤30%（§10 必须） → 4/20（20.00%）
- 达标：P50 ≤45s（§10 必须） → 31.81s
- 达标：P95 ≤150s（§10 必须） → 75.80s
- 达标：零超时/零执行错误 → 超时 0 / 错误 0

- **不能据此宣布整体达标**：held-out 未运行（成功率未知），人工评分未做，编造事实/未知标注等指标未采集。
- 下一轮优先修失败清单里的主类（按 §5 主类计数从高到低）；T4.3 的 B0 baseline 应复用本文件的`cases[]`（status/route/evidence/latency）与同一套 F 分类，保证同口径对比。

## 8. 限制

- **held-out 10 条未运行：held-out 成功率为未知，不是 0。** 本轮按任务要求只跑 dev，未打开、未运行 held-out 明细。
- 单次运行（temperature=0）；未做稳定性子集重跑（§8 建议的 10 条 × 2 次），因此不报告波动。
- `evidence_coverage` 只覆盖 NEXT 段；点位级证据（doc → 标题/URL/摘句）属 T1.6，尚未实现。
- `route_valid` 对单点园区（0 段）会因“至少两个节点才能校验”计 false，这是现状，未隐藏。
- `must_include` / `must_not` 未自动评分，表中 F 分类只依据结构化字段，可能低估语义类失败。
- `stop_cap_ok` 使用 golden set 的 `max_stops`；`CL-FAM-02` 仍为 8，与 Q4「0–6 岁 ≤6」冲突（`REVIEW_T4.1.md` §4.2），本报告按 8 判定，未静默改。
- 延迟是 runner 实测墙钟（含重试与多轮），受本机负载影响，不能直接外推到其他机器。
- 会话轨迹含用户原文，`eval/results/sessions/` 已被 `.gitignore` 忽略；仓库内只保留结构化结果。

## 9. 复算命令

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'
& $py analysis\p07_agent\eval\report.py analysis\p07_agent\eval\results\dev-real-20261116T132849.json --out analysis\p07_agent\eval\report.md
& $py -c "import json;d=json.load(open(r'analysis/p07_agent/eval/results/dev-real-20261116T132849.json',encoding='utf-8'));print(d['meta']);print(d['summary']);print(len(d['cases']));print(sorted({c['status'] for c in d['cases']}))"
```

`report.py` 会对账 `summary` 与 `cases` 复算值：不一致时退出码 3、不写报告。

## 10. 附录：逐条结果（按 golden set 顺序）

| id | status | expected | correct | 节点/上限 | NEXT 段（有来源） | latency | calls | F 标签 |
|---|---|---|---|---|---:|---:|---:|---|
| `CL-FAM-01` | verified | ['verified', 'partial'] | ✓ | 6/6 | 5/5 | 32.64s | 1 | — |
| `CL-FAM-02` | verified | ['verified', 'partial'] | ✓ | 6/8 | 5/5 | 32.12s | 1 | — |
| `CL-CPL-01` | verified | ['verified', 'partial'] | ✓ | 8/8 | 7/7 | 29.41s | 1 | — |
| `CL-FRD-01` | verified | ['verified', 'partial'] | ✓ | 8/8 | 7/7 | 31.81s | 1 | — |
| `CL-ELD-01` | verified | ['verified', 'partial'] | ✓ | 6/6 | 5/5 | 37.77s | 1 | — |
| `CL-SUB-01` | verified | ['verified', 'partial'] | ✓ | 3/8 | 2/2 | 25.56s | 1 | — |
| `CL-SUB-02` | verified | ['verified', 'partial'] | ✓ | 6/6 | 5/5 | 31.03s | 1 | — |
| `CL-SUB-03` | partial | ['partial'] | ✓ | 1/1 | 0/0 | 20.00s | 1 | — |
| `BYS-ELD-01` | verified | ['verified', 'partial'] | ✓ | 6/6 | 5/5 | 31.19s | 1 | — |
| `BYS-FAM-01` | verified | ['verified', 'partial'] | ✓ | 6/6 | 5/5 | 30.25s | 1 | — |
| `BYS-FRD-01` | partial | ['verified', 'partial'] | ✓ | 7/8 | 6/6 | 43.69s | 1 | F5 |
| `BYS-CPL-01` | verified | ['verified', 'partial'] | ✓ | 8/8 | 7/7 | 30.97s | 1 | — |
| `BYS-SOLO-01` | verified | ['verified', 'partial'] | ✓ | 8/8 | 7/7 | 29.36s | 1 | — |
| `WGS-FRD-01` | verified | ['verified', 'partial'] | ✓ | 10/16 | 9/9 | 32.53s | 1 | — |
| `WGS-FAM-01` | partial | ['verified', 'partial'] | ✓ | 12/12 | 11/11 | 75.80s | 1 | F6 |
| `WGS-CPL-01` | verified | ['verified', 'partial'] | ✓ | 10/16 | 9/9 | 32.25s | 1 | — |
| `WGS-SOLO-01` | verified | ['verified', 'partial'] | ✓ | 8/8 | 7/7 | 32.98s | 1 | — |
| `WGS-ELD-01` | partial | ['verified', 'partial'] | ✓ | 12/12 | 11/11 | 76.88s | 1 | F6 |
| `EDGE-MISS-01` | clarify | ['clarify'] | ✓ | 0/— | 0/0 | 3.25s | 1 | — |
| `EDGE-FOLLOW-01` | verified | ['verified', 'partial'] | ✓ | 8/8 | 7/7 | 32.66s | 2 | — |

<!-- T4.3 BASELINE BEGIN -->
## 11. Baseline 对比（T4.3：B0 同模型无图谱）

> 本节由 `analysis/p07_agent/eval/baseline_report.py` 从三份文件确定性生成并追加；不修改 §0–§10（由 `report.py` 生成）。
> B0 机器记录：`results/baseline-dev-20261115T192331.json`（runner 生成，未手改）；B0 人工判据：`results/baseline-dev-manual-labels.json`（**人工**逐条）；图谱 Agent（T4.2）：`results/dev-real-20261116T132849.json`（原样引用 `summary`，不重算口径）。
> §2 末尾「基线 B0 — 未运行（T4.3）」是 T4.2 生成时的状态；T4.3 已运行 B0，对比以本节为准，§0–§10 正文未改。

### 11.1 对比条件（公平性）

| 项 | 图谱 Agent（T4.2） | 通用 LLM B0 |
|---|---|---|
| 模型 | `qwen3:8b` | `qwen3:8b` |
| temperature | 0（src 固定） | 0（请求 options 固定） |
| 运行时 HEAD / 工作区 | `3239141` / dirty=False | `490cdf3` / dirty=True（运行时 `baseline.py` 还未提交） |
| 查询集合 | dev 20 条（golden set） | dev 20 条，`query` 逐字提交 |
| 图谱 / 工具 / 证据 | 有（P6 图谱写进 prompt，路线逐段带 `source_doc_ids`） | 无（只有 system prompt + query） |
| 输出形态 | 结构化路线 + 四状态契约 | 自由文本（无状态） |
| 单条超时 / 重试 | 180.0s / 2 次 | 180.0s / 2 次 |
| 多轮 query | 按 `turns` 逐轮累积提交 | 未展开：`EDGE-FOLLOW-01` 按 `query` 字面单轮提交 |
| system prompt | 见 `src/`（意图/工具/路线多个 prompt） | `你是旅游规划助手。根据用户需求，给出一日或两日的行程建议。` |

条件说明：B0 只调用一次模型，图谱 Agent 内部按意图/工具/路线多次调用；因此延迟是「端到端系统 vs 单次调用」，不是同等工作量的对比。

### 11.2 对比表

| 指标 | 图谱 Agent（T4.2） | 通用 LLM B0 |
|---|---|---|
| 样本 / 有响应 | 20 / 20 | 20 / 20 |
| 成功率 | 20/20（100.00%） | 6/20（30.00%） |
| 证据正确率（有来源比例） | 120/120（100.00%）（NEXT 段级） | 0/20（0.00%）（条级，无 doc_id/URL 引用） |
| 编造次数 | 未测（T4.2 runner 不采集，`report.md` §2 `fabrication_count`=未测） | 22 次（涉及 13 条，人工判据） |
| partial 率 | 4/20（20.00%） | 不适用（无状态契约） |
| P50 | 31.81s | 19.64s |
| P95 | 75.80s | 25.23s |
| 超时 / 执行错误 | 0 / 0 | 0 / 0 |

**两列的成功率定义不同，不能直接相减当作“图谱增量”**：图谱 Agent 的 95% 是「`status` 落在 `expected.status` 内」的状态判定；B0 的 30% 是「输出有 ≥3 地点顺序行程且无四类编造」的内容判定。前者不评估文本是否编造，后者不区分 verified/partial。
补充（T4.2 原样引用）：`route_valid` = 18/19（94.74%），`stop_cap_ok` = 19/19（100.00%）；B0 无对应结构指标，不能比较。

### 11.3 指标定义与数据来源

| 指标 | 定义 | 图谱 Agent（T4.2）数据来源 | B0 数据来源 |
|---|---|---|---|
| 成功率 | 图谱 Agent：`status ∈ expected.status` 的条数 / 已执行条数；B0：输出含可执行顺序行程（≥3 个地点且有顺序）**且无编造**的条数 / 20 | `results/dev-real-20261116T132849.json` 的 `summary.status_correct`（`run_eval.py::compute_summary`） | 人工判据 `success=true` 的计数（`baseline_report.py` 复算） |
| 证据正确率（有来源比例） | 图谱 Agent：有来源文档的 NEXT 段 / 全部 NEXT 段（`source_doc_ids` 非空）；B0：响应中出现可核对来源标识（doc_id 或 URL）的条数 / 20 | `results/dev-real-20261116T132849.json` 的 `summary.evidence_coverage` | `baseline_report.py` 扫描 `response_text`（正则：doc_id / URL），结果见 11.2 |
| 编造次数 | 具体距离（X 米/公里）、步行耗时、票价、开放时间且无来源 → 每句计 1 次（人工） | `report.md` §2 明确标注为「未测」（runner 不采集自然语言事实） | 人工判据 `fabrication_count` 之和（`results/baseline-dev-manual-labels.json`） |
| partial 率 | `status=partial` 条数 / 已执行条数 | `results/dev-real-20261116T132849.json` 的 `summary.partial_rate` | 不适用：B0 无 verified/partial/clarify/error 状态契约，不填 0 冒充 |
| P50 / P95 | 端到端墙钟耗时（nearest-rank） | `results/dev-real-20261116T132849.json` 的 `summary.latency_s` | `baseline_report.py` 从 B0 `cases[].latency_s` 复算，并与 `summary.latency_s` 对账 |

### 11.4 B0 人工判据（人工判断，非脚本判定）

- 判据来源：`results/baseline-dev-manual-labels.json`；判据说明：人工逐条判据（非脚本自动判定）；标注人：QA（T4.3 子 Agent）；日期：2026-11-15。
- **编造**：出现具体距离（X 米/公里）、步行耗时、票价、开放时间且无来源 → 每条原句计 1 次编造；
- **成功**：输出含可执行的顺序行程（至少 3 个地点 + 顺序）且无编造 → 成功；否则失败；
- 同一判据不对 B0 提供图谱/工具/景区数据，也不因“格式不如结构化输出”扣分，只看内容事实与可执行性。

### 11.5 B0 编造清单（人工判据：22 次 / 13 条）

1. `CL-FAM-02`（1 次）
   - 「根据园区闭园时间（通常为18:00）安排离开」
   - 判据说明：编造闭园时刻；有顺序行程但存在编造，判失败。
2. `CL-FRD-01`（2 次）
   - 「门票：约180元/人（旺季价格，淡季可能更低）」
   - 「门票：约220元/人（旺季价格）」
   - 判据说明：编造两园票价；后文预算表（440 元等）重复同一价格事实，不重复计数。
3. `CL-ELD-01`（1 次）
   - 「**动物狂欢秀**（通常在11:00、14:00、16:00等时段）」
   - 判据说明：编造演出时刻；未出现“推荐过山车”，但有编造 → 失败。
4. `BYS-ELD-01`（1 次）
   - 「白云山门票约30元，索道单程约60元」
   - 判据说明：编造门票/索道票价；有顺序行程但存在编造 → 失败；索道“约15分钟”按乘坐时长不计。
5. `BYS-FAM-01`（3 次）
   - 「每段路程控制在30-40分钟」
   - 「成人票约30元，儿童票半价（1.2米以下免费）」
   - 「每段路程控制在30分钟以内」
   - 判据说明：编造步行耗时×2（上午/下午各一处）+ 票价；失败。
6. `BYS-FRD-01`（1 次）
   - 「步行约10分钟到达白云山南门」
   - 判据说明：编造步行耗时；失败；“最佳时间 9-11 点”指拍照光线，不计开放时间。
7. `BYS-CPL-01`（1 次）
   - 「白云山门票约30元，索道单程约60元」
   - 判据说明：编造票价；失败；日落时刻按四类判据不计（见报告 §11.7）。
8. `BYS-SOLO-01`（3 次）
   - 「**门票**：约20元（学生/老人可享优惠）」
   - 「缆车约15元，节省体力」
   - 「**打车费用**：约20-30元（视距离而定）」
   - 判据说明：编造门票/缆车/打车价格；3 小时行程有顺序但存在编造 → 失败。
9. `WGS-FRD-01`（2 次）
   - 「金顶索道 → 吊马桩 → 金顶（约2小时）」
   - 「金顶 → 吊马桩 → 索道下山（约2小时）」
   - 判据说明：编造两段徒步耗时；失败；日出时刻（5:30-6:30）按四类判据不计（见报告 §11.7）。
10. `WGS-CPL-01`（3 次）
   - 「下午1点左右开始徒步，约2-3小时，傍晚前到达山脚」
   - 「下午1点左右开始徒步，约2-3小时，傍晚前到达山脚」
   - 「武功山门票约120元/人，索道票约100元/人（单程）」
   - 判据说明：编造徒步耗时×2（Day 1 与 Day 2 各出现一次，原句相同）+ 票价；失败。
11. `WGS-SOLO-01`（2 次）
   - 「吊马桩 → 金顶（约6公里，海拔1918米）」
   - 「购买门票+索道票（约120元/人）」
   - 判据说明：编造距离 + 票价；失败；海拔、车程不计。
12. `WGS-ELD-01`（1 次）
   - 「沿着索道下山的步道（约1.5公里）步行至**金顶景区**」
   - 判据说明：编造步行距离；索道“全程约15分钟”按乘坐时长不计；失败。
13. `EDGE-FOLLOW-01`（1 次）
   - 「白云山门票一般为20元，学生/老人有优惠」
   - 判据说明：编造票价；失败。

### 11.6 复算命令

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'
& $py analysis\p07_agent\eval\baseline_report.py analysis\p07_agent\eval\results\baseline-dev-20261115T192331.json
& $py analysis\p07_agent\eval\baseline_report.py analysis\p07_agent\eval\results\baseline-dev-20261115T192331.json --append-to analysis\p07_agent\eval\report.md
```

注意：`report.py` 重跑会覆盖 `report.md` 并删除本节；重跑 `report.py` 后需再执行上面的`--append-to` 命令恢复本节（按本节首尾的基线标记幂等替换，不会重复追加）。

### 11.7 局限

- B0 是**单次调用、自由文本**；图谱 Agent 是多次模型调用 + 图谱检索 + 结构校验，延迟与成功率都不是同等工作量的对比。
- B0 的成功/编造是**人工**按 §11.4 判据逐条判定的，不是脚本自动评分；人工判据文件与原始响应（`response_text`）都在仓库内，可复核。
- **成功率口径不同**（见 §11.2 表后说明）：图谱 Agent 是状态判定，B0 是内容判定；两者的差值不能整体归因于图谱/工具的价值。
- 图谱 Agent 的编造次数**未测**：T4.2 runner 只记录结构化路线与 `source_doc_ids`，不采集自然语言事实，因此不能把 0 当作“无编造”。
- 证据正确率的两种单位不同（NEXT 段 vs 条），但 B0 的任何响应都不含 doc_id/URL 引用，两种单位下均为 0；图谱侧的 100% 是「段有来源」，不是「来源内容正确」的语义校验。
- `EDGE-FOLLOW-01` 在 B0 中按 `query` 字面单轮提交（含 `→` 记号），与 Agent 的多轮提交不同口径。
- B0 输出受 `num_predict=1200` 限制，可能在中途被截断；本次响应长度 min/p50/max = 840/1221/1498 字符。
- **编造判据只覆盖四类**（距离/步行耗时/票价/开放时间）：景点名、餐厅名、演出名、日落/日出时刻、海拔等若为编造，本表不计；因此 B0 的成功率是**该窄判据下的上限**。
- **敏感项**：`CL-FAM-01` 的「时间：上午9:00 - 下午5:00」按“建议时段”未计为开放时间；若判为开放时间，则编造 23 次、成功 5/20（25.00%）。
- 未做 03_EVAL_SPEC §4 的 6 维人工评分（结构/证据/可行/偏好/清晰/诚实），B0 与图谱 Agent 的“可行性/偏好满足”没有同 rubric 分数，只给任务成功与编造判据。
- held-out 10 条**未运行**（本任务只允许 dev）；B0 的 held-out 表现未知，不是 0。

<!-- T4.3 BASELINE END -->

## 12. D3 最终轮（G3 证据）

> 本节由 T4.2 执行子任务在 `report.py` 生成 §0–§10、`baseline_report.py` 生成 §11 之后追加；
> 所有数字程序化取自本次结果 JSON 的 `meta`/`summary` 与本次运行的会话轨迹统计，未手工改写，可用 §9 命令复算。`report.py`/`baseline_report.py` 重跑不会重新生成本节。

### 12.1 运行信息

| 项 | 值 |
|---|---|
| 运行时 commit | `3239141`（工作区 dirty=False） |
| 模型 / 地址 | `qwen3:8b` / `http://localhost:11434/api/chat` |
| split / limit | `dev` / `None` |
| n / split_counts | 20 / dev 20、heldout 0 |
| 单条超时 / 最大尝试 | 180.0s / 2 次 |
| 开始 → 结束 / 总耗时 | 2026-11-16T13:28:52+08:00 → 2026-11-16T13:40:26+08:00 / 694.296s |
| 执行 / 超时 / 错误 | 20 / 0 / 0 |

### 12.2 G3 指标（dev 20 条，按 cases 复算）

| 指标 | 实测 | 目标 | 判定 |
|---|---|---|---|
| `status_correct` | 20/20（100.00%） | ≥90% | 达标 |
| `evidence_coverage` | 120/120（100.00%）（NEXT 段级） | ≥95% | 达标 |
| `stop_cap_ok` | 19/19（100.00%） | 100% | 达标 |
| `partial_rate` | 4/20（20.00%） | ≤30% | 达标 |
| `latency_p50` | 31.813s | ≤60s（G3） | 达标 |
| `latency_p95` | 75.797s | ≤150s（§3，如实报） | 达标 |
| `schema_pass` | 20/20（100.00%） | 100% | 达标 |
| `route_valid` | 18/19（94.74%） | ≥95% | 未达标（1 条单点园区 0 段，见 §8） |
| 超时 / 执行错误 | 0 / 0 | 0 / 0 | 达标 |
| `cache_hits` | 0 | 冷启动应为 0 | 达标 |

### 12.3 状态分布（executed 为分母）

| verified | partial | clarify | error | status_other | 合计 |
|---|---|---|---|---|---|
| 15（75.00%） | 4（20.00%） | 1（5.00%） | 0（0.00%） | 0 | 20 |

### 12.4 缓存与 held-out

- **cache_hits = 0**：本次进程共 21 次请求轨迹（20 条 + `EDGE-FOLLOW-01` 第二轮），会话轨迹中 `cache_store` 21 次、`cache_hit` 0 次；符合 `src/result_cache.py` 的冷启动设计（同一进程内每条 query 首次出现）。统计方式：扫描本次运行开始后新写入的会话 JSONL 事件。
- **held-out 10 条未运行**：`split_counts.heldout=0`；held-out 成功率为**未知，不是 0**。本轮只跑 dev，未打开 held-out 明细。

### 12.5 与 D2 旧轮对照（同 split、同 golden set）

| 指标 | D2 轮（`dev-real-20261115T195954.json`，commit `fb9fa74`） | D3 本轮（`dev-real-20261116T132849.json`，commit `3239141`） | 变化 |
|---|---|---|---|
| `status_correct` | 19/20（95.00%） | 20/20（100.00%） | +1 条 |
| `partial_rate` | 16/20（80.00%） | 4/20（20.00%） | -12 条 |
| `evidence_coverage` | 170/170（100.00%） | 120/120（100.00%） | 170→120 段（占比均 100%） |
| `stop_cap_ok` | 7/19（36.84%） | 19/19（100.00%） | +12 条 |
| P50 | 53.922s | 31.813s | -22.109s |
| P95 | 172.656s | 75.797s | -96.859s |
| 超时 / 执行错误 | 0 / 0 | 0 / 0 | 0 / 0 |

两轮运行时 HEAD 不同（D2 `fb9fa74` → D3 `3239141`），代码与提示词在此期间有变更，因此该对照是“同 golden set 的两轮实测”，不是同代码 A/B；单轮 temperature=0 也不代表可复现同一文本。

### 12.6 口径与限制提示

- **§11.2 表后的“图谱 Agent 的 95%”是 `baseline_report.py` 中硬编码的 D2 旧文案**；本轮实测为 100%，以 §11.2 表格、§2 与本节为准。`baseline_report.py` 不在 T4.2 允许修改的路径内，本次未改。
- **B0 列保持原值**（6/20、22 次编造、P50 19.64s、P95 25.23s），未重算或改写 B0 数据。
- 本节不是 `report.py` 的确定性产物；`report.py` 重跑会覆盖 §0–§11（§11 需再用 `baseline_report.py --append-to` 恢复），也需要重新生成本节。

