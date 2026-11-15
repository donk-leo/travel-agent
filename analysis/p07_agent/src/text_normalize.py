"""用户输入归一与提示注入检测（T2.6）。

归一只用于**模型输入**：``run_agent`` 的 ``query`` 字段始终保留用户原文，
页面展示不受影响。归一是确定性的（同输入同输出），不依赖模型。

覆盖：
- Unicode NFKC（全角数字/字母/空白/ASCII 标点归一）；
- 删除零宽与格式字符（ZWJ/BOM/软连字符等），控制字符折叠为空格；
- 全角空白→半角、连续空白折叠、首尾 strip；
- 去除 emoji，但不改中文/数字/英文及标点语义；
- 超长截断到 ``MAX_INPUT_CHARS``，并通过返回值 ``truncated`` 显式暴露；
- 空/纯空白返回空串；
- 中英文常见提示注入模式检测（只检测与标记，不在本模块执行任何动作）。
"""

import re
import unicodedata


#: 模型输入的最大字符数；超出部分截断并显式记录，不静默丢弃。
MAX_INPUT_CHARS = 4000

EMPTY_INPUT_MESSAGE = "请输入旅行需求。"

INJECTION_NOTICE = "检测到疑似指令注入，已按数据处理，未执行。"

PURE_INJECTION_MESSAGE = "请描述你想去的景区和游玩天数，我来帮你规划行程。"

TRUNCATION_NOTICE = (
    "输入超过 {limit} 字符，已截断后解析；原文仍保留在 query 字段，展示不受影响。"
)

# emoji / 象形符号。只去除符号本身，不影响中文、数字、英文与常用标点。
_EMOJI = re.compile(
    "["
    "\u2300-\u23FF"          # ⌚⏰ 等杂项技术符号
    "\u2600-\u27BF"          # 晴雨、手势、勾叉等杂项/装饰符号
    "\u2B00-\u2BFF"          # ⬆⭐ 等
    "\uFE00-\uFE0F"          # variation selector（emoji 呈现）
    "\u20E3"                 # 组合键帽
    "\U0001F000-\U0001FAFF"  # 表情、人物、旗帜、肤色修饰等
    "\u3030\u303D\u3297\u3299"
    "]+"
)

# 常见提示注入模式（中英）；命中只代表"疑似"，处置由调用方确定。
INJECTION_PATTERNS = (
    ("ignore_instruction_zh",
     re.compile(r"忽略(?:以上|之前|前面|所有|上述|上面|先前).{0,20}?指令")),
    ("ignore_instruction_en",
     re.compile(r"ignore\s+(?:all\s+|the\s+)?(?:previous|above)\s+instructions",
                re.IGNORECASE)),
    ("system_prompt",
     re.compile(r"system\s*prompt|系统提示词?", re.IGNORECASE)),
    ("role_override",
     re.compile(r"你现在是|扮演|进入开发者模式")),
    ("call_tool",
     re.compile(r"调用.{0,10}?工具")),
    ("delete_data",
     re.compile(r"删除.{0,10}?(?:图谱|数据)")),
    ("shell_command",
     re.compile(r"rm\s+-rf", re.IGNORECASE)),
    ("reveal_prompt",
     re.compile(r"输出.{0,10}?(?:提示词|prompt)", re.IGNORECASE)),
)

# 判断"是否还有旅行需求"的关键词；用于区分纯注入与"注入 + 正常需求"。
_TRAVEL_TOKENS = (
    "景区", "景点", "旅游", "旅行", "出游", "出行", "行程", "路线", "怎么走",
    "怎么玩", "玩", "逛", "一日", "半日", "小时", "住宿", "酒店", "门票",
    "交通", "地铁", "公交", "打车", "天",
)
_TRAVEL_AREAS = ("长隆", "白云山", "武功山")


class NormalizedText(str):
    """归一化后的文本；仍是 ``str``，额外携带 ``truncated`` 等显式标记。"""

    truncated = False
    original_length = 0

    def __new__(cls, value, truncated=False, original_length=None):
        obj = super().__new__(cls, value)
        obj.truncated = bool(truncated)
        obj.original_length = (
            len(value) if original_length is None else int(original_length)
        )
        return obj


def _strip_invisible(text):
    """删除零宽/格式字符；控制字符（换行、制表符等）折叠为空格。"""
    cleaned = []
    for char in text:
        category = unicodedata.category(char)
        if category == "Cf":
            # ZWJ/ZWNJ/BOM/软连字符等肉眼不可见字符，直接删除。
            continue
        if category == "Cc":
            cleaned.append(" ")
            continue
        cleaned.append(char)
    return "".join(cleaned)


def normalize_user_text(text):
    """归一用户输入，返回 ``NormalizedText``（``str`` 子类）。

    - ``None``/非字符串按空串处理；
    - 空或纯空白返回 ``""``；
    - 超过 ``MAX_INPUT_CHARS`` 时截断，并令返回值 ``.truncated is True``；
    - 同输入同输出，可重复调用。
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    original_length = len(text)

    normalized = unicodedata.normalize("NFKC", text)
    normalized = _strip_invisible(normalized)
    normalized = _EMOJI.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    truncated = len(normalized) > MAX_INPUT_CHARS
    if truncated:
        normalized = normalized[:MAX_INPUT_CHARS].strip()

    return NormalizedText(
        normalized, truncated=truncated, original_length=original_length
    )


def truncation_notice(limit=MAX_INPUT_CHARS):
    """超长截断的明示文案；调用方应写进 uncertainties/message。"""
    return TRUNCATION_NOTICE.format(limit=limit)


def _injection_spans(text):
    """返回所有命中模式的 ``(start, end)``，用于合并重叠命中。"""
    spans = []
    for _name, pattern in INJECTION_PATTERNS:
        spans.extend(match.span() for match in pattern.finditer(text))
    return spans


def detect_prompt_injection(text):
    """返回命中的注入模式名列表（去重、保持模式表顺序）。"""
    if not isinstance(text, str) or not text:
        return []
    hits = []
    for name, pattern in INJECTION_PATTERNS:
        if pattern.search(text) and name not in hits:
            hits.append(name)
    return hits


def strip_injection_markers(text):
    """删除命中的注入片段（合并重叠区间），其余文本保持不变。"""
    if not isinstance(text, str) or not text:
        return ""
    spans = sorted(_injection_spans(text))
    if not spans:
        return text
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    pieces = []
    cursor = 0
    for start, end in merged:
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def has_travel_request(text):
    """判断文本是否还包含旅行需求信号（用于区分纯注入）。"""
    if not isinstance(text, str):
        return False
    return any(token in text for token in _TRAVEL_TOKENS) or any(
        area in text for area in _TRAVEL_AREAS
    )


def is_pure_injection(text):
    """命中注入模式、且去掉注入片段后没有旅行需求 => 纯注入。"""
    if not detect_prompt_injection(text):
        return False
    remainder = strip_injection_markers(text)
    return not has_travel_request(remainder)
