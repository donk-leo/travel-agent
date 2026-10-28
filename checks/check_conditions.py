# -*- coding: utf-8 -*-
"""项目 5 自检：条件-建议抽取输出是否合规。

用法：
    python checks/check_conditions.py [analysis/p05_conditions/outputs/conditions.jsonl]

检查：必填字段、条件类型枚举、cond_id 唯一、条件/建议为原文片段、
映射表是否存在、按类型统计。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks._common import Report, check_fields, load_jsonl, not_ready  # noqa: E402
from lib.paths import ANALYSIS  # noqa: E402

OUT = ANALYSIS / "p05_conditions" / "outputs"
DEFAULT = OUT / "conditions.jsonl"
REQUIRED = ["cond_id", "doc_id", "scenic_area", "condition_type",
            "condition_text", "suggestion_text", "source_sentence"]
TYPES = {"天气", "人群", "时间", "体力", "预算", "交通", "其他"}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        return not_ready("p05_conditions", [path])

    rows = load_jsonl(path)
    rep = Report(f"p05_conditions · {path.name} · {len(rows)} 条条件-建议")
    check_fields(rep, rows, REQUIRED, {"condition_type": TYPES}, label="记录")

    ids = Counter(r.get("cond_id") for r in rows)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        rep.error(f"cond_id 重复：{dup[:5]}")

    for i, row in enumerate(rows, start=1):
        cond = str(row.get("condition_text", ""))
        sugg = str(row.get("suggestion_text", ""))
        sent = str(row.get("source_sentence", ""))
        if cond and sent and cond not in sent:
            rep.warn(f"第 {i} 条 condition_text 不是 source_sentence 的子串")
        if sugg and sent and sugg not in sent:
            rep.warn(f"第 {i} 条 suggestion_text 不是 source_sentence 的子串")

    rep.note(f"条件类型分布 {dict(Counter(r.get('condition_type') for r in rows))}")
    rep.note(f"景区分布 {dict(Counter(r.get('scenic_area') for r in rows))}")

    table = OUT / "映射表.xlsx"
    if not table.exists():
        rep.warn(f"缺少映射表 {table.name}（任务书要求 Excel/CSV 映射表）")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
