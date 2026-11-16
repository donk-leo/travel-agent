# P7 失败分类（T4.5 / dev20 D4 起点）

> **口径**：`03_EVAL_SPEC.md` §7（F1–F13 固定 taxonomy）、§3（自动指标）、§9（报告模板第 4 节）。
> **本文件只做分类、追溯、复现**：不改 agent 行为、不改评测口径、不改 golden set、
> 不改 `run_eval.py` / `report.py` / `baseline*.py` / `results/*.json`、不删任何样本。
> 失败分类全部来自真实 `cases`（`dev-real-20261116T132849.json`），不是人工编造的现象。

## 0. 环境与输入（只读）

| 项 | 值 |
|---|---|
| 结果文件 | `analysis/p07_agent/eval/results/dev-real-20261116T132849.json`（已跟踪，未改） |
| 结果文件 sha256 | `71513C5C1E250658B3053656D465941694ECC640B43EC07EEDD5106B099380A2` |
| 本任务基线（D4 起点 HEAD） | `f35bc7a431293dcadf08d0d9139724f8669fcc39` |
| 结果 JSON 记录的运行时 commit | `3239141`（`f35bc7a` 的祖先：D3 最后一轮 T4.2 跑在提交前） |
| 模型 / 模型地址 | `qwen3:8b` / `http://localhost:11434/api/chat` |
| 运行窗口（`meta`） | `2026-11-16T13:28:52+08:00` → `2026-11-16T13:40:26+08:00`，`duration_s=694.296` |
| split / limit / n | `dev` / `null` / **20** |
| 单条超时 / 最大尝试 | `180.0s` / `2` |
| `model_preflight` | `ok=true`（模型服务可达，`qwen3:8b` 在列） |
| 本文件生成时间 | 2026-11-16T13:59:57+08:00 |

### 0.1 summary（逐项取自结果 JSON，未手写成功率）

| summary 字段 | 值 |
|---|---|
| `status_counts` | verified 15 / **partial 4** / **clarify 1** / error 0；`status_other=0` |
| `status_correct` | 20/20（100%），分母=`executed` |
| `schema_pass` | 20/20（100%） |
| `evidence_coverage` | 120/120（100%），只覆盖 NEXT 段 |
| `route_valid` | 18/19（94.74%），分母=`validation_valid` 非 null 的 executed 条数 |
| `stop_cap_ok` | 19/19（100%） |
| `partial_rate` | 4/20（20%） |
| `latency_s` | `n=20`，P50 **31.813s**，P95 **75.797s**（nearest-rank） |
| `n_timeout_cases` / `n_error_cases` | 0 / 0 |
| `cache_hits` | 0（按 `report.md` §12 的统计口径：本轮会话轨迹 `cache_store` 21 次、`cache_hit` 0 次） |

**关键**：`status_correct=20/20` 与「5 条非 verified」并不矛盾——这 5 条的
`status` 都落在 `expected.status` 内，属于**预期内结果**（单点 partial、缺槽位 clarify）
或**状态正确但结构降级**（截断/均分兜底）。把它们一律叫「失败」会歪曲评测结论。

## 1. 结论先行

- 非 verified 用例 **5 条**（`CL-SUB-03`、`BYS-FRD-01`、`WGS-FAM-01`、`WGS-ELD-01`、`EDGE-MISS-01`），
  与 `cases` 逐条核对一致；**0 条未分类**。
- **P0 = 0**：没有 `status_correct=false`、没有 `schema_pass=false`、没有 timeout/error、
  证据覆盖 100%、stop_cap 100%；5 条全部落在 golden `expected.status` 内。
- 主类分布：**F2 1、F4 1、F5 1、F6 2**，其余 F1/F3/F7–F13 均为 0（见 §2.2）。
- 5 条**都不是被隐藏的样本**：结果文件仍为 **20 条**（`n_cases=20`、`split_counts.dev=20`），
  `golden_set.jsonl` 仍为 **30 条（20 dev + 10 held-out）**，未删、未改、未降级。
- 没有把 partial 改写成 verified，也没有把 expected 内结果冒充失败。

## 2. 分类口径与两条「补标签」规则

### 2.1 自动分类（`report.classify_case`，只读复用）

自动分类只读 runner 记录的结构化字段，确定性、可复算：

| case | `report.classify_case` 输出 | 说明 |
|---|---|---|
| `BYS-FRD-01` | `[('F5', 'route_truncated=true（路线截断）')]` | 命中 F5 分支 |
| `WGS-FAM-01` | `[('F6', 'day_plan_fallback=true（均分兜底）')]` | 命中 F6 分支 |
| `WGS-ELD-01` | `[('F6', 'day_plan_fallback=true（均分兜底）')]` | 命中 F6 分支 |
| `CL-SUB-03` | `[]` | `single_destination` 分支带 `max_stops>1` 守卫，而本条 `max_stops=1` |
| `EDGE-MISS-01` | `[]` | `no_route_nodes → F3` 分支显式排除 `expected` 含 `clarify` 的条 |

复算命令（离线，不调用模型）：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,r'analysis\p07_agent\eval');import report,json;d=json.load(open(r'analysis\p07_agent\eval\results\dev-real-20261116T132849.json',encoding='utf-8'));[print(c['id'],report.dedupe(report.classify_case(c))) for c in d['cases'] if c['status']!='verified']"
```

`report.py` 是**冻结项**（本任务白名单外，禁改）。因此 `CL-SUB-03` / `EDGE-MISS-01`
的 F 标签由 T4.5 在**文档与测试侧**给出，规则同样是确定性的：

### 2.2 T4.5 补标签规则（不是改分类器）

| 规则 | 条件（全部来自 `cases` 与 golden 字段） | 标签 | 语义 |
|---|---|---|---|
| A | `status=partial` 且 `expected.status==["partial"]` 且 `route.single_destination=true` 且 `node_count=1` 且 `max_stops=1` | **F4** | 单点园区未成路线（taxonomy：路线断段/不成线）；**预期内**，不是缺陷 |
| B | `status=clarify` 且 `expected.status==["clarify"]` 且 `route_reasons` 含 `no_route_nodes` 且 golden `boundary_kind=missing_slot`（golden 侧佐证；分类判定本身不读该字段） | **F2** | 槽位/意图路径标签：缺景区 → 追问；**不是缺陷**，clarify 正是 golden 期望 |

这两条规则只补「taxonomy 归类」，**不改变** `status`、`summary` 或任何评分：
`report.classify_case` 的返回值在文档中照实写出（`[]`），不伪装成它输出了 F4/F2。

### 2.3 主类计数（T4.5 口径，5 条全部分类）

| F 类 | 类别（§7） | 主类计数 | id |
|---|---|---:|---|
| F1 | 未覆盖/语言 | 0 | — |
| F2 | 意图/槽位错误 | 1 | `EDGE-MISS-01`（预期内缺槽位路径标签） |
| F3 | 工具漏选/错选 | 0 | — |
| F4 | 路线断段/方向错 | 1 | `CL-SUB-03`（预期内单点，未成路线） |
| F5 | 跨文档/截断 | 1 | `BYS-FRD-01` |
| F6 | 分天兜底 | 2 | `WGS-FAM-01`、`WGS-ELD-01` |
| F7 | 节奏不可行 | 0 | — |
| F8 | 证据缺失/错误 | 0 | — |
| F9 | 编造事实 | 0 | — |
| F10 | 条件噪声 | 0 | — |
| F11 | UI 困惑 | 0 | — |
| F12 | 延迟/超时 | 0 | — |
| F13 | 输出格式/语言 | 0 | — |
| **合计** | | **5** | **未分类 0** |

> F9/F10/F11 需要语义或人工判断，`classify_case` 不会自动命中；本文件对 5 条非 verified
> 逐条读了 `message` / `uncertainties` / `validation`，**未发现**编造事实或营销话术当作建议的证据。
> 这不等于「F9 全库为 0」：其余 15 条 verified 不在本任务分类对象内。

## 3. 总表（5 条非 verified，逐条一行）

| id | status | expected | F 主类 | 现象（结构化） | 预期内 | 复现命令（见 §5） | 日志 / 证据 | 责任任务 | 修复状态 |
|---|---|---|---|---|---|---|---|---|---|
| `CL-SUB-03` | partial | `["partial"]` | **F4**（auto=`[]`，规则 A） | 1 点 / 0 段；`single_destination`+`sub_area_not_applied`；`validation.valid=false`「至少需要两个节点」 | **是**（golden 期望单点 partial） | `repro_case.py --id CL-SUB-03`；或 `run_eval.py --split dev --limit 8`（第 8 条） | 结果 JSON `cases[CL-SUB-03]`；`sessions/session_fdf86ac9742242d894127dcb356e5072.jsonl` | 无（图谱/数据限制，非 P7 缺陷；上游 P6 无园内 NEXT） | `known/accepted` |
| `BYS-FRD-01` | partial | `["verified","partial"]` | **F5**（auto=`F5`） | 路线在「能仁寺」后缺 NEXT，截断为 7 点可核验前缀；6/6 段有来源；`route_truncated=true` | 状态在 expected 内，但**结构真实降级** | `repro_case.py --id BYS-FRD-01`；或 `--limit 11`（第 11 条） | 结果 JSON `cases[BYS-FRD-01]`；`sessions/session_f829435f5b4c420d8f89296c9dbf0c79.jsonl` | T2.4（沿用 `report.md` §4 既有映射；代码位置 `route_planner.py:604`） | `open P2` |
| `WGS-FAM-01` | partial | `["verified","partial"]` | **F6**（auto=`F6`） | 12 点 / 11 段全部核验通过，但两日按 **6+6 均分**；`day_plan_fallback=true` | 状态在 expected 内，但**结构真实降级** | `repro_case.py --id WGS-FAM-01`；或 `--limit 15`（第 15 条） | 结果 JSON `cases[WGS-FAM-01]`；`sessions/session_a0e0d4db15df4663af15b16a037ec1db.jsonl` | T2.3（分时行程 v2；代码位置 `route_planner.py:657`） | `open P2` |
| `WGS-ELD-01` | partial | `["verified","partial"]` | **F6**（auto=`F6`） | 12 点 / 11 段全部核验通过，但两日按 **6+6 均分**；`day_plan_fallback=true` | 状态在 expected 内，但**结构真实降级** | `repro_case.py --id WGS-ELD-01`；或 `--limit 18`（第 18 条） | 结果 JSON `cases[WGS-ELD-01]`；`sessions/session_cf376ac8e71a4d2fa433aadab2cab4c1.jsonl` | T2.3（分时行程 v2；代码位置 `route_planner.py:657`） | `open P2` |
| `EDGE-MISS-01` | clarify | `["clarify"]` | **F2**（auto=`[]`，规则 B；槽位路径标签，**非缺陷**） | 0 点 / 0 段；`no_route_nodes`；`validation_valid=null`；message「请补充景区名称和游玩天数。」 | **是**（golden 期望 clarify） | `repro_case.py --id EDGE-MISS-01`；或 `--limit 19`（第 19 条） | 结果 JSON `cases[EDGE-MISS-01]`；`sessions/session_ccdbf6894fe94242a1b9e1329d031801.jsonl` | 无（expected 内；文案打磨可归 T3.5，见 §6.3） | `known/accepted` |

**责任任务与修复状态的读法**：本任务禁改 `src/**`，所以状态只会是
`known/accepted`（预期内、按现状接受）或 `open P1/P2`（真实降级、留给后续治理）；
**没有任何一条写「已修复」**。

## 4. 逐条分类

### 4.1 `CL-SUB-03` — F4（预期内单点园区，未成路线）

- **现象**：`status=partial`（`expected=["partial"]`，`status_correct=true`）；
  `route.node_count=1`、`segment_count=0`、`single_destination=true`、
  `validation.valid=false`、`route_reasons=["single_destination","sub_area_not_applied"]`；
  `evidence.segments_total=0`（`coverage=null`，不是 100%）；
  message：「已按子园区「水上乐园」筛选出 1 个地点。「水上乐园」在图谱中没有独立路线连接，只保留该园区地点，供一日行程参考。」
- **根因**：intent 正确识别 `sub_area=水上乐园`，`search_poi` 只返回 1 个该园区地点；
  `validation` 明确「至少需要两个节点才能检查路线连接」。即**图谱没有水上乐园的园内 NEXT 连接**，
  P7 侧按 golden `notes`（「图谱没有园内独立连续路线时应为 partial（单点），不得回退拼其他园区路线」）
  给出单点 partial，行为与期望一致。属**上游数据/图谱限制**，不是 P7 逻辑缺陷。
- **复现**：
  ```powershell
  $env:PYTHONIOENCODING='utf-8'
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id CL-SUB-03 --dry-run   # 不调模型，先验证选条
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id CL-SUB-03             # 真实单条（需模型服务）
  ```
  等价全量复现：`run_eval.py --split dev --limit 8`（本条是 dev 第 8 条，会重跑前 7 条，耗时数分钟）。
- **日志**：结果 JSON 的 `cases[]` 按 id 检索；本轮会话轨迹
  `analysis/p07_agent/eval/results/sessions/session_fdf86ac9742242d894127dcb356e5072.jsonl`
  （含 intent→`sub_area=水上乐园`、`search_poi` 1 点、`validate_route`「至少需要两个节点」、`final_answer=partial`）。
  该目录被 `.gitignore` 忽略、不入库，属本轮本地产物。
- **责任任务**：无（预期内）。若要让它成线，需上游 P6 图谱补「水上乐园」园内 NEXT，
  不属 D4 的 P7 修复范围。
- **修复状态**：`known/accepted`（golden 就是 partial；`G3_GATE.md` §5 第 6 条记为「单点园区 1」）。
- **为什么不改评测口径**：`03_EVAL_SPEC.md` §2.2 对 `CL-SUB-03` 写死「partial（单点）」，
  §2.3 的 `max_stops=1` 也是这条单点期望的一部分。把 `expected` 改成 verified、或把这条删掉，
  都会把「图谱没有园内路线」这一真实限制从指标里抹掉，违反 §1.5「失败也记录」、
  §10「不得改 held-out 或手写指标」与 `AGENTS.md` §9.3「不得为指标好看删除难样本」。

### 4.2 `BYS-FRD-01` — F5（路线截断）

- **现象**：`status=partial`（`expected=["verified","partial"]`，`status_correct=true`）；
  `route.node_count=7`、`segment_count=6`、`validation.valid=true`、`fully_verified=true`、
  `route_truncated=true`、`route_reasons=["route_truncated"]`；
  `evidence=6/6`（100%）；message：「原路线在缺环处被截断，只保留了能够逐段核验的前半段；
  后半段需要调整需求或改用官方路线后重新规划。」
- **根因**：规划出的完整候选在「能仁寺」之后缺 NEXT（`validate_route` 记录
  `missing_connections` 含能仁寺→桃花涧、桃花涧→白云松涛、白云松涛→双溪别墅、
  双溪别墅→山庄旅舍、山庄旅舍→摩星岭）；`repair_route` 两次返回「图谱中没有找到连接两个节点的路径」，
  于是按策略截断到可核验前缀（麓湖公园→…→能仁寺），并以 `route_truncated` 降为 partial。
  即**截断策略是正确降级**，但「只能走前半段」对用户体验是真实损失，仍按 F5 记录。
- **复现**：
  ```powershell
  $env:PYTHONIOENCODING='utf-8'
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id BYS-FRD-01 --dry-run
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id BYS-FRD-01
  ```
  等价全量复现：`run_eval.py --split dev --limit 11`（第 11 条）。
- **日志**：`cases[BYS-FRD-01]`；会话
  `sessions/session_f829435f5b4c420d8f89296c9dbf0c79.jsonl`（含两次 repair 失败与 final route 的
  `uncertainties: 原路线在「能仁寺」之后缺少 NEXT 连接，已截断到可核验前缀。`）。
- **责任任务**：T2.4（沿用 `report.md` §4 的既有映射；`route_truncated` 置位在
  `src/route_planner.py:604`，属备选路线/路线规划范围）。
- **修复状态**：`open P2`（D3 只记录不修；`G3_GATE.md` §5 第 6 条「G4 继续治理」）。
- **为什么不改评测口径**：`expected` 本就允许 partial，状态判定没错；若把 partial 改写成
  verified，就等于把「后半段 5 处缺 NEXT」说成已核验，违反 `PRODUCT_SPEC.md` §5.5
  「不得因看起来顺升级状态」与 `03_EVAL_SPEC.md` §1.4「结构正确不等于行程可行」。

### 4.3 `WGS-FAM-01` — F6（分天均分兜底）

- **现象**：`status=partial`（`expected=["verified","partial"]`，`status_correct=true`）；
  `route.node_count=12`、`segment_count=11`、`validation.valid=true`、`fully_verified=true`、
  `day_plan_fallback=true`、`route_reasons=["day_plan_fallback"]`；
  `evidence=11/11`；`day_plan` 为 **day1=6 / day2=6**；message：「多日行程的天数分组是按节点数均分的
  展示结果，没有校验每日步行强度、住宿点和开放时间；请按实际体力重新分配。」
- **根因**：多日查询下模型输出不合法（会话 `uncertainties` 明确 `JSONDecodeError`），
  系统按单一来源最长连续链生成**确定性兜底路线**（12 点、11 段同源 `WGS-O-05`，连接全部核验通过），
  但分天只能用 `_normalize_day_plan` 的**按节点数均分**（6+6），没有真实日程校验。
  所以路线可信、分天不可信，状态降为 partial。
- **复现**：
  ```powershell
  $env:PYTHONIOENCODING='utf-8'
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id WGS-FAM-01 --dry-run
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id WGS-FAM-01
  ```
  等价全量复现：`run_eval.py --split dev --limit 15`（第 15 条）。
- **日志**：`cases[WGS-FAM-01]`；会话
  `sessions/session_a0e0d4db15df4663af15b16a037ec1db.jsonl`
  （`final_answer.route.proposal.day_plan=[6,6]`、
  `uncertainties: 天数分组按节点数均分…`、`模型输出不合法（JSONDecodeError）…`）。
- **责任任务**：T2.3（分时行程 v2；`route_planner.py:657` 调 `_normalize_day_plan`）。
- **修复状态**：`open P2`（`G3_GATE.md` §5 第 6/7 条：4 条多日/跨文档用例仍走第二次模型请求，
  G4 继续治理）。
- **为什么不改评测口径**：均分不是真实日程，把它写成 verified 等于把「未校验体力/住宿/开放时间」
  包装成「已验证可行」，违反 `PRODUCT_SPEC.md` §5.6「连接核验与行程可行分开」；
  也不该为此收紧 `expected`（golden 已冻结 partial 允许集）。

### 4.4 `WGS-ELD-01` — F6（分天均分兜底）

- **现象**：与 `WGS-FAM-01` 同构：`status=partial`、`node_count=12`、`segment_count=11`、
  `validation.valid=true`、`fully_verified=true`、`day_plan_fallback=true`、
  `route_reasons=["day_plan_fallback"]`；`day_plan=[6,6]`；`evidence=11/11`；
  同一句 message。
- **根因**：同一兜底路径（模型多日输出不合法 → 单一来源最长链兜底 → 按节点数均分 6+6）。
  本条意图为「老人、不徒步、能坐索道吗」，`uncertainties` 记录了「同行人识别为「老人」，
  按单日上限 6 个判断」；但分天仍未校验每日体力/住宿/开放时间，故 partial。
- **复现**：
  ```powershell
  $env:PYTHONIOENCODING='utf-8'
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id WGS-ELD-01 --dry-run
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id WGS-ELD-01
  ```
  等价全量复现：`run_eval.py --split dev --limit 18`（第 18 条）。
- **日志**：`cases[WGS-ELD-01]`；会话
  `sessions/session_cf376ac8e71a4d2fa433aadab2cab4c1.jsonl`。
- **责任任务**：T2.3（同 §4.3）。
- **修复状态**：`open P2`。
- **为什么不改评测口径**：同 §4.3；另外 P95 主要来自这两条（75.797s / 76.875s），
  但**不能靠改超时或删样本压 P95**，`03_EVAL_SPEC.md` §3 要求延迟按实测墙钟记录。

### 4.5 `EDGE-MISS-01` — F2（预期内 clarify；槽位路径标签，非缺陷）

- **现象**：`status=clarify`（`expected=["clarify"]`，`status_correct=true`）；
  `route.node_count=0`、`segment_count=0`、`validation_valid=null`、
  `route_reasons=["no_route_nodes"]`；`partial_reasons=[]`；
  message：「请补充景区名称和游玩天数。」
- **根因**：intent 解析出 `scenic_area=null`、`duration_days=2`、`constraints=["轻松一点"]`；
  fast_decision / decision 均判 `clarify`，理由「缺少景区名称，需要先补充」，
  与 golden `boundary_kind=missing_slot`、`must_include=["景区","天数"]` 一致。
  **这是正确行为**：缺景区时不猜、不直接出行程。
- **F2 的含义**：`03_EVAL_SPEC.md` §7 的 F2 是「意图/槽位错误」。
  本条没有「错误」，F2 只作为**槽位/意图路径的 taxonomy 标签**，说明失败面落在
  「槽位缺失 → 追问」路径上；按结果判**非缺陷、预期内**。不使用 F3 是因为
  `report.classify_case` 对 `expected` 含 clarify 的条显式不打 F3（没有规划请求就没有「工具漏选」）。
- **复现**：
  ```powershell
  $env:PYTHONIOENCODING='utf-8'
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id EDGE-MISS-01 --dry-run
  .\.venv\Scripts\python.exe analysis\p07_agent\eval\repro_case.py --id EDGE-MISS-01
  ```
  等价全量复现：`run_eval.py --split dev --limit 19`（第 19 条）。
- **日志**：`cases[EDGE-MISS-01]`；会话
  `sessions/session_ccdbf6894fe94242a1b9e1329d031801.jsonl`（7 个事件：
  `user_input → input_normalization → intent → fast_decision=clarify → decision=clarify →
  cache_store → final_answer=clarify`）。
- **责任任务**：无（预期内）。文案打磨属可选（见 §6.3），不阻断 G4。
- **修复状态**：`known/accepted`。
- **为什么不改评测口径**：golden 对这条的期望就是 `["clarify"]`；把它判成失败，
  或为了「有路线」而猜景区，都会直接违反 §2.2 的 `must_not`（不得猜景区、不得直接出行程）
  与 §3 的 `clarify_ok=100%` 目标。

## 5. 复现环境与统一命令

`analysis/p07_agent/eval/repro_case.py` 是本任务新增的**只读**单案例工具：
它只从 `golden_set.jsonl` 按 `--id` 选 1 条，单条执行**完全复用** `run_eval.run_case`
（同一 180s 超时、同一重试 1 次、同一字段提取），**不改任何评分逻辑**，默认只打印到 stdout。

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'

# 模型无关：只验证 id 存在、golden 字段可读（不 import agent、不调用模型）
& $py analysis\p07_agent\eval\repro_case.py --id CL-SUB-03 --dry-run

# 真实单条（需本机 Ollama 的 qwen3:8b；口径与全量评测一致）
& $py analysis\p07_agent\eval\repro_case.py --id CL-SUB-03
```

等价的全量重跑方式（会重跑目标之前的所有 dev 用例、耗时数分钟，需模型服务）：

| case | dev 中位置 | 命令 |
|---|---:|---|
| `CL-SUB-03` | 第 8 条 | `run_eval.py --split dev --limit 8` |
| `BYS-FRD-01` | 第 11 条 | `run_eval.py --split dev --limit 11` |
| `WGS-FAM-01` | 第 15 条 | `run_eval.py --split dev --limit 15` |
| `WGS-ELD-01` | 第 18 条 | `run_eval.py --split dev --limit 18` |
| `EDGE-MISS-01` | 第 19 条 | `run_eval.py --split dev --limit 19` |

> 注意：按 §8 禁止事项，`--limit` 重跑**不写进 `results/` 当新评测轮**；本任务未跑任何
> 全量/`--limit` 重跑，也未调用模型。

**本任务实测的复现命令退出码**（2026-11-16T13:59 前后，逐条执行）：

| 命令 | 退出码 | 输出摘要 |
|---|---:|---|
| `repro_case.py --id CL-SUB-03 --dry-run` | 0 | `status=None`、`mode=dry-run`、`executed=false` |
| `repro_case.py --id BYS-FRD-01 --dry-run` | 0 | 同上 |
| `repro_case.py --id WGS-FAM-01 --dry-run` | 0 | 同上 |
| `repro_case.py --id WGS-ELD-01 --dry-run` | 0 | 同上 |
| `repro_case.py --id EDGE-MISS-01 --dry-run` | 0 | 同上 |
| `repro_case.py --id NOPE-99 --dry-run` | 2 | `golden set 里没有 id='NOPE-99'`（负例，证明不会新建条目） |

`--dry-run` 分支不 import agent、不调用模型，可用于任何机器上验证选条与 golden 字段；
真实单条运行需要本机 Ollama，本次未执行（本任务不调用模型）。

### 5.1 会话日志如何定位（不编造）

`results/sessions/` 被 `.gitignore` 忽略、不入库，结果 JSON 也**没有**逐条记录 session id。
本轮定位方法（只读、可复核）：取本轮 `meta` 窗口（13:28:52→13:40:26）内新写入的 21 个
`session_*.jsonl`，读每个文件首行 `user_request`，与 golden dev 20 条顺序对照，
得到**严格单调**的一一映射（20 条各 1 个 + `EDGE-FOLLOW-01` 第 2 轮 1 个 = 21）。
据此引用 §3/§4 的 session 文件名；未引用不存在或无法归属的文件。

## 6. 全局声明与已知限制

### 6.1 0 条未分类

5 条非 verified **全部有 F 主类**（F2×1、F4×1、F5×1、F6×2），**0 条未分类**；
`report.md` §4 当前只展示 3 行（`classify_case` 对两条预期内结果不打标签）——
这是**报告展示层的覆盖缺口**，已在 §2 说明，不是数据缺失，也不是本文件漏分类。

### 6.2 P0 = 0（若发现 P0 只报告、不改 src）

判定依据：`status_correct=20/20`、`schema_pass=20/20`、`timeout=0`、`error=0`、
`evidence=120/120`、`stop_cap=19/19`；5 条非 verified 全部落在 expected 内。
本任务**未发现 P0**，因此**未改 `src/**` 任何文件**；若后续复核认为某条是 P0，
按任务约定只登记证据并停下来等父 Agent / 人类裁决。

### 6.3 已知限制（本任务不修，如实登记）

1. **单点园区缺园内路线**（`CL-SUB-03`）：上游 P6 图谱没有「水上乐园」园内 NEXT；
   P7 已按 golden 给出单点 partial，不虚构连接。要成线需上游数据/图谱补边。
2. **跨文档/截断**（`BYS-FRD-01`）：缺 NEXT 时截断到可核验前缀是正确降级，但用户只能拿到前半段；
   修复需补图谱连接或提供 2–3 条单一来源备选（T2.4），`G3_GATE.md` §5 第 6 条列为 G4 继续治理。
3. **多日均分兜底**（`WGS-FAM-01` / `WGS-ELD-01`）：模型多日输出不合法时走确定性兜底，
   路线同源可核验，但分天只按节点数均分；真实分时/住宿/体力校验属 T2.3。
4. **`report.classify_case` 的展示缺口**：预期内 partial/clarify 不打标签，导致 `report.md`
   的 F4/F2 计数为 0。`report.py` 是冻结项，本任务不改；建议后续任务（T5.3/T6.2 前）
   由人类授权决定是否扩展分类器，而不是在 T4.5 里绕过白名单。
5. **`EDGE-MISS-01` 文案瑕疵（P2 观察，非失败）**：intent 已解析出 `duration_days=2`，
   但 message 仍说「请补充景区名称和游玩天数」。golden `must_include=["景区","天数"]` 仍满足，
   不影响 `status_correct`；若打磨文案可归 T3.5（结果页/澄清话术），不阻断 G4。
6. **会话日志不入库**：`results/sessions/` 被 `.gitignore` 忽略；其他机器复现只能靠 §5 的命令
   重新生成本地日志，不能引用本机 session 文件作为仓库证据。

## 7. 未改动的冻结项（自证）

| 文件 | 本任务操作 |
|---|---|
| `eval/golden_set.jsonl` | 未改（sha256 `52CA6EDAAFEE8A3D9D3704534FC4990BC8E5FA3B249CDE43CEED96103E3A0893`） |
| `eval/run_eval.py` | 未改（sha256 `7E0C19E58631BC49498E7A23041541C6FF405E6BE61683D8078DE3AE83CB6F32`） |
| `eval/report.py` | 未改（sha256 `EF5FE417C6235E685A19FD4AF91A23A89068081B3FB9421C245E7125D2EE0141`） |
| `eval/baseline.py` / `eval/baseline_report.py` | 未改 |
| `eval/results/*.json` | 未改（本轮结果 sha256 `71513C5C1E250658B3053656D465941694ECC640B43EC07EEDD5106B099380A2`） |
| `src/**` / `web/**` / `static/**` | 0 改动 |
