#!/usr/bin/env python3
"""项目 2：基于 Jieba 自定义词典与正则规则的实体识别。

输入：
    scenic/<area>/data/processed/<area>_guides.csv 的 clean_content

输出：
    analysis/p02_entities/outputs/entities.jsonl
    analysis/p02_entities/outputs/entity_stats.json
    analysis/p02_entities/outputs/extraction_errors.json

方法：
    1. 加载 config/jieba_userdict.txt，使景区专名优先被 Jieba 切分；
    2. 以 entity_lexicon.csv 为准，将 Jieba token 映射为 POI / TRANSPORT；
    3. 用正则补充时刻、时长、日期区间和行程天数等 TIME 实体；
    4. 本地计算原文字符位置，保证 entity_text 可被 clean_content 精确回取。

用法：
    python analysis/p02_entities/src/run_all.py
    python analysis/p02_entities/src/run_all.py --areas changlong
    python analysis/p02_entities/src/run_all.py --dry-run

依赖：
    python -m pip install jieba
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "analysis" / "p02_entities"
CONFIG = PROJECT / "config"
OUTPUTS = PROJECT / "outputs"
AREAS = ("changlong", "baiyunshan", "wugongshan")


@dataclass(frozen=True)
class LexiconEntry:
    term: str
    entity_type: str
    scenic_area: str
    normalized_name: str
    alias_group: str
    notes: str


# 正则规则优先识别完整表达；同一区间内会保留更长的实体，避免把“9:00-12:00”拆成两个时刻。
TIME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[-–—~～至]\s*(?:[01]?\d|2[0-3]):[0-5]\d)?(?:前|后)?"),
    re.compile(r"(?:\d+|[一二三四五六七八九十两]+)\s*天\s*(?:\d+|[一二三四五六七八九十两]+)\s*(?:夜|晚)"),
    re.compile(r"第(?:[一二三四五六七八九十]|\d+)天"),
    re.compile(r"(?:\d+(?:\s*[-–—~～]\s*\d+)?|[一二三四五六七八九十两]+)\s*(?:小时|分钟)(?:内|左右)?"),
    re.compile(r"(?:[1-9]|1[0-2])月\s*[-–—~～至]\s*(?:[1-9]|1[0-2])月"),
    re.compile(r"(?:五一|周末|假期)"),
)

SENTENCE_BREAK = re.compile(r"[。！？；\n]")


def read_csv(path: Path) -> list[dict[str, str]]:
    """读取 UTF-8-SIG CSV，并在缺少输入时给出明确错误。"""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_lexicon() -> tuple[dict[str, list[LexiconEntry]], set[str]]:
    """读取主词典；同一词可因景区不同而有多个词条。"""
    path = CONFIG / "entity_lexicon.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        entries = [LexiconEntry(**row) for row in csv.DictReader(fh)]

    by_term: dict[str, list[LexiconEntry]] = defaultdict(list)
    for entry in entries:
        by_term[entry.term].append(entry)

    stopwords = {
        line.strip()
        for line in (CONFIG / "stopwords.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return by_term, stopwords


def load_jieba():
    """延迟导入，避免用户只查看 --help 时也必须安装 Jieba。"""
    try:
        import jieba  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "未安装 jieba。请先运行：python -m pip install jieba"
        ) from exc

    userdict = CONFIG / "jieba_userdict.txt"
    jieba.load_userdict(str(userdict))
    return jieba


def entry_for_area(entries: Iterable[LexiconEntry], scenic_area: str) -> LexiconEntry | None:
    """优先选择当前景区专属词条，其次选择跨景区通用词。"""
    applicable = [e for e in entries if e.scenic_area in ("*", scenic_area)]
    if not applicable:
        return None
    return next((e for e in applicable if e.scenic_area == scenic_area), applicable[0])


def sentence_at(text: str, start: int, end: int) -> str:
    """取实体所在句，供人工复核；位置仍始终以全文 clean_content 为准。"""
    before = text[:start]
    after = text[end:]
    left_matches = list(SENTENCE_BREAK.finditer(before))
    left = left_matches[-1].end() if left_matches else 0
    right_match = SENTENCE_BREAK.search(after)
    right = end + right_match.start() if right_match else len(text)
    return text[left:right].strip()


def resolve_overlaps(candidates: list[dict]) -> list[dict]:
    """同一区域只保留更长的候选；长度相同时优先 TIME、POI、TRANSPORT。"""
    priority = {"TIME": 0, "POI": 1, "TRANSPORT": 2}
    ordered = sorted(
        candidates,
        key=lambda item: (
            -(item["char_end"] - item["char_start"]),
            item["char_start"],
            priority[item["entity_type"]],
        ),
    )
    accepted: list[dict] = []
    for candidate in ordered:
        overlaps = any(
            candidate["char_start"] < kept["char_end"]
            and candidate["char_end"] > kept["char_start"]
            for kept in accepted
        )
        if not overlaps:
            accepted.append(candidate)
    return sorted(accepted, key=lambda item: (item["char_start"], item["char_end"], item["entity_type"]))


def extract_time_candidates(text: str) -> list[dict]:
    candidates: list[dict] = []
    for pattern in TIME_PATTERNS:
        for match in pattern.finditer(text):
            candidates.append(
                {
                    "entity_text": match.group(),
                    "entity_type": "TIME",
                    "char_start": match.start(),
                    "char_end": match.end(),
                    "normalized_name": match.group(),
                    # 与 standards/schema_entities.json 的 method 枚举保持一致；
                    # 具体规则类型由项目说明中的时间正则口径补充说明。
                    "method": "rule",
                    "confidence": 0.98,
                }
            )
    return candidates


def extract_document(
    jieba,
    row: dict[str, str],
    lexicon: dict[str, list[LexiconEntry]],
    stopwords: set[str],
) -> list[dict]:
    """抽取单篇文档，并在此处建立字符位置，禁止由模型或分词器猜位置。"""
    # 不 strip：字符位置必须严格基于 CSV 中原封不动的 clean_content。
    text = row.get("clean_content") or ""
    area = (row.get("scenic_area") or "").strip()
    candidates = extract_time_candidates(text)

    # tokenize 返回 (词语, 起点, 终点)，直接与全文使用同一套字符下标。
    for token, start, end in jieba.tokenize(text, mode="default"):
        if token in stopwords:
            continue
        entry = entry_for_area(lexicon.get(token, []), area)
        if entry is None or entry.entity_type == "TIME":
            continue
        candidates.append(
            {
                "entity_text": token,
                "entity_type": entry.entity_type,
                "char_start": start,
                "char_end": end,
                "normalized_name": entry.normalized_name,
                # 自定义词典驱动的 Jieba 识别属于 schema 中的 dic（词典法）。
                "method": "dic",
                "confidence": 0.95,
            }
        )

    # 词典中的“上午”等不能被正则全部覆盖；以 Jieba token 输出为准，避免按字符串盲扫造成重叠。
    for token, start, end in jieba.tokenize(text, mode="default"):
        entry = entry_for_area(lexicon.get(token, []), area)
        if entry is None or entry.entity_type != "TIME":
            continue
        candidates.append(
            {
                "entity_text": token,
                "entity_type": "TIME",
                "char_start": start,
                "char_end": end,
                "normalized_name": entry.normalized_name,
                "method": "dic",
                "confidence": 0.94,
            }
        )

    entities: list[dict] = []
    for item in resolve_overlaps(candidates):
        start, end = item["char_start"], item["char_end"]
        entity_text = text[start:end]
        # 防御性校验：输出前即保证满足 schema 的最重要约束。
        if entity_text != item["entity_text"]:
            raise ValueError(f"span 回取失败：{item['entity_text']!r} != {entity_text!r}")
        entities.append(
            {
                "doc_id": row.get("doc_id", ""),
                "scenic_area": area,
                "entity_text": entity_text,
                "normalized_name": item["normalized_name"],
                "entity_type": item["entity_type"],
                "char_start": start,
                "char_end": end,
                "sentence": sentence_at(text, start, end),
                "method": item["method"],
                "confidence": item["confidence"],
            }
        )
    return entities


def source_path(area: str) -> Path:
    return ROOT / "scenic" / area / "data" / "processed" / f"{area}_guides.csv"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="P2：Jieba + 自定义词典实体识别")
    parser.add_argument("--areas", nargs="+", choices=AREAS, default=list(AREAS), help="指定待处理景区；默认全部")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写输出文件")
    args = parser.parse_args()

    jieba = load_jieba()
    lexicon, stopwords = load_lexicon()
    entities: list[dict] = []
    errors: list[dict[str, str]] = []
    doc_counts: Counter[str] = Counter()

    for area_key in args.areas:
        try:
            for row in read_csv(source_path(area_key)):
                extracted = extract_document(jieba, row, lexicon, stopwords)
                entities.extend(extracted)
                doc_counts[row.get("doc_id", "")] += len(extracted)
            print(f"[完成] {area_key}: 已处理 {source_path(area_key).name}")
        except Exception as exc:  # 一个景区失败不阻断其他景区，失败原因单独落盘。
            errors.append({"area": area_key, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[失败] {area_key}: {exc}", file=sys.stderr)

    counts = Counter(entity["entity_type"] for entity in entities)
    by_area: dict[str, dict[str, int]] = {}
    for area in ("长隆", "广州白云山", "武功山"):
        by_area[area] = dict(Counter(e["entity_type"] for e in entities if e["scenic_area"] == area))
    stats = {
        "method": "jieba_userdict + regex_time",
        "areas_requested": args.areas,
        "documents_processed": len(doc_counts),
        "entities": len(entities),
        "by_type": dict(counts),
        "by_area": by_area,
        "failed_areas": errors,
    }

    print(f"实体总数：{len(entities)}；类型分布：{dict(counts)}")
    for area, values in by_area.items():
        print(f"  {area}: {values}")

    if not args.dry_run:
        write_jsonl(OUTPUTS / "entities.jsonl", entities)
        write_json(OUTPUTS / "entity_stats.json", stats)
        write_json(OUTPUTS / "extraction_errors.json", errors)
        print(f"输出：{OUTPUTS}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
