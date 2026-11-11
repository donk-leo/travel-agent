"""旅游 Agent 主流程：理解需求、决策、查询图谱、检查并记录结果。"""

import json

from condition_selector import find_relevant_conditions
from constraint_checker import check_constraints, check_plan
from intent_parser import parse_intent
from route_planner import plan_route
from scenic_aliases import CANONICAL_AREAS, canonicalize_scenic_area
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


def _check_message(check, fallback):
    return " ".join(filter(None, [check.get("explanation"), check.get("question")])) or fallback


def _route_problem(route, days):
    """返回路线不可直接标 complete 的原因；空字符串表示可用。"""
    if route is None:
        return ""
    proposal = route.get("proposal") or {}
    validation = route.get("validation") or {}
    if not proposal.get("node_ids"):
        return route.get("message") or "没有生成可用的路线节点。"

    if validation.get("valid") is not True or validation.get("fully_verified") is False:
        missing = validation.get("missing_connections") or []
        cross_doc = validation.get("cross_doc_transitions") or 0
        if missing:
            return (
                f"路线连接未通过图谱核验（{len(missing)} 处缺失），"
                "已保留路线供参考；请调整需求，或改用景区官方路线。"
            )
        if cross_doc:
            return (
                f"路线有 {cross_doc} 处跨来源文档跳转，"
                "这些分段不能证明属于同一条连续路线；"
                "已保留路线供参考，请改用单一来源的官方路线或调整需求。"
            )
        return "路线未通过图谱核验，已保留路线供参考；请调整需求。"

    if proposal.get("route_truncated"):
        return (
            "原路线在缺环处被截断，只保留了能够逐段核验的前半段；"
            "后半段需要调整需求或改用官方路线后重新规划。"
        )

    if days and days > 1 and proposal.get("day_plan_fallback"):
        return (
            "多日行程的天数分组是按节点数均分的展示结果，"
            "没有校验每日步行强度、住宿点和开放时间；请按实际体力重新分配。"
        )

    scope = route.get("scope") or {}
    if scope.get("requested") and not scope.get("applied"):
        return scope.get("note") or (
            f"子园区「{scope.get('requested')}」未应用，路线可能包含其他园区的地点。"
        )
    return ""


def run_agent(user_text):
    """执行一次请求；追问上下文由调用方传入完整文本。"""
    result = {
        "status": "working", "query": user_text, "intent": None,
        "decision": None, "tool_selection": None, "tool_decisions": [],
        "suggestions": [], "route": None, "poi_results": None,
        "poi_list_all": False, "message": "", "error": "", "scope": None,
        "needs_followup": False, "trace_file": "", "trace_json": ""
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
        # 避免用户看到 complete + 空路线却不知道是名称写法的问题。
        if decision["decision"] == "query_graph" and raw_area and not resolved_area:
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
            question = "请补充景区名称和游玩天数。" if decision["request_type"] == "plan" else "请补充景区名称。"
            decision = {"decision": "clarify", "request_type": decision["request_type"],
                        "reason": "查询所需的信息缺失，需要先补充。", "response": question}
        result["decision"] = decision
        trace.record_event("decision", decision=decision)

        if decision["decision"] == "clarify":
            result.update(status="clarify", needs_followup=True,
                          message=decision.get("response") or "请补充景区名称和游玩天数。")
        elif decision["decision"] == "reply":
            result.update(status="reply", message=decision.get("response") or "你好！我可以帮你规划游览路线。")
        else:
            result["needs_followup"] = True
            if decision["request_type"] == "info" and not intent.get("constraints"):
                # 普通事实查询不需要模型先推断地点是否存在；交给图谱查询。
                requirement_check = {"status": "ok", "explanation": "纯信息查询交由图谱核实。", "question": ""}
            else:
                requirement_check = check_constraints(user_text)
            trace.record_event("requirement_check", observation=requirement_check)
            if requirement_check["status"] != "ok":
                result.update(status="clarify", message=_check_message(
                    requirement_check, "需求需要进一步确认，请补充或调整。"))
            else:
                _query_graph(result, trace, user_text, area, days, sub_area)
                if result["status"] == "working":
                    route_problem = _route_problem(result["route"], days)
                    if route_problem:
                        result.update(
                            status="partial",
                            needs_followup=True,
                            message=" ".join(filter(None, [result["message"], route_problem]))
                        )
                    elif result["route"] is None and not result["suggestions"]:
                        # 仅展示图谱原始名称匹配，没有生成行动建议。
                        plan_check = {"status": "ok", "explanation": "仅展示图谱查询结果。", "question": ""}
                        trace.record_event("plan_check", observation=plan_check)
                        result.update(status="complete", needs_followup=False)
                        if result["poi_results"] == []:
                            result["message"] = " ".join(filter(None, [
                                result["message"], "图谱中没有找到匹配地点，请确认名称或尝试其他关键词。"
                            ]))
                    else:
                        plan_check = check_plan(user_text, result["route"], result["suggestions"])
                        trace.record_event("plan_check", observation=plan_check)
                        if plan_check["status"] != "ok":
                            result.update(status="clarify", needs_followup=True,
                                          message=_check_message(plan_check, "方案与需求可能存在冲突，请补充或调整。"),
                                          suggestions=[], route=None, poi_results=None)
                        else:
                            result.update(status="complete", needs_followup=False)
                            if result["poi_results"] == [] and not result["suggestions"] and result["route"] is None:
                                result["message"] = " ".join(filter(None, [
                                    result["message"], "图谱中没有找到匹配地点，请确认名称或尝试其他关键词。"
                                ]))
                            elif not result["suggestions"] and result["route"] is None and result["poi_results"] is None:
                                result["message"] = " ".join(filter(None, [
                                    result["message"], "暂时没有找到匹配的条件建议。"
                                ]))
    except Exception as exc:
        result.update(status="error", error=str(exc), needs_followup=True)
    finally:
        trace.record_event("final_answer", final_answer={
            "status": result["status"], "message": result["message"], "error": result["error"],
            "route": result["route"], "suggestions": result["suggestions"],
            "poi_results": result["poi_results"]
        })
        try:
            result["trace_json"] = json.dumps(trace.events, ensure_ascii=False, indent=2)
            result["trace_file"] = trace.save().name
        except Exception as exc:
            message = f"工具记录保存失败：{exc}"
            result["error"] = f'{result["error"]}；{message}' if result["error"] else message

    return result


def _query_graph(result, trace, user_text, area, days, sub_area=None):
    """按有限轮次选择工具，基于真实返回结果决定是否补查。"""
    observations = []
    executed = set()
    route_needs_refresh = False

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
                result.update(status="clarify", needs_followup=True,
                              message="暂时无法确定查询方式，请补充具体需求。")
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
                    result.update(status="clarify", needs_followup=True,
                                  message="请补充要查询的景点名称关键词。")
                    return
            key = (name, mode, keyword)
            if key in executed or (name != "search_poi" and any(k[0] == name for k in executed)):
                continue
            if name == "get_route_candidates" and not days:
                result.update(status="clarify", needs_followup=True, message="请补充游玩天数，以便规划路线。")
                return
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
                result["route"] = plan_route(
                    user_text, area, conditions=result["suggestions"],
                    trace=trace, sub_area=sub_area, days=days)
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
        result["route"] = plan_route(
            user_text, area, conditions=result["suggestions"],
            trace=trace, sub_area=sub_area, days=days)
        route_scope = result["route"].get("scope") or {}
        if route_scope.get("note"):
            result["message"] = " ".join(filter(None, [result["message"], route_scope["note"]]))
