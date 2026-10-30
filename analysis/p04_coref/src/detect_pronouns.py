# -*- coding: utf-8 -*-
"""P4 第一步：从三景区 clean_content 中检测代词，输出带绝对位置的候选表。

- 输入：scenic/<area>/data/processed/<area>_guides.csv（P1 冻结数据）
- 输出：analysis/p04_coref/outputs/pronoun_candidates.jsonl
        analysis/p04_coref/outputs/pronoun_stats.json

位置口径：以 clean_content 为准，字符下标从 0 开始，[pronoun_start, pronoun_end)。
同一句出现多个相同代词时，每个 occurrence 单独一行，靠 start 区分，不串号。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lib.io_utils import read_csv_sig, write_json, write_jsonl  # noqa: E402
from lib.paths import SCENIC_AREAS, analysis_dir, scenic_csv  # noqa: E402

PROJECT = "p04_coref"
OUT = analysis_dir(PROJECT) / "outputs"
CONFIG = analysis_dir(PROJECT) / "config"
SENT_END = __import__("re").compile(r"[。！？!?；;\n]+")


def load_pronouns() -> list[str]:
    words: list[str] = []
    for line in (CONFIG / "pronouns.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line)
    # 最长优先，保证“这里”不会被“这”抢先匹配
    return sorted(set(words), key=len, reverse=True)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for m in SENT_END.finditer(text):
        end = m.end()
        if end > start:
            spans.append((start, end))
        start = end
    if start < len(text):
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def main() -> None:
    import re

    pron_re = re.compile("|".join(re.escape(w) for w in load_pronouns()))
    rows: list[dict] = []
    by_pronoun: Counter[str] = Counter()
    by_area: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    docs_with_pronoun: set[str] = set()
    duplicate_sentence = 0

    for area in SCENIC_AREAS:
        records, _ = read_csv_sig(scenic_csv(area))
        for rec in records:
            doc_id = rec["doc_id"]
            text = rec.get("clean_content", "") or ""
            if not text:
                continue
            spans = sentence_spans(text)

            def span_of(pos: int) -> tuple[int, int]:
                for s, e in spans:
                    if s <= pos < e:
                        return s, e
                return 0, len(text)

            sent_hits: dict[tuple[int, int], Counter[str]] = defaultdict(Counter)
            for m in pron_re.finditer(text):
                s, e = span_of(m.start())
                sentence = text[s:e]
                row = {
                    "doc_id": doc_id,
                    "scenic_area": area,
                    "doc_type": rec.get("doc_type", ""),
                    "pronoun": m.group(),
                    "pronoun_start": m.start(),
                    "pronoun_end": m.end(),
                    "sentence": sentence,
                    "sentence_start": s,
                    "sentence_end": e,
                    "context_before": text[max(0, m.start() - 30):m.start()],
                    "context_after": text[m.end():m.end() + 30],
                }
                rows.append(row)
                sent_hits[(s, e)][m.group()] += 1
                by_pronoun[m.group()] += 1
                by_area[area] += 1
                by_type[rec.get("doc_type", "")] += 1
                docs_with_pronoun.add(doc_id)

            duplicate_sentence += sum(1 for c in sent_hits.values() for n in c.values() if n > 1)

    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT / "pronoun_candidates.jsonl", rows)
    stats = {
        "documents": len({r["doc_id"] for r in rows}),
        "documents_with_pronoun": len(docs_with_pronoun),
        "candidates": len(rows),
        "by_area": dict(by_area),
        "by_doc_type": dict(by_type),
        "by_pronoun": dict(by_pronoun.most_common()),
        "same_sentence_repeated_groups": duplicate_sentence,
        "note": "同句多个相同代词按 occurrence 分行，start 不同；此统计只用于报告。",
    }
    write_json(OUT / "pronoun_stats.json", stats)

    print(f"代词候选 {len(rows)} 条，覆盖 {len(docs_with_pronoun)} 篇文档")
    print("按代词：", dict(by_pronoun.most_common()))
    print("按景区：", dict(by_area))
    print("同句重复代词组：", duplicate_sentence)
    print("->", OUT / "pronoun_candidates.jsonl")


if __name__ == "__main__":
    main()
