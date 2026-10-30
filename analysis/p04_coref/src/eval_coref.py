# -*- coding: utf-8 -*-
"""P4 评估：在人工标注上计算准确率、覆盖率、精确率/召回率，并生成 eval.md。

定义（写进报告，保证可复算）：
- 准确率 accuracy = 判断正确的标注条数 / 标注总数
- 标注覆盖率 coverage = 模型给出非空先行词的标注条数 / 标注总数
- 精确率 precision = 正确且非空的条数 / 模型给出非空先行词的条数
- 召回率 recall = 正确且非空的条数 / gold 非空的条数
- 全量消解率 = coref.jsonl 中 antecedent 非空的条数 / 全部代词条数
空 gold + 空预测记为“正确”（识别出“无明确先行词”）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lib.io_utils import read_csv_sig, read_jsonl, write_json  # noqa: E402
from lib.paths import analysis_dir  # noqa: E402

PROJECT = "p04_coref"
OUT = analysis_dir(PROJECT) / "outputs"


def norm(s: str) -> str:
    return "".join(str(s or "").split()).strip("「」\"'“”")


def main() -> None:
    ann, _ = read_csv_sig(OUT / "annotations.csv")
    coref = {(r["doc_id"], int(r["pronoun_start"])): r for r in read_jsonl(OUT / "coref.jsonl")}
    total_all = len(coref)
    resolved_all = sum(1 for r in coref.values() if r.get("antecedent"))

    details: list[dict] = []
    for a in ann:
        key = (a["doc_id"], int(a["pronoun_start"]))
        pred = coref.get(key, {})
        gold = norm(a.get("gold_antecedent", ""))
        p = norm(pred.get("antecedent", ""))
        correct = (gold == p)
        details.append({
            "doc_id": a["doc_id"],
            "pronoun": a["pronoun"],
            "start": int(a["pronoun_start"]),
            "sentence": a.get("sentence", ""),
            "gold": gold,
            "pred": p,
            "pred_type": pred.get("antecedent_type", "UNKNOWN"),
            "confidence": pred.get("confidence", 0.0),
            "correct": correct,
            "note": a.get("note", ""),
        })

    n = len(details)
    correct_n = sum(1 for d in details if d["correct"])
    pred_nonempty = sum(1 for d in details if d["pred"])
    gold_nonempty = sum(1 for d in details if d["gold"])
    tp = sum(1 for d in details if d["pred"] and d["gold"] and d["correct"])
    accuracy = correct_n / n if n else 0.0
    coverage = pred_nonempty / n if n else 0.0
    precision = tp / pred_nonempty if pred_nonempty else 0.0
    recall = tp / gold_nonempty if gold_nonempty else 0.0

    stats = {
        "annotations": n,
        "correct": correct_n,
        "accuracy": round(accuracy, 4),
        "coverage_on_annotations": round(coverage, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "pred_nonempty": pred_nonempty,
        "gold_nonempty": gold_nonempty,
        "tp": tp,
        "all_candidates": total_all,
        "all_resolved": resolved_all,
        "all_resolution_rate": round(resolved_all / total_all, 4) if total_all else 0.0,
        "by_area": dict(Counter(d["doc_id"].split("-")[0] for d in details)),
        "errors": [
            {"doc_id": d["doc_id"], "pronoun": d["pronoun"], "start": d["start"],
             "gold": d["gold"], "pred": d["pred"], "sentence": d["sentence"][:160]}
            for d in details if not d["correct"]
        ],
    }
    write_json(OUT / "eval_stats.json", stats)

    def cell(s: str, limit: int = 46) -> str:
        s = str(s or "∅").replace("|", "\\|").replace("\n", " ").strip()
        return s if len(s) <= limit else s[:limit] + "…"

    lines: list[str] = []
    lines.append("# 项目4 共指消解 · 评估说明\n")
    lines.append("本文件由 `src/eval_coref.py` 根据 `outputs/annotations.csv` 与 `outputs/coref.jsonl` 自动生成，数字可复算。\n")
    lines.append("## 1. 指标定义\n")
    lines.append("- **准确率 accuracy** = 判断正确的标注条数 / 标注总数；空 gold + 空预测记为正确（识别出“无明确先行词”）。")
    lines.append("- **标注覆盖率 coverage** = 模型给出非空先行词的标注条数 / 标注总数。")
    lines.append("- **精确率 precision** = 正确且非空的条数 / 模型给出非空先行词的条数。")
    lines.append("- **召回率 recall** = 正确且非空的条数 / gold 非空的条数。")
    lines.append(f"- **全量消解率** = `coref.jsonl` 中 antecedent 非空条数 / 全部代词条数 = {resolved_all}/{total_all} = {stats['all_resolution_rate']:.2%}。\n")
    lines.append("## 2. 汇总结果\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---:|")
    lines.append(f"| 标注条数 | {n} |")
    lines.append(f"| 判断正确 | {correct_n} |")
    lines.append(f"| 准确率 | {accuracy:.2%} |")
    lines.append(f"| 标注覆盖率 | {coverage:.2%}（{pred_nonempty}/{n}） |")
    lines.append(f"| 精确率 | {precision:.2%}（TP {tp} / 预测非空 {pred_nonempty}） |")
    lines.append(f"| 召回率 | {recall:.2%}（TP {tp} / gold 非空 {gold_nonempty}） |")
    lines.append(f"| 全量消解率 | {stats['all_resolution_rate']:.2%}（{resolved_all}/{total_all}） |\n")
    lines.append("## 3. 逐条核对\n")
    lines.append("| # | doc_id | 代词@位置 | gold | 预测 | 判定 | 备注 |")
    lines.append("|---:|---|---|---|---|---|---|")
    for i, d in enumerate(details, 1):
        mark = "✅" if d["correct"] else "❌"
        lines.append(f"| {i} | {d['doc_id']} | {d['pronoun']}@{d['start']} | {cell(d['gold'])} | {cell(d['pred'])} | {mark} | {cell(d['note'], 60)} |")
    lines.append("\n> ∅ 表示“无明确先行词/未消解”。\n")

    lines.append("## 4. 错误分析\n")
    if stats["errors"]:
        for e in stats["errors"]:
            lines.append(f"- **{e['doc_id']} {e['pronoun']}@{e['start']}**：gold=`{e['gold']}`，预测=`{e['pred']}`。句子：{cell(e['sentence'], 120)}")
    else:
        lines.append("- 本轮标注无错误。")
    lines.append("")
    lines.append("四类典型错误：")
    lines.append("1. **P2 漏标 / 归一化偏差**：如“十环过山车”被漏标，最近的“垂直过山车”被误选；P3 只补到部分 POI。")
    lines.append("2. **后置指代**：`这里` 的先行词出现在代词之后（“第一站就是尖叫地带……我们将在这里”），最近前文规则天然看不到。")
    lines.append("3. **人物/动物/事件指代**：`他们`、`它`（蚊子）、`这`（瞬间）在 schema 中没有 PERSON/ANIMAL/EVENT 类型，宁可不消解。")
    lines.append("4. **路线/集合指代**：`这条`、`这些` 指向路线或复数集合，P4 schema 没有 ROUTE/集合类型，规则选择留空。\n")
    lines.append("## 5. 结论\n")
    lines.append(f"规则在 20 条人工标注上准确率 {accuracy:.1%}、精确率 {precision:.1%}；主要收益来自“同句/近邻 POI + 类型白名单”，主要损失来自 P2 漏标和后置指代。")
    lines.append("因此本方法定位为**高精度、可解释的基线**：宁可 `needs_review=true` 留空，也不把时间/人物/路线硬映射成 POI；后续可用 LLM 或模型对未消解项做二次判定。\n")

    (OUT / "eval.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"标注 {n}，准确率 {accuracy:.2%}，覆盖率 {coverage:.2%}，精确率 {precision:.2%}，召回率 {recall:.2%}")
    print(f"全量消解率 {stats['all_resolution_rate']:.2%}；错误 {len(stats['errors'])} 条")
    print("->", OUT / "eval.md")


if __name__ == "__main__":
    main()
