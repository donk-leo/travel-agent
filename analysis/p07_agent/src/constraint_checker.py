import json
import urllib.request


from config import MODEL, OLLAMA_URL

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["ok", "conflict", "needs_clarification"]
        },
        "explanation": {"type": "string"},
        "question": {"type": "string"}
    },
    "required": ["status", "explanation", "question"]
}

SYSTEM_PROMPT = """
你是旅游需求检查助手。检查用户的要求是否存在明显冲突。
用户可能分多次补充需求；后面的明确更正优先于前面的相应限制。

判断规则：
- ok：没有发现明显冲突。
- conflict：用户明确提出的要求难以同时成立，需要调整。
- needs_clarification：能否满足取决于缺失的信息，需要追问。

不要凭空假设用户的身体状况、预算数额、出行方式或景区实时情况。
不要凭常识判断景区或景点是否存在；名称是否存在交给图谱查询。
用户询问某景区是否包含某个地点，本身不构成冲突，也不需要先确认地点真实存在。
有冲突或需要追问时，用中文说明原因，并提出一个有帮助的问题。
如果问题涉及相互冲突的限制，请问用户愿意调整哪项限制；
不要提出仍然保留全部矛盾限制的替代方案。
例如，当多地游览与禁止所有移动方式相冲突时，仅减少景点数量无法解决移动问题；
请询问用户能否调整移动限制，或是否只停留在一处。
没有冲突时，question 返回空字符串。
"""


PLAN_PROMPT = """
你是旅游方案的约束检查助手。对照用户完整需求，检查最终路线与建议。
用户可能分多次补充需求；后面的明确更正优先于前面的相应限制。
只在方案明确违反用户要求时返回 conflict，并解释具体冲突与如何调整。
如果用户明确的硬性限制与路线中的具体行动存在关键歧义，返回 needs_clarification 并提出问题。
若没有发现冲突，返回 ok，question 为空。
重复经过景点或返回分岔点可以是合理路线，不要仅因重复而拦截或要求用户确认。
用户希望少走路或轻松游玩时，如果缺少距离、坡度或时长数据，不能据此认定路线冲突；保留需要确认的提示即可。
不要把地点名称中的索道直接等同于已经乘坐索道；明确的乘坐活动才表示乘坐。
条件建议应结合其适用条件和建议正文判断；不要把明确违反限制的措施作为推荐。
不能仅凭图谱中的 NEXT 关系推断实际步行距离、坡度或费用。
输入中的 route_nodes 是去重后的节点清单，仅用于检查明确行动，不表示路线顺序或是否往返。
用户可能只查询景点或建议；没有提供路线时，不要假设用户一定要求规划路线。
"""


def _check(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "format": CHECK_SCHEMA,
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

    verdict = json.loads(result["message"]["content"])
    if verdict.get("status") not in {"ok", "conflict", "needs_clarification"}:
        raise ValueError("约束检查返回了无效状态。")
    if not isinstance(verdict.get("explanation"), str) or not isinstance(verdict.get("question"), str):
        raise ValueError("约束检查返回的说明格式不正确。")
    return verdict


def check_constraints(user_text):
    return _check([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text}
    ])


def check_plan(user_text, route, suggestions):
    # Check distinct nodes for explicit actions; repeated visits do not block display.
    route_nodes = []
    if route and route.get("validation") and route["validation"].get("valid"):
        proposal = route.get("proposal") or {}
        route_nodes = list(dict.fromkeys(proposal.get("node_ids", [])))
    return _check([
        {"role": "system", "content": PLAN_PROMPT},
        {"role": "user", "content": json.dumps(
            {"user_request": user_text, "route_nodes": route_nodes, "suggestions": suggestions},
            ensure_ascii=False
        )}
    ])


if __name__ == "__main__":
    user_text = "我想一天游遍武功山的所有景点，但不能步行，也不能乘坐任何交通工具。"
    result = check_constraints(user_text)
    print(json.dumps(result, ensure_ascii=False, indent=2))
