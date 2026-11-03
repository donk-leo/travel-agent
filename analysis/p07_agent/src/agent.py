"""旅游 Agent 主流程：理解需求、决策、查询图谱、检查并记录结果。"""

import json

from condition_selector import find_relevant_conditions
from constraint_checker import check_constraints, check_plan
from intent_parser import parse_intent
from route_planner import plan_route
from tool_decider import decide_next_step
from tool_selector import select_tools
from tools import search_poi
from trace_log import SessionTrace


MAX_DECISION_ROUNDS = 3
ALLOWED_TOOLS = {"get_conditions", "get_route_candidates", "search_poi"}


def _check_message(check, fallback):
    return " ".join(filter(None, [check.get("explanation"), check.get("question")])) or fallback


def run_agent(user_text):
    """执行一次请求；追问上下文由调用方传入完整文本。"""
    result = {
        "status": "working", "query": user_text, "intent": None,
        "decision": None, "tool_selection": None, "tool_decisions": [],
        "suggestions": [], "route": None, "poi_results": None,
        "poi_list_all": False, "message": "", "error": "",
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

        decision = decide_next_step(user_text, intent)
        if decision.get("decision") not in {"clarify", "query_graph", "reply"}:
            raise ValueError("决策器返回了无效的下一步。")
        if decision.get("request_type") not in {"plan", "info", "other"}:
            raise ValueError("决策器返回了无效的需求类型。")

        area = intent.get("scenic_area")
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
                _query_graph(result, trace, user_text, area, days)
                if result["status"] == "working":
                    if result["route"] is None and not result["suggestions"]:
                        # 仅展示图谱原始名称匹配，没有生成行动建议。
                        plan_check = {"status": "ok", "explanation": "仅展示图谱查询结果。", "question": ""}
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


def _query_graph(result, trace, user_text, area, days):
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
            if name == "search_poi":
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
                result["poi_results"] = trace.call_tool(
                    "search_poi", search_poi, keyword=keyword, scenic_area=area, limit=limit)
                result["poi_list_all"] = mode == "all_pois"
                observations.append({"tool": name, "keyword": keyword,
                                     "count": len(result["poi_results"]),
                                     "examples": result["poi_results"][:5]})
            else:
                result["route"] = plan_route(user_text, area, conditions=result["suggestions"], trace=trace)
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
        result["route"] = plan_route(user_text, area, conditions=result["suggestions"], trace=trace)
