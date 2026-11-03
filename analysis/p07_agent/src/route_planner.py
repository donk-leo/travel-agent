import json
import urllib.request
from condition_selector import find_relevant_conditions
from tools import get_route_candidates, validate_route, repair_route


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
6.参考 condition_suggestions 里的条件建议及其来源。
可以提出合理推测；对于图谱中没有明确提供的步行距离、游玩时长或
适用条件，不要直接说已经确定，请在 uncertainties 中说明需要确认的内容。
"""


def plan_route(user_text, scenic_area, conditions=None, trace=None):
    def call_tool(name, function, **arguments):
        if trace is None:
            return function(**arguments)
        return trace.call_tool(name, function, **arguments)
    candidates = call_tool(
        "get_route_candidates",
        get_route_candidates,
        scenic_area=scenic_area
    )

    if not candidates:
        return {
            "proposal": None,
            "validation": None,
            "message": "该景区没有查询到路线连接。"
        }

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
                        "route_candidates": candidates,
                        "condition_suggestions":conditions
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
        repair_info = None

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

    if validation["valid"]:
        seen = set()
        repeated = []
        for node_id in proposal["node_ids"]:
            if node_id in seen and node_id not in repeated:
                repeated.append(node_id)
            seen.add(node_id)

        if repeated:
            names = [node_id.split("|")[-1] for node_id in repeated]
            proposal["uncertainties"].append(
                "路线会重复经过：" + "、".join(names)
                + "；返回分岔点可能是合理的，实际步行距离和坡度仍需确认。"
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

    if validation["valid"]:
        message = "路线连接已通过图谱核验。"
    else:
        message = "路线连接未通过图谱核验，需要重新规划。"

    return {
        "proposal": proposal,
        "validation": validation,
        "message": message
    }


if __name__ == "__main__":
    from trace_log import SessionTrace

    user_text = "我和朋友去广州白云山玩一天，喜欢自然风景和拍照，希望少爬坡。"
    trace = SessionTrace()

    result = plan_route(user_text, scenic_area="广州白云山", trace=trace)

    print("路线结果：", result["message"])
    print("记录的工具：", [event["tool"] for event in trace.events])
