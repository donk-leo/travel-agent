# -*- coding: utf-8 -*-
"""项目 1 自检：判断某景区 *_guides.csv 能否直接参与三景区合并。

用法：
    python checks/check_scenic.py scenic/changlong/data/processed/changlong_guides.csv
    python checks/check_scenic.py a.csv b.csv c.csv
    python checks/check_scenic.py --dir scenic/wugongshan/data/processed

检查项（对应 docs/01_统一规范.md 与 standards/schema_scenic.json）：
    1. 合并必需 9 列齐全（与 scenic/wugongshan/src/merge_group.py 的 REQUIRED 一致）
    2. doc_id 格式 <景区码>-<O|T>-<两位序号>，同表内不重复
    3. doc_type 取值合法
    4. clean_content 非空且 ≥ 50 字（过短须标 is_valid=False）
    5. is_valid 可解析为布尔
    6. clean_hash（或 clean_content）无重复
    7. 每景区满足「官方路线 ≥ 1 且有效游记 ≥ 3」

退出码：0 通过；1 存在阻塞合并的问题。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.schema import (  # noqa: E402
    DOC_ID_RE, DOC_TYPE_ENUM, MIN_CLEAN_CHARS, REQUIRED_COLUMNS,
    clean_hash, is_true,
)
from lib.io_utils import read_csv_sig  # noqa: E402
from checks._common import Report  # noqa: E402

NUMERIC_COLS = ["char_raw", "char_clean", "para_raw", "para_clean"]


def check_file(path: Path) -> Report:
    rep = Report(f"{path}")
    if not path.exists():
        rep.error(f"文件不存在：{path}")
        return rep

    rows, cols = read_csv_sig(path)
    if not rows:
        rep.error("文件为空（没有数据行）")
        return rep

    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        rep.error(f"缺少合并必需字段：{missing}")
    if "clean_hash" not in cols:
        rep.warn("缺少 clean_hash 列，合并时将按 clean_content 去重")

    seen_ids: set[str] = set()
    hashes: dict[str, int] = {}
    types: dict[str, int] = {}
    invalid = 0

    for i, row in enumerate(rows, start=2):  # 2 = 第一条数据在 CSV 中的行号
        doc_id = (row.get("doc_id") or "").strip()
        if not doc_id:
            rep.error(f"第 {i} 行：doc_id 为空")
        elif not DOC_ID_RE.match(doc_id):
            rep.error(f"第 {i} 行：doc_id 格式不合规（应形如 CL-O-01）：{doc_id}")
        elif doc_id in seen_ids:
            rep.error(f"第 {i} 行：doc_id 重复：{doc_id}")
        seen_ids.add(doc_id)

        dtype = (row.get("doc_type") or "").strip()
        if dtype not in DOC_TYPE_ENUM:
            rep.error(f"第 {i} 行：doc_type 非法（只允许 {list(DOC_TYPE_ENUM)}）：{dtype}")
        types[dtype] = types.get(dtype, 0) + 1

        clean = (row.get("clean_content") or "").strip()
        if not clean:
            rep.error(f"第 {i} 行（{doc_id}）：clean_content 为空")
        elif len(re.sub(r"\s+", "", clean)) < MIN_CLEAN_CHARS:
            msg = f"第 {i} 行（{doc_id}）：clean_content 仅 {len(clean)} 字，偏短"
            if is_true(row.get("is_valid", "")):
                rep.error(msg + "，却标 is_valid=True（应标 False 并写 quality_flags）")
            else:
                rep.warn(msg + "（已标无效，可保留）")

        valid_raw = (row.get("is_valid") or "").strip()
        if valid_raw and valid_raw.lower() not in {"true", "false", "1", "0", "yes", "no", "是", "否"}:
            rep.error(f"第 {i} 行：is_valid 无法解析为布尔：{valid_raw}")
        if not is_true(valid_raw):
            invalid += 1

        for c in NUMERIC_COLS:
            v = (row.get(c) or "").strip()
            if v and not re.fullmatch(r"-?\d+(\.\d+)?", v):
                rep.warn(f"第 {i} 行：{c} 不是数字：{v}")

        key = (row.get("clean_hash") or "").strip() or clean_hash(clean)
        hashes[key] = hashes.get(key, 0) + 1

    dup = {k: v for k, v in hashes.items() if v > 1}
    if dup:
        rep.error(f"存在 {len(dup)} 组重复正文（clean_hash 相同），合并时会被去重")

    official = types.get("官方路线", 0)
    valid_notes = sum(
        1 for r in rows
        if (r.get("doc_type") or "").strip() in ("游客游记", "站点攻略")
        and is_true(r.get("is_valid", ""))
    )
    if official < 1:
        rep.error("没有官方路线（任务书要求每个景区 ≥ 1 条真实路线页）")
    if valid_notes < 3:
        rep.error(f"有效游客游记只有 {valid_notes} 篇（任务书要求 ≥ 3 篇）")

    rep.note(f"记录数 {len(rows)}，类型 {types}，无效 {invalid}，"
             f"官方 {official} / 有效游记 {valid_notes}")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="项目1 数据集自检")
    ap.add_argument("files", nargs="*", help="CSV 路径")
    ap.add_argument("--dir", help="扫描目录下的 *_guides.csv")
    args = ap.parse_args()

    files = [Path(p) for p in args.files]
    if args.dir:
        files += sorted(Path(args.dir).glob("*_guides.csv"))
    if not files:
        ap.print_help()
        return 2

    failed = 0
    for f in files:
        failed |= check_file(f).finish()
    return failed


if __name__ == "__main__":
    sys.exit(main())
