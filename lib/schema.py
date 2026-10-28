# -*- coding: utf-8 -*-
"""字段常量与行级校验（与 standards/schema_scenic.json 保持同步）。"""
from __future__ import annotations

import hashlib
import re

#: 项目 1 主数据集 24 列（顺序即输出顺序）
SCENIC_COLUMNS = [
    "doc_id", "scenic_area", "doc_type", "subtype", "title", "author",
    "publish_date", "source_site", "source_url", "extract_rule",
    "raw_content", "clean_content", "char_raw", "char_clean", "para_raw",
    "para_clean", "removed_char_ratio", "noise_lines_removed", "emoji_removed",
    "urls_removed", "dup_paragraphs_removed", "quality_flags", "is_valid",
    "clean_hash",
]

#: 合并必需列（与 scenic/wugongshan/src/merge_group.py 的 REQUIRED 一致）
REQUIRED_COLUMNS = [
    "doc_id", "scenic_area", "doc_type", "title", "source_site",
    "source_url", "raw_content", "clean_content", "is_valid",
]

DOC_TYPE_ENUM = ("官方路线", "游客游记", "站点攻略")
DOC_ID_RE = re.compile(r"^[A-Z]{2,5}-[OT]-\d{2}$")
AREA_CODE = {"changlong": "CL", "baiyunshan": "BYS", "wugongshan": "WGS"}
MIN_CLEAN_CHARS = 50

_TRUE = {"true", "1", "yes", "y", "是"}


def is_true(value) -> bool:
    return str(value).strip().lower() in _TRUE


def clean_hash(text: str) -> str:
    """与武功山一致：sha1(去掉所有空白后的 clean_content)。"""
    return hashlib.sha1(re.sub(r"\s+", "", text or "").encode("utf-8")).hexdigest()


def parse_doc_id(doc_id: str) -> tuple[str, str, str] | None:
    """'CL-O-01' -> ('CL', 'O', '01')；格式非法返回 None。"""
    if not DOC_ID_RE.match(doc_id or ""):
        return None
    area, kind, seq = doc_id.split("-")
    return area, kind, seq


def count_paragraphs(text: str) -> int:
    return len([ln for ln in (text or "").split("\n") if ln.strip()])


def make_doc_id(area: str, is_official: bool, seq: int) -> str:
    code = AREA_CODE.get(area)
    if not code:
        raise ValueError(f"未知景区：{area}")
    return f"{code}-{'O' if is_official else 'T'}-{seq:02d}"
