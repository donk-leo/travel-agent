import json
import urllib.request

from tools import get_conditions, get_condition_evidence


from config import MAX_TOKENS, MODEL, OLLAMA_URL

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
MAX_SELECTED = 5
SEASON_ALIASES = {
    "春天": "春", "春季": "春",
    "夏天": "夏", "夏季": "夏",
    "秋天": "秋", "秋季": "秋",
    "冬天": "冬", "冬季": "冬",
}
SEASONS = tuple(SEASON_ALIASES)


def _text_key(value):
    return " ".join(str(value or "").split()).casefold()


def _season_mismatch(user_text, condition_text):
    """用户没有提季节时，不同季节的专门建议不进入结果。"""
    user_seasons = {SEASON_ALIASES[season] for season in SEASONS if season in user_text}
    condition_seasons = {SEASON_ALIASES[season] for season in SEASONS if season in condition_text}
    return bool(condition_seasons) and not (condition_seasons & user_seasons)


def apply_selection(conditions, selections, user_text="", limit=MAX_SELECTED):
    """校验模型编号，按条件+建议去重，并限制返回条数。"""
    selected = []
    seen_indexes = set()
    seen_text = set()

    for item in selections:
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(conditions):
            raise ValueError(f"模型返回了不存在的候选编号：{index}")
        if index in seen_indexes:
            continue
        seen_indexes.add(index)

        condition = conditions[index]
        if _season_mismatch(user_text, condition["condition_text"]):
            continue

        key = (
            _text_key(condition["condition_text"]),
            _text_key(condition["suggestion_text"]),
        )
        if key in seen_text:
            continue
        seen_text.add(key)

        selected.append({
            "condition": condition,
            "needs_verification": bool(item.get("needs_verification")),
        })
        if len(selected) >= limit:
            break

    return selected


def generate_reasons(user_text, conditions):
    """一次调用为最多 5 条建议生成理由，避免每条建议单独请求模型。"""
    if not conditions:
        return []

    schema = {
        "type": "object",
        "properties": {
            "reasons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "reason": {"type": "string"}
                    },
                    "required": ["index", "reason"]
                }
            }
        },
        "required": ["reasons"]
    }
    prompt = """
你是旅游规划助手。根据用户需求，为每条候选建议各写一句话理由。
只使用建议本身和用户明确表达的信息，允许合理推测并用“可能”表达。
不要添加原建议没有提到的具体措施、地点、客流或时间结论；不要把推测说成确定事实。
不要声称用户提出了实际没有提出的偏好；适用条件不确定时保留条件。
每条理由都要独立，不要重复建议正文。
"""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(
                {
                    "user_request": user_text,
                    "conditions": [
                        {
                            "index": index,
                            "condition": condition["condition_text"],
                            "suggestion": condition["suggestion_text"]
                        }
                        for index, condition in enumerate(conditions)
                    ]
                },
                ensure_ascii=False
            )}
        ],
        "format": schema,
        "think": False,
        "options": {"temperature": 0, "num_predict": MAX_TOKENS},
        "stream": False
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        raw = json.loads(result["message"]["content"])["reasons"]
    except Exception:
        raw = []

    reasons = {}
    for item in raw:
        index = item.get("index")
        reason = item.get("reason")
        if isinstance(index, int) and 0 <= index < len(conditions) and isinstance(reason, str):
            reasons[index] = reason.strip()
    return reasons


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
        "options": {"temperature": 0, "num_predict": MAX_TOKENS},
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
        "options": {"temperature": 0, "num_predict": MAX_TOKENS},
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
    selection = json.loads(result["message"]["content"])
    selected = apply_selection(
        conditions,
        selection.get("selections", []),
        user_text=user_text,
    )
    reasons = generate_reasons(
        user_text,
        [item["condition"] for item in selected],
    )

    for index, item in enumerate(selected):
        item["reason"] = reasons.get(index) or (
            f"该建议是否适用取决于条件“{item['condition']['condition_text']}”。"
        )

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