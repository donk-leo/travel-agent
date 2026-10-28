# -*- coding: utf-8 -*-
"""项目 4 自检：共指消解输出与人工标注是否齐全。

用法：
    python checks/check_coref.py [analysis/p04_coref/outputs/coref.jsonl]

检查：必填字段、方法枚举、代词/先行词 span、标注文件 ≥5 条、评估文件存在。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks._common import (  # noqa: E402
    Report, check_fields, check_int_range, load_jsonl, not_ready,
)
from lib.paths import ANALYSIS  # noqa: E402
from lib.io_utils import read_csv_sig  # noqa: E402

OUT = ANALYSIS / "p04_coref" / "outputs"
DEFAULT = OUT / "coref.jsonl"
REQUIRED = ["doc_id", "pronoun", "pronoun_start", "pronoun_end", "sentence", "method"]
METHODS = {"rule_nearest", "model", "llm"}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        return not_ready("p04_coref", [path])

    rows = load_jsonl(path)
    rep = Report(f"p04_coref · {path.name} · {len(rows)} 条消解结果")
    check_fields(rep, rows, REQUIRED, {"method": METHODS}, label="结果")
    check_int_range(rep, rows, "pronoun_start", "pronoun_end", label="代词 span")

    resolved = sum(1 for r in rows if str(r.get("antecedent", "")).strip())
    rep.note(f"已消解 {resolved}/{len(rows)}；"
             f"方法分布 {dict(Counter(r.get('method') for r in rows))}")

    ann = OUT / "annotations.csv"
    if not ann.exists():
        rep.error(f"缺少人工标注文件：{ann}")
    else:
        ann_rows, cols = read_csv_sig(ann)
        need = ["doc_id", "pronoun", "pronoun_start", "sentence", "gold_antecedent"]
        missing = [c for c in need if c not in cols]
        if missing:
            rep.error(f"annotations.csv 缺列：{missing}")
        if len(ann_rows) < 5:
            rep.error(f"人工标注只有 {len(ann_rows)} 条（要求 ≥ 5 条）")
        else:
            rep.note(f"人工标注 {len(ann_rows)} 条")

    if not (OUT / "eval.md").exists():
        rep.error("缺少评估说明：outputs/eval.md（准确率/覆盖率计算过程）")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
