import json
import urllib.request

from condition_selector import find_relevant_conditions
from sub_area_scope import filter_route_candidates
from tools import (
    get_route_candidates,
    optimize_route,
    repair_route,
    route_metrics,
    validate_route,
)


from config import MODEL, OLLAMA_URL

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "node_ids": {
            "type": "array",
            "items": {"type": "string"}
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
可以结合不同来源文档的连接，但路线中相邻两个节点必须存在
从前一个节点指向后一个节点的 NEXT 连接。

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
可以提出合理推测；对于图谱中没有明确提供的步行距离、游玩时长或
适用条件，不要直接说已经确定，请在 uncertainties 中说明需要确认的内容。
"""


def plan_route(user_text, scenic_area, conditions=None, trace=None, sub_area=None):
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
        "note": "",
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
        }

    # 用户指定子园区时，只保留该园区的来源文档；连接不足会回退整个景区。
    scope = filter_route_candidates(all_candidates, sub_area, scenic_area)
    candidates = scope["candidates"]

    if conditions is None:
        conditions = find_relevant_conditions(
            user_text, scenic_area, trace=trace
        )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_request": user_text,
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
        "options": {"temperature": 0},
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

        proposal = json.loads(result["message"]["content"])
        validation = call_tool(
            "validate_route",
            validate_route,
            node_ids=proposal["node_ids"],
            candidates=candidates
        )
        print(
            f"第 {attempt + 1} 次路线核验：",
            json.dumps(validation, ensure_ascii=False),
            flush=True
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

    print(
        "模型提出的路线：",
        json.dumps(proposal, ensure_ascii=False),
        flush=True
    )
    print(
        "路线核验结果：",
        json.dumps(validation, ensure_ascii=False),
        flush=True
    )
    print(
        "路线结构指标：",
        json.dumps(metrics, ensure_ascii=False),
        flush=True
    )

    if validation["valid"]:
        message = "路线连接已通过图谱核验。"
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
    }


if __name__ == "__main__":
    from trace_log import SessionTrace

    user_text = "我和朋友去广州白云山玩一天，喜欢自然风景和拍照，希望少爬坡。"
    trace = SessionTrace()

    result = plan_route(user_text, scenic_area="广州白云山", trace=trace)

    print("路线结果：", result["message"])
    print("记录的工具：", [event["tool"] for event in trace.events])
