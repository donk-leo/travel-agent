# -*- coding: utf-8 -*-
"""把人工标注的 gold 标签与 coref.jsonl 对齐，生成 outputs/annotations.csv。

标注本身在 config/annotations_gold.csv（人工维护），这里只补全 pronoun/sentence，
并校验每个 (doc_id, pronoun_start) 都能在检测结果中找到，防止“标了但没检测到”。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lib.io_utils import read_csv_sig, read_jsonl, write_csv_sig  # noqa: E402
from lib.paths import analysis_dir  # noqa: E402

PROJECT = "p04_coref"
OUT = analysis_dir(PROJECT) / "outputs"
GOLD = analysis_dir(PROJECT) / "config" / "annotations_gold.csv"


def main() -> None:
    coref = {(r["doc_id"], int(r["pronoun_start"])): r for r in read_jsonl(OUT / "coref.jsonl")}
    gold_rows, _ = read_csv_sig(GOLD)
    rows: list[dict] = []
    missing: list[str] = []
    for g in gold_rows:
        key = (g["doc_id"], int(g["pronoun_start"]))
        hit = coref.get(key)
        if not hit:
            missing.append(f"{key[0]}@{key[1]}")
            continue
        rows.append({
            "doc_id": hit["doc_id"],
            "scenic_area": hit.get("scenic_area", ""),
            "doc_type": hit.get("doc_type", ""),
            "pronoun": hit["pronoun"],
            "pronoun_start": hit["pronoun_start"],
            "pronoun_end": hit["pronoun_end"],
            "sentence": hit["sentence"],
            "sentence_start": hit.get("sentence_start", 0),
            "gold_antecedent": g["gold_antecedent"].strip(),
            "gold_type": g["gold_type"].strip(),
            "note": g["note"].strip(),
        })

    if missing:
        raise SystemExit(f"标注样本未在 coref.jsonl 中找到：{missing}")
    if len(rows) < 5:
        raise SystemExit(f"标注不足 5 条：{len(rows)}")

    write_csv_sig(
        OUT / "annotations.csv", rows,
        ["doc_id", "scenic_area", "doc_type", "pronoun", "pronoun_start",
         "pronoun_end", "sentence", "sentence_start", "gold_antecedent", "gold_type", "note"],
    )
    print(f"人工标注 {len(rows)} 条 -> {OUT / 'annotations.csv'}")
    for r in rows:
        print(f"  {r['doc_id']} {r['pronoun']}@{r['pronoun_start']} gold={r['gold_antecedent'] or '∅'} ({r['gold_type']})")


if __name__ == "__main__":
    main()
