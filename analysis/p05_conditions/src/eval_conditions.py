# -*- coding: utf-8 -*-
"""P5 人工抽查评估：读取 20 条标注，输出 manual_review.csv / eval_conditions.md。"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from lib.paths import analysis_dir  # noqa: E402

ROOT = analysis_dir("p05_conditions")
OUT = ROOT / "outputs"
GOLD = ROOT / "config" / "manual_review_gold.csv"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> int:
    rows = {r["cond_id"]: r for r in load_jsonl(OUT / "conditions.jsonl")}
    with GOLD.open(encoding="utf-8-sig", newline="") as f:
        gold = list(csv.DictReader(f))

    missing = [g["cond_id"] for g in gold if g["cond_id"] not in rows]
    if missing:
        raise SystemExit(f"标注中的 cond_id 不存在：{missing}")

    merged = []
    for g in gold:
        r = rows[g["cond_id"]]
        merged.append({
            "cond_id": r["cond_id"],
            "scenic_area": r["scenic_area"],
            "doc_id": r["doc_id"],
            "condition_type": r["condition_type"],
            "condition_text": r["condition_text"],
            "suggestion_text": r["suggestion_text"],
            "label": g["label"],
            "reason": g["reason"],
        })

    with (OUT / "manual_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
        w.writeheader()
        w.writerows(merged)

    counts = Counter(m["label"] for m in merged)
    n = len(merged)
    correct = counts.get("正确", 0)
    partial = counts.get("部分正确", 0)
    wrong = counts.get("错误", 0)
    stats = {
        "reviewed": n,
        "correct": correct,
        "partial": partial,
        "wrong": wrong,
        "strict_accuracy": round(correct / n, 4),
        "lenient_accuracy": round((correct + partial) / n, 4),
        "by_area": dict(Counter(m["scenic_area"] for m in merged)),
        "by_type": dict(Counter(m["condition_type"] for m in merged)),
        "errors": [m for m in merged if m["label"] != "正确"],
    }
    (OUT / "eval_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 项目5 条件-建议抽取 · 人工抽查评估",
        "",
        f"- 抽查样本：{n} 条（三景区分层抽取）",
        f"- 正确：{correct} 条；部分正确：{partial} 条；错误：{wrong} 条",
        f"- 严格准确率（仅“正确”）：{correct}/{n} = {correct / n:.2%}",
        f"- 宽松可用率（正确 + 部分正确）：{correct + partial}/{n} = {(correct + partial) / n:.2%}",
        "",
        "> 判定口径：条件与建议均成立、且建议可执行，记“正确”；条件或建议有一侧偏弱、"
        "但另一侧仍可用，记“部分正确”；条件/建议错配、或建议已失效/不属于游览建议，记“错误”。",
        "",
        "## 逐条结果",
        "",
        "| cond_id | 景区 | 类型 | 条件 | 建议 | 判定 | 理由 |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in merged:
        cond = m["condition_text"].replace("|", "\\|")
        sugg = m["suggestion_text"].replace("|", "\\|")
        reason = m["reason"].replace("|", "\\|")
        lines.append(f"| {m['cond_id']} | {m['scenic_area']} | {m['condition_type']} | {cond} | {sugg} | {m['label']} | {reason} |")

    lines += [
        "",
        "## 错误与部分正确分析",
        "",
        f"- **条件角色不一致**：{counts.get('部分正确', 0)} 条中有 2 条属于“条件人群/场景”与“建议对象”不一致，"
        "如 CND-0035 条件为儿童，建议却面向家长；CND-0001 的“停车”是场景而非游客状态。",
        "- **条件指代过泛**：CND-0016 的“如果时间差不多”没有说明是什么时间，建议本身（坐火车）成立，"
        "但条件不可直接执行。",
        "- **建议缺具体对象**：CND-0025 只写“进入梦幻童话世界”，没有落到具体项目或地点。",
        "- **时效性内容**：CND-0027 的“十周岁生日”是活动信息，不是稳定可复用的建议。",
        "- **非游览建议**：CND-0028 的心理建设建议成立，但不属于景区游览操作。",
        "",
        "## 结论",
        "",
        "规则基线在“条件明确 + 建议动作明确”的句子上表现稳定；主要误差来自隐式条件识别"
        "（把场景/主题词当条件）和长句建议边界。后续应优先扩充人工标注、增加“条件角色”校验，"
        "并对时效性内容加发布时间过滤。",
        "",
    ]
    (OUT / "eval_conditions.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"reviewed={n} correct={correct} partial={partial} wrong={wrong}")
    print(f"strict={correct / n:.2%} lenient={(correct + partial) / n:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())