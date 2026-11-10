import json
import urllib.error
import urllib.request


from config import MODEL, OLLAMA_URL
from scenic_aliases import canonicalize_scenic_area
from sub_area_scope import detect_sub_area

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "scenic_area": {"type": ["string", "null"]},
        "duration_days": {"type": ["integer", "null"]},
        "traveler_profiles": {
            "type": "array",
            "items": {"type": "string"}
        },
        "preferences": {
            "type": "array",
            "items": {"type": "string"}
        },
        "constraints": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": [
        "scenic_area",
        "duration_days",
        "traveler_profiles",
        "preferences",
        "constraints"
    ]
}

SYSTEM_PROMPT = """
你是旅游规划系统的需求解析器。阅读用户的完整需求，提取以下字段：
如果用户后续明确更正先前的要求，以后续更正为准。

- scenic_area：用户提到的景区名称。
- duration_days：游玩天数。
- traveler_profiles：同行人群。
- preferences：想体验的活动或喜欢的游玩方式。
- constraints：用户对行程提出的限制或希望尽量做到的条件，
  例如步行强度、预算、时间安排、无障碍需求等。

注意区分明确的硬性要求和“尽量”“希望”等弹性要求；
提取时保留原有语气，不要把弹性要求改成强制要求。
对于用户明确表达的限制或希望，请放入 constraints，不要遗漏。

景区或天数没有明确提到时填 null；其他列表没有内容时填空列表。
不要猜测用户没有说的信息。
只返回符合给定 JSON Schema 的结果。
"""


PROFILE_KEYWORDS = (
    "孩子", "儿童", "小朋友", "宝宝", "幼儿", "亲子", "带娃",
    "老人", "长辈", "父母", "爸妈", "爷爷", "奶奶", "外公", "外婆",
    "情侣", "伴侣", "爱人", "对象", "朋友", "同学", "同事", "闺蜜",
)


def _merge_profiles(text, profiles):
    """模型偶尔漏掉“朋友”等同行人；用原文关键词做确定性补全。"""
    merged = list(dict.fromkeys(profiles or []))
    for keyword in PROFILE_KEYWORDS:
        if keyword in text and keyword not in merged:
            merged.append(keyword)
    return merged


def parse_intent(user_text):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text}
        ],
        "format": INTENT_SCHEMA,
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

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError("无法连接本地 Ollama，请确认 Ollama 正在运行。") from exc

    content = result.get("message", {}).get("content", "")
    intent = json.loads(content)

    expected_fields = set(INTENT_SCHEMA["required"])
    if set(intent) != expected_fields:
        raise ValueError("模型返回的字段与意图结构不一致。")

    # 模型偶尔只保留“朋友/老人”在正文里，不写入 profiles；这里做确定性补全，
    # 避免后续路线规划看不到同行人。
    intent["traveler_profiles"] = _merge_profiles(
        user_text, intent.get("traveler_profiles")
    )

    # 模型通常保留用户原话里的景区写法，这里统一成图谱里的标准名。
    # 无法确认的写法保留原值，由主流程追问，而不是拿去做精确匹配。
    raw_area = intent.get("scenic_area")
    canonical_area = canonicalize_scenic_area(raw_area)
    if canonical_area:
        intent["scenic_area"] = canonical_area

    # 景区名标准化后，再单独识别子园区（如“长隆欢乐世界”）。
    # 子园区不是景区，不能覆盖 scenic_area；仅在长隆下生效。
    sub_area, _ = detect_sub_area(user_text)
    intent["sub_area"] = sub_area if intent.get("scenic_area") == "长隆" else None

    return intent


if __name__ == "__main__":
    sample = "带孩子和老人去长隆玩一天，游乐项目为主，尽量少走路。"
    print(json.dumps(parse_intent(sample), ensure_ascii=False, indent=2))
