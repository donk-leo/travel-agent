# 项目 7：测试记录

运行时间（UTC）：2026-11-03T09:16:46.634136+00:00；模型：`qwen3:8b`。
所有需求均为人工设计的测试输入；“火星大峡谷”是用于无匹配测试的虚构名称。原始机器结果见 [evaluation_results.json](evaluation_results.json)。

| 场景 | 输入与现象 | 状态 | 人工检查 | 会话轨迹 |
|---|---|---|---|---|
| 亲子与老人一日游 | 我想带孩子和老人去长隆玩一天，喜欢游乐项目，尽量少走路。 | `complete` | 提取出孩子、老人和少走路；路线 18 段均有 NEXT 证据，但存在重复路段，无法确认少走路及一日可行性。 | [记录](sessions/session_3629eec0861b48b58a5743f824bac6d8.jsonl) |
| 朋友白云山一日游 | 我和朋友去广州白云山玩一天，喜欢自然风景和拍照，希望少爬坡。 | `complete` | 图谱路线通过连接检查，偏好与限制提取正确；同行“朋友”遗漏，路线存在重复。 | [记录](sessions/session_a6928a80dfb74539b610e991271cf114.jsonl) |
| 伴侣武功山两日游 | 我和伴侣去武功山玩两天，想看日出、欣赏自然风景，预算有限，希望行程不要太累。 | `complete` | 识别两天、伴侣、预算与体力偏好；有图谱路线，但未分配两天行程，费用及日出时间缺少依据。 | [记录](sessions/session_d15f7c63bfd24240b42cd0c2ad00f14c.jsonl) |
| 缺少景区与天数 | 我想和父母出去玩，希望行程轻松一点。 | `clarify` | 未生成路线，追问景区和天数。 | [记录](sessions/session_4954f7276e564ce8b475a7e6e5280511.jsonl) |
| 追问后补充 | 我想和父母出去玩，希望行程轻松一点。 / 广州白云山，一天。 | `complete` | 把两句合并后识别父母、白云山、一天及轻松偏好；本条为合并文本实测，网页会话衔接另由离线测试检查。 | [记录](sessions/session_0c47b5f59f0446e6986f5eaee272d0f9.jsonl) |
| 冲突需求 | 我想一天游遍武功山的所有景点，但不能步行，也不能乘坐任何交通工具。 | `clarify` | 识别要求难以同时满足，追问调整；未展示路线。 | [记录](sessions/session_fdf93c705afe439a8932db7259417c2d.jsonl) |
| 图谱无匹配（人工虚构的名称） | 广州白云山有没有叫火星大峡谷的景点？ | `complete` | 按虚构关键词查询图谱，结果为空并提示确认名称；不证明现实中不存在。 | [记录](sessions/session_1036c022300c423a95fa8f7386ef9e2d.jsonl) |
| 查询白云山地点 | 广州白云山有哪些景点？ | `complete` | 按景区列出图谱中 42 条 POI 记录；这些是抽取节点，不等于官方完整景点名录。 | [记录](sessions/session_5aa092241931485da235215a9397e695.jsonl) |

## 本次观察

- 后续网页体验发现模型将白云山一日游识别为规划请求，却只选择了建议和景点列表、没有查询路线。已增加系统兜底：规划请求漏选路线工具时补充调用，并在会话中记录“系统补充”。该分支由 `test_plan_request_queries_route_if_model_omits_it` 覆盖；本地模型隔离网页实测中显示了路线且 14 段连接通过图谱核验。该实测使用临时会话文件，与下表原始案例分开。
- 网页两轮实测：首轮“和父母出去玩”追问景区和天数；第二轮补充“广州白云山，一天”后，保留“父母”和“希望行程轻松一点”。分别见[首轮轨迹](sessions/session_932995abba9c47f2ba68033c07c8f368.jsonl)和[补充后轨迹](sessions/session_cf6973276e154d1ea621b2b2db4a817a.jsonl)。
- `complete` 表示流程返回了结果，`clarify` 表示提出补充或冲突问题；它们不等于人工判定路线一定可行。
- 路线存在但图谱连接核验不通过时，状态改为 `partial` 并保留路线提示，不再标为 `complete`；规划请求的 POI 关键词无名称匹配时，会列出当前景区或子园区全部 POI 供选择，而不是只显示空结果。人群/体验偏好词（儿童、亲子、老人、情侣、刺激、少走路等）不再当地点名搜索，页面标题为“当前范围地点”，并注明列表未按偏好过滤。
- 亲子老人、朋友白云山和伴侣武功山三条路线分别有 18、18、5 条 `NEXT` 连接通过程序核验；该核验不验证路况、距离、坡度、价格、时间或适龄性。
- 白云山测试中“朋友”未进入 `traveler_profiles`；亲子与白云山路线出现重复节点；上表武功山两日记录是修改前运行结果，当时没有逐日安排。
- 2026-11-09 本地修改后，多日请求会把 `duration_days` 传给路线规划，并按 `day_plan` 分天展示；模型未给出或分组不合法时按节点数均分并标注不确定性。该版本尚未重跑完整真实模型案例。
- 条件建议与模型理由可能带有未经证实的“减少步行”“适合老人”等推测；天气、费用、时间和项目适用性仍需核实。
- 曾出现“拍日落”的建议配上“错峰出行”理由：已改为每条建议单独生成理由，但模型仍可能生成不准确内容；失败现象和后续方案见章节报告。
- 曾出现模型在图谱查询前断言陌生景点不存在；现在对没有约束的普通信息查询直接查图谱。前后真实轨迹可分别查看 [修正前](sessions/session_5d34a42ed29948c8a4219b0ed5a79615.jsonl) 和 [修正后](sessions/session_1036c022300c423a95fa8f7386ef9e2d.jsonl)。

## 路线整理与子园区范围（2026-11-09 离线复算）

以下数字由 `python3 analysis/p07_agent/src/analyze_route_optimization.py` 从 `evaluation_results.json` 中的模型原始路线确定性复算得到，**不重新调用模型**：

| 案例 | 景区 | 模型原始路线 | 整理后 | 是否变化 | 算法 |
|---|---|---|---|---|---|
| 亲子与老人一日游（`family_elder_one_day`） | 长隆 | 18 步 / 重复 6 | 13 步 / 重复 1 | 是 | held_karp |
| 朋友白云山一日游（`friends_one_day`） | 广州白云山 | 18 步 / 重复 6 | 17 步 / 重复 5 | 是 | held_karp |
| 伴侣武功山两日游（`couple_two_days`） | 武功山 | 5 步 / 重复 1 | 5 步 / 重复 1 | 否 | original |
| 追问后补充（`followup_combined`） | 广州白云山 | 14 步 / 重复 4 | 10 步 / 重复 0 | 是 | held_karp |

- 步数指图谱 `NEXT` 连接的段数，不是实际步行距离；“重复”指同一地点在路线中再次出现。整理只改变顺序与连接方式，目标地点集合不变，逐段来源仍可核验；武功山案例的返程终点（中庵索道）被保留。
- `evaluation_results.json` 仍是 2026-11-03 优化前的真实运行记录。本次没有重跑本地模型（当前机器未运行 Ollama），因此没有把离线复算结果伪装成新的模型输出。
- 子园区范围由 `tests/test_sub_area_scope.py` 覆盖（19 条）：别名识别、与 P1 `subtype` 对照、景点归属（含跨园区记为未知）、候选与景点筛选、回退说明、agent 透传。
- 路线整理由 `tests/test_route_optimization.py` 覆盖（8 条）：指标统计、重复循环整理、返程终点保留、补全绕开已访问节点、`plan_route` 集成（模拟模型）与子园区候选过滤。

## 离线检查与复现

`python3 -m unittest discover -s analysis/p07_agent/tests -v` 使用真实 P6 图谱与模拟模型/工具，检查连接核验、补全、追问上下文、矛盾拦截、无匹配、决策轮次、子园区范围、路线整理、多日分天、偏好词回退与跨文档核验（共 60 条）。模拟案例不作为真实模型表现。

`python3 analysis/p07_agent/src/analyze_route_optimization.py` 读取已有真实模型路线，离线输出整理前后对照，不调用模型、不改原始结果。

`python3 analysis/p07_agent/src/run_evaluation.py` 用本地 Ollama 重跑上述人工设计的真实模型请求，生成新的 `evaluation_results.json` 和会话轨迹。模型输出、用时及文件名可能变化；本报告是本次运行的人工记录，重跑后应重新核对。

## 2026-11-10 第二轮非 UI 修复后

- 离线测试：`python -m unittest discover -s analysis/p07_agent/tests -q` 共 **60 条通过**；新增覆盖跨文档路线、无路线 `partial`、分天 fallback `partial`、条件去重/上限/季节性、同行人补全、`check_plan` 完整 payload。
- 真实查询“我想去萍乡武功山风景名胜区玩三天，带孩子”：约 68.6 秒；`status=partial`；路线 25 节点，13 处连接缺失，`day_plan` 9/11/5（模型分天，非均分），3 条建议；不再返回 `complete`。
- 当前 `valid` 只表示逐段有 NEXT 证据；`fully_verified` 还要求同来源连续。页面/结果若显示 `partial`，应理解为“有参考路线，但不能证明可行”。
- 会话默认写到 `%LOCALAPPDATA%\p07_agent_sessions`；仓库内旧 `outputs/sessions/*.jsonl` 是历史记录，不再新增。`run_evaluation.py` 会把有路线但 `fully_verified` 不为 true 的案例计为失败。
- 8 案例真实评估：第一次完整跑完，结果为 `family_elder_one_day`、`friends_one_day`、`couple_two_days`、`followup_combined` 均 `partial`，`missing_information`/`conflicting_constraints` 为 `clarify`，`no_match`/`list_pois` 为 `complete`；但会话目录设在用户 `%TEMP%` 时当前运行环境报 `WinError 5`，8 条记录均因无 trace 被计失败。改用工作区可写目录重跑 11 分钟仅完成 2 例，遂中止。`evaluation_results.json` 因此仍保留 2026-11-03 旧记录，完整重跑需在可写 `P07_SESSION_DIR` 下单独执行。

## 2026-11-11 P6 路线连续性收尾

- 路线规划改为**单来源文档**：`route_planner.select_primary_candidate` 按“用户点名地点数、连接数、官方优先”选一份候选，后续模型、修复、优化、分天都只用这份文档的 `NEXT` 边；结果写 `source_doc_id`，核验通过时提示“单一来源”。这样不再出现跨文档拼接的假连续。
- 若模型仍生成缺环路线，截断到第一处缺环前的可核验前缀，标记 `route_truncated=true`；Agent 返回 `partial`，不把后半段当成完整路线。
- 路线请求限制 `num_predict=1800`、`num_ctx=8192`，其他模型调用限制 `num_predict=1200`；JSON 解析失败降级为空路线并提示，不再抛异常。
- 离线测试：`python -m unittest discover -s analysis/p07_agent/tests -q` 共 **64 条通过**；新增单来源选择、单来源路线核验、子园区候选与截断分支覆盖。
- 真实查询“我想去萍乡武功山风景名胜区玩三天，带孩子”：65.5 秒；`status=partial`；`source_doc_id=WGS-O-05`；`valid=true`、`fully_verified=true`、跨文档 0、缺段 0；10 节点；`route_truncated=true`；`day_plan` 4/3/3（均分 fallback）；3 条建议。路线本身已通过单一来源核验，`partial` 只因截断和分天均分。
- 8 案例完整评估在最新代码上重跑时，前两例约 2 分钟完成：`family_elder_one_day` 返回 `complete`（12 节点全部通过单一来源核验），`friends_one_day` 返回 `partial`（截断到 5 节点可核验前缀）。第三例 `couple_two_days` 卡住超过 10 分钟仍未完成，遂中止，其余 5 例未跑。单例耗时不适合一次跑完，本轮不把未完成的评估写成结果；`evaluation_results.json` 仍是 2026-11-03 旧记录。单来源与截断逻辑由 64 条离线测试、上述真实查询和已完成的两例验证。

## 2026-11-11 网页输出与单点子园区修复

- 新增 `src/itinerary.py`：把已核验路线按天拆成“上午/中午/下午”的自然语言行程，网页新增“建议行程”块；不再只显示箭头链。行程不调用模型，开放时间、距离、餐饮与适龄性继续提示以现场为准。
- 模型返回空 `node_ids` 时，用单一来源候选的最长连续 NEXT 链兜底（最多 12 个节点），并注明“按单一来源最长连续链兜底”；避免武功山三日游页面没有路线。
- 水上乐园在 P6 中只有一个地点节点、没有独立 NEXT 连接；现在返回单点 proposal（`single_destination=true`），只生成该园区的“单点一日游”行程，不再回退整个景区拼出“野生动物世界→水上乐园”。
- `trace_log` 不再在导入时调用 `tempfile.gettempdir()`，默认写 `%LOCALAPPDATA%\p07_agent_sessions`；修复受限环境下 Flask 启动报 `FileNotFoundError`、网页“无法访问”的问题。
- 离线测试：`python -m unittest discover -s analysis/p07_agent/tests -q` 共 **69 条通过**；`check_agent.py` 通过（11 会话/152 步）。
- 真实查询“带孩子去武功山玩三天”：86.0 秒；`status=partial`；`source_doc_id=WGS-O-05`；`valid=true`、`fully_verified=true`；12 节点；`day_plan` 4/4/4；网页显示第 1/2/3 天及上午/中午/下午。
- 真实查询“带孩子去长隆水上乐园玩一天”：22.9 秒；`status=partial`；单节点“长隆水上乐园”；网页显示“建议行程”和“没有独立路线连接”，并只保留水上乐园节点。
- 这两条查询仍为 `partial`：三日游的 `day_plan` 是均分展示，水上乐园没有园内路线；页面会把原因写出来，不再显示为完整可行方案。
