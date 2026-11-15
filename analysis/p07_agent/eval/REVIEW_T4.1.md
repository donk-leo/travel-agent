# T4.1 golden set 人工复核清单（30 条 / 20 dev + 10 held-out）

> 复核对象：`analysis/p07_agent/eval/golden_set.jsonl`（30 条）、`run_eval.py` 状态口径、`tests/test_eval_schema.py`、`README.md`。  
> 任务：`01_TASK_BOARD.md` T4.1（DoD：30 条分层；20 dev / 10 held-out；边界 ≥8；人工复核）。  
> 生成：2026-11-15，QA 子 Agent（T4.1）。本文件只列**复核要点与机器校验结果**；本轮**未跑真实模型**，不含任何手写评测指标。

## 0. 结论摘要

- 机器校验全绿：30 条 / 唯一 30 / dev 20 + held-out 10；query 与 `03_EVAL_SPEC.md` §2.2 逐字比对 **30/30** 一致（mismatch=0）；边界 **17** 条（≥8）；schema 校验问题 **0** 处。
- 状态别名已删除：`normalize_status("complete")` → `None`、`normalize_status("reply")` → `None`；`complete` 也不再是合法 `expected.status`。
- 本轮无模型调用（三种 split 的 dry-run `model_calls` 合计 0），`results/` 历史文件未改。
- **待人类最终确认项 7 个，见 §4**；其中 3 个是任务明确要求必列的：CL-INFO-01 裁定、CL-FAM-02 的 `max_stops=8` 与 Q4「≤6」口径、held-out 未参与调参的承诺。

## 1. 机器校验结果（2026-11-15 实际运行）

| # | 检查项 | 命令 / 方式 | 结果 |
|---:|---|---|---|
| 1 | 条数 / id 唯一 | 读取 JSONL + `set(ids)` | 30 条，唯一 30 |
| 2 | split 分布 | `collections.Counter` | dev 20 / heldout 10 |
| 3 | 顺序 | 与 §2.2 表逐行对比 | 一致 |
| 4 | query 逐字 | 解析 §2.2 表格后 `==` 比较 | 30/30 一致，mismatch 0 |
| 5 | schema | `run_eval.validate_case` 逐条 | 0 处问题 |
| 6 | 边界计数 | `boundary is True` | 17 条（≥8） |
| 7 | 状态别名 | `normalize_status` | `complete`→None，`reply`→None，四值原样 |
| 8 | dry-run 三种 split | `run_eval.py --split dev/heldout/all --dry-run` | 选中 20 / 10 / 30，退出码均 0，`model_calls=0` |
| 9 | eval 单测 | `python -m unittest analysis.p07_agent.eval.tests.test_eval_schema -q` | 17 tests OK |
| 10 | 主测试套件 | `python -m unittest discover -s analysis\p07_agent\tests -q` | 93 tests OK（未回退） |
| 11 | 项目自检 | `python checks\check_agent.py analysis\p07_agent` | 退出码 0 |

关键命令输出（节选）：

```text
n 30 unique 30
Counter({'dev': 20, 'heldout': 10})
boundary 17
  BYS-2D-01, BYS-CONFLICT-01, BYS-INFO-01, BYS-SOLO-01, CL-2D-01, CL-FRD-01, CL-INFO-01, CL-SUB-01, CL-SUB-02, CL-SUB-03, EDGE-FOLLOW-01, EDGE-MISS-01, EDGE-NOMATCH-01, EDGE-UNSUP-01, WGS-3D-01, WGS-BUDGET-01, WGS-INFO-01
query_mismatch 0
normalize complete -> None
normalize verified -> verified
```

## 2. 30 条清单（按 §2.2 顺序）

| # | id | split | 边界 | expected.status | 一句话判定要点 |
|---:|---|---|---|---|---|
| 1 | `CL-FAM-01` | dev | — | `verified/partial` | 5 岁亲子 ≤6 点；“少走路”不得声称已满足 |
| 2 | `CL-FAM-02` | dev | — | `verified/partial` | 种子保留 max_stops=8（与 Q4≤6 冲突，待确认） |
| 3 | `CL-CPL-01` | dev | — | `verified/partial` | 成人情侣 ≤8 点；刺激只按节点标签 |
| 4 | `CL-FRD-01` | dev | ✓ `budget_constraint` | `verified/partial` | 预算无票价须标未知；成人 ≤8 点 |
| 5 | `CL-ELD-01` | dev | — | `verified/partial` | 老人 ≤6 点；硬排除过山车 |
| 6 | `CL-SUB-01` | dev | ✓ `sub_area_scope` | `verified/partial` | 只在欢乐世界内选点，不得拼其他园区 |
| 7 | `CL-SUB-02` | dev | ✓ `sub_area_scope` | `verified/partial` | 只在野生动物世界内选点；年龄未写按 6 从严 |
| 8 | `CL-SUB-03` | dev | ✓ `single_destination` | `partial` | 单点 partial，不得回退拼路线 |
| 9 | `CL-2D-01` | heldout | ✓ `multi_day_fallback` | `verified/partial` | 两日亲子 12 点；均分兜底须标 partial |
| 10 | `CL-INFO-01` | heldout | ✓ `info_only` | `verified` | held-out 裁定；列表须带来源、不编适龄信息 |
| 11 | `BYS-ELD-01` | dev | — | `verified/partial` | 老人 ≤6 点；不编坡度数据 |
| 12 | `BYS-FAM-01` | dev | — | `verified/partial` | 4 岁亲子 ≤6 点；无坡度数据不得编造 |
| 13 | `BYS-FRD-01` | dev | — | `verified/partial` | 成人 ≤8 点；不编坐标/距离 |
| 14 | `BYS-CPL-01` | dev | — | `verified/partial` | 日落无数据只能标未知；成人 ≤8 点 |
| 15 | `BYS-SOLO-01` | dev | ✓ `time_budget` | `verified/partial` | 半日 3 小时；cap=8 为待确认口径 |
| 16 | `BYS-2D-01` | heldout | ✓ `missing_feature_data` | `partial/clarify` | 露营无数据须说明，给 partial/clarify |
| 17 | `BYS-INFO-01` | heldout | ✓ `info_only` | `verified` | 只列图谱内寺庙并给来源 |
| 18 | `BYS-CONFLICT-01` | heldout | ✓ `constraint_conflict` | `clarify` | 冲突须 clarify，不得硬出行程 |
| 19 | `WGS-FRD-01` | dev | — | `verified/partial` | 两日成人 16 点；不编日出时刻 |
| 20 | `WGS-FAM-01` | dev | — | `verified/partial` | 两日亲子 12 点；不编索道票价 |
| 21 | `WGS-CPL-01` | dev | — | `verified/partial` | 两日成人 16 点；自然风光按标签 |
| 22 | `WGS-SOLO-01` | dev | — | `verified/partial` | 单日成人 8 点；经典路线须连续有据 |
| 23 | `WGS-ELD-01` | dev | — | `verified/partial` | 两日老人 12 点；不编索道运营信息 |
| 24 | `WGS-3D-01` | heldout | ✓ `multi_day_fallback` | `partial` | 三日亲子 18 点；分天兜底只能 partial |
| 25 | `WGS-INFO-01` | heldout | ✓ `info_only` | `verified` | 金顶交通只引图谱边与来源 |
| 26 | `WGS-BUDGET-01` | heldout | ✓ `budget_constraint` | `verified/partial` | 预算无票价须标未知；两日 16 点 |
| 27 | `EDGE-MISS-01` | dev | ✓ `missing_slot` | `clarify` | 缺景区/天数须追问，不得猜 |
| 28 | `EDGE-FOLLOW-01` | dev | ✓ `multi_turn` | `verified/partial` | 多轮复用累积文本，不重复问景区 |
| 29 | `EDGE-UNSUP-01` | heldout | ✓ `unsupported_area` | `clarify` | 明确不支持西湖，只列三个覆盖景区 |
| 30 | `EDGE-NOMATCH-01` | heldout | ✓ `no_match` | `verified` | 说“图谱没有”而非“现实没有” |

## 3. 分层与边界计数

| strata | 条数 | dev | held-out |
|---|---:|---:|---:|
| 长隆 | 10 | 8 | 2 |
| 白云山 | 8 | 5 | 3 |
| 武功山 | 8 | 5 | 3 |
| 边界（EDGE） | 4 | 2 | 2 |
| **合计** | **30** | **20** | **10** |

边界分类（`boundary_kind` 计数）：

| boundary_kind | 条数 | id |
|---|---:|---|
| `info_only` | 3 | `CL-INFO-01`、`BYS-INFO-01`、`WGS-INFO-01` |
| `budget_constraint` | 2 | `CL-FRD-01`、`WGS-BUDGET-01` |
| `multi_day_fallback` | 2 | `CL-2D-01`、`WGS-3D-01` |
| `sub_area_scope` | 2 | `CL-SUB-01`、`CL-SUB-02` |
| `constraint_conflict` | 1 | `BYS-CONFLICT-01` |
| `missing_feature_data` | 1 | `BYS-2D-01` |
| `missing_slot` | 1 | `EDGE-MISS-01` |
| `multi_turn` | 1 | `EDGE-FOLLOW-01` |
| `no_match` | 1 | `EDGE-NOMATCH-01` |
| `single_destination` | 1 | `CL-SUB-03` |
| `time_budget` | 1 | `BYS-SOLO-01` |
| `unsupported_area` | 1 | `EDGE-UNSUP-01` |

其他数据形态（供复核）：

- `expected.status` 分布：`verified/partial` 20；`partial` 2；`verified` 4；`partial/clarify` 1；`clarify` 3
- `max_stops` 分布：`6` 5；`8` 9；`1` 1；`12` 3；`None` 7；`16` 4；`18` 1

## 4. 待人类最终确认项

> 以下 7 项中，第 1–3 项是任务明确要求必列的「待确认」；第 4–7 项是 QA 在填 §2.3 字段时发现的规范/产品口径差异。QA 只给建议，不替人类做裁定。

### 4.1 CL-INFO-01 split 由 dev 改为 held-out（必确认）

- **现状**：`split=heldout`，`notes` 已写入“T4.1（2026-11-15）父 Agent 裁定”及理由；`query` 未改。
- **依据**：`03_EVAL_SPEC.md` §2.2 原就标 `held-out`；§2.1 要求长隆 2 条 held-out；30 条铺开后只有该解能同时满足「§2.2 逐条」与「20 dev / 10 held-out」。
- **风险**：该条在 D0 阶段曾作为 dev 用于串通评测骨架，若人类认为它已被“污染”，则不能算严格 held-out；需人类决定是否保留。
- **若不同意**：必须同时改 §2.1/§2.2 或换另一条进 held-out，并保持 20/10——不能只改 JSONL。
- **QA 建议**：维持 `heldout`；该条只包含 query 与期望，不含任何模型输出，D0 的 dev 标记是 10 条种子阶段的产物，未据此调过 prompt。

### 4.2 CL-FAM-02 的 `max_stops=8` 与 Q4「≤6」不一致（必确认）

- **现状**：`max_stops=8`，沿用 §2.3 示例与 D0 冻结种子；**未静默改**。
- **矛盾**：Q4 已签字「带 0–6 岁儿童/老人 → 单日 ≤6」；该条 persona 是「孩子 + 老人」，按 Q4 应为 6。`notes` 与 README §9 均保留该冲突。
- **影响**：T4.2 真实跑若返回 >6 点，`stop_cap_ok` 按 8 仍可能判 true，会低估越界；T0.3 历史跑该条返回 12 点，8/6 都会 false。
- **待确认**：是否把该条收紧到 6？（涉及“冻结种子不静默改”与“Q4 口径”的取舍）
- **QA 建议**：由人类签字后**单独一次提交**改为 6，并在 `REVIEW`/`README` 记录变更；在此之前保持 8，不用评测结果反推。

### 4.3 held-out 未参与调参的承诺（必确认）

- **现状**：T4.1 无任何模型调用、无 prompt/阈值/规则调整；held-out 10 条只是按 §2.2 写入数据集，未运行、未查看输出。
- **可核对**：本轮 `results/*-dryrun-*.json` 的 `model_calls` 全为 0；`git diff` 只含 `analysis/p07_agent/eval/**`。
- **待确认**：人类是否认可“截至 2026-11-15，held-out 未参与调参”可作为对外表述；T4.2 打开 held-out 后该承诺即失效，需重新声明。
- **QA 建议**：在 T4.2 报告 §1 记录首次打开 held-out 的时间与 commit，作为隔离证据。

### 4.4 BYS-SOLO-01 半日（0.5 天）上限未在 Q4 定义

- **现状**：`days=0.5`、`max_stops=8`（沿用成人单日上限）。
- **问题**：Q4 只写“单日”，未写半天/3 小时；若按 3 小时可行节奏，8 点明显偏多。
- **待确认**：半日是否另设上限（如 4）？
- **QA 建议**：暂不臆造新阈值；若人类给出半日口径，再统一改。

### 4.5 CL-SUB-02 孩子年龄未写，按亲子从严取 6

- **现状**：§2.2 人群列只写“子园区、亲子”，query 未写年龄；`max_stops=6`（从严）。
- **待确认**：是否认可“未写年龄的亲子按 0–6 岁从严”；若否，应改为 8 并在 `notes` 说明。

### 4.6 EDGE-NOMATCH-01 的期望状态 `verified` 与 PRODUCT_SPEC S2 不同

- **现状**：按 §2.2 期望列「verified/无匹配」记为 `["verified"]`。
- **差异**：`PRODUCT_SPEC.md` §8 的 S2 写「无匹配 → `clarify`（只能列地点）或 `partial`（能出兜底路线）」。
- **待确认**：评测口径以 §2.2 文字为准（verified = 正确回答“图谱没有”），还是按 S2 放宽为 `[clarify, partial]`？
- **QA 建议**：若人类按 S2，则 `golden_set` 的 `expected.status` 需改，属于规范变更，不能由 QA 单方面改。

### 4.7 `expected.must_include` / `must_not` 是 QA 从 query 推导的

- **说明**：§2.2 只给 query / split / 期望状态；`must_include`、`must_not`、`evidence_required` 按 §2.3 schema 由 QA 从 query、人群列与已知数据缺口（无距离/票价/开放时间/坐标）推导，未引入 query 之外的新事实。
- **待确认**：请人类抽查新增 20 条的关键词是否合理，尤其是 `must_not` 是否过严。

## 5. 复核方式（可复现）

```powershell
Set-Location E:\ProgramProject\travel-agent
$env:PYTHONIOENCODING='utf-8'
$py = ".\.venv\Scripts\python.exe"
& $py -c "import json,collections;rows=[json.loads(l) for l in open(r'analysis\p07_agent\eval\golden_set.jsonl',encoding='utf-8') if l.strip()];ids=[r['id'] for r in rows];print('n',len(rows),'unique',len(set(ids)));print(collections.Counter(r['split'] for r in rows));print('boundary',sum(1 for r in rows if r.get('boundary')),sorted(r['id'] for r in rows if r.get('boundary')))"
& $py analysis\p07_agent\eval\run_eval.py --split dev --dry-run
& $py analysis\p07_agent\eval\run_eval.py --split heldout --dry-run
& $py analysis\p07_agent\eval\run_eval.py --split all --dry-run
& $py -m unittest analysis.p07_agent.eval.tests.test_eval_schema -q
& $py -m unittest discover -s analysis\p07_agent\tests -q
& $py checks\check_agent.py analysis\p07_agent
```

## 6. 本轮边界与声明

- 只改 `analysis/p07_agent/eval/**`；未改 `src/**`、`tests/**`（p07 主套件）、`web/`、`static/`、`scenic/**`、`docs/**` 等；`results/` 历史 JSON 未改。
- 未跑真实模型、未手写任何成功率/延迟/证据覆盖率；held-out 明细未在开发期查看。
- 若 `03_EVAL_SPEC.md` §2.2 后续变更，以规范为准，并重跑 §5 的校验命令后再复核本清单。
