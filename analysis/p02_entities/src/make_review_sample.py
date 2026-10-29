#!/usr/bin/env python3
"""生成 P2 人工抽查表。

从 entities.jsonl 中按“实体类型 × 景区”分层抽取 30 条：每类 10 条。
每条保留原句、定位片段和完整 clean_content，方便复核人独立验证实体与位置。

用法：
    python analysis/p02_entities/src/make_review_sample.py
"""
from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "analysis" / "p02_entities"
OUTPUTS = PROJECT / "outputs"
AREAS = ("长隆", "广州白云山", "武功山")
TYPES = ("POI", "TRANSPORT", "TIME")

# 30 条：每一类 10 条，同时让每个景区在每一类里至少有 3 条。
QUOTAS = {
    ("POI", "长隆"): 4,
    ("POI", "广州白云山"): 3,
    ("POI", "武功山"): 3,
    ("TRANSPORT", "长隆"): 3,
    ("TRANSPORT", "广州白云山"): 4,
    ("TRANSPORT", "武功山"): 3,
    ("TIME", "长隆"): 3,
    ("TIME", "广州白云山"): 3,
    ("TIME", "武功山"): 4,
}


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_clean_texts() -> dict[str, str]:
    result: dict[str, str] = {}
    for area in ("changlong", "baiyunshan", "wugongshan"):
        path = ROOT / "scenic" / area / "data" / "processed" / f"{area}_guides.csv"
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                result[row["doc_id"]] = row["clean_content"]
    return result


def excerpt(text: str, start: int, end: int, radius: int = 80) -> str:
    left, right = max(0, start - radius), min(len(text), end + radius)
    prefix = "…" if left else ""
    suffix = "…" if right < len(text) else ""
    return prefix + text[left:right].replace("\n", " / ") + suffix


def pick_diverse(rows: list[dict], count: int, rng: random.Random) -> list[dict]:
    """优先覆盖不同文档，再在不足时从同一文档补足。"""
    shuffled = rows[:]
    rng.shuffle(shuffled)
    selected: list[dict] = []
    seen_docs: set[str] = set()
    for row in shuffled:
        if row["doc_id"] not in seen_docs:
            selected.append(row)
            seen_docs.add(row["doc_id"])
        if len(selected) == count:
            return selected
    for row in shuffled:
        if row not in selected:
            selected.append(row)
        if len(selected) == count:
            return selected
    if len(selected) < count:
        raise ValueError(f"样本不足：需要 {count}，实际只有 {len(selected)}")
    return selected


def main() -> None:
    entities = load_jsonl(OUTPUTS / "entities.jsonl")
    clean_texts = load_clean_texts()
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for entity in entities:
        groups[(entity["entity_type"], entity["scenic_area"])].append(entity)

    rng = random.Random(20261028)
    samples: list[dict] = []
    for entity_type in TYPES:
        for area in AREAS:
            key = (entity_type, area)
            samples.extend(pick_diverse(groups[key], QUOTAS[key], rng))

    # 先按类型、景区、文档和位置排序，便于纸面或 Excel 逐条核验。
    samples.sort(key=lambda r: (TYPES.index(r["entity_type"]), AREAS.index(r["scenic_area"]), r["doc_id"], r["char_start"]))
    out = OUTPUTS / "manual_review_samples.csv"
    fields = [
        "sample_id", "doc_id", "scenic_area", "entity_text", "entity_type",
        "char_start", "char_end", "normalized_name", "method", "confidence",
        "source_sentence", "source_excerpt", "clean_content_full",
        "manual_verdict", "issue_type", "suggested_correction", "reviewer_note",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for index, entity in enumerate(samples, start=1):
            text = clean_texts[entity["doc_id"]]
            start, end = int(entity["char_start"]), int(entity["char_end"])
            # 生成前再次验证，避免把无法回取的样本交给复核人。
            if text[start:end] != entity["entity_text"]:
                raise ValueError(f"{entity['doc_id']} 的字符位置无法回取 {entity['entity_text']!r}")
            writer.writerow(
                {
                    "sample_id": f"P2-R{index:02d}",
                    "doc_id": entity["doc_id"],
                    "scenic_area": entity["scenic_area"],
                    "entity_text": entity["entity_text"],
                    "entity_type": entity["entity_type"],
                    "char_start": start,
                    "char_end": end,
                    "normalized_name": entity.get("normalized_name", ""),
                    "method": entity.get("method", ""),
                    "confidence": entity.get("confidence", ""),
                    "source_sentence": entity.get("sentence", ""),
                    "source_excerpt": excerpt(text, start, end),
                    "clean_content_full": text,
                    "manual_verdict": "待复核",
                    "issue_type": "",
                    "suggested_correction": "",
                    "reviewer_note": "",
                }
            )

    counts = defaultdict(int)
    for row in samples:
        counts[(row["entity_type"], row["scenic_area"])] += 1
    print(f"已生成 {len(samples)} 条人工抽查样本：{out}")
    for key in sorted(counts):
        print(f"  {key[0]} / {key[1]}: {counts[key]}")


if __name__ == "__main__":
    main()
