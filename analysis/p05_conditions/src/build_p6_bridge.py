# -*- coding: utf-8 -*-
"""生成 P5 → P6 的条件锚点桥接表。

P5 的 conditions.jsonl 只记录条件在 clean_content 中的位置，不直接记录
POI/路线 id。P6 建 HAS_CONDITION 边时需要知道“这条条件挂到哪个 POI”。
本脚本按同一 doc_id 内的字符区间做重叠/最近匹配，输出一张派生表；
它不修改 conditions.jsonl，也不改变 P5 的 schema。

用法（仓库根目录）：
    python analysis/p05_conditions/src/build_p6_bridge.py
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
P5 = REPO / "analysis/p05_conditions/outputs/conditions.jsonl"
P2 = REPO / "analysis/p02_entities/outputs/entities.jsonl"
OUT_DIR = REPO / "analysis/p05_conditions/outputs"
CSV_OUT = OUT_DIR / "p6_condition_poi.csv"
STATS_OUT = OUT_DIR / "p6_bridge_stats.json"
DOC_OUT = OUT_DIR / "P6_接入说明.md"

# 条件句与 POI 的距离超过这个值就不硬挂，退到景区节点。
MAX_NEAREST_DISTANCE = 80


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def span_distance(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if overlap(a_start, a_end, b_start, b_end):
        return 0
    if a_end <= b_start:
        return b_start - a_end
    return a_start - b_end


def pick_poi(cond: dict, pois: list[dict]) -> tuple[dict | None, str, int, int]:
    """返回 (poi, match_type, overlap_chars, distance)。

    只在有文本证据或区间重叠时挂 POI；仅“在同一句里”不构成挂载理由，
    否则“膝盖负担较大”会被挂到同句任意景点上。
    """
    c_start = int(cond.get("char_start", 0))
    c_end = int(cond.get("char_end", c_start + 1))
    s_start = int(cond.get("sentence_start", c_start))
    s_end = int(cond.get("sentence_end", c_end))
    c_text = (cond.get("condition_text") or "").strip()
    sug_text = (cond.get("suggestion_text") or "").strip()
    area = (cond.get("scenic_area") or "").strip()

    best: tuple[tuple, dict, int, int, str] | None = None
    for poi in pois:
        p_start = int(poi.get("char_start", 0))
        p_end = int(poi.get("char_end", p_start + 1))
        name = (poi.get("normalized_name") or poi.get("entity_text") or "").strip()
        if not name:
            continue
        # 景区同名 POI 不当作具体景点，退到景区节点。
        if name == area:
            continue
        ov = overlap(c_start, c_end, p_start, p_end)
        sent_ov = overlap(s_start, s_end, p_start, p_end)
        dist = span_distance(c_start, c_end, p_start, p_end)
        cond_hit = int(bool(c_text) and (c_text in name or name in c_text))
        sug_hit = int(bool(sug_text) and name in sug_text)
        # 证据优先级：条件词直接点名 > 建议里点名 > 区间重叠 > 句内距离。
        key = (cond_hit, sug_hit, ov, sent_ov, -dist, p_end - p_start)
        if best is None or key > best[0]:
            best = (key, poi, ov, dist, name)

    if best is None:
        return None, "area_fallback", 0, 10**9

    _, poi, ov, dist, _name = best
    if ov:
        return poi, "poi_overlap", ov, 0
    if dist <= MAX_NEAREST_DISTANCE:
        # cond_hit / sug_hit 是文本证据；如果没有，说明只是句内近邻，不硬挂。
        key = best[0]
        if key[0]:
            return poi, "poi_text", 0, dist
        if key[1]:
            return poi, "poi_suggestion", 0, dist
    return None, "area_fallback", 0, dist


def main() -> int:
    conditions = load_jsonl(P5)
    entities = load_jsonl(P2)

    by_doc: dict[str, list[dict]] = {}
    for e in entities:
        if e.get("entity_type") != "POI":
            continue
        by_doc.setdefault(str(e.get("doc_id", "")), []).append(e)

    rows: list[dict] = []
    for cond in conditions:
        doc_id = str(cond.get("doc_id", ""))
        area = str(cond.get("scenic_area", ""))
        poi, match_type, ov, dist = pick_poi(cond, by_doc.get(doc_id, []))
        if poi is not None:
            name = (poi.get("normalized_name") or poi.get("entity_text") or "").strip()
            target_type = "POI"
            target_name = name
            target_key = f"POI|{area}|{name}"
            ent_start = poi.get("char_start", "")
            ent_end = poi.get("char_end", "")
        else:
            target_type = "SCENIC_AREA"
            target_name = area
            target_key = f"AREA|{area}"
            ent_start = ent_end = ""

        row = {
            "cond_id": cond.get("cond_id", ""),
            "doc_id": doc_id,
            "scenic_area": area,
            "condition_type": cond.get("condition_type", ""),
            "condition_text": cond.get("condition_text", ""),
            "suggestion_text": cond.get("suggestion_text", ""),
            "source_sentence": cond.get("source_sentence", ""),
            "condition_char_start": cond.get("char_start", ""),
            "condition_char_end": cond.get("char_end", ""),
            "target_type": target_type,
            "target_key": target_key,
            "target_name": target_name,
            "match_type": match_type,
            "overlap_chars": ov,
            "distance": "" if poi is None else dist,
            "anchor_confidence": {
                "poi_overlap": 0.95,
                "poi_text": 0.80,
                "poi_suggestion": 0.65,
                "area_fallback": 0.30,
            }[match_type],
            "poi_char_start": ent_start,
            "poi_char_end": ent_end,
            "is_duplicate": bool(cond.get("is_duplicate", False)),
            "recommended_for_graph": not bool(cond.get("is_duplicate", False)),
        }
        rows.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "cond_id", "doc_id", "scenic_area", "condition_type",
        "condition_text", "suggestion_text", "source_sentence",
        "condition_char_start", "condition_char_end",
        "target_type", "target_key", "target_name", "match_type",
        "overlap_chars", "distance", "anchor_confidence",
        "poi_char_start", "poi_char_end", "is_duplicate", "recommended_for_graph",
    ]
    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    stats = {
        "total": len(rows),
        "recommended_for_graph": sum(1 for r in rows if r["recommended_for_graph"]),
        "duplicates": sum(1 for r in rows if r["is_duplicate"]),
        "by_match_type": dict(Counter(r["match_type"] for r in rows)),
        "by_target_type": dict(Counter(r["target_type"] for r in rows)),
        "by_area": dict(Counter(r["scenic_area"] for r in rows)),
        "by_condition_type": dict(Counter(r["condition_type"] for r in rows)),
        "duplicate_cond_ids": [r["cond_id"] for r in rows if r["is_duplicate"]],
        "max_nearest_distance": MAX_NEAREST_DISTANCE,
    }
    with STATS_OUT.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    sample = [r for r in rows if r["match_type"] == "poi_overlap"][:5]
    sample_lines = "\n".join(
        f"| {r['cond_id']} | {r['condition_text']} | {r['target_name']} | {r['match_type']} |"
        for r in sample
    )
    if not sample_lines:
        sample_lines = "| — | — | — | — |"

    dup_lines = "\n".join(f"- `{cid}`" for cid in stats["duplicate_cond_ids"]) or "- 无"

    doc = f"""# P5 → P6 条件接入说明

本文件由 `analysis/p05_conditions/src/build_p6_bridge.py` 自动生成，配合
`p6_condition_poi.csv` 使用。它解决的是“P5 只有字符位置、没有 POI id”的接口缺口，
**不修改** `conditions.jsonl`，也不改变 P5 的 schema。

## 版本与输入

- P5 交接卡：`standards/handover/p05_conditions.yaml`
- P5 输出：`analysis/p05_conditions/outputs/conditions.jsonl`（tag 见交接卡）
- P2 实体：`analysis/p02_entities/outputs/entities.jsonl`（`v0.2-p02`）
- P3 路线：`analysis/p03_routes/outputs/routes.jsonl`（`v0.3-p03`，无 `scenic_area`，按 `doc_id` 前缀推断）

## 桥接规则

1. 仅在同一 `doc_id` 内匹配，且只匹配 P2 的 `entity_type == "POI"`；
2. 优先取与 `condition_text` 字符区间**重叠**的 POI（`poi_overlap`，置信度 0.95）；
3. 条件词直接点名某个 POI（`poi_text`，0.80），或建议句里点名某个 POI（`poi_suggestion`，0.65），
   且距离 ≤ {MAX_NEAREST_DISTANCE} 字时挂到该 POI；
4. 仅“同一句里有个景点”不构成挂载理由；没有文本证据或区间重叠时，
   退到景区节点 `AREA|<景区>`（`area_fallback`，0.30），不硬挂；
5. `is_duplicate=true` 的记录仍保留在桥接表中，但 `recommended_for_graph=false`；
6. `target_key` 是给 P6 的稳定键：POI 用 `POI|<景区>|<标准名>`，景区用 `AREA|<景区>`；
   如果 P6 有更细的节点 id 方案，可用 `doc_id + poi_char_start/end` 重新对齐。

## 统计

- 条件总数：{stats['total']}
- 建议入图（非重复）：{stats['recommended_for_graph']}
- 重复标记：{stats['duplicates']}（{', '.join(stats['duplicate_cond_ids']) or '无'}）
- 匹配方式：{json.dumps(stats['by_match_type'], ensure_ascii=False)}
- 目标类型：{json.dumps(stats['by_target_type'], ensure_ascii=False)}
- 景区分布：{json.dumps(stats['by_area'], ensure_ascii=False)}

## 示例

| cond_id | condition_text | target_name | match_type |
|---|---|---|---|
{sample_lines}

## 给 P6 的注意事项

- P5 只有 13/28 篇文档抽出条件，**缺失不等于“无条件”**；图里不要把“没有条件”误读成“条件为空”。
- P5 的 3 条重复记录（见上）建议默认过滤；如果保留，需在 `graph_qa.md` 说明理由。
- `scenic_area` 用中文原值（长隆 / 广州白云山 / 武功山），与 P2 一致；P3 没有该字段，用 `doc_id` 前缀推断。
- 如果 P6 决定跳过 P5，可不建 `HAS_CONDITION` 边；P6 的必需输入只有 P2、P3。
- 条件节点本身建议用 `CONDITION:<cond_id>`；与 POI 的边为 `HAS_CONDITION`，方向为 `POI -> CONDITION`。
"""
    DOC_OUT.write_text(doc, encoding="utf-8")

    print(f"写出 {CSV_OUT.relative_to(REPO)}：{len(rows)} 行")
    print(f"写出 {STATS_OUT.relative_to(REPO)}")
    print(f"写出 {DOC_OUT.relative_to(REPO)}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())