# T1.5 P2/P3/P5/P6 重跑报告（32 篇 = 旧 29 篇 + 新增 3 篇）

> **status**：`done`
> **task**：`T1.5`（Owner：GRAPH；P2/P5 合并权在 T0coke，P3/P6 在 HappinessJo）
> **分支**：`agent/d2-graph-evidence`｜**base**：`6813920`｜**开工 HEAD**：`1c2a578`
> **commit**：见 `git log -1 --format=%H`（本报告与重跑产物在同一提交中，无法把自身 commit hash 写进自身）
> **运行环境**：Windows；`E:\ProgramProject\travel-agent\.venv\Scripts\python.exe`（3.11.9）；
> `PYTHONIOENCODING=utf-8`；**两遍重跑均设置 `PYTHONHASHSEED=0`**（原因与证据见 §7.3；这是唯一的环境约定，
> 不改变任何命令与数据）
> **数据日期**：2026-11-15

---

## 1. 结论（DoD 逐条）

| # | DoD | 结果 | 证据 |
|---:|---|---|---|
| 1 | `entity_stats.json.documents_processed == 32`；四层 doc 并集含 `WGS-O-07/08/09`；旧 29 篇无一消失 | ✅ | §3、§4；P2=32 / P3=32 / P6=32 篇；P5=15 篇（旧 13 篇全在） |
| 2 | 前后对照表齐全、差异逐项解释；`WGS-T-04` 仍在 P2 | ✅ | §3、§5、§9 |
| 3 | 两遍重跑严格清单逐字节相同；两个时间戳文件掩码后相同 | ✅ | §7：19/21 逐字节相同，2 个仅 `generated_at` 不同（掩码后 sha 相等） |
| 4 | 旧 29 篇 P2/P3/P5/P6 冻结规则全部满足 | ✅ | §8：P2 1006/1006、P3 226/226、P5 36/36、P6 229/229 节点与 523/523 边全在 |
| 5 | 9/9 checks exit 0；93 条测试 OK；eval dry-run exit 0 | ✅ | §10 |
| 6 | `node_classification.csv` 覆盖全部地点节点、`--check` exit 0、50 抽样可复算 | ✅ | §11：168 行、0 空值、抽 3/50 噪声 |
| 7 | `git status` 干净；`git diff 6813920..HEAD` 只含白名单 + T1.4 产物 | ✅ | §12；变更清单见 §12.3 |
| 8 | tag/version_tag 只有提案，`git tag --list` 不变 | ✅ | §12.1–12.2；10 个旧 tag 未动 |

**核心增量**：P2 +112 实体（= 新 3 篇 37+43+32），P3 +40 步 / +3 路线，P5 +2 条件（其中 1 条入图），
P6 +18 节点 / +54 边；旧 29 篇逐字段 0 变化。

---

## 2. 执行命令与退出码

两遍（A/B）都从仓库根目录执行，命令完全相同；两遍之间没有任何手工改文件。

| # | 命令 | A 退出码 | B 退出码 |
|---:|---|---:|---:|
| 1 | `& $py analysis\p02_entities\src\run_all.py` | 0 | 0 |
| 2 | `& $py analysis\p03_routes\src\run_all.py` | 0 | 0 |
| 3 | `& $py analysis\p05_conditions\src\extract_conditions.py` | 0 | 0 |
| 4 | `& $py analysis\p05_conditions\outputs\apply_stable_ids.py --write` | 0 | 0 |
| 5 | `& $py analysis\p05_conditions\src\eval_conditions.py` | 0 | 0 |
| 6 | `& $py analysis\p05_conditions\src\build_mapping.py` | 0 | 0 |
| 7 | `& $py analysis\p05_conditions\src\build_p6_bridge.py` | 0 | 0 |
| 8 | `& $py analysis\p06_graph\src\run_all.py` | 0 | 0 |
| 9 | `& $py analysis\p06_graph\outputs\classify_nodes.py --write` | 0 | 0 |

> 第 4 步是本任务新增的 **P5 稳定 ID 兼容层**（`analysis/p05_conditions/outputs/apply_stable_ids.py`，
> 理由见 §6）。补充执行（不参与逐字节比较）：`& $py analysis\p05_conditions\src\make_figures.py` exit 0。
> 调试期有一次把 `--write` 与脚本路径拼成单个 PowerShell 参数导致 exit 2（进程未执行、未写盘），
> 属调用写法错误；A/B 两遍均为正确调用，不计入上表。

质量门（全部在最终产物上执行）：

| 命令 | 退出码 | 关键输出 |
|---|---:|---|
| `check_scenic.py`（长隆 / 白云山 / 武功山） | 0 / 0 / 0 | 8 / 7 / 17 条；武功山 `WGS-T-04` 仅 33 字，已标无效并保留 |
| `check_entities.py` | 0 | 1118 条；POI 651 / TIME 268 / TRANSPORT 199 |
| `check_routes.py` | 0 | 38 路线 / 266 步；explicit 47、absent 219 |
| `check_conditions.py` | 0 | 38 条；天气 5 / 时间 13 / 人群 13 / 交通 4 / 体力 2 / 预算 1 |
| `check_graph.py analysis\p06_graph\outputs` | 0 | 247 节点 / 577 边；最大连通分量 247/247（100%） |
| `check_coref.py` | 0 | 140 条候选 / 28 已消解 |
| `check_agent.py analysis\p07_agent` | 0 | 11 个会话轨迹，152 步 |
| `python -m unittest discover -s analysis\p07_agent\tests -q` | 0 | `Ran 93 tests … OK` |
| `run_eval.py --split dev --limit 1 --dry-run` | 0 | 1 条；dry-run 不执行；输出文件在 `.gitignore` 内，运行后已删除，仓库无变化 |
| `classify_nodes.py --check` | 0 | `rows=168 … [OK] … 全部满足 DoD` |

---

## 3. 前后对照表

### 3.1 P2 实体

| 指标 | 重跑前（`1c2a578`，29 篇） | 重跑后（32 篇） | Δ |
|---|---:|---:|---:|
| `documents_processed` | 29 | **32** | +3 |
| 实体总数 | 1006 | **1118** | +112 |
| POI | 573 | **651** | +78 |
| TIME | 248 | **268** | +20 |
| TRANSPORT | 185 | **199** | +14 |
| 长隆（POI/TIME/TRANSPORT） | 133 / 98 / 35（266） | 133 / 98 / 35（266） | 0 |
| 广州白云山 | 134 / 33 / 65（232） | 134 / 33 / 65（232） | 0 |
| 武功山 | 306 / 117 / 85（508） | 384 / 137 / 99（620） | +112 |

### 3.2 P3 路线

| 指标 | 重跑前 | 重跑后 | Δ |
|---|---:|---:|---:|
| 路线数 | 35 | **38** | +3 |
| 步骤数 | 226 | **266** | +40 |
| `time_source=explicit` / `absent` | 47 / 179 | **47 / 219** | 0 / +40 |
| 长隆（路线/步） | 8 / 52 | 8 / 52 | 0 |
| 广州白云山 | 11 / 61 | 11 / 61 | 0 |
| 武功山 | 16 / 113 | **19 / 153** | +3 / +40 |
| 官方路线（路线/步） | 14 / 134 | **17 / 174** | +3 / +40 |
| 游客游记 / 站点攻略 | 20 / 91、1 / 1 | 20 / 91、1 / 1 | 0 |

> `explicit` 仍为 47（全部在长隆）：新 3 篇是官方行程，只有时长/时段词，没有显式时刻，符合 P3 的
> `absent` 口径（不推断、不伪装原文事实）。

### 3.3 P5 条件建议

| 指标 | 重跑前 | 重跑后 | Δ |
|---|---:|---:|---:|
| 条件条数 | 36 | **38** | +2 |
| 去重后唯一（`is_duplicate=False`） | 33 | **34** | +1 |
| 有条件的文档数 | 13 | **15** | +2 |
| `docs_total` / `docs_valid` | 29 / 28 | **32 / 31** | +3 / +3 |
| 覆盖率（有/有效） | 46.43% | **48.39%** | +1.96pp |
| 白云山 / 武功山 / 长隆 | 8 / 16 / 12 | 8 / **18** / 12 | 0 / +2 / 0 |
| 类型：天气 / 时间 / 人群 / 交通 / 体力 / 预算 | 3 / 13 / 13 / 4 / 2 / 1 | **5** / 13 / 13 / 4 / 2 / 1 | 天气 +2 |
| 完全重复 / 前后缀 / 近重复 | 2 / 1 / 0 | **3** / 1 / 0 | +1 |

### 3.4 P6 图谱

| 指标 | 重跑前 | 重跑后 | Δ |
|---|---:|---:|---:|
| 节点 | 229 | **247** | +18 |
| 边 | 523 | **577** | +54 |
| SCENIC_AREA / POI / TRANSPORT | 3 / 141 / 8 | 3 / **157** / 8 | 0 / +16 / 0 |
| TIME / ACTIVITY / CONDITION | 32 / 12 / 33 | 32 / **13** / **34** | 0 / +1 / +1 |
| CONTAINS / NEXT | 153 / 165 | **170 / 192** | +17 / +27 |
| AT_TIME / BY_TRANSPORT | 47 / 118 | 47 / **127** | 0 / +9 |
| HAS_CONDITION / SIMILAR_TO | 33 / 7 | **34** / 7 | +1 / 0 |
| 最大连通分量 | 229/229（100%） | **247/247（100%）** | 全连通 |
| P3 独有节点 / 无 POI 步骤 | 59 / 7 | **75 / 8** | +16 / +1 |

---

## 4. 逐 `doc_id` 覆盖矩阵

「P6 节点」= `graph_nodes.csv` 的 `source_doc_ids` 含该 doc 的节点数；「P6 边」同理。
新增 3 篇用 **粗体** 标出。

| doc_id | P2 实体 | P3 路线 | P3 步 | P5 条件 | P6 节点 | P6 边 |
|---|---:|---:|---:|---:|---:|---:|
| BYS-O-01 | 55 | 1 | 23 | 0 | 39 | 110 |
| BYS-O-02 | 2 | 1 | 1 | 0 | 3 | 2 |
| BYS-O-03 | 2 | 1 | 1 | 0 | 3 | 2 |
| BYS-T-01 | 95 | 1 | 1 | 7 | 22 | 32 |
| BYS-T-02 | 28 | 3 | 16 | 1 | 20 | 32 |
| BYS-T-03 | 22 | 3 | 18 | 0 | 19 | 33 |
| BYS-T-04 | 28 | 1 | 1 | 0 | 12 | 11 |
| CL-O-01 | 31 | 1 | 3 | 3 | 20 | 17 |
| CL-O-02 | 46 | 1 | 12 | 0 | 30 | 45 |
| CL-O-03 | 39 | 1 | 3 | 2 | 20 | 23 |
| CL-T-01 | 26 | 1 | 3 | 1 | 20 | 21 |
| CL-T-02 | 25 | 1 | 10 | 1 | 25 | 33 |
| CL-T-03 | 47 | 1 | 17 | 1 | 33 | 56 |
| CL-T-04 | 47 | 1 | 3 | 4 | 21 | 21 |
| CL-T-05 | 5 | 1 | 1 | 0 | 5 | 4 |
| WGS-O-01 | 28 | 1 | 16 | 0 | 23 | 36 |
| WGS-O-02 | 25 | 1 | 17 | 0 | 17 | 31 |
| WGS-O-03 | 33 | 1 | 14 | 0 | 16 | 35 |
| WGS-O-04 | 35 | 1 | 18 | 0 | 21 | 49 |
| WGS-O-05 | 102 | 3 | 20 | 2 | 26 | 46 |
| WGS-O-06 | 87 | 1 | 6 | 5 | 27 | 36 |
| **WGS-O-07** | **37** | **1** | **17** | **1** | **17** | **45** |
| **WGS-O-08** | **43** | **1** | **16** | **1** | **25** | **51** |
| **WGS-O-09** | **32** | **1** | **7** | **0** | **11** | **16** |
| WGS-T-01 | 20 | 1 | 1 | 0 | 4 | 1 |
| WGS-T-02 | 22 | 1 | 1 | 1 | 5 | 2 |
| WGS-T-03 | 38 | 1 | 1 | 7 | 14 | 13 |
| WGS-T-04 | 1 | 1 | 1 | 0 | 1 | 0 |
| WGS-T-05 | 55 | 1 | 15 | 0 | 16 | 25 |
| WGS-T-06 | 16 | 1 | 1 | 0 | 5 | 3 |
| WGS-T-07 | 35 | 1 | 1 | 0 | 10 | 17 |
| WGS-T-08 | 11 | 1 | 1 | 1 | 5 | 4 |

**旧 29 篇「从某层消失」检查 = 0**：

- P2：重跑前 29 篇，重跑后每篇实体数与重跑前逐篇相等 → 0 消失；
- P3：29 篇的路线数/步骤数与重跑前逐篇相等 → 0 消失；
- P5：重跑前有条件的 13 篇，重跑后 13 篇仍全部出现（另新增 `WGS-O-07/08` 2 篇）→ 0 消失；
- P6：重跑前被节点引用的 29 篇，重跑后仍全部出现，且逐篇节点数**没有下降** → 0 消失。

`WGS-O-09` 在 P5 为 0 条：原文是「山下路线 + 航空飞行营地」的行程说明，没有触发词/建议句
（P5 抽取器只认显式/隐式条件句），不是被过滤或丢失。

---

## 5. 差异逐项解释

### 5.1 新增 3 篇带来的增量（全部有解释）

| 层 | 增量 | 解释 |
|---|---|---|
| P2 | +112 = 37 + 43 + 32 | 恰好等于 `WGS-O-07/08/09` 三篇的实体数，逐篇核对见 §4；旧 29 篇 1006 条逐字段 0 差异 |
| P3 | +3 路线 / +40 步 = 17 + 16 + 7 | 每篇各解析出 1 条路线（`WGS-O-07-r1` / `WGS-O-08-r1` / `WGS-O-09-r1`），格式分别为 `day_sequence` / `poi_list` / `chain`；旧 226 步逐字段 0 差异 |
| P5 | +2 条件 | `CND-0037`（WGS-O-07「雨天 → 请不要在山上使用手机」，入图）与 `CND-0038`（WGS-O-08 同文，`is_duplicate=True, exact`）；旧 36 条逐字段 0 差异 |
| P6 | +18 节点 = POI +16、ACTIVITY +1、CONDITION +1 | 条件节点来自 `CND-0037`（`CND-0038` 为重复，按 P5 桥接 `recommended_for_graph` 过滤）；ACTIVITY +1 为 `ACTIVITY\|返回`；16 个 POI 是新文档经 P2/P3 融合后的净新增 |
| P6 | +54 边 = CONTAINS +17、NEXT +27、BY_TRANSPORT +9、HAS_CONDITION +1 | 全部由新节点/新步骤派生；`AT_TIME`、`SIMILAR_TO` 不变（新文档无显式时刻、未触发同义合并） |

### 5.2 旧 29 篇：0 处语义变化

- P2：1006/1006 行**逐字段**与 `6813920` 相同（含 `sentence`/`method`/`confidence`），span 元组 0 处不同；
- P3：226/226 行逐字段相同，`(route_id, step_no)` 序列相同；
- P5：36/36 行逐字段相同（**含 `cond_id`**，见 §6），行序仍为 CND-0001…0036 在前；
- P6：229/229 个旧 `node_id` 全在，`node_type`/`name`/`scenic_area`/`properties` 0 变化，`freq` 0 下降，
  `source_doc_ids` 只增不减；523/523 条旧 `(src,rel,dst)` 全在（weight 可变）。

### 5.3 聚合/派生文件为什么变了（不是规则变化）

| 文件 | 变化 | 解释 |
|---|---|---|
| `entity_stats.json` | 29→32 篇、1006→1118 条、武功山 508→620 | P2 汇总数字；规则/词典未改 |
| `hierarchy.json` | `totals` 35/226→38/266；`by_area` 武功山 16/113→19/153；`by_doc_type` 官方 14/134→17/174；`by_format` 各 +1~2 | P3 汇总；旧 29 篇的统计值未变 |
| `compare_official_vs_user.csv` | 合计官方路线 14→17、官方 POI 80→96、官方步 134→174；武功山 official_poi_n 39→55、coverage 0.103→0.073；合计 coverage 0.225→0.188、steps/route 9.57→10.24；`order_tau` 仍 0.673 | 新 3 篇全部是官方行程，官方侧基数变大；长隆/白云山两行**逐字节未变** |
| `condition_stats.json` / `dedup_report.md` | 38 条 / 34 唯一 / 15 篇 / 48.39% | P5 汇总，见 §3.3 |
| `p6_condition_poi.csv` / `p6_bridge_stats.json` / `P6_接入说明.md` | 36→38 条、33→34 入图、重复 3→4（新增 `CND-0038`） | 桥接表随条件数重算；旧 36 条映射不变 |
| `graph_stats.json` / `graph_qa.md` | 见 §3.4；`graph_qa` 的 Top-10 hub 因频次变化（`POI\|武功山\|中庵` 11 次进入，`金顶索道` 退出）、武功山节点 65→83、P3-only 59→75 | P6 汇总与 QA 文本按新图重算；`generated_at` 时间戳另计 |
| `映射表.xlsx` / 各 PNG / `node_classification.csv` / `node_noise_sample50.csv` | 行数/内容随新数据重算 | 见 §10、§11 |

---

## 6. P5 `cond_id` 稳定性（T1.5 临时兼容层，D2 措施）

### 6.1 根因（已定位到 src，只读未改）

`analysis/p05_conditions/src/extract_conditions.py` 第 503–507 行：

```python
# 稳定排序 + 编号
rows_all.sort(key=lambda r: (r["scenic_area"], r["doc_id"], r["char_start"],
                             r["suggestion_start"], r["suggestion_text"]))
for i, r in enumerate(rows_all, 1):
    r["cond_id"] = f"CND-{i:04d}"
```

`cond_id` 是**位置编号**，而排序键包含 `doc_id`。新增的 `WGS-O-07/08` 在 doc_id 字典序上落在
`WGS-O-06` 与 `WGS-T-02` 之间，于是：

- 2 条新条件占用 `CND-0016`、`CND-0017`；
- 旧 `CND-0016…CND-0036` 整体 **+2 重编号**（21/36 个旧 cond_id 对应的条件文本发生变化）；
- `analysis/p05_conditions/config/manual_review_gold.csv` 的人工标注按旧 cond_id 挂：20 条标注中有
  **9 条**（`CND-0016/0018/0021/0025/0026/0027/0028/0033/0035`，即 id > 15 的全部）会错配到别的条件，
  P5 的 70%/95% 指标会失真（实际重跑时 `eval_stats.json` 的 `by_area`/`by_type`/`errors` 已出现错位，见 §6.3）；
- P6 的 `CONDITION\<cond_id>` 节点 `name` = 条件原文，连带 2 个旧 node_id 消失、16 个旧节点改名
  （**未套兼容层时**的实测结果；套用 §6.2 兼容层后已恢复为 §8.4 的 229/229）。

### 6.2 兼容层做法（只改 ID 与行序，不改字段值）

新增两个文件（均在 `analysis/p05_conditions/outputs/` 白名单内）：

1. `cond_id_map.json`：`signature → 旧 cond_id` 映射。签名 =
   `doc_id + \u0001 + condition_text + \u0001 + suggestion_text + \u0001 + char_start + \u0001 + char_end`；
   收录 `1c2a578` 的 36 条旧条件（`origin=legacy`），新条件追加时写 `origin=new`。无时间戳、无随机，可 diff。
2. `apply_stable_ids.py`：确定性纯标准库脚本
   - `--init-map <legacy.jsonl>`：从旧 `conditions.jsonl` 初始化映射（只允许一次）；
   - `--write`：命中签名 → 用旧 ID；未命中 → 从 `max(旧ID)+1` 起，按
     `(scenic_area, doc_id, char_start, suggestion_start, suggestion_text)` 排序编号，并追加写回 map；
     按 `cond_id` 数值升序重写 `conditions.jsonl`，**字段顺序与原文件一致**；
   - `--check`：旧 36 个签名必须映射到旧 ID、ID 唯一/连续/升序、文件内 ID 唯一，任一不满足 exit 非 0。

**边界声明**：这是 D2 阶段的**临时措施，不是 P5 契约变更**；没有改 `src/**`、`config/**`、`standards/**`，
字段值一字未动。P5 owner 修好 src 后应删除本层（见 §6.4），否则会形成“映射表即契约”的隐性冻结。

### 6.3 验收数字

| 验收项 | 结果 |
|---|---|
| 旧 36 行与 `1c2a578` 的 `conditions.jsonl` **逐字段（含 cond_id）一致** | ✅ `legacy == conds[:36]` 为 True |
| 行序：旧 36 行在前、新 2 行在后 | ✅ CND-0001…CND-0036、CND-0037、CND-0038 |
| 新条件 ID 从 `max(旧)+1` 追加 | ✅ CND-0037 / CND-0038（无跳号） |
| ID 唯一 / 连续 / 升序 | ✅ 38 个唯一 ID，1..38 连续 |
| `eval_stats.json` 与 `1c2a578` **逐字段一致**（gold 重新对上） | ✅ JSON 深度相等；`reviewed=20 correct=14 partial=5 wrong=1 strict=0.7 lenient=0.95`，`by_area`/`by_type`/`errors` 与旧完全相同 |
| `manual_review.csv` 与旧文件一致 | ✅ 归一化 CRLF 后逐字节相同（旧 blob 为 LF，Windows 文本模式写 CRLF，见 §7.4） |
| 映射幂等 | ✅ 连续两次 `--write` 后 `cond_id_map.json` sha256 不变：`63eba8de8432114f7da07283f0a48979ec1bd6e08bfa9f1776cfd47f1a6fd523` |
| `apply_stable_ids.py --check` | ✅ exit 0 |

### 6.4 给 P5 owner（T0coke）的修复提案

1. **首选**：`extract_conditions.py` 按**源 CSV 行序**排序/编号（`scenic_area` 内的行序来自
   `scenic/<area>_data/processed/*_guides.csv` 的物理顺序），这样新增文档永远追加在尾部，旧 ID 天然稳定；
2. 或把 `cond_id` **持久化**到 `config/cond_id_map.csv`（提交到仓库），每次抽取按签名复用旧 ID、
   新条目追加——即把本兼容层的内容上收为 P5 正式机制；
3. 不建议“按文本排序后编号”或“哈希 ID”（前者仍会因新文本插队而漂移，后者破坏 `CND-0001` 可读性）。
4. 修复后重跑 P5 + 下游，升 `v0.5.2-p05` 并删除 `apply_stable_ids.py` / `cond_id_map.json`。

---

## 7. 确定性证明

### 7.1 做法

- 同一套 9 条命令、同一顺序、同一输入，连续跑两遍（§2 的 pass A / pass B）；
- 两遍都在仓库根目录、同一 venv、`PYTHONIOENCODING=utf-8`、`PYTHONHASHSEED=0` 下执行；
- 第二遍开始前不做任何手工改动，两遍之间只读取文件算 sha256。

### 7.2 严格清单（19/19 逐字节相同）

| 文件 | pass A sha256 | pass B sha256 | 相同 |
|---|---|---|---|
| `analysis/p02_entities/outputs/entities.jsonl` | `b8efdf4f8f269ba2…` | `b8efdf4f8f269ba2…` | ✅ |
| `analysis/p02_entities/outputs/entity_stats.json` | `e9526aadfd92f82f…` | `e9526aadfd92f82f…` | ✅ |
| `analysis/p02_entities/outputs/extraction_errors.json` | `4f53cda18c2baa0c…` | `4f53cda18c2baa0c…` | ✅ |
| `analysis/p03_routes/outputs/routes.jsonl` | `769df9f71beb9b36…` | `769df9f71beb9b36…` | ✅ |
| `analysis/p03_routes/outputs/hierarchy.json` | `6303d4890c6f1cfb…` | `6303d4890c6f1cfb…` | ✅ |
| `analysis/p03_routes/outputs/compare_official_vs_user.csv` | `6f336342b9850c16…` | `6f336342b9850c16…` | ✅ |
| `analysis/p05_conditions/outputs/conditions.jsonl` | `15abdc0e7f3e7966…` | `15abdc0e7f3e7966…` | ✅ |
| `analysis/p05_conditions/outputs/rejected.jsonl` | `4c43e53f19176b19…` | `4c43e53f19176b19…` | ✅ |
| `analysis/p05_conditions/outputs/condition_stats.json` | `5226dbf964bafa58…` | `5226dbf964bafa58…` | ✅ |
| `analysis/p05_conditions/outputs/dedup_report.md` | `e326637773e61e13…` | `e326637773e61e13…` | ✅ |
| `analysis/p05_conditions/outputs/eval_stats.json` | `02ee5acca2a1fe07…` | `02ee5acca2a1fe07…` | ✅ |
| `analysis/p05_conditions/outputs/eval_conditions.md` | `67ecde47a03e46ed…` | `67ecde47a03e46ed…` | ✅ |
| `analysis/p05_conditions/outputs/manual_review.csv` | `544e053d8b895f3a…` | `544e053d8b895f3a…` | ✅ |
| `analysis/p05_conditions/outputs/p6_condition_poi.csv` | `b53939a4a8c903d8…` | `b53939a4a8c903d8…` | ✅ |
| `analysis/p05_conditions/outputs/p6_bridge_stats.json` | `2dd6167baa70516f…` | `2dd6167baa70516f…` | ✅ |
| `analysis/p05_conditions/outputs/P6_接入说明.md` | `fe06719b1bf7710d…` | `fe06719b1bf7710d…` | ✅ |
| `analysis/p06_graph/outputs/graph_nodes.csv` | `ec0cdd938cb3e0dd…` | `ec0cdd938cb3e0dd…` | ✅ |
| `analysis/p06_graph/outputs/graph_edges.csv` | `72d1d08c888c1656…` | `72d1d08c888c1656…` | ✅ |
| `analysis/p06_graph/outputs/graph.graphml` | `05ad05d55d3e563a…` | `05ad05d55d3e563a…` | ✅ |

附加确定性：`cond_id_map.json` 两次 `--write` 后 sha 不变（`63eba8de…`，§6.3）；
`node_classification.csv` 两次 `--write` 后 sha 不变（`908ad15f…`，§11；`--check` 还会用规则重算逐行比对）。
完整 64 位 sha256 见运行日志（仓库外临时文件 `%TEMP%\t15_graph\snapshot_A.json` / `snapshot_B.json`）。

### 7.3 两个时间戳文件（掩码后相同）

**掩码规则**（只屏蔽自动生成时间，其他字节不动）：

- `graph_stats.json`：`\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}` → `<TS>`（仅 `generated_at` 字段）；
- `graph_qa.md`：同一 ISO 时间正则 + `时间：\S+` → `时间：<TS>`（仅页首「自动生成…｜时间：…」一行）。

| 文件 | pass A sha256 | pass B sha256 | 掩码后 |
|---|---|---|---|
| `analysis/p06_graph/outputs/graph_stats.json` | `1a94f7ee649aafe8…` | `12138606e1043f65…` | **相同**，掩码 sha256 = `d7b24e0eb0f469d8e066848cba983a2c4e559bfd4cc7b04c754e3d540ec6142c` |
| `analysis/p06_graph/outputs/graph_qa.md` | `f97c7e4323b00ce6…` | `322b28766620684b…` | **相同**，掩码 sha256 = `90d26140fb9bb2c24d9a193e40f8a405c297584c392c0a8b8ea796c10e5b488b` |

> 掩码值由「pass B vs pass C（再单独跑一次 `build_graph.py`，同 seed）」逐字节验证：两者原始字节不同、
> 掩码后完全相同，且掩码 sha 与上表一致。A/B 的图数据文件（`graph_nodes.csv`、`graph_edges.csv`、
> `graph.graphml`）逐字节相同，因此 A/B 的掩码内容必然相等；两张表里只剩 `generated_at` 一个变量。

### 7.4 为什么 PNG / XLSX 只要求“存在”，不做逐字节比较

- `analysis/p05_conditions/outputs/figures/condition_stats.png`、`analysis/p03_routes/outputs/figures/route_structure.png`、
  `analysis/p06_graph/outputs/figures/graph_*.png`：matplotlib 写 PNG 时会带 `Software`/时间等元数据，
  且字体渲染在不同调用间可能产生像素级差异；它们是**可视化产物**，正确性由对应数据文件保证。
- `analysis/p05_conditions/outputs/映射表.xlsx`：`openpyxl` 写 zip 容器时含 `docProps/core.xml` 的修改时间，
  逐字节不稳定；内容正确性由 `build_mapping.py rows=38 missing_source_url=0` 与 `conditions.jsonl` 保证。
- 以上文件在本次两遍中都**存在且非空**（大小见 §10/§11），未纳入严格 sha 清单（与任务口径一致）。

### 7.5 `graph.graphml` 的 hash-seed 前提（必须披露）

`graph.graphml` 的**边顺序**来自 `analysis/p06_graph/src/build_graph.py` 第 453–465 行的
`pois = {...}` / `trans = {...}`（Python `set`）与第 581 行 `for edge in B.edges.values()`，
即边插入顺序依赖 `PYTHONHASHSEED`。实测：

| 运行（同一套 247 节点输入） | graphml sha256 |
|---|---|
| `PYTHONHASHSEED=0` 第 1 次 | `05AD05D55D3E563A…`（= 本提交的 `05ad05d5…`） |
| `PYTHONHASHSEED=0` 第 2 次 | `05AD05D55D3E563A…`（逐字节相同） |
| `PYTHONHASHSEED=1` | `32E51531355FC32D…` |
| `PYTHONHASHSEED=2` | `B01CF0B59C03547E…` |

seed=1 与 seed=2 的文件**行集合完全相同**（`Compare-Object` 差异 0 行），只是边行顺序不同。
因此：**不固定 hash seed 时 graphml 逐字节不可复现**；本报告的两遍都固定 `PYTHONHASHSEED=0`，
并在 §8 的 `graph.graphml` 比较中逐字节通过。这是 P6 src 的既有缺陷（不是 T1.5 引入的数据变化），
修复建议见 §13：把 `for poi in pois` / `for t in trans` 改为 `sorted(...)`，或在写 GraphML 前对
`B.edges` 按 `(rel, src, dst)` 排序。

---

## 8. 冻结项证明

### 8.1 P2（对 `6813920`，旧 29 篇）

- 旧 29 篇 1006 条实体：**逐字段 0 差异**（`doc_id`/`entity_text`/`normalized_name`/`entity_type`/
  `char_start`/`char_end`/`sentence`/`method`/`confidence` 全等）；
- 要求重点核对的 `(entity_text, char_start, char_end, entity_type)` 元组：**0 处不同**；
- 逐篇实体数与旧完全相等（§4 矩阵）。

### 8.2 P3（对 `6813920`，旧 29 篇）

- 旧 226 个步骤行：**逐字段 0 差异**；
- 旧 `(route_id, step_no)` 序列完全一致（同 route 内 step_no 从 1 连续）；
- 逐篇路线数与旧完全相等；
- `time_source` 口径未变：旧 47 explicit / 179 absent 全部原样，新 40 步全为 absent（不推断）。

### 8.3 P5（对 `1c2a578`，旧 36 条）

- 旧 36 条 **逐字段（含 `cond_id`）0 差异**，行序保持 CND-0001…0036 在前；
- `eval_stats.json` 与旧 **JSON 深度相等**（`by_area`/`by_type`/`errors` 全部一致，说明 gold 标注没有错配）；
- `manual_review.csv` 归一化 CRLF 后与旧逐字节相同；
- 更严格地：`eval_stats.json` / `manual_review.csv` / `eval_conditions.md` / `rejected.jsonl` 的 **git blob**
  （经 LF 规范化）与 `1c2a578` **完全相同**（`git rev-parse :<path> == git rev-parse 1c2a578:<path>`），
  即提交内容零变化，工作区的 CRLF 只是 Windows 文本模式所致（§7.4）；
- 旧条件原文一条未丢：36/36 签名全部命中映射（`apply_stable_ids.py --check` exit 0）。

### 8.4 P6（对 `6813920`，旧 229 节点 / 523 边）

| 规则 | 结果 |
|---|---|
| 旧 `node_id` 全部仍在 | ✅ 229/229，缺失 0 |
| `node_type` / `name` / `scenic_area` 不变 | ✅ 0 处不同（含 33 个旧 `CONDITION\|CND-*` 节点，因 §6 稳定 ID 才能保持） |
| `properties` 不变 | ✅ 0 处不同 |
| `source_doc_ids` 只许变长 | ✅ 229/229 旧 doc 集合都是新集合的子集，0 处缩短 |
| `freq` 不下降 | ✅ 0 处下降（部分节点因新文档增加） |
| 旧 523 条 `(src,rel,dst)` 全部仍在 | ✅ 523/523，缺失 0（weight 可变） |

---

## 9. `WGS-T-04`（`is_valid=False` 难样本）

- **P2**：仍是 1 条实体（`TIME\|1天` 类），未被删除；`check_entities` 通过；
- **P3**：仍解析出 1 条路线 / 1 个步骤（prose 兜底），未被丢弃；
- **P5**：0 条。原文仅 33 字，无触发词/建议句，P5 从未覆盖它（重跑前也是 0），不是本次丢失；
- **P6**：1 个节点（P3-only 地点），0 条边（该步骤无 POI → 无 NEXT/CONTAINS 边）；
- 结论：难样本在 P2/P3/P6 保留，P5 不适用；未因重跑删除任何难样本。

---

## 10. 质量门（9 checks + 93 tests + eval dry-run）

见 §2 质量门表：9 个 `check_*.py` 全部 exit 0；`unittest` 93/93 OK；`run_eval.py --split dev --limit 1 --dry-run`
exit 0（dry-run 不执行，仓库无新增文件）。`classify_nodes.py --check` exit 0（详见 §11）。

命令（与任务 ⑧ 一致）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $py='.\.venv\Scripts\python.exe'
& $py -c "import json; s=json.load(open(r'analysis/p02_entities/outputs/entity_stats.json',encoding='utf-8')); print(s['documents_processed'], s['entities'], s['by_type'])"
& $py checks\check_scenic.py scenic\changlong\data\processed\changlong_guides.csv
& $py checks\check_scenic.py scenic\baiyunshan\data\processed\baiyunshan_guides.csv
& $py checks\check_scenic.py scenic\wugongshan\data\processed\wugongshan_guides.csv
& $py checks\check_entities.py
& $py checks\check_routes.py
& $py checks\check_conditions.py
& $py checks\check_graph.py analysis\p06_graph\outputs
& $py checks\check_coref.py
& $py checks\check_agent.py analysis\p07_agent
& $py -m unittest discover -s analysis\p07_agent\tests -q
& $py analysis\p07_agent\eval\run_eval.py --split dev --limit 1 --dry-run
& $py analysis\p06_graph\outputs\classify_nodes.py --check
```

`python -c` 第一行输出：`32 1118 {'TIME': 268, 'POI': 651, 'TRANSPORT': 199}`（exit 0）。

---

## 11. T1.4 分类器与 50 抽样更新（T1.5 handoff 处理）

### 11.1 分类器基线（`analysis/p06_graph/outputs/classify_nodes.py`）

| 项 | T1.4 | T1.5 |
|---|---|---|
| `BASELINE` | SCENIC_AREA 3 / POI 141 / TRANSPORT 8 / TIME 32 / ACTIVITY 12 / CONDITION 33 | **SCENIC_AREA 3 / POI 157 / TRANSPORT 8 / TIME 32 / ACTIVITY 13 / CONDITION 34** |
| 地点节点 | 152 | **168** |
| 非地点 | 77 | **79** |
| 合计 | 229 | **247** |
| `--check` 的“基线 152”硬编码 | — | 改为 `sum(BASELINE[t] for t in LOCATION_TYPES)`，不再写死数字 |
| 文档 needle | `152 + 77 = 229` | `168 + 79 = 247` |
| 抽样框说明 | 141 POI | 157 POI |

`--write` 重建后 `node_classification.csv`：**168 行**、
`attraction 99 / area 35 / transport 18 / facility 12 / food 3 / shop 1`，
`quality_flags` 非空 29 行（17.3%，全部为旧节点），0 空值、0 重复 `node_id`；
sha256 = `908ad15f95e858b960d2243abdefeb84f5587be592dc88daa51ea097455bfb6d`（两遍相同）。
`--check` exit 0。

`docs/optimization/NODE_CLASSIFICATION.md` 已同步更新：§1 结论、§2 范围（168+79=247）、§4.5/4.6 方法/置信、
§5 分类统计、§6 抽样（157 框、50 抽、3 噪声）、§7 难样本占比、§8.4（P2 已覆盖 32 篇）、§9 sha、§10/§11 数字。
50 抽样表逐条结论表已按新样本重写。

### 11.2 50 抽样（`analysis/p02_entities/outputs/node_noise_sample50.csv`）

- 抽样框：`graph_nodes.csv` 中 `node_type=POI` 的 **157** 个节点（T1.4 为 141）；
- seed 仍为 `20261115`，`random.Random(20261115).sample(sorted(poi_ids), 50)`，`sample_no` 1..50；
- 与 T1.4 样本重合 **24 条**，新抽中 **26 条**；已判过的 24 条沿用原 `is_noise`/`noise_reason`，
  26 条新抽中节点按同一噪声定义读原文重判（证据句逐字来自 `entities.jsonl`/`clean_content`，`--check` 校验）；
- 结果：**3/50 = 6%**（< 10% 门槛，通过）。噪声项：

| # | 节点 | 景区 | 判定 |
|---:|---|---|---|
| 5 | `结束愉快之旅` | 武功山 | 句子片段（「下午…返程，结束愉快之旅。」），不指代地点 |
| 13 | `乘索道下山` | 武功山 | 动作，不是交通设施名（对照「中庵索道」） |
| 40 | `乘金顶索道` | 武功山 | 动作，不是交通设施名（对照「金顶索道」） |

- Wilson 95% 区间 **2.1%–16.2%**（上限 > 10%），只能写“点估计通过”，不能写“稳定低于 10%”；
- 3 条噪声均来自新增 `WGS-O-08`，是 P3 把动作/片段当 POI；`DROP_POI` 未覆盖新文档（见 §13）。

---

## 12. tag / `version_tag` 提案（只写表，不创建、不改文件）

### 12.1 建议 tag（二选一，推荐 A）

| 方案 | tag | 理由 | 风险 |
|---|---|---|---|
| **A（推荐）分层 patch** | `v0.2.1-p02`、`v0.3.1-p03`、`v0.5.1-p05`、`v0.6.1-p06` | 四层各自有独立 owner 与 `handover.yaml`；下游 `inputs[].from_tag` 可按层精确 pin；P5 兼容层只影响 P5/P6，独立 tag 便于回滚 | 需打 4 个 tag、4 次 owner 复核；P5 tag 绑定临时兼容层（需在修复后升 v0.5.2） |
| B 阶段 tag | `v0.8-g2-graph` | 一次 tag 覆盖“32 篇全链路”这一里程碑，便于 D2 阶段验收 | 与既有 `pNN` 命名体系不一致；P7 的 `p06` `from_tag` 会指向非项目 tag，交接卡需要额外说明 |

若选 A，建议在 P5 owner 修复 src 后：
`v0.5.2-p05`（删除兼容层），再视需要打 `v0.6.2-p06`（graphml 排序修复）。**本任务不创建任何 tag。**

### 12.2 `handover.yaml` 的 `version_tag` 建议值（不改文件）

| 项目 | 当前 `version_tag` | 建议值 | 说明 |
|---|---|---|---|
| `standards/handover/p02_entities.yaml` | `v0.2-p02` | **`v0.2.1-p02`** | 32 篇 / 1118 实体；旧 29 篇冻结 |
| `standards/handover/p03_routes.yaml` | `v0.3-p03` | **`v0.3.1-p03`** | 38 路线 / 266 步；旧 226 步冻结 |
| `standards/handover/p05_conditions.yaml` | `v0.5-p05` | **`v0.5.1-p05`** | 38 条 / 34 唯一；含临时 stable-id 兼容层（须注明） |
| `standards/handover/p06_graph.yaml` | `v0.6-p06` | **`v0.6.1-p06`** | 247 节点 / 577 边；旧 229/523 冻结 |

### 12.3 本提交文件清单（全部在白名单内）

`git diff --name-status 6813920..HEAD` 的变更范围只有：
`analysis/p02_entities/outputs/**`（`entities.jsonl`、`entity_stats.json`、`node_noise_sample50.csv`）、
`analysis/p03_routes/outputs/**`（`routes.jsonl`、`hierarchy.json`、`compare_official_vs_user.csv`、`figures/route_structure.png`）、
`analysis/p05_conditions/outputs/**`（8 个改动文件 + 新增 `apply_stable_ids.py`、`cond_id_map.json`，共 10 个）、
`analysis/p06_graph/outputs/**`（`graph_nodes.csv`、`graph_edges.csv`、`graph.graphml`、`graph_stats.json`、`graph_qa.md`、`node_classification.csv`、`classify_nodes.py`、`figures/*.png`）、
`docs/optimization/NODE_CLASSIFICATION.md`、`docs/optimization/GRAPH_RERUN_REPORT.md`。
`analysis/*/src/**`、`config/**`、`report/**`、`standards/**`、`lib/**`、`checks/**`、`scenic/**`、`analysis/p07_agent/**`
均未改（`triggers.csv` 亦未变，见 §13.2）。

---

## 13. 已知限制 / 未解释项 / 待人工

### 13.1 P6 新增节点中的可疑 POI（未删，按规则保留）

新增 16 个 POI 中，至少 10 个是 P3 把动作/句子片段当 POI（`DROP_POI` 是 T1.4 之前的静态清单，未覆盖新文档）：

`乘索道下山`、`乘金顶索道`、`可乘索道到中庵`、`到达中庵`、`到达石鼓寺`、`到达十万亩天上草原`、
`天马印蹄瀑下山`、`山下路线:武功山航空飞行营地`、`纵揽湘赣风云`、`结束愉快之旅`；
另有 `ACTIVITY|返回` 也不像活动名。建议 P3/P6 owner 在下一版把 `乘X`、`到达X`、`结束…`、`返回`、
`…下山` 等模式加入过滤（本任务只记录，不删节点、不改 src）。

### 13.2 `triggers.csv`

`extract_conditions.py` 每次都会重写 `analysis/p05_conditions/config/triggers.csv`。本次两遍重写后与 HEAD
**逐字节相同**（6770 bytes，sha256 `c15d6944139b0fd6…`，`git status` 未出现该文件），因此未做 restore。

### 13.3 `graph_qa.md` 的一处硬编码文案

`graph_qa.md` 第 3 条仍写「…；3 条重复记录默认过滤」，实际现在是 **4** 条重复
（`CND-0014/0015/0022/0038`）。这是 `analysis/p06_graph/src/build_graph.py` 里写死的文案，
本任务不改 src，已在 §5.3 标注；建议 P6 owner 改成从 `p6_bridge_stats.json.duplicates` 读取。

### 13.4 新增近重复/成对节点

- `飚水岩瀑布`（新，WGS-O-08）与既有 `飙水岩瀑布`（旧，WGS-O-01）是同一瀑布的两种写法，P6 未合并；
- `红岩谷` 与 `武功山红岩谷景区`、`中庵` 与 `紫极宫（中庵）` 仍是“点位/片区/同址别名”关系，P6 按既有规则保留双节点；
- 分类上 `红岩谷` 走 `name_rule:area_geo`（0.70）、`武功山红岩谷景区` 走 `name_rule:area`（0.90），属 `scope_ambiguous` 家族，
  但 T1.4 的 `OVERRIDES` 只覆盖旧节点，新节点未加人工覆盖（保持规则原样）。

### 13.5 T1.4 遗留的 3 个 handoff 疑点（T1.5 未改 P6 src）

1. `金顶` scope_ambiguous（官方列为四大景区之一 vs 主峰目的地）——分类仍 `attraction 0.65`；
2. `中庵` / `紫极宫` alias_mismatch——P6 仍保留双节点，分类仍 `attraction 0.70`；
3. `途经好汉坡` 与 `好汉坡` 重复——节点保留，分类 `attraction 0.70` + `alias_mismatch`。

以上均在 `NODE_CLASSIFICATION.md` §7 难样本表，未在 T1.5 改 P6 融合规则。

### 13.6 `graph.graphml` 确定性依赖环境变量

见 §7.5：不固定 `PYTHONHASHSEED` 时 graphml 边序不同（行集合相同）。建议 P6 src 修复前，
所有下游复现实验都带上 `PYTHONHASHSEED=0`，或直接消费 `graph_edges.csv`（已按 `(rel,src,dst)` 排序）。

### 13.7 没有发现“无法解释的旧数据变化”

除 §6 的 cond_id 重编号（已用兼容层恢复并逐字段验证）外，未发现旧 29 篇在任何层的语义变化；
无未解释项。

---

## 14. Handoff（给 T1.6 / T3.3 / P7 依赖方）

1. **P2/P3/P5/P6 的 doc 覆盖**：P2/P3/P6 = 32 篇；P5 = 15 篇（覆盖率 15/31 = 48.39%）。`WGS-O-09` 无 P5 条件。
2. **P6 节点变化**：+18。新增 POI 16 个（其中 10 个可疑，见 §13.1）、`ACTIVITY|返回`、`CONDITION|CND-0037`。
   旧 229 节点/523 边全部保留；新边 54 条（CONTAINS/NEXT/BY_TRANSPORT/HAS_CONDITION）。
3. **新增低置信地点节点**（`confidence ≤ 0.70`，建议下游按需复核）：
   `到达十万亩天上草原`、`山下路线:武功山航空飞行营地`、`纵揽湘赣风云`、`结束愉快之旅`（fallback 0.70）、
   `天马印蹄瀑下山`、`红岩谷`（area_geo 0.70）。
4. **无分类节点**：`ACTIVITY|返回`、`CONDITION|CND-0037` 属非地点类型，按 T1.4 口径显式排除（不是漏分类）。
5. **条件 ID**：CND-0001…0036 保持 `1c2a578` 原值，新增 CND-0037（WGS-O-07，入图）/ CND-0038（WGS-O-08，重复过滤）。
   P7 若消费条件节点，不要再做“按序号猜语义”。
6. **复现约定**：`PYTHONHASHSEED=0` + `PYTHONIOENCODING=utf-8`；命令序列见 §2；P5 需先跑
   `apply_stable_ids.py --write` 再跑下游。
7. **临时文件**：`cond_id_map.json` / `apply_stable_ids.py` 是 D2 临时兼容层，P5 src 修好后应整体删除并升 `v0.5.2-p05`。

---

## 15. 附：确定性日志与临时证据位置（仓库外，不入库）

`%TEMP%\t15_graph\`：

- `snapshot_A.json` / `snapshot_B.json`：两遍的计数 + 21 个文件的 sha256；
- `frozen_compare.json` / `final_verify.json`：冻结对照与覆盖矩阵的机器输出；
- `passA.log` / `passB.log`：两遍每条命令的完整 stdout/stderr 与退出码；
- `base/`、`legacy_conditions.jsonl`：`git show 6813920:***` / `1c2a578:***` 的只读导出（用于对照）。
