# -*- coding: utf-8 -*-
"""小组汇总：把三位成员各自景区的主数据集合并成一份三景区汇总表。

约定：每位成员交付 `data/processed/<景区>_guides.csv`，字段与本项目一致
（doc_id / scenic_area / doc_type / ... / clean_content / is_valid ...）。

用法：
    python src/merge_group.py                          # 自动扫描 data/processed/*_guides.csv
    python src/merge_group.py a.csv b.csv c.csv        # 指定三个文件
输出：
    outputs/三景区汇总数据集.csv
    outputs/三景区汇总统计.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from common import OUTPUT_DIR, PROCESSED_DIR, setup_logging

REQUIRED = ["doc_id", "scenic_area", "doc_type", "title", "source_site",
            "source_url", "raw_content", "clean_content", "is_valid"]


def main() -> None:
    setup_logging()
    files = [Path(p) for p in sys.argv[1:]] or sorted(PROCESSED_DIR.glob("*_guides.csv"))
    if not files:
        raise SystemExit("未找到 *_guides.csv，请先运行各景区的清洗流程或显式传入文件。")

    frames = []
    for f in files:
        df = pd.read_csv(f, encoding="utf-8-sig", keep_default_na=False)
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            raise SystemExit(f"{f.name} 缺少字段：{missing}")
        frames.append(df)
        print(f"读入 {f.name}: {len(df)} 条")
    data = pd.concat(frames, ignore_index=True)

    before = len(data)
    data = data.drop_duplicates(subset=["clean_hash"] if "clean_hash" in data.columns else ["clean_content"])
    print(f"合并去重：{before} -> {len(data)} 条")

    data.to_csv(OUTPUT_DIR / "三景区汇总数据集.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    stats = (data.assign(is_valid=data["is_valid"].astype(str).str.lower().isin(["true", "1", "yes"]))
                 .groupby(["scenic_area", "doc_type"])
                 .agg(记录数=("doc_id", "count"), 有效数=("is_valid", "sum"),
                      清洗后字数=("char_clean", "sum"))
                 .reset_index())
    stats.to_csv(OUTPUT_DIR / "三景区汇总统计.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    print(stats.to_string(index=False))

    areas = data["scenic_area"].nunique()
    if areas < 3:
        print(f"提示：当前只有 {areas} 个景区，任务书要求 3 个；请补齐其他成员的数据。")
    print(f"汇总完成 -> {OUTPUT_DIR / '三景区汇总数据集.csv'}")


if __name__ == "__main__":
    main()
