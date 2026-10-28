# -*- coding: utf-8 -*-
"""项目 2 自检：实体识别输出是否符合契约。

用法：
    python checks/check_entities.py [analysis/p02_entities/outputs/entities.jsonl]

检查：必填字段、实体类型枚举、span 合法性、entity_text 与 clean_content 精确对应、
重复实体、按类型/景区的数量统计。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks._common import (  # noqa: E402
    Report, check_fields, check_int_range, load_jsonl, not_ready,
)
from lib.paths import ANALYSIS, SCENIC_AREAS, scenic_csv  # noqa: E402
from lib.io_utils import read_csv_sig  # noqa: E402

DEFAULT = ANALYSIS / "p02_entities" / "outputs" / "entities.jsonl"
REQUIRED = ["doc_id", "entity_text", "entity_type", "char_start", "char_end"]
TYPES = {"POI", "TRANSPORT", "TIME"}


def load_clean_texts() -> dict[str, str]:
    texts: dict[str, str] = {}
    for area in SCENIC_AREAS:
        path = scenic_csv(area)
        if path.exists():
            rows, _ = read_csv_sig(path)
            for r in rows:
                texts[(r.get("doc_id") or "").strip()] = r.get("clean_content") or ""
    return texts


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        return not_ready("p02_entities", [path])

    rows = load_jsonl(path)
    rep = Report(f"p02_entities · {path.name} · {len(rows)} 条实体")
    check_fields(rep, rows, REQUIRED, {"entity_type": TYPES}, label="实体")
    check_int_range(rep, rows, "char_start", "char_end")

    texts = load_clean_texts()
    seen: set[tuple] = set()
    counts, by_area = Counter(), Counter()
    for i, row in enumerate(rows, start=1):
        doc_id = (row.get("doc_id") or "").strip()
        text = (row.get("entity_text") or "").strip()
        counts[row.get("entity_type")] += 1
        by_area[doc_id.split("-")[0]] += 1

        key = (doc_id, row.get("char_start"), row.get("char_end"), text)
        if key in seen:
            rep.error(f"第 {i} 条重复：{key}")
        seen.add(key)

        if doc_id not in texts:
            rep.error(f"第 {i} 条的 doc_id 不在三景区数据集中：{doc_id}")
            continue
        try:
            start, end = int(row["char_start"]), int(row["char_end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < 0 or end > len(texts[doc_id]):
            rep.error(f"第 {i} 条 span 越界：{start}..{end} > {len(texts[doc_id])}")
        elif texts[doc_id][start:end] != text:
            rep.error(f"第 {i} 条 entity_text 与原文不一致：{text!r} != "
                      f"{texts[doc_id][start:end]!r}（doc {doc_id}）")

    rep.note(f"类型分布 {dict(counts)}；景区分布 {dict(by_area)}")
    for t, minimum in (("POI", 50), ("TIME", 20)):
        if counts.get(t, 0) < minimum:
            rep.warn(f"{t} 只有 {counts.get(t, 0)} 个（验收建议 ≥ {minimum}）")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
