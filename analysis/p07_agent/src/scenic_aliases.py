"""景区名称归一化。

图谱里的景区名是 ``长隆``、``广州白云山``、``武功山``，用户输入则可能
带市名、景区后缀或子园区名。所有图谱查询都先经过这里，避免因为名称写法
不同而返回空结果。
"""

import re
import unicodedata


# 图谱中的三个标准景区名，必须与 p06_graph 的 SCENIC_AREA 节点一致。
CANONICAL_AREAS = ("长隆", "广州白云山", "武功山")

# 常用写法 -> 图谱标准名。只做精确映射，不做“包含即匹配”，避免把
# “洛阳白云山”“珠海长隆”等外地同名景区误映射到本项目的数据上。
ALIASES = {
    # 长隆
    "长隆": "长隆",
    "广州长隆": "长隆",
    "广州长隆旅游度假区": "长隆",
    "长隆旅游度假区": "长隆",
    "长隆度假区": "长隆",
    "长隆欢乐世界": "长隆",
    "广州长隆欢乐世界": "长隆",
    "长隆野生动物世界": "长隆",
    "广州长隆野生动物世界": "长隆",
    "长隆野生动物园": "长隆",
    "长隆水上乐园": "长隆",
    "长隆国际大马戏": "长隆",
    "长隆飞鸟乐园": "长隆",
    # 白云山
    "白云山": "广州白云山",
    "广州白云山": "广州白云山",
    "广州市白云山": "广州白云山",
    "白云山风景区": "广州白云山",
    "白云山风景名胜区": "广州白云山",
    "白云山景区": "广州白云山",
    "白云山旅游区": "广州白云山",
    "广州白云山风景区": "广州白云山",
    "广州白云山风景名胜区": "广州白云山",
    # 武功山
    "武功山": "武功山",
    "江西武功山": "武功山",
    "萍乡武功山": "武功山",
    "武功山风景区": "武功山",
    "武功山风景名胜区": "武功山",
    "武功山景区": "武功山",
    "武功山旅游区": "武功山",
    "武功山旅游度假区": "武功山",
    "武功山国家级风景名胜区": "武功山",
}

# 从长到短处理，避免只去掉“景区”而留下“风景”。
_SUFFIXES = (
    "国家级风景名胜区",
    "风景名胜区",
    "旅游度假区",
    "风景区",
    "度假区",
    "旅游区",
    "景区",
)

_PREFIXES = ("广州市", "广州", "江西省", "江西", "萍乡市", "萍乡")

_PUNCTUATION = re.compile(r"[\s\u3000·•・\-—_()（）【】\[\]《》<>\"'“”‘’/]+")


def _normalize(text):
    """去掉空白、常见标点和大小写差异。"""
    text = unicodedata.normalize("NFKC", text).strip()
    return _PUNCTUATION.sub("", text).casefold()


def _strip_affixes(text):
    """反复去掉景区通用后缀，再去掉一次城市/省份前缀。"""
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            if len(text) > len(suffix) and text.endswith(suffix):
                text = text[: -len(suffix)]
                changed = True
                break

    for prefix in _PREFIXES:
        if len(text) > len(prefix) and text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text


def canonicalize_scenic_area(value):
    """把用户写法转成图谱标准名；无法确认时返回 ``None``。

    只接受精确别名或“去掉通用前后缀后”的精确别名。这样既支持
    “广州长隆旅游度假区”，也不会把“洛阳白云山”错认成广州白云山。
    """
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    candidates = [raw, _normalize(raw)]
    # 同时尝试“只去后缀”和“后缀 + 前缀都去”的结果。
    normalized = _normalize(raw)
    candidates.append(_strip_affixes(normalized))
    for prefix in _PREFIXES:
        if normalized.startswith(prefix):
            candidates.append(_strip_affixes(normalized[len(prefix):]))
            break

    for candidate in candidates:
        if candidate in ALIASES:
            return ALIASES[candidate]
        if candidate.casefold() in ALIASES:
            return ALIASES[candidate.casefold()]

    return None