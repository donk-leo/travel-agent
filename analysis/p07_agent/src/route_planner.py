import json
import urllib.request

from condition_selector import find_relevant_conditions
from sub_area_scope import SUB_AREA_ANCHORS, filter_route_candidates
from tools import (
    get_route_candidates,
    optimize_route,
    repair_route,
    route_metrics,
    validate_route,
)


from config import ROUTE_MAX_TOKENS, ROUTE_NUM_CTX, MODEL, OLLAMA_URL

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "node_ids": {
            "type": "array",
            "items": {"type": "string"}
        },
        "day_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer"},
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["day", "node_ids"]
            }
        },
        "explanation": {"type": "string"},
        "uncertainties": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["node_ids", "explanation", "uncertainties"]
}

SYSTEM_PROMPT = """
你是旅游路线规划助手。

根据用户需求，从提供的图谱连接中规划一条可能合适的路线。
优先在同一来源文档内规划，不要把不同来源文档的片段拼成一条“连续”路线；
如果无法避免跨文档，必须在 explanation/uncertainties 中明确说明缺环，
不能声称已经核验通过。路线中相邻两个节点必须存在从前一个节点指向
后一个节点的 NEXT 连接。

要求：
1. node_ids 按游览顺序填写，节点 ID 必须来自候选连接。
2. 综合考虑用户的同行人群、偏好和限制条件，允许合理规划。
3. 不要编造图谱中没有的连接、距离或具体时间。
4. 无法确认的适用条件或信息写入 uncertainties。
5. 如果无法规划出至少两个节点的路线，node_ids 返回空列表，
   并在 explanation 中说明原因。
6. 参考 condition_suggestions 里的条件建议及其来源。
7. 如果 scope.sub_area 不为空，说明用户指定了子园区：只使用该范围内的
   地点规划，不要把其它子园区的地点加进来。
8. 尽量让路线少走回头路：同一段连接不要重复走；确实需要返回分岔点时，
   在 explanation 里说明原因。
9. 如果输入的 duration_days >= 2，必须同时返回 day_plan：按天分组，
   每天至少一个节点，day 从 1 开始连续编号，所有 node_ids 按原顺序
   恰好覆盖一次；每天只能包含整体路线中的连续片段。
10. explanation 不超过 80 字；uncertainties 最多 3 条、每条不超过 50 字。
    只输出 JSON，不要输出 JSON 之外的说明。
11. node_ids 最多 12 个节点。候选连接更长时，只选其中连续的一段核心路线，
    不要为了凑数跳过中间节点，也不要把整条长链全部抄进来。
可以提出合理推测；对于图谱中没有明确提供的步行距离、游玩时长或
适用条件，不要直接说已经确定，请在 uncertainties 中说明需要确认的内容。
"""


def _coerce_days(value):
    """把意图里的天数转成正整数；没有天数或格式不对时返回 None。"""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days >= 1 else None


def _node_names(candidates):
    """从候选连接里收集节点 ID 到名称的映射，供页面按天展示。"""
    names = {}
    for group in candidates or []:
        for connection in group.get("connections", []):
            names[connection.get("from_node_id")] = connection.get("from_name", "")
            names[connection.get("to_node_id")] = connection.get("to_name", "")
    return names


def _normalize_day_plan(node_ids, raw_plan, days):
    """校验模型给的分天方案；不合法时按节点数均分，并返回是否回退。"""
    node_ids = list(node_ids or [])
    if not node_ids:
        return [], False
    if days <= 1:
        return [{"day": 1, "node_ids": node_ids}], False

    if isinstance(raw_plan, list):
        groups = []
        flattened = []
        valid = True
        for item in raw_plan:
            if not isinstance(item, dict):
                valid = False
                break
            day = item.get("day")
            ids = item.get("node_ids")
            if (not isinstance(day, int) or isinstance(day, bool)
                    or not isinstance(ids, list) or not ids
                    or not all(isinstance(node_id, str) for node_id in ids)):
                valid = False
                break
            groups.append({"day": day, "node_ids": ids})
            flattened.extend(ids)
        if (valid and flattened == node_ids and len(groups) == days
                and sorted(group["day"] for group in groups) == list(range(1, days + 1))):
            groups.sort(key=lambda group: group["day"])
            return groups, False

    # 模型没有按天分组，或分组与 node_ids 对不上时，按节点数均分。
    # 这只是展示分组，不代表每日强度合理；调用方会写入 uncertainties。
    group_count = min(days, len(node_ids))
    base, extra = divmod(len(node_ids), group_count)
    groups = []
    start = 0
    for index in range(group_count):
        size = base + (1 if index < extra else 0)
        groups.append({
            "day": index + 1,
            "node_ids": node_ids[start:start + size]
        })
        start += size
    for day in range(group_count + 1, days + 1):
        groups.append({"day": day, "node_ids": []})
    return groups, True


def _doc_is_official(doc_id):
    return "-O-" in (doc_id or "")


def select_primary_candidate(candidates, user_text, scope_applied=False):
    """选一份来源作为本次规划的唯一依据。

    P6 的 NEXT 边来自不同游记，跨文档拼接看起来连续，实际不能证明是
    同一条路线。这里优先选用户原文点到地点最多的来源；用户没有点名时，
    普通查询优先官方路线，指定子园区时优先该范围内连接最多的那份。
    """
    if not candidates:
        return None

    official_bonus = 1 if scope_applied else 10

    def score(item):
        names = {
            edge["from_name"] for edge in item["connections"]
        } | {
            edge["to_name"] for edge in item["connections"]
        }
        matched = sum(
            1 for name in names
            if len(name) >= 2 and name in user_text
        )
        return (
            matched,
            len(item["connections"])
            + (official_bonus if _doc_is_official(item["source_doc_id"]) else 0),
            len(names),
        )

    return max(candidates, key=score)


def _candidate_chain(candidates):
    """从单份来源的连接中还原最长连续节点链，作为模型失败时的兜底。"""
    adjacency = {}
    all_nodes = set()
    for candidate in candidates or []:
        for connection in candidate.get("connections", []):
            source = connection.get("from_node_id")
            target = connection.get("to_node_id")
            if not source or not target:
                continue
            adjacency.setdefault(source, []).append(target)
            all_nodes.add(source)
            all_nodes.add(target)

    best = []

    def walk(node, path, seen):
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for next_node in adjacency.get(node, []):
            if next_node in seen:
                continue
            walk(next_node, path + [next_node], seen | {next_node})

    for node in all_nodes:
        walk(node, [node], {node})
    return best


def _clean_list(values):
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def plan_route(user_text, scenic_area, conditions=None, trace=None,
               sub_area=None, days=None, profiles=None, preferences=None,
               constraints=None):
    days = _coerce_days(days)
    profiles = _clean_list(profiles)
    preferences = _clean_list(preferences)
    constraints = _clean_list(constraints)
    system_prompt = SYSTEM_PROMPT
    if days and days > 1:
        system_prompt += (
            f"\n本次 duration_days={days}，请把 node_ids 分成 {days} 天，"
            "并在 day_plan 中逐天列出连续节点。"
        )
    if profiles or preferences or constraints:
        requirement_lines = ["\n用户约束（规划时必须显式考虑，不能忽略）："]
        if profiles:
            requirement_lines.append(
                "- 同行人：" + "、".join(profiles) + "。"
            )
        if preferences:
            requirement_lines.append(
                "- 偏好：" + "、".join(preferences) + "。"
            )
        if constraints:
            requirement_lines.append(
                "- 限制：" + "、".join(constraints) + "。"
            )
        requirement_lines.append(
            "如果图谱没有足够信息验证某项约束（如适龄、步行距离、开放时间），"
            "必须在 uncertainties 中说明，不要声称已经满足。"
        )
        system_prompt += "\n".join(requirement_lines)

    def call_tool(name, function, **arguments):
        if trace is None:
            return function(**arguments)
        return trace.call_tool(name, function, **arguments)

    all_candidates = call_tool(
        "get_route_candidates",
        get_route_candidates,
        scenic_area=scenic_area
    )

    empty_scope = {
        "requested": sub_area,
        "applied": False,
        "fallback": bool(sub_area),
        "note": "该景区没有查询到路线连接。",
        "kept_docs": [],
        "dropped_docs": [],
    }

    if not all_candidates:
        return {
            "proposal": None,
            "validation": None,
            "message": "该景区没有查询到路线连接。",
            "scope": empty_scope,
            "metrics": None,
            "source_doc_id": None,
        }

    # 用户指定子园区时，只保留该园区的来源文档；连接不足会回退整个景区。
    scope = filter_route_candidates(all_candidates, sub_area, scenic_area)
    candidates = scope["candidates"]

    primary = select_primary_candidate(
        candidates, user_text, scope_applied=scope["applied"]
    )
    if primary is not None:
        candidates = [primary]

    if conditions is None:
        conditions = find_relevant_conditions(
            user_text, scenic_area, trace=trace
        )

    # 有些子园区（如长隆水上乐园）在 P6 里只有一个地点节点，没有独立的
    # NEXT 连接。此时不要回退到整个景区再拼一条包含野生动物世界的路线，
    # 只返回该园区地点，由上层按“单点一日游”处理。
    anchor = SUB_AREA_ANCHORS.get(sub_area) if sub_area else None
    if anchor and not scope["applied"]:
        names = _node_names(candidates)
        if anchor in names:
            node_ids = [anchor]
            validation = validate_route(node_ids, candidates)
            proposal = {
                "node_ids": node_ids,
                "node_names": names,
                "day_plan": [{"day": 1, "node_ids": node_ids}],
                "duration_days": days,
                "explanation": (
                    f"图谱没有「{sub_area}」的独立连续路线，"
                    "只提供该园区地点，不虚构园内连接。"
                ),
                "uncertainties": [
                    "园内项目顺序、开放时间和餐饮位置需要以现场为准。"
                ],
                "source_doc_id": primary["source_doc_id"] if primary else None,
            }
            if profiles or preferences or constraints:
                proposal["user_constraints"] = {
                    "profiles": profiles,
                    "preferences": preferences,
                    "constraints": constraints,
                }
            single_scope = dict(scope)
            # 单点分支不扩大范围；清掉“已扩大到整个景区”的通用提示，
            # 避免和实际返回的单点路线矛盾。
            single_scope["note"] = ""
            return {
                "proposal": proposal,
                "validation": validation,
                "message": (
                    f"「{sub_area}」在图谱中没有独立路线连接，"
                    "只保留该园区地点，供一日行程参考。"
                ),
                "scope": single_scope,
                "metrics": route_metrics(node_ids, candidates),
                "source_doc_id": primary["source_doc_id"] if primary else None,
                "single_destination": True,
            }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_request": user_text,
                        "duration_days": days,
                        "scope": {
                            "scenic_area": scenic_area,
                            "sub_area": sub_area if scope["applied"] else None,
                            "note": scope["note"],
                        },
                        "route_candidates": candidates,
                        "condition_suggestions": conditions
                    },
                    ensure_ascii=False
                )
            }
        ],
        "format": ROUTE_SCHEMA,
        "think": False,
        "options": {"temperature": 0, "num_predict": ROUTE_MAX_TOKENS,
                    "num_ctx": ROUTE_NUM_CTX},
        "stream": False
    }

    # 最多尝试两次：首次规划，失败后根据核验结果重新规划
    validation = None
    for attempt in range(2):
        request = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)

        try:
            proposal = json.loads(result["message"]["content"])
        except json.JSONDecodeError:
            # 本地小模型在长路线/多日分天时偶尔会把 JSON 截断。
            # 不把整个请求抛成 error，交给上层按“路线未通过核验”处理。
            proposal = {
                "node_ids": [],
                "explanation": "模型返回的路线 JSON 不完整，未生成可用路线。",
                "uncertainties": ["模型输出被截断，建议缩短行程或重试。"],
            }
        if primary is not None:
            proposal["source_doc_id"] = primary["source_doc_id"]
        if profiles or preferences or constraints:
            proposal["user_constraints"] = {
                "profiles": profiles,
                "preferences": preferences,
                "constraints": constraints,
            }

        # 本地小模型有时会返回空 node_ids（JSON 截断或直接放弃）。候选
        # 连接本身来自单一来源，按最长连续链兜底，避免页面完全无路线。
        if len(proposal.get("node_ids") or []) < 2:
            chain = _candidate_chain(candidates)
            if len(chain) >= 2:
                proposal["node_ids"] = chain[:12]
                proposal["explanation"] = (
                    "模型没有生成可用节点，已按单一来源的最长连续链生成兜底路线；"
                    "这不是模型自由编造的路线。"
                )
                proposal.setdefault("uncertainties", []).append(
                    "兜底路线按图谱连接顺序生成，具体游玩时长和体力强度需要确认。"
                )

        validation = call_tool(
            "validate_route",
            validate_route,
            node_ids=proposal["node_ids"],
            candidates=candidates
        )
        if sub_area and not scope["applied"]:
            proposal.setdefault("uncertainties", []).append(
                scope["note"] or f"子园区「{sub_area}」未应用，路线可能包含其他园区的地点。"
            )
        if validation["valid"]:
            break

        if attempt == 0:
            feedback = {
                "message": (
                    "上一条路线未通过图谱核验。请根据候选连接重新规划，"
                    "确保每两个相邻节点都有方向正确的 NEXT 连接。"
                    "可以根据游览需要返回分岔点；如果路线重复经过节点，请说明原因。"
                ),
                "validation": validation
            }

            payload["messages"].append({
                "role": "assistant",
                "content": json.dumps(proposal, ensure_ascii=False)
            })
            payload["messages"].append({
                "role": "user",
                "content": json.dumps(feedback, ensure_ascii=False)
            })

    if not validation["valid"]:
        repair_info = call_tool(
            "repair_route",
            repair_route,
            node_ids=proposal["node_ids"],
            candidates=candidates
        )
        if repair_info["repaired"]:
            proposal["node_ids"] = repair_info["node_ids"]
            validation = repair_info["validation"]

            # 补全后路线发生了变化，使用新的说明
            proposal["explanation"] = (
                "根据原规划和图谱连接补全了中间游览步骤，"
                "每段连接均可查看来源。"
            )

            proposal["uncertainties"].append(
                "补全路径的实际步行距离、坡度和游玩时长需要进一步确认。"
            )

    # 模型常把“终点”后又接回另一个起点，形成一段无法补全的反向跳转。
    # 与其展示一条 1 处缺环的完整路线，不如截断到最后一个可核验节点，
    # 并把“被截断”作为 partial 的原因交给上层。
    if not validation["valid"]:
        missing = (validation.get("missing_connections") or [None])[0]
        if missing:
            for index in range(len(proposal["node_ids"]) - 1):
                if (proposal["node_ids"][index] == missing["from_node_id"]
                        and proposal["node_ids"][index + 1] == missing["to_node_id"]):
                    prefix = proposal["node_ids"][:index + 1]
                    prefix_validation = validate_route(prefix, candidates)
                    if len(prefix) >= 2 and prefix_validation["valid"]:
                        proposal["node_ids"] = prefix
                        validation = prefix_validation
                        proposal["route_truncated"] = True
                        missing_name = missing.get("from_name") or missing["from_node_id"].split("|")[-1]
                        proposal["uncertainties"].append(
                            f"原路线在「{missing_name}」之后缺少 NEXT 连接，"
                            "已截断到可核验前缀。"
                        )
                    break

    metrics = route_metrics(proposal["node_ids"], candidates)

    # 图谱连接核验通过后，再做一次确定性整理：在保留起点（和返程终点）的
    # 前提下重排目标地点，减少同一批景点被反复经过的情况。
    if validation["valid"]:
        optimization = optimize_route(proposal["node_ids"], candidates)
        if trace is not None:
            trace.record_event("route_optimization", observation={
                "method": optimization["method"],
                "optimized": optimization["optimized"],
                "before": optimization["original_metrics"],
                "after": optimization["metrics"],
            })

        metrics = optimization["metrics"]
        if optimization["optimized"]:
            proposal["node_ids"] = optimization["node_ids"]
            validation = optimization["validation"]
            proposal["uncertainties"].append(optimization["note"])
            proposal["explanation"] = (
                (proposal.get("explanation") or "").strip()
                + "（程序已按图谱 NEXT 连接重排地点顺序以减少重复经过，"
                  "逐段来源见核验结果。）"
            ).strip()

    if validation["valid"]:
        repeated_names = [
            node_id.split("|")[-1] for node_id in metrics["repeated_node_ids"]
        ]
        if repeated_names:
            proposal["uncertainties"].append(
                "路线仍会重复经过：" + "、".join(repeated_names)
                + "；返回分岔点可能是合理的。"
                "图谱没有实际距离、坡度和通行情况数据，"
                "不能据此比较实际体力消耗。"
            )
        else:
            proposal["uncertainties"].append(
                "图谱没有实际距离、坡度和通行情况数据，"
                "不能据此比较实际体力消耗。"
            )

    if days:
        names = _node_names(candidates)
        node_ids = proposal.get("node_ids") or []
        day_plan, day_plan_fallback = _normalize_day_plan(
            node_ids, proposal.get("day_plan"), days
        )
        proposal["duration_days"] = days
        proposal["day_plan"] = day_plan
        proposal["day_plan_fallback"] = bool(days > 1 and day_plan_fallback)
        proposal["day_plan_source"] = "even_split" if proposal["day_plan_fallback"] else "model"
        proposal["node_names"] = {
            node_id: names.get(node_id) or node_id.split("|")[-1]
            for node_id in node_ids
        }
        if days > 1 and day_plan_fallback:
            proposal.setdefault("uncertainties", []).append(
                "天数分组按节点数均分，仅用于展示，未考虑每日步行强度、"
                "住宿点和开放时间；请结合实际情况调整。"
            )

    if validation["valid"]:
        if validation.get("fully_verified") is False:
            message = "路线逐段连接存在，但跨来源文档无法证明连续。"
        else:
            message = "路线连接已通过图谱核验。"
        if primary is not None:
            source_type = "官方路线" if _doc_is_official(primary["source_doc_id"]) else "游记"
            message += f"（单一来源：{source_type} {primary['source_doc_id']}）"
        if scope["applied"]:
            message += f"（查询范围：{scenic_area} · {sub_area}）"
    else:
        message = "路线连接未通过图谱核验，需要重新规划。"

    return {
        "proposal": proposal,
        "validation": validation,
        "message": message,
        "scope": scope,
        "metrics": metrics,
        "source_doc_id": primary["source_doc_id"] if primary is not None else None,
    }


if __name__ == "__main__":
    from trace_log import SessionTrace

    user_text = "我和朋友去广州白云山玩一天，喜欢自然风景和拍照，希望少爬坡。"
    trace = SessionTrace()

    result = plan_route(user_text, scenic_area="广州白云山", trace=trace)

    print("路线结果：", result["message"])
    print("记录的工具：", [event["tool"] for event in trace.events])
