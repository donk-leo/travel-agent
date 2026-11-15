# P7 评测报告（2026-11-15 / split=dev，n=20）

> 本文件由 `analysis/p07_agent/eval/report.py` 从 `dev-real-20261115T184428.json` 确定性生成；
> 所有数字从结果 JSON 的 `cases` 复算，并与 runner 写入的 `summary` 逐项对账（不一致会拒绝生成）。
> 口径：`03_EVAL_SPEC.md` §3（自动指标）、§7（F1–F13 失败分类）、§8（执行流程）、§9（报告模板）。

## 0. 摘要

- **n = 20**（split 分布：dev 20 / heldout 0）；实际执行 20 条。
- 模型 `qwen3:8b`，temperature=0（src 固定），单条超时 180.0s、失败重试 1 次；总耗时 1679.25s。
- **成功率（status_correct / executed）= 19/20（95.00%）**；按全量 n 的保守口径 = 19/20（95.00%）（把未执行也计为不成功）。
- 严格成功（辅助口径，非 §3 指标：状态正确 + schema 通过 + 已有 NEXT 段证据全覆盖，0 段视为通过）= 19/20。
- 证据覆盖率 = 170/170（100.00%）；partial 率 = 4/20（20.00%）；P50 / P95 = 53.00s / 173.01s。
- 超时 0 条、执行错误 0 条；失败/警告 16 条（主类：F2×1、F6×3、F7×12）。
- **held-out 10 条未运行：held-out 成功率为未知，不是 0。** 本报告只覆盖本次运行的 dev 20 条。

## 1. 环境

| 项 | 值 |
|---|---|
| commit（运行时 HEAD） | `512f9df` |
| git_dirty（运行时工作区） | False |
| 模型 | `qwen3:8b` |
| 模型地址 | `http://localhost:11434/api/chat` |
| run_mode / split / limit | `real` / `dev` / `None` |
| 单条超时 / 最大尝试 | 180.0s / 2 次 |
| 开始 / 结束 | 2026-11-15T18:44:28+08:00 → 2026-11-15T19:12:28+08:00 |
| 总耗时 | 1679.25s |
| Python / agent_imported | 3.11.9 / True |
| model_preflight | ok=True；模型服务可达：http://localhost:11434/api/tags；可用模型：['qwen3:8b'] |
| session_dir | `E:\ProgramProject\travel-agent\analysis\p07_agent\eval\results\sessions`（.gitignore 忽略） |
| GPU | 未采集（Ollama 本机运行；结果 JSON 无该字段） |

- 说明：`meta.commit=512f9df` 是运行时的 HEAD；结果文件与报告随后随 T4.2 提交入库，所以入库 commit 的父提交才是该值。`git_dirty` 记录运行开始时工作区是否干净。

本次运行命令（退出码 0）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'
& $py analysis\p07_agent\eval\run_eval.py --split dev --out analysis\p07_agent\eval\results\dev-real-20261115T184428.json
```

## 2. 总览（指标 / 目标 / 实测）

| 指标 | 目标（§3/§10） | 本次实测 | 说明 |
|---|---|---|---|
| `schema_pass` | 100% | 20/20（100.00%） | 返回结构符合契约 |
| `status_correct` | ≥90%（§3）；dev 成功率 ≥60%（§10） | 19/20（95.00%） | 状态落在 `expected.status` 内 |
| dev 成功率（按全量 n） | ≥60% | 19/20（95.00%） | 未执行计为不成功，保守口径 |
| `route_valid` | ≥95% | 17/18（94.44%） | `validation_valid` 非 null 的条目 |
| `evidence_coverage` | 100% 段；≥95% 点 | 170/170（100.00%） | 只覆盖 NEXT 段 |
| `stop_cap_ok` | 100% | 7/19（36.84%） | `node_count <= expected.max_stops` |
| `partial_rate` | ≤30% | 4/20（20.00%） | `status=partial` 占比 |
| `latency_p50` | ≤45s | 53.00s | nearest-rank |
| `latency_p95` | ≤150s | 173.01s | nearest-rank |
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
| 14（70.00%） | 4（20.00%） | 2（10.00%） | 0（0.00%） | 0 | 20 |

证据覆盖率复算：170 / 170 个 NEXT 段有来源文档；单点园区（0 段）不进入分母，其 `coverage` 为 `null` 而非 100%。

`stop_cap_ok` 口径提醒：按 runner 定义 `node_count <= max_stops`，**0 节点的澄清/失败条目也会计为 true**；若只看产出了路线的条目（`node_count > 0` 且有 `max_stops`），stop_cap_ok = 6/18（33.33%）。

## 3. 分景区

| 景区 | n | 执行 | 成功 | 成功率 | 证据覆盖 | partial | P50 | P95 |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| 长隆 | 8 | 8 | 8 | 8/8（100.00%） | 68/68（100.00%） | 1 | 50.59s | 99.50s |
| 白云山 | 5 | 5 | 4 | 4/5（80.00%） | 42/42（100.00%） | 0 | 170.78s | 173.33s |
| 武功山 | 5 | 5 | 5 | 5/5（100.00%） | 51/51（100.00%） | 3 | 151.31s | 164.00s |
| 边界（EDGE） | 2 | 2 | 2 | 2/2（100.00%） | 9/9（100.00%） | 0 | 6.58s | 77.22s |
| **合计** | **20** | **20** | **19** | **19/20（95.00%）** | **170/170（100.00%）** | **4** | **53.00s** | **173.01s** |

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

完整日志：`analysis/p07_agent/eval/results/dev-real-20261115T184428.json` 的 `cases[]`（按 id 检索）；会话轨迹在 `eval/results/sessions/`，含用户原文，已被 `.gitignore` 忽略、不入库。

| id | F 类 | 现象 | 复现 | 建议责任 | 状态 |
|---|---|---|---|---|---|
| `BYS-SOLO-01` | **F2** 意图/槽位错误（含 F3） | status=clarify，期望=['verified', 'partial']；no_route_nodes（规划请求未产出路线） | `Repro BYS-SOLO-01`（见 §4.1） | T2.6 | 未修（T4.2 仅记录） |
| `CL-CPL-01` | **F7** 节奏不可行 | 路线 12 点 > max_stops=8 | `Repro CL-CPL-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `CL-ELD-01` | **F7** 节奏不可行 | 路线 12 点 > max_stops=6 | `Repro CL-ELD-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `CL-FAM-01` | **F7** 节奏不可行 | 路线 12 点 > max_stops=6 | `Repro CL-FAM-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `CL-FAM-02` | **F7** 节奏不可行 | 路线 12 点 > max_stops=8 | `Repro CL-FAM-02`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `CL-FRD-01` | **F7** 节奏不可行 | 路线 12 点 > max_stops=8 | `Repro CL-FRD-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `CL-SUB-02` | **F7** 节奏不可行 | 路线 12 点 > max_stops=6 | `Repro CL-SUB-02`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `BYS-CPL-01` | **F7** 节奏不可行 | 路线 12 点 > max_stops=8 | `Repro BYS-CPL-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `BYS-ELD-01` | **F7** 节奏不可行 | 路线 10 点 > max_stops=6 | `Repro BYS-ELD-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `BYS-FAM-01` | **F7** 节奏不可行 | 路线 12 点 > max_stops=6 | `Repro BYS-FAM-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `BYS-FRD-01` | **F7** 节奏不可行 | 路线 12 点 > max_stops=8 | `Repro BYS-FRD-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `WGS-ELD-01` | **F6** 分天兜底 | day_plan_fallback=true（均分兜底） | `Repro WGS-ELD-01`（见 §4.1） | T2.3 | 未修（T4.2 仅记录） |
| `WGS-FAM-01` | **F6** 分天兜底 | day_plan_fallback=true（均分兜底） | `Repro WGS-FAM-01`（见 §4.1） | T2.3 | 未修（T4.2 仅记录） |
| `WGS-FRD-01` | **F6** 分天兜底 | day_plan_fallback=true（均分兜底） | `Repro WGS-FRD-01`（见 §4.1） | T2.3 | 未修（T4.2 仅记录） |
| `WGS-SOLO-01` | **F7** 节奏不可行 | 路线 10 点 > max_stops=8 | `Repro WGS-SOLO-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |
| `EDGE-FOLLOW-01` | **F7** 节奏不可行 | 路线 10 点 > max_stops=8 | `Repro EDGE-FOLLOW-01`（见 §4.1） | T2.2 | 未修（T4.2 仅记录） |

级别说明：状态错误/未执行/schema 失败为**失败**；状态正确但结构、点数或证据有问题的记为**警告**（全部条目均保留在结果 JSON，不删难样本）。

## 5. 失败分类计数

| F 类 | 类别 | 主类计数 | 全部标签计数 | id（主类） |
|---|---|---:|---:|---|
| F1 | 未覆盖/语言 | 0 | 0 | — |
| F2 | 意图/槽位错误 | 1 | 1 | `BYS-SOLO-01` |
| F3 | 工具漏选/错选 | 0 | 1 | — |
| F4 | 路线断段/方向错 | 0 | 0 | — |
| F5 | 跨文档/截断 | 0 | 0 | — |
| F6 | 分天兜底 | 3 | 3 | `WGS-ELD-01`、`WGS-FAM-01`、`WGS-FRD-01` |
| F7 | 节奏不可行 | 12 | 12 | `CL-CPL-01`、`CL-ELD-01`、`CL-FAM-01`、`CL-FAM-02`、`CL-FRD-01`、`CL-SUB-02`、`BYS-CPL-01`、`BYS-ELD-01`、`BYS-FAM-01`、`BYS-FRD-01`、`WGS-SOLO-01`、`EDGE-FOLLOW-01` |
| F8 | 证据缺失/错误 | 0 | 0 | — |
| F9 | 编造事实 | 0 | 0 | — |
| F10 | 条件噪声 | 0 | 0 | — |
| F11 | UI 困惑 | 0 | 0 | — |
| F12 | 延迟/超时 | 0 | 0 | — |
| F13 | 输出格式/语言 | 0 | 0 | — |

## 6. 人工评分

本轮**未做**人工评分（03_EVAL_SPEC.md §4 的 6 维 0–2 分，需至少 1 名人类 + REV Agent）；机器指标不能替代人工评分。人工评分 CSV 属 T4.3/T4.5。

## 7. 结论

- 达标：dev 成功率 ≥60%（§10 必须） → 19/20（95.00%）
- 达标：status_correct ≥90%（§3） → 19/20（95.00%）
- 达标：schema_pass 100%（§3） → 20/20（100.00%）
- 未达标：route_valid ≥95%（§3） → 17/18（94.44%）
- 未达标：stop_cap_ok 100%（§3） → 7/19（36.84%）
- 达标：证据覆盖 ≥95%（§10 必须） → 170/170（100.00%）
- 达标：partial 率 ≤30%（§10 必须） → 4/20（20.00%）
- 未达标：P50 ≤45s（§10 必须） → 53.00s
- 未达标：P95 ≤150s（§10 必须） → 173.01s
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
- **接近超时**：`BYS-FAM-01` 173.01s、`BYS-FRD-01` 173.33s、`BYS-CPL-01` 170.78s、`WGS-FRD-01` 164.00s 已达到单条超时阈值的 90% 以上；本次均在第 1 次尝试返回、未触发重试，但稳定性风险高（T2.7 性能）。
- 试跑 1 条（CL-FAM-01）用于确认链路，其 `dev-real-smoke.json` 已删除，**未计入**本报告；本报告只来自一次 dev 全量运行。
- 会话轨迹含用户原文，`eval/results/sessions/` 已被 `.gitignore` 忽略；仓库内只保留结构化结果。

## 9. 复算命令

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'
& $py analysis\p07_agent\eval\report.py analysis\p07_agent\eval\results\dev-real-20261115T184428.json --out analysis\p07_agent\eval\report.md
& $py -c "import json;d=json.load(open(r'analysis/p07_agent/eval/results/dev-real-20261115T184428.json',encoding='utf-8'));print(d['meta']);print(d['summary']);print(len(d['cases']));print(sorted({c['status'] for c in d['cases']}))"
```

`report.py` 会对账 `summary` 与 `cases` 复算值：不一致时退出码 3、不写报告。

## 10. 附录：逐条结果（按 golden set 顺序）

| id | status | expected | correct | 节点/上限 | NEXT 段（有来源） | latency | calls | F 标签 |
|---|---|---|---|---|---:|---:|---:|---|
| `CL-FAM-01` | verified | ['verified', 'partial'] | ✓ | 12/6 | 11/11 | 51.91s | 1 | F7 |
| `CL-FAM-02` | verified | ['verified', 'partial'] | ✓ | 12/8 | 11/11 | 51.38s | 1 | F7 |
| `CL-CPL-01` | verified | ['verified', 'partial'] | ✓ | 12/8 | 11/11 | 50.59s | 1 | F7 |
| `CL-FRD-01` | verified | ['verified', 'partial'] | ✓ | 12/8 | 11/11 | 49.33s | 1 | F7 |
| `CL-ELD-01` | verified | ['verified', 'partial'] | ✓ | 12/6 | 11/11 | 53.50s | 1 | F7 |
| `CL-SUB-01` | verified | ['verified', 'partial'] | ✓ | 3/8 | 2/2 | 39.03s | 1 | — |
| `CL-SUB-02` | verified | ['verified', 'partial'] | ✓ | 12/6 | 11/11 | 99.50s | 1 | F7 |
| `CL-SUB-03` | partial | ['partial'] | ✓ | 1/1 | 0/0 | 27.22s | 1 | — |
| `BYS-ELD-01` | verified | ['verified', 'partial'] | ✓ | 10/6 | 9/9 | 72.23s | 1 | F7 |
| `BYS-FAM-01` | verified | ['verified', 'partial'] | ✓ | 12/6 | 11/11 | 173.01s | 1 | F7 |
| `BYS-FRD-01` | verified | ['verified', 'partial'] | ✓ | 12/8 | 11/11 | 173.33s | 1 | F7 |
| `BYS-CPL-01` | verified | ['verified', 'partial'] | ✓ | 12/8 | 11/11 | 170.78s | 1 | F7 |
| `BYS-SOLO-01` | clarify | ['verified', 'partial'] | ✗ | 0/8 | 0/0 | 7.05s | 1 | F2、F3 |
| `WGS-FRD-01` | partial | ['verified', 'partial'] | ✓ | 12/16 | 11/11 | 164.00s | 1 | F6 |
| `WGS-FAM-01` | partial | ['verified', 'partial'] | ✓ | 12/12 | 11/11 | 153.61s | 1 | F6 |
| `WGS-CPL-01` | verified | ['verified', 'partial'] | ✓ | 10/16 | 9/9 | 52.53s | 1 | — |
| `WGS-SOLO-01` | verified | ['verified', 'partial'] | ✓ | 10/8 | 9/9 | 53.00s | 1 | F7 |
| `WGS-ELD-01` | partial | ['verified', 'partial'] | ✓ | 12/12 | 11/11 | 151.31s | 1 | F6 |
| `EDGE-MISS-01` | clarify | ['clarify'] | ✓ | 0/— | 0/0 | 6.58s | 1 | — |
| `EDGE-FOLLOW-01` | verified | ['verified', 'partial'] | ✓ | 10/8 | 9/9 | 77.22s | 2 | F7 |

