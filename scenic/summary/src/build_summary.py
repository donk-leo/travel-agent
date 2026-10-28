# -*- coding: utf-8 -*-
"""三景区合并：读取 scenic/ 下三个已冻结的 *_guides.csv，去重并输出汇总数据。

不重新清洗、不修改各景区 clean_content；只做字段校验、合并、去重和统计。

用法（仓库根）：
    python scenic/summary/src/build_summary.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SUMMARY = ROOT / "scenic" / "summary"
DATA = SUMMARY / "data"
OUT = SUMMARY / "outputs"
DATA.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

COLS = [
    "doc_id", "scenic_area", "doc_type", "subtype", "title", "author",
    "publish_date", "source_site", "source_url", "extract_rule",
    "raw_content", "clean_content", "char_raw", "char_clean", "para_raw",
    "para_clean", "removed_char_ratio", "noise_lines_removed", "emoji_removed",
    "urls_removed", "dup_paragraphs_removed", "quality_flags", "is_valid",
    "clean_hash",
]
AREAS = [
    ("长隆", ROOT / "scenic" / "changlong" / "data" / "processed" / "changlong_guides.csv"),
    ("广州白云山", ROOT / "scenic" / "baiyunshan" / "data" / "processed" / "baiyunshan_guides.csv"),
    ("武功山", ROOT / "scenic" / "wugongshan" / "data" / "processed" / "wugongshan_guides.csv"),
]


def main() -> None:
    frames = []
    for area, path in AREAS:
        df = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
        missing = [c for c in COLS if c not in df.columns]
        if missing:
            raise SystemExit(f"{path} 缺字段：{missing}")
        df = df[COLS].copy()
        df["is_valid"] = df["is_valid"].astype(str).str.lower().isin(["true", "1", "yes"])
        df["author"] = df["author"].replace("", "未知")
        df["publish_date"] = df["publish_date"].replace("", "未知")
        print(f"{area}: {len(df)} 条 <- {path.relative_to(ROOT)}")
        frames.append(df)

    df = pd.concat(frames, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates(subset=["clean_hash"]).reset_index(drop=True)
    print(f"合并：{before} -> {len(df)} 条（按 clean_hash 去重）")

    # 统一排序：景区 -> 官方 -> 游记 -> 攻略 -> doc_id
    order = {"官方路线": 0, "游客游记": 1, "站点攻略": 2}
    df["__area"] = pd.Categorical(df["scenic_area"], [a for a, _ in AREAS], ordered=True)
    df["__type"] = df["doc_type"].map(order).fillna(9)
    df = df.sort_values(["__area", "__type", "doc_id"]).drop(columns=["__area", "__type"]).reset_index(drop=True)

    df.to_csv(DATA / "三景区汇总数据集.csv", index=False, encoding="utf-8-sig", lineterminator="
")

    rows = []
    for area, _ in AREAS:
        g = df[df.scenic_area == area]
        rows.append({
            "景区": area,
            "记录数": len(g),
            "官方路线": int((g.doc_type == "官方路线").sum()),
            "游客游记": int((g.doc_type == "游客游记").sum()),
            "站点攻略": int((g.doc_type == "站点攻略").sum()),
            "有效游客游记": int(((g.doc_type == "游客游记") & g.is_valid).sum()),
            "有效记录": int(g.is_valid.sum()),
            "原始字数": int(g.char_raw.sum()),
            "清洗后字数": int(g.char_clean.sum()),
            "满足最低要求": bool((g.doc_type == "官方路线").sum() >= 1
                              and ((g.doc_type == "游客游记") & g.is_valid).sum() >= 3),
        })
    stat = pd.DataFrame(rows)
    stat.to_csv(DATA / "三景区汇总统计.csv", index=False, encoding="utf-8-sig", lineterminator="
")
    print(stat.to_string(index=False))

    summary = {
        "records": len(df),
        "areas": int(df.scenic_area.nunique()),
        "official": int((df.doc_type == "官方路线").sum()),
        "travelogue": int((df.doc_type == "游客游记").sum()),
        "guide": int((df.doc_type == "站点攻略").sum()),
        "valid": int(df.is_valid.sum()),
        "char_raw": int(df.char_raw.sum()),
        "char_clean": int(df.char_clean.sum()),
        "missing_author": int((df.author == "未知").sum()),
        "missing_date": int((df.publish_date == "未知").sum()),
        "duplicates": int(df.clean_hash.duplicated().sum()),
        "by_area": rows,
    }
    (OUT / "统计摘要.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print("输出 ->", DATA, "|", OUT)


if __name__ == "__main__":
    main()
