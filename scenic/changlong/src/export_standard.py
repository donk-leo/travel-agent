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
from lib.clean_rules import strip_html, unescape_entities  # noqa: E402

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


def to_plain_text(html_or_text: str) -> str:
    """把抽取结果统一成"纯文本"口径（与武功山/白云山一致）。

    官网三篇的原始抽取结果是 innerHTML，含大量样式标签；组内另外两个景区的
    raw_content 都是"去标签后的正文"。若不做这一步，长隆的 char_raw 会虚高，
    跨景区的"原始字数 / 删除比例"统计不可比。
    注意：这里只去标签、还原实体、统一换行，**保留模板噪声**（raw 的语义就是清洗前）。
    """
    text = unescape_entities(html_or_text or "")
    text = strip_html(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(ln.strip() for ln in text.split("\n")).strip()


def convert_row(row: dict) -> dict:
    raw = to_plain_text(row.get("raw_text") or "")
    clean = (row.get("clean_text") or "").replace("\r\n", "\n").strip()
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

    char_raw = len(re.sub(r"\s+", "", raw))
    char_clean = int(row.get("char_count_no_space") or len(re.sub(r"\s+", "", clean)))
    para_raw, para_clean = count_paragraphs(raw), count_paragraphs(clean)
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
        "char_raw": char_raw,
        "char_clean": char_clean,
        "para_raw": para_raw,
        "para_clean": para_clean,
        "removed_char_ratio": round(1 - char_clean / char_raw, 3) if char_raw else 0.0,
        "noise_lines_removed": max(0, para_raw - para_clean),
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
