import json
import urllib.request

from tools import get_conditions, get_condition_evidence


from config import MODEL, OLLAMA_URL

SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "needs_verification": {"type": "boolean"}
                },
                "required": ["index", "needs_verification"]
            }
        }
    },
    "required": ["selections"]
}

SYSTEM_PROMPT = """
你是旅游规划助手。逐条阅读候选建议，结合用户需求选择可能有帮助的建议。

建议只需帮助到任一同行人或满足一项偏好，不要求同时满足全部需求。
仅因没有提到某位同行人或某项限制，不要排除建议；
若适用性或条件不确定，仍可选择并标记需要核实。

明显不相关或者明确与用户限制冲突的可以排除。
只返回候选编号，不要创造建议。

needs_verification 表示是否需要核实活动时间、适用人群或其他重要条件。

确实没有相关建议时返回空列表。
"""
def generate_reason(user_text, condition):
    """只针对已选中的单条建议生成理由。"""
    schema = {
        "type": "object",
        "properties": {
            "reason": {"type": "string"}
        },
        "required": ["reason"]
    }

    prompt = """
你是旅游规划助手。根据用户需求，用一句话解释这条建议可能有什么帮助。
只使用建议本身和用户明确表达的信息，允许合理推测并用“可能”表达。
不要添加原建议没有提到的具体措施、地点、客流或时间结论；不要把推测说成确定事实。
不要声称用户提出了实际没有提出的偏好；适用条件不确定时保留条件。
"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_request": user_text,
                        "condition": condition
                    },
                    ensure_ascii=False
                )
            }
        ],
        "format": schema,
        "think": False,
        "options": {"temperature": 0},
        "stream": False
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)

    return json.loads(result["message"]["content"])["reason"]

def select_conditions(user_text, conditions):
    candidates = [
        {
            "index": index,
            "condition": item["condition_text"],
            "suggestion": item["suggestion_text"]
        }
        for index, item in enumerate(conditions)
    ]

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"user_request": user_text, "candidates": candidates},
                    ensure_ascii=False
                )
            }
        ],
        "format": SELECTION_SCHEMA,
        "think": False,
        "options": {"temperature": 0},
        "stream": False
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    print("模型筛选原始结果：", result["message"]["content"], flush=True)
    selection = json.loads(result["message"]["content"])
    selected = []
    seen = set()

    for item in selection["selections"]:
        index = item["index"]

        if not 0 <= index < len(conditions):
            raise ValueError(f"模型返回了不存在的候选编号：{index}")

        if index in seen:
            continue

        seen.add(index)
        condition = conditions[index]

        selected.append({
            "condition": condition,
            "reason": generate_reason(user_text, condition),
            "needs_verification": item["needs_verification"]
        })

    return selected



def find_relevant_conditions(user_text, scenic_area, trace=None):
    """查询景区条件，由模型筛选，并附上图谱来源。"""

    def call_tool(name, function, **arguments):
        if trace is None:
            return function(**arguments)
        return trace.call_tool(name, function, **arguments)

    condition_types = ["天气", "人群", "时间", "体力", "预算", "交通", "其他"]
    conditions = []

    for condition_type in condition_types:
        conditions.extend(
            call_tool(
                "get_conditions",
                get_conditions,
                condition_type=condition_type,
                scenic_area=scenic_area
            )
        )

    if not conditions:
        return []

    selected = select_conditions(user_text, conditions)

    for item in selected:
        condition = item["condition"]

        item["evidence"] = call_tool(
            "get_condition_evidence",
            get_condition_evidence,
            condition_text=condition["condition_text"],
            suggestion_text=condition["suggestion_text"],
            scenic_area=scenic_area
        )

    return selected


if __name__ == "__main__":
    from trace_log import SessionTrace

    user_text = "我想带孩子去长隆玩一天，喜欢游乐项目。"
    trace = SessionTrace()

    selected = find_relevant_conditions(
        user_text,
        scenic_area="长隆",
        trace=trace
    )

    print("选中的建议数量：", len(selected))
    print("记录的工具调用次数：", len(trace.events))
    print("第一条工具记录：")
    print(json.dumps(trace.events[0], ensure_ascii=False, indent=2))