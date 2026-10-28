# -*- coding: utf-8 -*-
"""可复用的清洗原语。

设计原则（与 docs/01_统一规范.md 一致）：
  1. 保序：不重排、不合并段落；
  2. 保时：不改写时间语义，只修明显的排版错误；
  3. 可回溯：调用方负责保存 raw_content，本模块只提供纯函数。

各景区可以只选用其中一部分，但**不要在项目里复制后修改**——需要新规则就扩展本文件并走 PR。
"""
from __future__ import annotations

import re

# ---------- 正则常量 ----------
RE_BLOCK_TAG = re.compile(r"<(?:br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", re.I)
RE_ANY_TAG = re.compile(r"<[^>]+>")
RE_ENTITY = re.compile(r"&(quot|amp|nbsp|lt|gt|#39|ldquo|rdquo|hellip);")
ENTITY_MAP = {
    "&quot;": '"', "&amp;": "&", "&nbsp;": " ", "&lt;": "<", "&gt;": ">",
    "&#39;": "'", "&ldquo;": "“", "&rdquo;": "”", "&hellip;": "…",
}
RE_EMOJI = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U0001F1E6-\U0001F1FF" "\u2300-\u27BF"
    "\u2B00-\u2BFF" "\u203C\u2049" "\uFE0F" "\u200B-\u200F" "\uFEFF" "]"
)
#: 图标字体私有区字符（网页里常显示为空白方块）
RE_PUA = re.compile(r"[\uE000-\uF8FF]")
ARROW_MAP = {"➡": "→", "➔": "→", "➜": "→", "⟶": "→", "⇒": "→"}
RE_SPACE = re.compile(r"[\u00A0\u3000\t\u2002-\u200A\u202F\u205F]")
RE_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RE_PHONE = re.compile(r"(?:400|800)[-\s]?\d{3}[-\s]?\d{4}")
CJK = r"\u4e00-\u9fff"
PREV = r"\u4e00-\u9fff”’」』）】…\)\]\""
PUNCT_MAP = [
    (re.compile(rf"(?<=[{PREV}]),"), "，"),
    (re.compile(rf"(?<=[{PREV}]);"), "；"),
    (re.compile(rf"(?<=[{PREV}])!"), "！"),
    (re.compile(rf"(?<=[{PREV}])\?"), "？"),
    (re.compile(rf"(?<=[{CJK}]):"), "："),
]
RE_QUOTE_CJK = re.compile(r'"([^"\n]{1,40}?)"')
RE_PAREN_CJK = re.compile(r"\(([^()\n]{0,40}?[\u4e00-\u9fff][^()\n]{0,40}?)\)")
RE_TIME_DOT = re.compile(r"(?<![\d:])(\d{1,2})\s*[.．]\s*(\d{2})(?![\d:])")
RE_MULTI_NL = re.compile(r"\n{2,}")
RE_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def strip_html(text: str) -> str:
    """块级标签转换行后剔除其余标签。"""
    text = RE_BLOCK_TAG.sub("\n", text or "")
    return RE_ANY_TAG.sub("", text)


def unescape_entities(text: str) -> str:
    for old, new in ENTITY_MAP.items():
        text = text.replace(old, new)
    return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)


def remove_symbols(text: str) -> str:
    """删 emoji / 私有区字符 / 装饰符号；箭头保留语义（写成 →）。"""
    for k, v in ARROW_MAP.items():
        text = text.replace(k, v)
    text = RE_PUA.sub("", text)
    return RE_EMOJI.sub("", text)


def remove_links(text: str) -> str:
    text = RE_URL.sub("", text)
    text = RE_EMAIL.sub("", text)
    return RE_PHONE.sub("", text)


def normalize_whitespace(text: str) -> str:
    text = RE_SPACE.sub(" ", text)
    text = "\n".join(ln.strip() for ln in text.split("\n"))
    text = RE_MULTI_SPACE.sub(" ", text)
    text = RE_MULTI_NL.sub("\n", text)
    return text.strip()


def normalize_punct(text: str) -> str:
    for pat, rep in PUNCT_MAP:
        text = pat.sub(rep, text)
    text = RE_QUOTE_CJK.sub(lambda m: f"“{m.group(1)}”", text)
    text = RE_PAREN_CJK.sub(lambda m: f"（{m.group(1)}）", text)
    # 时间排版噪声 09. 40 -> 09:40（对“编号+时间”做保护）
    text = RE_TIME_DOT.sub(
        lambda m: f"{m.group(1)}:{m.group(2)}" if 0 <= int(m.group(1)) <= 23 else m.group(0),
        text,
    )
    text = re.sub(r"\.{3,}", "……", text)
    text = re.sub(r"([，。、；：！？])\1+", r"\1", text)
    text = re.sub(r"(?<=[（【《“])[ \t]+", "", text)
    text = re.sub(r"[ \t]+(?=[）】》，。、；：！？])", "", text)
    return text


def basic_clean(text: str) -> str:
    """默认流水线（各景区可在此基础上追加站点专属规则）。"""
    text = strip_html(text)
    text = unescape_entities(text)
    text = remove_links(text)
    text = remove_symbols(text)
    text = normalize_whitespace(text)
    text = normalize_punct(text)
    return text
