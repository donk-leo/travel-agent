# -*- coding: utf-8 -*-
"""P4 第二步：基于最近实体 + 类型/距离约束的规则消解。

输入：
  - outputs/pronoun_candidates.jsonl（detect_pronouns.py 产出）
  - analysis/p02_entities/outputs/entities.jsonl（P2 冻结实体）
  - analysis/p03_routes/outputs/routes.jsonl（补充 P2 漏标的 POI，仅作候选）
输出：
  - outputs/coref.jsonl
  - outputs/coref_stats.json

方法：rule_nearest。对每个代词，在同一文档中找它之前的 POI/交通/时间实体，
按“代词类型 → 实体类型”的白名单过滤，再用“类型权重 + 距离 + 同句 + 路线命中”打分；
低于阈值则保留空 antecedent，并写 needs_review/reason，避免硬凑先行词。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lib.io_utils import read_csv_sig, read_jsonl, write_json, write_jsonl  # noqa: E402
from lib.paths import SCENIC_AREAS, analysis_dir, scenic_csv  # noqa: E402

PROJECT = "p04_coref"
OUT = analysis_dir(PROJECT) / "outputs"
MAX_DISTANCE = 100
THRESHOLD = 0.60

# 代词类别：决定允许的实体类型与基础类型权重
PRONOUN_CLASS = {
    "这里": "locative", "这儿": "locative", "这边": "locative",
    "那里": "locative", "那儿": "locative", "那边": "locative",
    "这个": "demonstrative", "那个": "demonstrative", "这座": "demonstrative",
    "这些": "plural", "那些": "plural", "这条": "route",
    "它": "object", "它们": "object",
    "这次": "trip", "这时": "time", "那时": "time",
    "这样": "manner", "那样": "manner",
    "他们": "person", "她们": "person",
    "这": "bare", "那": "bare",
}

# 类别 -> {实体类型: 类型权重}
TYPE_ALLOW = {
    "locative": {"POI": 1.0},
    "demonstrative": {"POI": 1.0},
    "object": {"POI": 1.0, "TRANSPORT": 0.85},
    "time": {"TIME": 1.0},
    "person": {},          # schema 无 PERSON 类型，不硬映射
    "manner": {},          # 方式指代，非实体
    "bare": {},            # “这份攻略”等指示限定语，不指向具体实体
    "route": {},           # “这条线”是路线指代，P4 schema 没有 ROUTE 类型
    "plural": {},          # “这些/那些”是复数集合，不强行选单个 POI
    "trip": {},            # “这次”指整段行程/事件，没有 EVENT 实体
}
TYPE_BASE = {"POI": 1.0, "TRANSPORT": 0.8, "TIME": 0.8, "EVENT": 0.5}

# 距离/同句约束：越不明确的代词越保守
LIMITS = {
    "locative": {"same_sentence": 55, "previous": 35},
    "demonstrative": {"same_sentence": 50, "previous": 50},
    "object": {"same_sentence": 60, "previous": 50},
    "time": {"same_sentence": 60, "previous": 40},
}

TIME_HEAD = ("冬日", "冬天", "时候", "时间", "时间点", "季节", "周末", "假期",
             "节日", "月份", "年份", "天", "晚", "次", "段")
GENERIC_POI = re.compile(
    r"(此次|我们|可以|途经|到达|返回|挑战|游览|乘坐|步行|下山|上山|结束|开始|"
    r"前往|然后|这里|那里|建议|选择|排队|入园|出园|午餐|晚餐|住宿|露营|"
    r"看日出|看日落|拍照|打卡|第一站|第二站|第三站|全程|路线|线路|沿途)"
)

UNRESOLVED = {
    "locative": "前文无同句/近邻 POI 候选",
    "demonstrative": "前文无同句 POI 候选，或为时间/复数指代",
    "object": "前文无 POI/交通候选，或为人物/动物指代",
    "time": "前文无时间候选",
    "person": "人物指代，schema 无 PERSON 类型",
    "manner": "方式指代，不对应具体实体",
    "bare": "指示限定语（如“这份/这段”），不指向具体实体",
    "route": "路线指代，schema 无 ROUTE 类型",
    "plural": "复数集合指代，不强行选单个实体",
    "trip": "整段行程/事件指代，无 EVENT 实体",
}


def load_candidates() -> list[dict]:
    return list(read_jsonl(OUT / "pronoun_candidates.jsonl"))


def load_texts() -> dict[str, str]:
    texts: dict[str, str] = {}
    for area in SCENIC_AREAS:
        records, _ = read_csv_sig(scenic_csv(area))
        for rec in records:
            texts[rec["doc_id"]] = rec.get("clean_content", "") or ""
    return texts


def locate(text: str, name: str, near: int) -> tuple[int, int] | None:
    """在 near 附近找名称的真实 span；P3 的 source_span 偶有偏移，不能直接用。"""
    if not name or not text:
        return None
    win_start = max(0, near - 8)
    idx = text.find(name, win_start, min(len(text), near + len(name) + 12))
    if idx < 0:
        idx = text.find(name)
    if idx < 0:
        return None
    return idx, idx + len(name)


def load_entities(texts: dict[str, str]) -> dict[str, list[dict]]:
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for e in read_jsonl(analysis_dir("p02_entities") / "outputs" / "entities.jsonl"):
        name = str(e.get("normalized_name") or e.get("entity_text") or "").strip()
        if not name:
            continue
        by_doc[e["doc_id"]].append({
            "entity_text": e.get("entity_text", name),
            "name": name,
            "type": e.get("entity_type", ""),
            "start": int(e["char_start"]),
            "end": int(e["char_end"]),
            "confidence": float(e.get("confidence") or 0.9),
            "source": "p02",
        })

    # P3 的 POI 步骤只用于补 P2 漏标；先按名称/邻近位置还原真实 span，再过滤泛化词
    route_path = analysis_dir("p03_routes") / "outputs" / "routes.jsonl"
    if route_path.exists():
        for r in read_jsonl(route_path):
            name = str(r.get("poi") or "").strip()
            if not name or len(name) < 2 or len(name) > 14 or GENERIC_POI.search(name):
                continue
            span = r.get("source_span") or []
            near = int(span[0]) if span else 0
            found = locate(texts.get(r.get("doc_id", ""), ""), name, near)
            if not found:
                continue
            start, end = found
            by_doc[r["doc_id"]].append({
                "entity_text": name,
                "name": name,
                "type": "POI",
                "start": start,
                "end": end,
                "confidence": 0.7,
                "source": "p03",
            })

    for doc_id, rows in by_doc.items():
        best: dict[tuple[int, int, str], dict] = {}
        for e in rows:
            key = (e["start"], e["end"], e["name"])
            if key not in best or (e["source"] == "p02" and best[key]["source"] != "p02"):
                best[key] = e
        by_doc[doc_id] = sorted(best.values(), key=lambda x: (x["start"], x["end"]))
    return by_doc


def load_route_pois() -> dict[str, set[str]]:
    pois: dict[str, set[str]] = defaultdict(set)
    path = analysis_dir("p03_routes") / "outputs" / "routes.jsonl"
    if path.exists():
        for r in read_jsonl(path):
            poi = str(r.get("poi") or "").strip()
            if poi:
                pois[r["doc_id"]].add(poi)
    return pois


def make_row(row: dict, cls: str, ent: dict | None, score: float, reason: str,
             distance: int, candidates: list[tuple]) -> dict:
    resolved = ent is not None
    return {
        "doc_id": row["doc_id"],
        "scenic_area": row.get("scenic_area", ""),
        "doc_type": row.get("doc_type", ""),
        "pronoun": row["pronoun"],
        "pronoun_start": int(row["pronoun_start"]),
        "pronoun_end": int(row["pronoun_end"]),
        "sentence": row["sentence"],
        "sentence_start": int(row.get("sentence_start", 0)),
        "antecedent": ent["name"] if resolved else "",
        "antecedent_start": int(ent["start"]) if resolved else None,
        "antecedent_end": int(ent["end"]) if resolved else None,
        "antecedent_type": ent["type"] if resolved else "UNKNOWN",
        "method": "rule_nearest",
        "confidence": round(min(0.99, score), 3) if resolved else 0.0,
        "needs_review": (not resolved) or score < 0.70,
        "pronoun_class": cls,
        "distance": distance,
        "candidate_count": len(candidates),
        "reason": reason,
    }


def resolve_one(row: dict, entities: list[dict], route_pois: set[str]) -> dict:
    pronoun = row["pronoun"]
    cls = PRONOUN_CLASS.get(pronoun, "bare")
    allowed = TYPE_ALLOW.get(cls, {})
    p_start = int(row["pronoun_start"])
    s_start = int(row["sentence_start"])
    s_end = int(row["sentence_end"])
    before = row.get("context_before", "")[-2:]
    after = row.get("context_after", "")[:4]

    # 语义护栏：这些情况即使有近邻实体也不应硬消解
    if cls == "locative" and before[-1:] in "我你他她咱":
        return make_row(row, cls, None, 0.0, "“我/你/他/她+这里”是说话人位置，非实体指代", 0, [])
    if cls == "object" and pronoun == "它们":
        return make_row(row, cls, None, 0.0, "复数代词，指向多个对象", 0, [])
    if cls == "object" and before[-1:] in "与和跟给让":
        return make_row(row, cls, None, 0.0, "“与/和/跟/给/让+它”多指人物或动物，不映射为 POI", 0, [])
    if cls == "demonstrative" and after.startswith(TIME_HEAD):
        return make_row(row, cls, None, 0.0, "“这个/那个+时间词”是时间限定语，不是实体指代", 0, [])
    if cls in {"plural", "route", "trip", "person", "manner", "bare"}:
        return make_row(row, cls, None, 0.0, UNRESOLVED.get(cls, "无可用候选"), 0, [])

    candidates: list[tuple[float, int, bool, dict]] = []
    for ent in entities:
        if ent["end"] > p_start or ent["type"] not in allowed:
            continue
        distance = p_start - ent["end"]
        if distance > MAX_DISTANCE:
            continue
        same_sentence = s_start <= ent["start"] and ent["end"] <= s_end
        limit = LIMITS.get(cls, LIMITS["object"])
        if distance > (limit["same_sentence"] if same_sentence else limit["previous"]):
            continue
        proximity = max(0.0, 1.0 - distance / 80.0)
        route_hit = 1.0 if ent["name"] in route_pois else 0.0
        score = (0.55 * TYPE_BASE.get(ent["type"], 0.3)
                 + 0.25 * proximity
                 + 0.15 * (1.0 if same_sentence else 0.0)
                 + 0.05 * route_hit)
        candidates.append((score, distance, same_sentence, ent))

    if not candidates:
        return make_row(row, cls, None, 0.0, UNRESOLVED.get(cls, "无可用候选"), 0, [])

    candidates.sort(key=lambda x: (-x[0], x[1], -x[3]["end"]))
    best_score, best_dist, same_sent, best = candidates[0]
    if best_score < THRESHOLD:
        return make_row(row, cls, None, best_score,
                        f"最高分 {best_score:.2f} 低于阈值 {THRESHOLD}", best_dist, candidates)

    reason = f"同句{'是' if same_sent else '否'}；距离 {best_dist}；类型 {best['type']}"
    if len(candidates) > 1:
        reason += f"；候选 {len(candidates)} 个，取最高分"
    return make_row(row, cls, best, best_score, reason, best_dist, candidates)


def main() -> None:
    candidates = load_candidates()
    texts = load_texts()
    entities = load_entities(texts)
    route_pois = load_route_pois()

    rows = [resolve_one(c, entities.get(c["doc_id"], []), route_pois.get(c["doc_id"], set()))
            for c in candidates]

    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT / "coref.jsonl", rows)

    resolved = [r for r in rows if r["antecedent"]]
    by_area = Counter(r["scenic_area"] for r in rows)
    res_area = Counter(r["scenic_area"] for r in resolved)
    by_pron = Counter(r["pronoun"] for r in rows)
    res_pron = Counter(r["pronoun"] for r in resolved)
    by_type = Counter(r["antecedent_type"] for r in resolved)
    reasons = Counter(r["reason"] for r in rows if not r["antecedent"])
    stats = {
        "documents_with_pronoun": len({r["doc_id"] for r in rows}),
        "candidates": len(rows),
        "resolved": len(resolved),
        "unresolved": len(rows) - len(resolved),
        "resolution_rate": round(len(resolved) / max(1, len(rows)), 4),
        "by_area": {
            a: {"total": by_area[a], "resolved": res_area[a],
                "rate": round(res_area[a] / max(1, by_area[a]), 4)}
            for a in sorted(by_area)
        },
        "by_pronoun": {
            p: {"total": by_pron[p], "resolved": res_pron[p]}
            for p in sorted(by_pron, key=lambda x: (-by_pron[x], x))
        },
        "by_antecedent_type": dict(by_type),
        "unresolved_reasons": dict(reasons.most_common()),
        "threshold": THRESHOLD,
        "max_distance": MAX_DISTANCE,
        "method": "rule_nearest",
    }
    write_json(OUT / "coref_stats.json", stats)

    print(f"代词 {len(rows)}，已消解 {len(resolved)}，未消解 {len(rows) - len(resolved)}")
    print("按景区：", json.dumps(stats["by_area"], ensure_ascii=False))
    print("先行词类型：", dict(by_type))
    print("未消解原因：", dict(reasons.most_common(6)))
    print("->", OUT / "coref.jsonl")


if __name__ == "__main__":
    main()
