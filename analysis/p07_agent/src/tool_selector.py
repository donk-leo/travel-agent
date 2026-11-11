import json
import urllib.request


from config import MAX_TOKENS, MODEL, OLLAMA_URL

SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "tools": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "get_conditions",
                    "get_route_candidates",
                    "search_poi"
                ]
            }
        },
        "search_mode": {
            "type": "string",
            "enum": ["all_pois", "keyword", "none"]
        },
        "search_keyword": {"type": "string"},
        "reason": {"type": "string"}
    },
    "required": ["tools", "search_mode", "search_keyword", "reason"]
}

SYSTEM_PROMPT = """
你是旅游 Agent 的工具选择器。根据用户需求，决定需要查询哪些图谱工具。

可用工具：
- get_conditions：查询与人群、天气、体力、交通等有关的条件建议。
- get_route_candidates：查询有图谱 NEXT 关系的路线连接。
- search_poi：列出景区内的地点，或根据地点名称关键词查询。

规划游览路线时，应选择 get_route_candidates；
需要参考人群、偏好或限制条件时，可以选择 get_conditions；
需要列出景区里的景点或查找具体景点名称时，选择 search_poi。

选择 search_poi 时，search_mode 有两种：
- all_pois：用户询问景区里有哪些景点，search_keyword 留空。景区名称不是景点关键词。
- keyword：用户想查名称包含特定词的地点，search_keyword 填这个词。
没有选择 search_poi 时，search_mode 为 none，search_keyword 留空。
人群或体验偏好（如儿童、亲子、老人、情侣、刺激、少走路、轻松）不是地点名称；
这类需求不要用 keyword 搜索，改用 all_pois，并在 reason 中说明“列表未按偏好过滤”。
例如“广州白云山有哪些景点”选择 all_pois，关键词为空；
“长隆有哪些名字包含熊猫的景点”选择 keyword，关键词为熊猫；
“带孩子去长隆欢乐世界”选择 all_pois，不要把“儿童”当地点关键词。

可以同时选择多个工具。不要选择列表以外的工具。
输入包括用户需求、已经调用的工具和结果摘要。根据结果判断是否还需要补查：
信息足够时返回空 tools；不要重复调用已查过的条件或路线工具。
景点查询没有结果时可以换一个有依据的关键词，但不要重复相同查询或虚构结果。
reason 用一句话解释选择。
"""


def select_tools(user_text, observations=None, executed_tools=None):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "user_request": user_text,
                "observations": observations or [],
                "executed_tools": executed_tools or []
            }, ensure_ascii=False)}
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

    return json.loads(result["message"]["content"])


if __name__ == "__main__":
    user_text = "我想带孩子去长隆玩一天，喜欢游乐项目，尽量少走路。"
    result = select_tools(user_text)
    print(json.dumps(result, ensure_ascii=False, indent=2))
