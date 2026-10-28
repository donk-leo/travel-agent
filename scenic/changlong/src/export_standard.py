# -*- coding: utf-8 -*-
"""长隆：把本地历史数据集（20 列英文结构）转换为组内标准 24 列。

输入：data/interim/legacy_20col.csv（由 experiment1_chimelong 的清洗流程产出，随仓库提交）
输出：data/processed/changlong_guides.csv（24 列，UTF-8-SIG）

映射规则见 docs/01_统一规范.md 第 5 节。

用法：
    python scenic/changlong/src/export_standard.py
    python scenic/changlong/src/export_standard.py --input 别的.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from lib.schema import SCENIC_COLUMNS, clean_hash, count_paragraphs  # noqa: E402
from lib.io_utils import read_csv_sig, write_csv_sig  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
DEFAULT_IN = BASE / "data" / "interim" / "legacy_20col.csv"
DEFAULT_OUT = BASE / "data" / "processed" / "changlong_guides.csv"

#: 旧 doc_id 前缀 -> 新编码
ID_PREFIX = {"CHL-O": "CL-O-", "CHL-N": "CL-T-"}


def map_doc_id(old: str) -> str:
    """CHL-O01 -> CL-O-01；CHL-N01 -> CL-T-01。"""
    for old_prefix, new_prefix in ID_PREFIX.items():
        if old.startswith(old_prefix):
            seq = old[len(old_prefix):].zfill(2)
            return f"{new_prefix}{seq}"
    raise ValueError(f"无法识别的 doc_id：{old}")


def from_log(log: str, label: str) -> int:
    """从 cleaning_log 中取出某条规则的削减量，如 '去除 emoji 与装饰符号-173'。"""
    match = re.search(rf"{re.escape(label)}-(\d+)", log or "")
    return int(match.group(1)) if match else 0


def convert_row(row: dict) -> dict:
    raw = row.get("raw_text") or ""
    clean = row.get("clean_text") or ""
    log = row.get("cleaning_log") or ""
    author = (row.get("author") or "").strip()
    date = (row.get("publish_date") or "").strip()
    park = (row.get("park") or "").strip()
    valid = str(row.get("is_valid", "")).strip().lower() in {"true", "1"}

    flags = ["长隆"]
    if park:
        flags.append(f"子园区:{park}")
    if not author:
        flags.append("作者缺失")
    if not date:
        flags.append("日期缺失")
    if not valid:
        flags.append("文本过短")

    return {
        "doc_id": map_doc_id((row.get("doc_id") or "").strip()),
        "scenic_area": "长隆",
        "doc_type": (row.get("doc_type") or "").strip(),
        "subtype": park or "未分类",
        "title": (row.get("title") or "").strip(),
        "author": author or "未知",
        "publish_date": date or "未知",
        "source_site": (row.get("source_site") or "").strip(),
        "source_url": (row.get("source_url") or "").strip(),
        "extract_rule": (row.get("extract_rule") or "").strip(),
        "raw_content": raw,
        "clean_content": clean,
        "char_raw": len(re.sub(r"\s+", "", raw)),
        "char_clean": int(row.get("char_count_no_space") or len(re.sub(r"\s+", "", clean))),
        "para_raw": count_paragraphs(raw),
        "para_clean": count_paragraphs(clean),
        "removed_char_ratio": round(float(row.get("reduction_rate") or 0), 3),
        "noise_lines_removed": max(0, count_paragraphs(raw) - count_paragraphs(clean)),
        "emoji_removed": from_log(log, "去除 emoji 与装饰符号"),
        "urls_removed": from_log(log, "去除网址/邮箱/客服电话"),
        "dup_paragraphs_removed": from_log(log, "段内重复行去重"),
        "quality_flags": ";".join(flags),
        "is_valid": "True" if valid else "False",
        "clean_hash": clean_hash(clean),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="长隆 20 列 -> 24 列标准格式")
    ap.add_argument("--input", default=str(DEFAULT_IN))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    rows, cols = read_csv_sig(args.input)
    if not rows:
        raise SystemExit(f"输入为空：{args.input}")
    out = [convert_row(r) for r in rows]
    write_csv_sig(args.output, out, SCENIC_COLUMNS)

    print(f"转换完成：{len(out)} 条 -> {args.output}")
    for r in out:
        print(f"  {r['doc_id']:<8} {r['doc_type']:<5} {r['subtype']:<10} "
              f"raw={r['char_raw']:>5} clean={r['char_clean']:>5} valid={r['is_valid']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
