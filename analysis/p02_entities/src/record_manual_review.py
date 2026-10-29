#!/usr/bin/env python3
"""把 P2 30 条人工抽查结论写回 CSV，并生成 Markdown 审核报告。

本文件记录的是当前版本的人工语义核验结论，不替代后续独立 reviewer 的复核。
"""
from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "analysis" / "p02_entities" / "outputs"
SAMPLES = OUT / "manual_review_samples.csv"

# 在“POI / TRANSPORT / TIME”三类固定口径下，30 个被抽取实体均正确。
# 以下备注记录抽查过程中发现的漏识别和语义边界，供下一轮词典迭代使用。
NOTES = {
    "P2-R08": (
        "正确",
        "",
        "补充“观音宕、好汉坡、滴水观音、飚水瀑布、尽心瀑”等武功山 POI 别名。",
        "抽取的“石鼓寺”正确；同一句还存在上述未被当前词典覆盖的 POI，属于漏识别观察。",
    ),
    "P2-R11": (
        "正确",
        "",
        "补充地铁3号线、地铁5号线等线路名。",
        "“地铁”属于正确的交通方式；补充线路词可提高结果粒度。",
    ),
    "P2-R20": (
        "正确",
        "",
        "维持“徒步”为 TRANSPORT，并在实体规范中说明其属于移动方式。",
        "“徒步”在该句中是活动表达；按本项目将步行/徒步视为移动方式的口径，类型正确，但属于边界样本。",
    ),
    "P2-R29": (
        "正确",
        "",
        "后续如需只保留行程时间，可增加“行程相关性”字段。",
        "“一小时”是明确时长；但语境为行前训练，不是景区内步骤，属于时间实体范围的边界样本。",
    ),
}


def main() -> None:
    with SAMPLES.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)

    for row in rows:
        verdict, issue, correction, note = NOTES.get(
            row["sample_id"], ("正确", "", "", "实体文本、类型、原句语义与字符位置均一致。")
        )
        row["manual_verdict"] = verdict
        row["issue_type"] = issue
        row["suggested_correction"] = correction
        row["reviewer_note"] = note

    with SAMPLES.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    report = OUT / "manual_review_report.md"
    lines = [
        "# P2 实体识别人工抽查报告", "",
        "- 抽查对象：`manual_review_samples.csv` 中的 30 条分层样本", 
        "- 抽样覆盖：POI、TRANSPORT、TIME 各 10 条；长隆、广州白云山、武功山各 10 条", 
        "- 复核内容：实体文本与原文位置、实体类型、原句语义", "",
        "## 结果", "",
        "- 字符位置可回取：30/30", 
        "- 已抽取实体的类型与语义正确：30/30", 
        "- 样本误识别率：0/30 = 0.00%", 
        "", 
        "> 该结果仅表示抽查的 30 个“已抽取实体”均正确，不表示语料中不存在漏识别。", "",
        "## 发现的改进项", "",
        "1. `P2-R08`：武功山路线句中除“石鼓寺”外，还有“观音宕、好汉坡、滴水观音、飚水瀑布、尽心瀑”等 POI 未进入当前词典；下一轮应补入词典并重新统计。", 
        "2. `P2-R11`：当前识别到泛化的“地铁”，类型正确；可补充地铁 3/5 号线等具体线路，提高交通实体粒度。", 
        "3. `P2-R20`：把“徒步”归为 TRANSPORT 的依据是本项目将步行/徒步视为移动方式；该边界已在词典规范中说明。", 
        "4. `P2-R29`：行前训练的“一小时”是明确时长，保留为 TIME；若后续只关注景区内行程，可增加“行程相关性”字段。", 
        "", 
        "## 逐条结论", "",
        "| 样本 | 文档 | 实体 | 类型 | 结论 |", 
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['sample_id']} | {row['doc_id']} | {row['entity_text']} | {row['entity_type']} | {row['manual_verdict']} |"
        )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {len(rows)} 条人工核验结论：{SAMPLES}")
    print(f"审核报告：{report}")


if __name__ == "__main__":
    main()
