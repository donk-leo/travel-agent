import json
import urllib.request


from config import MODEL, OLLAMA_URL

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["clarify", "query_graph", "reply"]
        },
        "request_type": {
            "type": "string",
            "enum": ["plan", "info", "other"]
        },
        "reason": {"type": "string"},
        "response": {"type": "string"}
    },
    "required": ["decision", "request_type", "reason", "response"]
}

SYSTEM_PROMPT = """
你是旅游 Agent 的决策器。根据用户输入和已解析的旅行约束，
决定下一步做什么：

- clarify：行程规划缺少景区或天数，或景点信息查询缺少景区。
- query_graph：行程规划的景区和天数都明确，或景点信息查询的景区明确。
- reply：普通问候等不需要查询图谱的输入。

request_type 是 plan（规划路线或行程）、info（仅查询景点或建议）、
other（问候等）。仅查询景点或建议时不需要提供游玩天数。
以输入中的 intent.scenic_area 和 intent.duration_days 为已解析信息，
scenic_area 不为空即景区已明确，不要再次询问景区。
例如用户问“长隆有哪些名字包含熊猫的景点”，且 scenic_area 为“长隆”，
即使 duration_days 为 null，也选择 request_type 为 info、decision 为 query_graph。
reason 用一句话解释决策。
clarify 时，response 给出需要补充的问题。
reply 时，response 给出简短回复。
query_graph 时，response 返回空字符串。
"""


def decide_next_step(user_text, intent):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"user_request": user_text, "intent": intent},
                    ensure_ascii=False
                )
            }
        ],
        "format": DECISION_SCHEMA,
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

    return json.loads(result["message"]["content"])


if __name__ == "__main__":
    user_text = "我想带孩子去长隆玩一天，喜欢游乐项目。"
    intent = {
        "scenic_area": "长隆",
        "duration_days": 1,
        "traveler_profiles": ["孩子"],
        "preferences": ["游乐项目"],
        "constraints": []
    }

    result = decide_next_step(user_text, intent)
    print(json.dumps(result, ensure_ascii=False, indent=2))
