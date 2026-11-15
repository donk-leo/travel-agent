"""旅游 Agent 主流程：理解需求、决策、查询图谱、检查并记录结果。"""

import json

from condition_selector import find_relevant_conditions
from constraint_checker import check_constraints, check_plan
from intent_parser import parse_intent
from itinerary import build_itinerary
from route_planner import plan_route
from scenic_aliases import CANONICAL_AREAS, canonicalize_scenic_area
from status import (
    STATUS_CLARIFY, STATUS_ERROR, STATUS_PARTIAL, STATUS_VERIFIED,
    build_what_verified, is_contract_violation, make_reason, normalize_status,
)
from sub_area_scope import detect_sub_area, filter_poi_results
from tool_decider import decide_next_step
from tool_selector import select_tools
from tools import search_poi
from trace_log import SessionTrace


MAX_DECISION_ROUNDS = 3
ALLOWED_TOOLS = {"get_conditions", "get_route_candidates", "search_poi"}

# 这些词描述的是人群或体验偏好，不是地点名称；拿去做 POI 名称搜索必然为空。
PREFERENCE_KEYWORDS = (
    "儿童", "孩子", "小朋友", "亲子", "宝宝", "幼儿", "带娃", "遛娃",
    "老人", "长辈", "父母", "情侣", "朋友", "年轻人",
    "刺激", "轻松", "少走路", "省力",
)


def _is_preference_keyword(value):
    text = str(value or "").strip()
    return bool(text) and any(token in text for token in PREFERENCE_KEYWORDS)


def _keep_sub_area_suggestions(suggestions, sub_area):
    """只保留在任意字段中明确提到该子园区的建议。"""
    if not sub_area:
        return list(suggestions or [])
    return [
        item for item in (suggestions or [])
        if sub_area in json.dumps(item, ensure_ascii=False)
    ]


def _check_message(check, fallback):
    message = " ".join(
        str(value).strip()
        for value in (check.get("explanation"), check.get("question"))
        if value
    ).strip()
    return message or fallback


def _reason_text(*candidates, default):
    """取第一条非空文案，避免把空白字符串写进 reasons（reasons[].text 必须非空）。"""
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _check_reason_code(check_status):
    """约束检查未通过时的原因码：冲突归 constraint_conflict，缺信息归 missing_slot。"""
    return "constraint_conflict" if check_status == "conflict" else "missing_slot"


def _route_problems(route, days):
    """返回路线不能判 verified 的全部原因；空列表表示可判 verified。

    判定口径与旧版一致（PRODUCT_SPEC.md §5.1 对 verified 的定义）：只看逐段
    NEXT 证据、单一来源、未截断、未按节点数均分兜底、子园区范围已落实。
    """
    if route is None:
        return []
    problems = []
    proposal = route.get("proposal") or {}
    validation = route.get("validation") or {}
    if route.get("single_destination"):
        problems.append(make_reason(
            "single_destination",
            _reason_text(route.get("message"),
                         default="该子园区只提供地点级建议，没有连续路线。")
        ))
    elif not proposal.get("node_ids"):
        problems.append(make_reason(
            "empty_match",
            _reason_text(route.get("message"), default="没有生成可用的路线节点。")
        ))
    elif validation.get("valid") is not True or validation.get("fully_verified") is False:
        missing = validation.get("missing_connections") or []
        cross_doc = validation.get("cross_doc_transitions") or 0
        if missing:
            problems.append(make_reason("missing_connection", (
                f"路线连接未通过图谱核验（{len(missing)} 处缺失），"
                "已保留路线供参考；请调整需求，或改用景区官方路线。"
            )))
        elif cross_doc:
            problems.append(make_reason("cross_doc", (
                f"路线有 {cross_doc} 处跨来源文档跳转，"
                "这些分段不能证明属于同一条连续路线；"
                "已保留路线供参考，请改用单一来源的官方路线或调整需求。"
            )))
        else:
            problems.append(make_reason(
                "missing_connection",
                "路线未通过图谱核验，已保留路线供参考；请调整需求。"
            ))
    elif proposal.get("route_truncated"):
        problems.append(make_reason("route_truncated", (
            "原路线在缺环处被截断，只保留了能够逐段核验的前半段；"
            "后半段需要调整需求或改用官方路线后重新规划。"
        )))
    elif days and days > 1 and proposal.get("day_plan_fallback"):
        problems.append(make_reason("day_plan_fallback", (
            "多日行程的天数分组是按节点数均分的展示结果，"
            "没有校验每日步行强度、住宿点和开放时间；请按实际体力重新分配。"
        )))

    scope = route.get("scope") or {}
    # 单点园区本来就只返回地点级建议，不能用“子园区未应用”再记一条原因。
    if (not route.get("single_destination")
            and scope.get("requested") and not scope.get("applied")):
        problems.append(make_reason("scope_not_applied", _reason_text(
            scope.get("note"),
            default=f"子园区「{scope.get('requested')}」未应用，路线可能包含其他园区的地点。"
        )))
    return problems


def run_agent(user_text):
    """执行一次请求；追问上下文由调用方传入完整文本。

    返回值 ``status`` 只可能是 ``verified`` / ``partial`` / ``clarify`` / ``error``
    四值之一，并同时带 ``reasons`` 与 ``what_verified``。契约出处：
    ``docs/optimization/PRODUCT_SPEC.md`` §5；HappinessJo 2026-11-15 按「建议默认」
    签字，见 ``travel-agent-run/optimization/state/G0_GATE.md`` §9。
    """
    result = {
        "query": user_text, "intent": None,
        "decision": None, "tool_selection": None, "tool_decisions": [],
        "suggestions": [], "route": None, "poi_results": None,
        "poi_list_all": False, "message": "", "error": "", "scope": None,
        "itinerary": None, "needs_followup": False, "reasons": [],
        "what_verified": None, "trace_file": "", "trace_json": "",
        "trace_error": ""
    }
    trace = SessionTrace()
    trace.record_event("user_input", user_request=user_text)

    try:
        if not user_text.strip():
            raise ValueError("请输入旅行需求。")

        intent = parse_intent(user_text)
        result["intent"] = intent
        trace.record_event("intent", observation=intent)

        # 解析器已经做过一次归一化；这里再兜一层，兼容直接调用 run_agent
        # 或测试中传入旧版解析器结果的情况。
        raw_area = intent.get("scenic_area")
        resolved_area = canonicalize_scenic_area(raw_area)
        area = resolved_area or raw_area
        if resolved_area and resolved_area != raw_area:
            intent["scenic_area"] = resolved_area
            result["intent"] = intent
            trace.record_event("scenic_area_canonicalized", observation={
                "raw": raw_area, "canonical": resolved_area
            })

        # 子园区范围：用户说“长隆欢乐世界”时，景区名归一为“长隆”，这里再把
        # 子园区单独记下来，后续查询优先限制在对应园区。
        sub_area = intent.get("sub_area")
        scope_note = ""
        if area == "长隆":
            if not sub_area:
                sub_area, scope_note = detect_sub_area(user_text)
            intent["sub_area"] = sub_area
            if sub_area or scope_note:
                trace.record_event("sub_area_scope", observation={
                    "scenic_area": area, "sub_area": sub_area, "note": scope_note
                })
        else:
            sub_area = None
            intent["sub_area"] = None
        result["scope"] = {"scenic_area": area, "sub_area": sub_area, "note": scope_note}
        if scope_note:
            result["message"] = scope_note

        decision = decide_next_step(user_text, intent)
        if decision.get("decision") not in {"clarify", "query_graph", "reply"}:
            raise ValueError("决策器返回了无效的下一步。")
        if decision.get("request_type") not in {"plan", "info", "other"}:
            raise ValueError("决策器返回了无效的需求类型。")

        # 不在图谱覆盖范围内的名称不能当成“查到了但结果为空”。直接追问，
        # 避免用户看到成功状态 + 空路线却不知道是名称写法的问题。
        clarify_code = "missing_slot"
        if decision["decision"] == "query_graph" and raw_area and not resolved_area:
            clarify_code = "unsupported_area"
            display_area = str(raw_area).strip()[:30]
            decision = {
                "decision": "clarify",
                "request_type": decision["request_type"],
                "reason": "景区名称不在当前图谱覆盖范围内。",
                "response": (
                    f"目前图谱只覆盖{'、'.join(CANONICAL_AREAS)}；"
                    f"没有识别出“{display_area}”对应的景区。"
                    "请确认景区名称，或换用图谱中的名称。"
                )
            }

        days = intent.get("duration_days")
        missing = not area or (decision["request_type"] == "plan" and not days)
        if decision["decision"] == "query_graph" and missing:
            clarify_code = "missing_slot"
            question = "请补充景区名称和游玩天数。" if decision["request_type"] == "plan" else "请补充景区名称。"
            decision = {"decision": "clarify", "request_type": decision["request_type"],
                        "reason": "查询所需的信息缺失，需要先补充。", "response": question}
        result["decision"] = decision
        trace.record_event("decision", decision=decision)

        if decision["decision"] == "clarify":
            message = decision.get("response") or "请补充景区名称和游玩天数。"
            result.update(
                status=STATUS_CLARIFY, needs_followup=True, message=message,
                reasons=[make_reason(clarify_code, _reason_text(
                    decision.get("response"), decision.get("reason"), message,
                    default="请补充景区名称和游玩天数。"))]
            )
        elif decision["decision"] == "reply":
            # 旧状态 reply（问候/非规划）按 §5.4 归入 clarify：本质是等用户给需求。
            message = decision.get("response") or "你好！我可以帮你规划游览路线。"
            result.update(
                status=STATUS_CLARIFY, message=message,
                reasons=[make_reason("missing_slot", _reason_text(
                    decision.get("reason"), message,
                    default="本次请求是问候，需要先说明景区与游玩天数。"))]
            )
        else:
            result["needs_followup"] = True
            if decision["request_type"] == "info" and not intent.get("constraints"):
                # 普通事实查询不需要模型先推断地点是否存在；交给图谱查询。
                requirement_check = {"status": "ok", "explanation": "纯信息查询交由图谱核实。", "question": ""}
            else:
                requirement_check = check_constraints(user_text)
            trace.record_event("requirement_check", observation=requirement_check)
            if requirement_check["status"] != "ok":
                check_message = _check_message(
                    requirement_check, "需求需要进一步确认，请补充或调整。")
                result.update(
                    status=STATUS_CLARIFY, message=check_message,
                    reasons=[make_reason(
                        _check_reason_code(requirement_check["status"]), check_message)]
                )
            else:
                clarified = _query_graph(result, trace, user_text, area, days, sub_area)
                if clarified:
                    result["reasons"] = [make_reason("missing_slot", _reason_text(
                        result.get("message"), default="请补充具体需求。"))]
                else:
                    problems = _route_problems(result["route"], days)
                    if problems:
                        result.update(
                            status=STATUS_PARTIAL,
                            needs_followup=True,
                            reasons=problems,
                            message=" ".join(filter(None, [result["message"], problems[0]["text"]]))
                        )
                    elif result["route"] is None and not result["suggestions"]:
                        # 仅展示图谱原始名称匹配，没有生成行动建议。
                        plan_check = {"status": "ok", "explanation": "仅展示图谱查询结果。", "question": ""}
                        trace.record_event("plan_check", observation=plan_check)
                        result.update(status=STATUS_VERIFIED, needs_followup=False)
                        if result["poi_results"] == []:
                            result["message"] = " ".join(filter(None, [
                                result["message"], "图谱中没有找到匹配地点，请确认名称或尝试其他关键词。"
                            ]))
                    else:
                        plan_check = check_plan(user_text, result["route"], result["suggestions"])
                        trace.record_event("plan_check", observation=plan_check)
                        if plan_check["status"] != "ok":
                            check_message = _check_message(
                                plan_check, "方案与需求可能存在冲突，请补充或调整。")
                            result.update(
                                status=STATUS_CLARIFY, needs_followup=True,
                                message=check_message,
                                reasons=[make_reason(
                                    _check_reason_code(plan_check["status"]), check_message)],
                                suggestions=[], route=None, poi_results=None)
                        else:
                            result.update(status=STATUS_VERIFIED, needs_followup=False)
                            if result["poi_results"] == [] and not result["suggestions"] and result["route"] is None:
                                result["message"] = " ".join(filter(None, [
                                    result["message"], "图谱中没有找到匹配地点，请确认名称或尝试其他关键词。"
                                ]))
                            elif not result["suggestions"] and result["route"] is None and result["poi_results"] is None:
                                result["message"] = " ".join(filter(None, [
                                    result["message"], "暂时没有找到匹配的条件建议。"
                                ]))
        if result.get("route"):
            # 单点子园区（如水上乐园）的条件建议来自整个景区，容易把其他园区的
            # 项目写进本园区行程；只保留确实提到该子园区的建议。
            if sub_area and result["route"].get("single_destination"):
                before = len(result["suggestions"])
                result["suggestions"] = _keep_sub_area_suggestions(
                    result["suggestions"], sub_area
                )
                if before and not result["suggestions"]:
                    result["message"] = " ".join(filter(None, [
                        result["message"],
                        f"图谱中没有「{sub_area}」专属的条件建议，未展示其他园区的建议。"
                    ]))
            requirements = _route_requirements(result)
            result["itinerary"] = build_itinerary(
                result["route"], result.get("suggestions"), area, sub_area,
                profiles=requirements["profiles"],
                preferences=requirements["preferences"],
                constraints=requirements["constraints"])
    except Exception as exc:
        error_text = _reason_text(str(exc), default="内部异常，未生成行程。")
        result.update(
            status=STATUS_ERROR, error=str(exc), needs_followup=True,
            reasons=[make_reason("model_error", error_text)]
        )
    finally:
        _finalize_result_status(result)
        trace.record_event("final_answer", final_answer={
            "status": result["status"], "message": result["message"], "error": result["error"],
            "route": result["route"], "suggestions": result["suggestions"],
            "poi_results": result["poi_results"]
        })
        try:
            result["trace_json"] = json.dumps(trace.events, ensure_ascii=False, indent=2)
            result["trace_file"] = trace.save().name
        except Exception as exc:
            # 会话记录只是可复现性材料；保存失败不应把已生成的行程标成失败。
            result["trace_error"] = f"会话记录未保存（不影响行程结果）：{exc}"

    return result


def _finalize_result_status(result):
    """把返回状态收敛到四值，并补齐 ``reasons`` / ``what_verified``。

    PRODUCT_SPEC.md §5.1 只允许 ``verified`` / ``partial`` / ``clarify`` / ``error``；
    §5.4 规定 ``None`` / 缺失 / 未定义值一律按 ``error`` 并记 ``contract_violation=1``；
    §5.1 规定 ``verified`` 的原因清单必须为空，其余三态必须非空。
    """
    raw_status = result.get("status")
    if is_contract_violation(raw_status):
        result["contract_violation"] = 1
    status = normalize_status(raw_status)
    result["status"] = status

    reasons = [item for item in (result.get("reasons") or []) if isinstance(item, dict)]
    if status == STATUS_VERIFIED:
        reasons = []
    elif not reasons:
        fallback_code = {
            STATUS_PARTIAL: "empty_match",
            STATUS_CLARIFY: "missing_slot",
            STATUS_ERROR: "model_error",
        }[status]
        fallback_text = _reason_text(
            result.get("message"), result.get("error"), default="未生成行程。")
        reasons = [make_reason(fallback_code, fallback_text)]
    result["reasons"] = reasons
    result["what_verified"] = build_what_verified(status, result.get("route"))


def _route_requirements(result):
    """把意图解析出的同行人/偏好/限制整理成 planner 可用的列表。"""
    intent = result.get("intent") or {}
    return {
        "profiles": intent.get("traveler_profiles") or [],
        "preferences": intent.get("preferences") or [],
        "constraints": intent.get("constraints") or [],
    }


def _query_graph(result, trace, user_text, area, days, sub_area=None):
    """按有限轮次选择工具，基于真实返回结果决定是否补查。

    返回 ``True`` 表示查询阶段已经给出 ``clarify`` 结论；``False`` 表示没有
    阻断性问题，由 ``run_agent`` 继续判定 ``verified`` / ``partial``。
    """
    observations = []
    executed = set()
    route_needs_refresh = False
    clarified = False

    for _ in range(MAX_DECISION_ROUNDS):
        selection = trace.call_tool(
            "select_tools", select_tools, user_text=user_text,
            observations=observations, executed_tools=sorted({key[0] for key in executed})
        )
        result["tool_decisions"].append(selection)
        if result["tool_selection"] is None:
            result["tool_selection"] = selection
        tool_names = selection.get("tools")
        if not isinstance(tool_names, list) or any(
            not isinstance(name, str) or name not in ALLOWED_TOOLS for name in tool_names
        ):
            raise ValueError("工具选择器返回了无效工具。")
        # A planning request needs route evidence even if the model omitted it.
        # Keep the model's original choice in the trace and record this addition separately.
        if (result["decision"]["request_type"] == "plan"
                and "get_route_candidates" not in tool_names
                and not any(key[0] == "get_route_candidates" for key in executed)):
            tool_names = [*tool_names, "get_route_candidates"]
            adjustment = {
                "kind": "system_adjustment",
                "tools": ["get_route_candidates"],
                "reason": "行程规划需要图谱路线连接，系统补充路线查询。"
            }
            result["tool_decisions"].append(adjustment)
            trace.record_event("decision_adjustment", decision=adjustment)
        if not tool_names:
            if not executed:
                result.update(status=STATUS_CLARIFY, needs_followup=True,
                              message="暂时无法确定查询方式，请补充具体需求。")
                clarified = True
            break

        progressed = False
        # 同轮先查询条件，路线规划时可以参考这些结果。
        for name in ("get_conditions", "search_poi", "get_route_candidates"):
            if name not in tool_names:
                continue
            mode = selection.get("search_mode") if name == "search_poi" else ""
            keyword = selection.get("search_keyword") if name == "search_poi" else ""
            preference_note = ""
            if name == "search_poi":
                if mode == "keyword" and _is_preference_keyword(keyword):
                    preference_note = (
                        f"“{str(keyword).strip()}”是人群或体验偏好，不是地点名称；"
                        "已改为列出当前范围全部地点，未按偏好过滤。"
                    )
                    mode, keyword = "all_pois", ""
                if mode == "all_pois":
                    keyword, limit = "", 10000
                elif mode == "keyword" and isinstance(keyword, str) and keyword.strip():
                    keyword, limit = keyword.strip(), 10
                else:
                    result.update(status=STATUS_CLARIFY, needs_followup=True,
                                  message="请补充要查询的景点名称关键词。")
                    return True
            key = (name, mode, keyword)
            if key in executed or (name != "search_poi" and any(k[0] == name for k in executed)):
                continue
            if name == "get_route_candidates" and not days:
                result.update(status=STATUS_CLARIFY, needs_followup=True, message="请补充游玩天数，以便规划路线。")
                return True
            executed.add(key)
            progressed = True

            if name == "get_conditions":
                result["suggestions"] = find_relevant_conditions(user_text, area, trace=trace)
                if result["route"] is not None:
                    route_needs_refresh = True
                observations.append({"tool": name, "count": len(result["suggestions"]),
                                     "examples": [x["condition"] for x in result["suggestions"][:5]]})
            elif name == "search_poi":
                # 指定子园区时先放宽取数上限，筛选后再截断，避免截断在园区外地点上。
                scoped_limit = 10000 if sub_area else limit
                poi_results = trace.call_tool(
                    "search_poi", search_poi, keyword=keyword, scenic_area=area, limit=scoped_limit)
                poi_scope_note = ""
                if sub_area:
                    raw_count = len(poi_results)
                    poi_results, poi_scope_note = filter_poi_results(poi_results, sub_area, area)
                    if mode == "keyword" and len(poi_results) > 10:
                        poi_results = poi_results[:10]
                    trace.record_event("sub_area_filter", observation={
                        "sub_area": sub_area, "raw_count": raw_count,
                        "kept": len(poi_results), "note": poi_scope_note,
                    })
                fallback_used = False
                # 行程规划里的“儿童友好/刺激”等偏好常被当作 POI 关键词，
                # 直接返回空会让页面误以为景区没有地点；此时列出全景区地点供选择。
                if (not poi_results and mode == "keyword"
                        and result["decision"].get("request_type") == "plan" and area):
                    fallback_results = trace.call_tool(
                        "search_poi", search_poi, keyword="", scenic_area=area, limit=10000)
                    if sub_area:
                        fallback_results, fallback_note = filter_poi_results(
                            fallback_results, sub_area, area)
                        poi_scope_note = " ".join(filter(None, [poi_scope_note, fallback_note]))
                    if fallback_results:
                        poi_results = fallback_results
                        fallback_used = True
                        result["message"] = "没有找到名称匹配的地点，已改为列出当前范围全部地点，供你判断。"
                result["poi_results"] = poi_results
                result["poi_list_all"] = mode == "all_pois" or fallback_used
                if preference_note:
                    result["message"] = " ".join(filter(None, [result["message"], preference_note]))
                if poi_scope_note:
                    result["message"] = " ".join(filter(None, [result["message"], poi_scope_note]))
                observations.append({"tool": name, "keyword": keyword,
                                     "count": len(poi_results), "fallback": fallback_used,
                                     "examples": poi_results[:5]})
            else:
                requirements = _route_requirements(result)
                result["route"] = plan_route(
                    user_text, area, conditions=result["suggestions"],
                    trace=trace, sub_area=sub_area, days=days,
                    profiles=requirements["profiles"],
                    preferences=requirements["preferences"],
                    constraints=requirements["constraints"])
                route_scope = result["route"].get("scope") or {}
                if route_scope.get("note"):
                    result["message"] = " ".join(filter(None, [result["message"], route_scope["note"]]))
                validation = result["route"].get("validation") or {}
                observations.append({"tool": name, "valid": validation.get("valid", False),
                                     "missing_connections": validation.get("missing_connections", []),
                                     "message": result["route"].get("message", "")})
        if not progressed:
            break
    else:
        result["message"] = "已达到查询轮次上限，结果可能不完整。"
        trace.record_event("decision_limit", observation={
            "max_rounds": MAX_DECISION_ROUNDS,
            "message": result["message"]
        })

    if route_needs_refresh and result["route"] is not None:
        requirements = _route_requirements(result)
        result["route"] = plan_route(
            user_text, area, conditions=result["suggestions"],
            trace=trace, sub_area=sub_area, days=days,
            profiles=requirements["profiles"],
            preferences=requirements["preferences"],
            constraints=requirements["constraints"])
        route_scope = result["route"].get("scope") or {}
        if route_scope.get("note"):
            result["message"] = " ".join(filter(None, [result["message"], route_scope["note"]]))

    return clarified
