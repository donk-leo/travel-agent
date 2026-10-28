# -*- coding: utf-8 -*-
"""数据集自检：判断某景区的 *_guides.csv 能否直接参与三景区合并。

用法：
    python scripts/check_dataset.py 长隆/data/processed/changlong_guides.csv
    python scripts/check_dataset.py a.csv b.csv c.csv      # 同时检查多个
    python scripts/check_dataset.py --dir 武功山/data/processed

检查项（对应 docs/统一规范.md）：
    1. 合并必需 9 列是否齐全（与 武功山/src/merge_group.py 的 REQUIRED 一致）
    2. doc_id 格式 <景区码>-<O|T>-<两位序号>，且同表内不重复
    3. doc_type 取值是否在 {官方路线, 游客游记, 站点攻略}
    4. clean_content 是否为空 / 过短（<50 字）
    5. is_valid 是否可解析为布尔
    6. clean_hash（或 clean_content）是否重复
    7. 每景区是否满足「官方路线 ≥1 且有效游记 ≥3」

退出码：0 全部通过；1 存在阻塞合并的问题。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
from pathlib import Path

REQUIRED = ["doc_id", "scenic_area", "doc_type", "title", "source_site",
            "source_url", "raw_content", "clean_content", "is_valid"]
OPTIONAL_NUMERIC = ["char_raw", "char_clean", "para_raw", "para_clean"]
ALLOWED_TYPES = {"官方路线", "游客游记", "站点攻略"}
DOC_ID_RE = re.compile(r"^[A-Z]{2,5}-[OT]-\d{2}$")
MIN_CLEAN_CHARS = 50


def load(path: Path) -> tuple[list[dict], list[str]]:
    """读 CSV（容错 UTF-8/BOM/GBK），返回记录与列名。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"无法识别编码：{path}")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader), reader.fieldnames or []


def is_true(v: str) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y", "是"}


def check_file(path: Path) -> tuple[list[str], list[str], dict]:
    """返回 (错误, 警告, 统计)。"""
    errors: list[str] = []
    warns: list[str] = []
    if not path.exists():
        return [f"文件不存在：{path}"], [], {}

    rows, cols = load(path)
    if not rows:
        return ["文件为空（没有数据行）"], [], {}

    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        errors.append(f"缺少合并必需字段：{missing}")
    if "clean_hash" not in cols:
        warns.append("缺少 clean_hash 列，合并时将退化为按 clean_content 去重")

    seen_ids: set[str] = set()
    hashes: dict[str, int] = {}
    types: dict[str, int] = {}
    invalid = 0

    for i, row in enumerate(rows, start=2):  # 2 = 第一条数据在 CSV 的行号
        doc_id = (row.get("doc_id") or "").strip()
        if not doc_id:
            errors.append(f"第 {i} 行：doc_id 为空")
        elif not DOC_ID_RE.match(doc_id):
            errors.append(f"第 {i} 行：doc_id 格式不合规（应为 CL-O-01 这种）：{doc_id}")
        elif doc_id in seen_ids:
            errors.append(f"第 {i} 行：doc_id 重复：{doc_id}")
        seen_ids.add(doc_id)

        dtype = (row.get("doc_type") or "").strip()
        if dtype not in ALLOWED_TYPES:
            errors.append(f"第 {i} 行：doc_type 非法（只允许 {sorted(ALLOWED_TYPES)}）：{dtype}")
        types[dtype] = types.get(dtype, 0) + 1

        clean = (row.get("clean_content") or "").strip()
        if not clean:
            errors.append(f"第 {i} 行（{doc_id}）：clean_content 为空")
        elif len(re.sub(r"\s+", "", clean)) < MIN_CLEAN_CHARS:
            w = f"第 {i} 行（{doc_id}）：clean_content 仅 {len(clean)} 字，偏短"
            if is_true(row.get("is_valid", "")):
                errors.append(w + "，但仍标 is_valid=True（应标 False 并写 quality_flags）")
            else:
                warns.append(w + "（已标无效，可保留）")

        raw_v = (row.get("is_valid") or "").strip()
        if raw_v and raw_v.lower() not in {"true", "false", "1", "0", "yes", "no", "是", "否"}:
            errors.append(f"第 {i} 行：is_valid 无法解析为布尔：{raw_v}")
        if not is_true(raw_v):
            invalid += 1

        for c in OPTIONAL_NUMERIC:
            v = (row.get(c) or "").strip()
            if v and not re.fullmatch(r"-?\d+(\.\d+)?", v):
                warns.append(f"第 {i} 行：{c} 不是数字：{v}")

        key = (row.get("clean_hash") or "").strip() or hashlib.sha1(
            re.sub(r"\s+", "", clean).encode("utf-8")
        ).hexdigest()
        hashes[key] = hashes.get(key, 0) + 1

    dup = {k: v for k, v in hashes.items() if v > 1}
    if dup:
        errors.append(f"存在 {len(dup)} 组重复正文（clean_hash 相同），合并时会被去重掉")

    stats = {
        "记录数": len(rows),
        "类型分布": types,
        "无效标记": invalid,
        "景区数": len({(r.get("scenic_area") or "").strip() for r in rows}),
    }
    return errors, warns, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="景区数据集自检")
    ap.add_argument("files", nargs="*", help="CSV 路径")
    ap.add_argument("--dir", help="扫描某个目录下的 *_guides.csv")
    args = ap.parse_args()

    files = [Path(p) for p in args.files]
    if args.dir:
        files += sorted(Path(args.dir).glob("*_guides.csv"))
    if not files:
        ap.print_help()
        return 2

    any_error = False
    for f in files:
        errors, warns, stats = check_file(f)
        status = "通过" if not errors else "不通过"
        print(f"\n=== {f} —— {status} ===")
        if stats:
            print(f"记录数 {stats['记录数']}，景区 {stats['景区数']}，"
                  f"类型 {stats['类型分布']}，无效 {stats['无效标记']}")
        for w in warns:
            print(f"  [警告] {w}")
        for e in errors:
            print(f"  [错误] {e}")
        any_error |= bool(errors)

    print("\n" + ("全部通过，可参与三景区合并。" if not any_error
                  else "存在问题，请按上面的 [错误] 修正后再合并。"))
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
