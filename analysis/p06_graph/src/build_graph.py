# -*- coding: utf-8 -*-
"""项目 6 知识图谱构建：P2 实体 + P3 路线 + P5 条件 → 节点/边/GraphML/图/QA。

用法（在仓库根目录或任意目录都能跑）：
    python analysis/p06_graph/src/build_graph.py                  # 三景区总图
    python analysis/p06_graph/src/build_graph.py --areas changlong  # 只跑长隆（分阶段验收）

输入只读：analysis/p02_entities、analysis/p03_routes、analysis/p05_conditions 的已交付产出。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.io_utils import read_csv_sig, read_jsonl, write_csv_sig  # noqa: E402
from lib.paths import ANALYSIS  # noqa: E402

PROJECT_DIR = ANALYSIS / "p06_graph"
P2_PATH = ANALYSIS / "p02_entities/outputs/entities.jsonl"
P3_PATH = ANALYSIS / "p03_routes/outputs/routes.jsonl"
P5_PATH = ANALYSIS / "p05_conditions/outputs/conditions.jsonl"
P5_BRIDGE_PATH = ANALYSIS / "p05_conditions/outputs/p6_condition_poi.csv"
P3_ALIAS_PATH = ANALYSIS / "p03_routes/config/alias.csv"
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")

AREA_ORDER = ("长隆", "广州白云山", "武功山")
AREA_ALIASES = {
    "changlong": "长隆", "cl": "长隆", "长隆": "长隆",
    "baiyunshan": "广州白云山", "bys": "广州白云山", "广州白云山": "广州白云山",
    "wugongshan": "武功山", "wgs": "武功山", "武功山": "武功山",
}
DOC_PREFIX = {"CL": "长隆", "BYS": "广州白云山", "WGS": "武功山"}

#: P2 里把景区名当 POI 抽出来的两条，按 SCENIC_AREA 建模
SCENIC_LEVEL_NAMES = {"武功山", "广州白云山"}

#: P3 句子片段/动作式伪 POI：不建节点（graph_qa.md 逐条记录）
DROP_POI = {
    "南门下山",
    "完玻璃栈道就可以下山了",
    "此次我们挑战经典的武功山沈明线",
    "明月山景区大门终点",
}

#: P3 伪 POI 实为活动/时段：转成 ACTIVITY 节点（保留它们携带的显式时间）
RECLASS_ACTIVITY = {
    "刺激项目黄金时段": "刺激项目",
    "错峰午餐": "错峰午餐",
    "沉浸体验": "沉浸体验",
    "午餐休息区": "午餐休息",
    "夜场演出": "夜场演出",
}

#: 交通方式归一（概念层共享，见 graph_qa.md 融合规则 R3）
TRANSPORT_CANON = {
    "游览观光车": "观光车",
    "免费巴士": "巴士",
    "大巴": "巴士",
    "公交": "巴士",
}
METRO_RE = re.compile(r"^地铁\d+号线$")

#: P3 伪 POI 中保留为 POI 的（设施/地名/区域），在 graph_qa.md 里逐条注明
KEEP_POI_NOTE = ["安检入口", "明月山6281梯", "羊狮慕小火车站", "家庭亲子区", "巡游主街段", "欢乐主街区"]

#: 未合并但语义相近的 POI（父子/层级写法），保留双节点 + SIMILAR_TO
SIMILAR_PAIRS = [
    ("广州白云山", "摩星岭", "摩星岭景区", "层级写法：景区 vs 主峰"),
    ("广州白云山", "明珠楼", "明珠楼景区", "层级写法：景区 vs 楼"),
    ("广州白云山", "鸣春谷", "鸣春谷景区", "层级写法：景区 vs 谷"),
    ("广州白云山", "山顶公园", "山顶广场", "同一山顶片区的两种叫法"),
    ("广州白云山", "云台景区", "云台花园", "花园位于景区内"),
    ("广州白云山", "麓湖景区", "麓湖公园", "同一片区的两种叫法"),
    ("长隆", "熊猫村", "长隆大熊猫中心", "同一游览对象的不同命名，待人工确认"),
]

PROSE_MARK = "整篇路线概述"

TYPE_COLOR = {
    "POI": "#4C78A8",
    "SCENIC_AREA": "#E45756",
    "TRANSPORT": "#72B7B2",
    "TIME": "#F58518",
    "ACTIVITY": "#B279A2",
    "CONDITION": "#54A24B",
}
TYPE_ORDER = ["SCENIC_AREA", "POI", "TRANSPORT", "ACTIVITY", "TIME", "CONDITION"]
EDGE_STYLE = {
    "CONTAINS": {"color": "#CFCFCF", "lw": 0.8, "ls": "-", "label": "CONTAINS 包含"},
    "NEXT": {"color": "#8C8C8C", "lw": 1.0, "ls": "-", "label": "NEXT 先后"},
    "BY_TRANSPORT": {"color": "#72B7B2", "lw": 1.0, "ls": "--", "label": "BY_TRANSPORT 交通"},
    "AT_TIME": {"color": "#F58518", "lw": 1.0, "ls": ":", "label": "AT_TIME 时间"},
    "HAS_CONDITION": {"color": "#54A24B", "lw": 1.0, "ls": "-.", "label": "HAS_CONDITION 条件"},
    "SIMILAR_TO": {"color": "#B279A2", "lw": 1.0, "ls": (0, (1, 2)), "label": "SIMILAR_TO 近似"},
}


# --------------------------------------------------------------------------- #
# 数据容器
# --------------------------------------------------------------------------- #
@dataclass
class Node:
    node_id: str
    node_type: str
    name: str
    scenic_area: str = ""
    docs: set[str] = field(default_factory=set)
    occurrences: int = 0
    props: dict = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    rel: str
    dst: str
    weight: float = 1.0
    docs: set[str] = field(default_factory=set)
    props: dict = field(default_factory=dict)


class Builder:
    def __init__(self, areas: tuple[str, ...]) -> None:
        self.areas = areas
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}

    def add_node(self, node_id: str, node_type: str, name: str, area: str = "",
                 doc: str | None = None, occurrences: int = 1, **props) -> Node:
        node = self.nodes.get(node_id)
        if node is None:
            node = Node(node_id, node_type, name, area)
            self.nodes[node_id] = node
        if doc:
            node.docs.add(doc)
        node.occurrences += occurrences
        if props:
            node.props.update(props)
        return node

    def add_edge(self, src: str, rel: str, dst: str, weight: float = 1.0,
                 doc: str | None = None, accumulate: bool = True, **props) -> None:
        key = (src, rel, dst)
        edge = self.edges.get(key)
        if edge is None:
            edge = Edge(src, rel, dst, weight if not accumulate else 0.0)
            self.edges[key] = edge
        if accumulate:
            edge.weight += weight
        else:
            edge.weight = weight
        if doc:
            edge.docs.add(doc)
        if props:
            edge.props.update(props)


# --------------------------------------------------------------------------- #
# 读入与归一
# --------------------------------------------------------------------------- #
def area_of(doc_id: str) -> str:
    prefix = doc_id.split("-")[0]
    if prefix not in DOC_PREFIX:
        raise ValueError(f"未知 doc_id 前缀：{doc_id}")
    return DOC_PREFIX[prefix]


def norm_name(text: str) -> str:
    return (text or "").strip()


def norm_transport(name: str) -> tuple[str, dict]:
    """返回 (规范名, 额外属性)。"""
    raw = norm_name(name)
    if METRO_RE.match(raw):
        return "地铁", {"lines": [raw.replace("地铁", "")]}
    if raw in TRANSPORT_CANON:
        return TRANSPORT_CANON[raw], {}
    return raw, {}


def load_alias() -> dict[tuple[str, str], str]:
    rows, _ = read_csv_sig(P3_ALIAS_PATH)
    alias = {}
    for row in rows:
        a, c = norm_name(row.get("alias")), norm_name(row.get("canonical"))
        area = norm_name(row.get("scenic_area"))
        if a and c:
            alias[(area, a)] = c
    return alias


# --------------------------------------------------------------------------- #
# 构建
# --------------------------------------------------------------------------- #
def build(areas: tuple[str, ...]) -> tuple[Builder, dict]:
    B = Builder(areas)
    stats: dict = {"areas": list(areas), "fusion": {}, "quality": {}, "time": {}}

    entities = [e for e in read_jsonl(P2_PATH) if area_of(e["doc_id"]) in areas]
    routes = [r for r in read_jsonl(P3_PATH) if area_of(r["doc_id"]) in areas]
    conditions = [c for c in read_jsonl(P5_PATH) if c["scenic_area"] in areas]
    bridge_rows, _ = read_csv_sig(P5_BRIDGE_PATH)
    bridge = [b for b in bridge_rows if b["scenic_area"] in areas]
    alias = load_alias()

    # --- 景区节点 -------------------------------------------------------- #
    area_docs: dict[str, set[str]] = defaultdict(set)
    for e in entities:
        area_docs[e["scenic_area"]].add(e["doc_id"])
    for r in routes:
        area_docs[area_of(r["doc_id"])].add(r["doc_id"])
    for row in bridge:
        area_docs[row["scenic_area"]].add(row["doc_id"])
    for area in areas:
        node = B.add_node(f"SCENIC_AREA|{area}", "SCENIC_AREA", area, area,
                          occurrences=1, **{"source": "P2/P3 doc_id 前缀"})
        node.docs.update(area_docs[area])

    # --- POI 融合 -------------------------------------------------------- #
    p2_pois = [e for e in entities if e["entity_type"] == "POI"
               and norm_name(e["normalized_name"]) not in SCENIC_LEVEL_NAMES]
    p3_pois = [r for r in routes if norm_name(r.get("poi"))]

    p2_names: dict[str, set[str]] = defaultdict(set)
    for e in p2_pois:
        p2_names[e["scenic_area"]].add(norm_name(e["normalized_name"]))
    p3_names: dict[str, set[str]] = defaultdict(set)
    for r in p3_pois:
        name = norm_name(r["poi"])
        if name in SCENIC_LEVEL_NAMES or name in DROP_POI or name in RECLASS_ACTIVITY:
            continue
        p3_names[area_of(r["doc_id"])].add(name)

    poi_node: dict[tuple[str, str], str] = {}
    rule_counts = Counter()
    alias_hits: list[dict] = []
    p2_only: dict[str, list[str]] = defaultdict(list)
    p3_only: dict[str, list[str]] = defaultdict(list)

    for area in areas:
        area_p3 = p3_names.get(area, set())
        matched_p3: set[str] = set()
        for name in sorted(p2_names.get(area, set())):
            canonical = alias.get((area, name), name)
            if name in area_p3:
                target, rule = name, "R1_exact"
            elif canonical in area_p3:
                target, rule = canonical, "R2_alias"
                alias_hits.append({"area": area, "p2": name, "p3": canonical})
            else:
                target, rule = name, "R1_exact"
            poi_node[(area, target)] = f"POI|{area}|{target}"
            if target in area_p3:
                matched_p3.add(target)
                rule_counts[rule] += 1
            else:
                rule = "P2_only"
                rule_counts["P2_only"] += 1
                p2_only[area].append(name)
            B.add_node(f"POI|{area}|{target}", "POI", target, area, occurrences=0,
                       **{"merge_rule": rule, "origins": "P2"})
        for name in sorted(area_p3 - matched_p3):
            poi_node[(area, name)] = f"POI|{area}|{name}"
            B.add_node(f"POI|{area}|{name}", "POI", name, area, occurrences=0,
                       **{"merge_rule": "P3_only", "origins": "P3"})
            rule_counts["P3_only"] += 1
            p3_only[area].append(name)

    # POI 的来源文档与出现次数（P2 + P3）
    for e in p2_pois:
        area, name = e["scenic_area"], norm_name(e["normalized_name"])
        nid = poi_node.get((area, name)) or poi_node.get((area, alias.get((area, name), name)))
        if nid in B.nodes:
            B.nodes[nid].docs.add(e["doc_id"])
            B.nodes[nid].occurrences += 1
    for r in p3_pois:
        area, name = area_of(r["doc_id"]), norm_name(r["poi"])
        nid = poi_node.get((area, name))
        if nid in B.nodes:
            B.nodes[nid].docs.add(r["doc_id"])
            B.nodes[nid].occurrences += 1

    # --- 交通节点 -------------------------------------------------------- #
    transport_node: dict[str, str] = {}
    transport_raw: dict[str, set] = defaultdict(set)
    transport_docs: dict[str, set] = defaultdict(set)
    transport_areas: dict[str, set] = defaultdict(set)
    transport_lines: dict[str, set] = defaultdict(set)
    for e in entities:
        if e["entity_type"] != "TRANSPORT":
            continue
        raw = norm_name(e["normalized_name"])
        canon, extra = norm_transport(raw)
        nid = f"TRANSPORT|{canon}"
        transport_node[raw] = nid
        transport_raw[canon].add(raw)
        transport_docs[canon].add(e["doc_id"])
        transport_areas[canon].add(e["scenic_area"])
        for line in extra.get("lines", []):
            transport_lines[canon].add(line)
        B.add_node(nid, "TRANSPORT", canon, "", doc=e["doc_id"], occurrences=1)
    for canon, nid in ((c, f"TRANSPORT|{c}") for c in transport_raw):
        node = B.nodes[nid]
        areas_of = sorted(transport_areas[canon])
        node.scenic_area = "跨景区" if len(areas_of) > 1 else areas_of[0]
        node.props.update({
            "raw_names": sorted(transport_raw[canon]),
            "areas": "、".join(areas_of),
        })
        if transport_lines.get(canon):
            node.props["lines"] = sorted(transport_lines[canon])

    # --- 时间节点（只建能挂上边的显式时间） -------------------------------- #
    time_rows = [r for r in routes if norm_name(r.get("time_norm"))]
    time_values = {norm_name(r["time_norm"]) for r in time_rows}
    for value in sorted(time_values):
        node = B.add_node(f"TIME|{value}", "TIME", value, "",
                          occurrences=sum(1 for r in time_rows if norm_name(r["time_norm"]) == value),
                          **{"source": "P3 time_norm（time_source=explicit）"})
        node.docs.update(r["doc_id"] for r in time_rows if norm_name(r["time_norm"]) == value)
    stats["time"] = {
        "explicit_steps": len(time_rows),
        "unique_values": len(time_values),
        "by_area": dict(Counter(area_of(r["doc_id"]) for r in time_rows)),
    }

    # --- 活动节点 -------------------------------------------------------- #
    activity_node: dict[str, str] = {}
    activity_docs: dict[str, set] = defaultdict(set)
    activity_areas: dict[str, set] = defaultdict(set)

    def add_activity(name: str, area: str, doc: str) -> None:
        nid = f"ACTIVITY|{name}"
        activity_node[name] = nid
        activity_docs[name].add(doc)
        activity_areas[name].add(area)
        B.add_node(nid, "ACTIVITY", name, area, doc=doc, occurrences=1,
                   **{"source": "P3 activity"})

    for r in routes:
        name = norm_name(r.get("poi"))
        if name in RECLASS_ACTIVITY:
            add_activity(RECLASS_ACTIVITY[name], area_of(r["doc_id"]), r["doc_id"])
    activity_only_steps = 0
    for r in routes:
        if norm_name(r.get("poi")):
            continue
        act = norm_name(r.get("activity"))
        if not act or act.startswith(PROSE_MARK):
            continue
        activity_only_steps += 1
        add_activity(act, area_of(r["doc_id"]), r["doc_id"])

    # 活动步里仍带 POI 的 activity（如 南门/入园）写入 POI 属性，不另建节点
    poi_activity: dict[str, set] = defaultdict(set)
    for r in routes:
        poi = norm_name(r.get("poi"))
        act = norm_name(r.get("activity"))
        if not poi or not act or act.startswith(PROSE_MARK):
            continue
        if (area_of(r["doc_id"]), poi) in poi_node:
            poi_activity[poi_node[(area_of(r["doc_id"]), poi)]].add(act)

    # --- 条件节点 -------------------------------------------------------- #
    cond_nodes = {}
    for row in bridge:
        if row.get("recommended_for_graph") != "True":
            continue
        cid = row["cond_id"]
        nid = f"CONDITION|{cid}"
        cond_nodes[cid] = nid
        B.add_node(nid, "CONDITION", row["condition_text"], row["scenic_area"],
                   doc=row["doc_id"], occurrences=1,
                   **{
                       "cond_id": cid,
                       "condition_type": row["condition_type"],
                       "suggestion": row["suggestion_text"],
                       "match_type": row["match_type"],
                       "anchor_confidence": row["anchor_confidence"],
                   })

    # --- 边：CONTAINS ---------------------------------------------------- #
    for node in B.nodes.values():
        if node.node_type in {"POI", "ACTIVITY"}:
            src = f"SCENIC_AREA|{node.scenic_area}"
            B.add_edge(src, "CONTAINS", node.node_id, weight=1)
            B.edges[(src, "CONTAINS", node.node_id)].docs.update(node.docs)

    # --- 边：NEXT + AT_TIME ---------------------------------------------- #
    by_route: dict[str, list] = defaultdict(list)
    for r in routes:
        by_route[r["route_id"]].append(r)
    next_pairs = Counter()
    time_edges = 0
    for rid in sorted(by_route):
        rows = sorted(by_route[rid], key=lambda x: x["step_no"])
        seq: list[tuple[str, str]] = []  # (node_id, doc_id)
        for r in rows:
            poi = norm_name(r.get("poi"))
            act = norm_name(r.get("activity"))
            if poi in SCENIC_LEVEL_NAMES or poi in DROP_POI:
                continue
            if poi:
                if poi in RECLASS_ACTIVITY:
                    seq.append((f"ACTIVITY|{RECLASS_ACTIVITY[poi]}", r["doc_id"]))
                elif (area_of(r["doc_id"]), poi) in poi_node:
                    seq.append((poi_node[(area_of(r["doc_id"]), poi)], r["doc_id"]))
            elif act and not act.startswith(PROSE_MARK):
                seq.append((f"ACTIVITY|{act}", r["doc_id"]))
        for (s, sdoc), (d, ddoc) in zip(seq, seq[1:]):
            next_pairs[(s, d)] += 1
            B.add_edge(s, "NEXT", d, weight=1, doc=sdoc)
            if ddoc != sdoc:
                B.edges[(s, "NEXT", d)].docs.add(ddoc)
        for r in rows:
            t = norm_name(r.get("time_norm"))
            if not t or r.get("time_source") != "explicit":
                continue
            poi = norm_name(r.get("poi"))
            act = norm_name(r.get("activity"))
            if poi in DROP_POI or poi in SCENIC_LEVEL_NAMES:
                continue
            if poi:
                src = (f"ACTIVITY|{RECLASS_ACTIVITY[poi]}" if poi in RECLASS_ACTIVITY
                       else poi_node.get((area_of(r["doc_id"]), poi)))
            elif act and not act.startswith(PROSE_MARK):
                src = f"ACTIVITY|{act}"
            else:
                src = None
            if src:
                B.add_edge(src, "AT_TIME", f"TIME|{t}", weight=1, doc=r["doc_id"],
                           **{"time_period": r.get("time_period", "")})
                time_edges += 1

    # --- 边：BY_TRANSPORT（P2 同句共现） ---------------------------------- #
    by_sentence: dict[tuple[str, str], list] = defaultdict(list)
    for e in entities:
        by_sentence[(e["doc_id"], e["sentence"])].append(e)
    transport_edges = 0
    for (doc, _sentence), items in by_sentence.items():
        pois = {norm_name(i["normalized_name"]) for i in items if i["entity_type"] == "POI"}
        trans = {norm_transport(norm_name(i["normalized_name"]))[0]
                 for i in items if i["entity_type"] == "TRANSPORT"}
        for poi in pois:
            if poi in SCENIC_LEVEL_NAMES:
                continue
            src = poi_node.get((area_of(doc), poi))
            if not src:
                continue
            for t in trans:
                B.add_edge(src, "BY_TRANSPORT", f"TRANSPORT|{t}", weight=1, doc=doc,
                           **{"evidence": "P2 同句共现"})
                transport_edges += 1

    # --- 边：HAS_CONDITION ------------------------------------------------ #
    cond_edges = 0
    cond_missing = []
    for row in bridge:
        if row.get("recommended_for_graph") != "True":
            continue
        cid = row["cond_id"]
        conf = float(row.get("anchor_confidence") or 0.5)
        if row["target_type"] == "POI":
            key = row["target_key"].split("|", 1)[1]
            src = f"POI|{key}"
            if src not in B.nodes:
                cond_missing.append(row["target_key"])
                src = f"SCENIC_AREA|{row['scenic_area']}"
        else:
            src = f"SCENIC_AREA|{row['scenic_area']}"
        B.add_edge(src, "HAS_CONDITION", cond_nodes[cid], weight=conf,
                   doc=row["doc_id"], accumulate=False,
                   **{"match_type": row["match_type"]})

    # --- 边：SIMILAR_TO --------------------------------------------------- #
    similar = 0
    for area, a, b, basis in SIMILAR_PAIRS:
        na, nb = f"POI|{area}|{a}", f"POI|{area}|{b}"
        if na in B.nodes and nb in B.nodes:
            B.add_edge(na, "SIMILAR_TO", nb, weight=0.6, accumulate=False,
                       **{"basis": basis, "decision": "保留双节点（父子关系不合并）"})
            similar += 1

    # --- 收尾统计 -------------------------------------------------------- #
    for nid, acts in poi_activity.items():
        if nid in B.nodes:
            B.nodes[nid].props["activities"] = sorted(acts)

    stats["fusion"] = {
        "rule_counts": dict(rule_counts),
        "alias_hits": alias_hits,
        "p2_only": {a: v for a, v in p2_only.items()},
        "p3_only": {a: v for a, v in p3_only.items()},
        "transport_raw_to_canon": {c: sorted(v) for c, v in transport_raw.items()},
        "similar_pairs": [
            {"area": a, "a": x, "b": y, "basis": b}
            for a, x, y, b in SIMILAR_PAIRS
            if f"POI|{a}|{x}" in B.nodes and f"POI|{a}|{y}" in B.nodes
        ],
        "similar_edges": similar,
    }
    stats["quality"] = {
        "drop_poi": sorted(DROP_POI),
        "reclass_activity": RECLASS_ACTIVITY,
        "activity_only_steps": activity_only_steps,
        "condition_missing_targets": cond_missing,
        "time_edges": time_edges,
        "transport_edges": transport_edges,
        "next_edges": sum(1 for k in B.edges if k[1] == "NEXT"),
        "next_weight": sum(e.weight for e in B.edges.values() if e.rel == "NEXT"),
        "poi_activity_annotations": {k: sorted(v) for k, v in poi_activity.items()},
    }
    stats["counts"] = {
        "nodes": len(B.nodes),
        "edges": len(B.edges),
        "by_type": dict(Counter(n.node_type for n in B.nodes.values())),
        "by_rel": dict(Counter(e.rel for e in B.edges.values())),
        "conditions": len(conditions),
        "conditions_recommended": sum(1 for b in bridge if b.get("recommended_for_graph") == "True"),
    }
    return B, stats


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def write_graph_files(B: Builder, out_dir: Path, stats: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    node_rows = []
    for node in sorted(B.nodes.values(), key=lambda n: (TYPE_ORDER.index(n.node_type), n.node_id)):
        node_rows.append({
            "node_id": node.node_id,
            "node_type": node.node_type,
            "name": node.name,
            "scenic_area": node.scenic_area,
            "source_doc_ids": ";".join(sorted(node.docs)),
            "freq": len(node.docs),
            "properties": json.dumps(node.props, ensure_ascii=False, sort_keys=True),
        })
    write_csv_sig(out_dir / "graph_nodes.csv", node_rows,
                  ["node_id", "node_type", "name", "scenic_area",
                   "source_doc_ids", "freq", "properties"])

    edge_rows = []
    for edge in sorted(B.edges.values(), key=lambda e: (e.rel, e.src, e.dst)):
        edge_rows.append({
            "src": edge.src,
            "rel": edge.rel,
            "dst": edge.dst,
            "weight": round(edge.weight, 2),
            "source_doc_ids": ";".join(sorted(edge.docs)),
            "properties": json.dumps(edge.props, ensure_ascii=False, sort_keys=True),
        })
    write_csv_sig(out_dir / "graph_edges.csv", edge_rows,
                  ["src", "rel", "dst", "weight", "source_doc_ids", "properties"])

    stats["generated_at"] = datetime.now().isoformat(timespec="seconds")
    with (out_dir / "graph_stats.json").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(stats, ensure_ascii=False, indent=2))

    # GraphML（Gephi / Neo4j 导入用）
    import networkx as nx
    G = nx.MultiDiGraph()
    for node in B.nodes.values():
        G.add_node(node.node_id, node_type=node.node_type, name=node.name,
                   scenic_area=node.scenic_area, freq=len(node.docs),
                   source_doc_ids=";".join(sorted(node.docs)),
                   properties=json.dumps(node.props, ensure_ascii=False))
    for edge in B.edges.values():
        G.add_edge(edge.src, edge.dst, key=edge.rel, rel=edge.rel, weight=float(edge.weight),
                   source_doc_ids=";".join(sorted(edge.docs)),
                   properties=json.dumps(edge.props, ensure_ascii=False))
    nx.write_graphml(G, out_dir / "graph.graphml")


# --------------------------------------------------------------------------- #
# 图
# --------------------------------------------------------------------------- #
def _setup_font():
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    fm.fontManager.addfont(str(FONT_PATH))
    name = fm.FontProperties(fname=str(FONT_PATH)).get_name()
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _area_subgraph(B: Builder, area: str):
    import networkx as nx
    area_ids = {n.node_id for n in B.nodes.values() if n.scenic_area == area}
    shared = set()
    for e in B.edges.values():
        if e.src in area_ids:
            shared.add(e.dst)
        if e.dst in area_ids:
            shared.add(e.src)
    keep = area_ids | shared
    G = nx.Graph()
    for nid in keep:
        G.add_node(nid, node_type=B.nodes[nid].node_type)
    for e in B.edges.values():
        if e.src in keep and e.dst in keep and e.rel != "SIMILAR_TO":
            G.add_edge(e.src, e.dst, rel=e.rel)
    return G, keep


def _draw(B: Builder, G, keep: set[str], path_edges: list[tuple[str, str]], out_png: Path) -> None:
    plt = _setup_font()
    import matplotlib.patches as mpatches
    from matplotlib.lines import Line2D
    import networkx as nx

    pos = nx.spring_layout(G, seed=42, k=1.6 / math.sqrt(max(1, G.number_of_nodes())),
                           iterations=120)
    degrees = dict(G.degree())
    fig, ax = plt.subplots(figsize=(15, 11))
    # 先画 CONTAINS，避免压住关键边
    for rel in ["CONTAINS", "AT_TIME", "HAS_CONDITION", "BY_TRANSPORT", "NEXT"]:
        style = EDGE_STYLE[rel]
        segs = [(u, v) for u, v, d in G.edges(data=True) if d["rel"] == rel]
        if not segs:
            continue
        nx.draw_networkx_edges(G, pos, edgelist=segs, ax=ax, edge_color=style["color"],
                               width=style["lw"], style=style["ls"], alpha=0.55)
    if path_edges:
        nx.draw_networkx_edges(G, pos, edgelist=path_edges, ax=ax, edge_color="#D62728",
                               width=3.0, alpha=0.95)
    sizes = [120 + 55 * degrees.get(n, 0) for n in G.nodes]
    colors = [TYPE_COLOR.get(B.nodes[n].node_type, "#999999") for n in G.nodes]
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=sizes, node_color=colors,
                           edgecolors="white", linewidths=0.8, alpha=0.95)
    labels = {n: B.nodes[n].name for n in sorted(G.nodes, key=lambda x: -degrees[x])[:14]}
    for n in G.nodes:
        if B.nodes[n].node_type == "SCENIC_AREA":
            labels[n] = B.nodes[n].name
    nx.draw_networkx_labels(G, pos, labels=labels, ax=ax, font_size=8)
    ax.axis("off")
    handles = [mpatches.Patch(color=TYPE_COLOR[t], label=f"{t}（{sum(1 for n in keep if B.nodes[n].node_type == t)}）")
               for t in TYPE_ORDER]
    handles += [Line2D([0], [0], color=s["color"], lw=2, ls=s["ls"], label=s["label"])
                for s in EDGE_STYLE.values()]
    ax.legend(handles=handles, loc="lower left", fontsize=8, frameon=True, ncol=2)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def draw_figures(B: Builder, out_dir: Path, stats: dict) -> list[str]:
    import matplotlib.patches as mpatches
    import networkx as nx
    fig_dir = out_dir / "figures"
    made = []
    routes = [r for r in read_jsonl(P3_PATH) if area_of(r["doc_id"]) in B.areas]
    for area in B.areas:
        G, keep = _area_subgraph(B, area)
        # 关键路径：该景区步数最多的路线
        by_route: dict[str, list] = defaultdict(list)
        for r in routes:
            if area_of(r["doc_id"]) == area:
                by_route[r["route_id"]].append(r)
        best_route, best_rows = None, []
        for rid, rows in by_route.items():
            if len(rows) > len(best_rows):
                best_route, best_rows = rid, rows
        seq = []
        for r in sorted(best_rows, key=lambda x: x["step_no"]):
            poi = norm_name(r.get("poi"))
            if poi in SCENIC_LEVEL_NAMES or poi in DROP_POI:
                continue
            if poi:
                nid = (f"ACTIVITY|{RECLASS_ACTIVITY[poi]}" if poi in RECLASS_ACTIVITY
                       else f"POI|{area}|{poi}")
            else:
                act = norm_name(r.get("activity"))
                nid = f"ACTIVITY|{act}" if act and not act.startswith(PROSE_MARK) else None
            if nid and nid in G:
                seq.append(nid)
        path_edges = list(zip(seq, seq[1:]))
        png = fig_dir / f"graph_{AREA_SLUG[area]}.png"
        _draw(B, G, keep, path_edges, png)
        made.append(str(png.relative_to(out_dir)))
    # 三景区总览（只在三景区都选时画）
    if len(B.areas) < 3:
        return made
    G = nx.Graph()
    for nid in B.nodes:
        G.add_node(nid)
    for e in B.edges.values():
        if e.rel != "SIMILAR_TO":
            G.add_edge(e.src, e.dst, rel=e.rel)
    fig, ax = _setup_font().subplots(figsize=(18, 14))
    pos = nx.spring_layout(G, seed=7, k=1.2 / math.sqrt(G.number_of_nodes()), iterations=90)
    area_color = {"长隆": "#E45756", "广州白云山": "#4C78A8", "武功山": "#54A24B", "跨景区": "#B279A2", "": "#BBBBBB"}
    for rel in ["CONTAINS", "BY_TRANSPORT", "HAS_CONDITION", "AT_TIME", "NEXT"]:
        style = EDGE_STYLE[rel]
        segs = [(u, v) for u, v, d in G.edges(data=True) if d["rel"] == rel]
        if segs:
            nx.draw_networkx_edges(G, pos, edgelist=segs, ax=ax, edge_color=style["color"],
                                   width=0.5, style=style["ls"], alpha=0.25)
    colors = [area_color.get(B.nodes[n].scenic_area, "#BBBBBB") for n in G.nodes]
    sizes = [40 + 12 * G.degree(n) for n in G.nodes]
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=sizes, node_color=colors,
                           edgecolors="white", linewidths=0.4, alpha=0.9)
    hubs = sorted(G.nodes, key=lambda n: -G.degree(n))[:18]
    nx.draw_networkx_labels(G, pos, {n: B.nodes[n].name for n in hubs}, ax=ax, font_size=8)
    ax.axis("off")
    handles = [mpatches.Patch(color=c, label=a) for a, c in area_color.items() if a in ("长隆", "广州白云山", "武功山", "跨景区")]
    ax.legend(handles=handles, loc="lower left", fontsize=10)
    fig.tight_layout()
    png = fig_dir / "graph_overview.png"
    fig.savefig(png, dpi=160, bbox_inches="tight")
    _setup_font().close(fig)
    made.append(str(png.relative_to(out_dir)))
    return made


AREA_SLUG = {"长隆": "changlong", "广州白云山": "baiyunshan", "武功山": "wugongshan"}


# --------------------------------------------------------------------------- #
# 连通性与 QA
# --------------------------------------------------------------------------- #
def connectivity(B: Builder) -> dict:
    adj: dict[str, set[str]] = defaultdict(set)
    for e in B.edges.values():
        adj[e.src].add(e.dst)
        adj[e.dst].add(e.src)
    seen, comps = set(), []
    for n in B.nodes:
        if n in seen:
            continue
        stack, size = [n], 0
        seen.add(n)
        while stack:
            cur = stack.pop()
            size += 1
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        comps.append(size)
    comps.sort(reverse=True)
    total = len(B.nodes)
    area_nodes = {a: {n.node_id for n in B.nodes.values() if n.scenic_area == a}
                  for a in B.areas}
    no_shared = {}
    for a, ids in area_nodes.items():
        # 去掉跨景区共享节点（area=跨景区/空）后的最大分量
        adj2 = {n: {x for x in adj[n] if x in ids} for n in ids}
        seen2, best = set(), 0
        for n in ids:
            if n in seen2:
                continue
            stack, size = [n], 0
            seen2.add(n)
            while stack:
                cur = stack.pop()
                size += 1
                for nxt in adj2[cur]:
                    if nxt not in seen2:
                        seen2.add(nxt)
                        stack.append(nxt)
            best = max(best, size)
        no_shared[a] = best
    shared = {n.node_id for n in B.nodes.values()
              if n.node_type == "TRANSPORT" and n.scenic_area == "跨景区"}
    kept = [n for n in B.nodes if n not in shared]
    seen2, best2 = set(), 0
    for n in kept:
        if n in seen2:
            continue
        stack, size = [n], 0
        seen2.add(n)
        while stack:
            cur = stack.pop()
            size += 1
            for nxt in adj[cur]:
                if nxt in shared or nxt in seen2:
                    continue
                seen2.add(nxt)
                stack.append(nxt)
        best2 = max(best2, size)
    return {"nodes": total, "components": comps, "largest": comps[0],
            "ratio": comps[0] / max(1, total), "area_nodes": {a: len(v) for a, v in area_nodes.items()},
            "area_largest_without_shared": no_shared,
            "largest_without_shared": best2,
            "ratio_without_shared": best2 / max(1, total)}


def write_qa(B: Builder, stats: dict, conn: dict, out_dir: Path) -> None:
    counts = stats["counts"]
    fusion = stats["fusion"]
    quality = stats["quality"]
    time_stats = stats["time"]
    by_type = counts["by_type"]
    by_rel = counts["by_rel"]

    adj: dict[str, set[str]] = defaultdict(set)
    for e in B.edges.values():
        adj[e.src].add(e.dst)
        adj[e.dst].add(e.src)
    top = sorted(B.nodes.values(), key=lambda n: -len(adj[n.node_id]))[:10]

    lines = []
    add = lines.append
    add("# P6 图谱质量验证与查询手册（graph_qa.md）\n")
    add(f"> 自动生成：`analysis/p06_graph/src/build_graph.py`｜时间：{stats['generated_at']}")
    add(f"> 输入：P2 `v0.2-p02`、P3 `v0.3-p03`、P5 `v0.5-p05`（只读）")
    add(f"> 覆盖景区：{'、'.join(B.areas)}\n")
    add("## 1. 规模\n")
    add(f"- 节点 **{counts['nodes']}**：" + "、".join(
        f"{t} {by_type.get(t, 0)}" for t in TYPE_ORDER))
    add(f"- 边 **{counts['edges']}**：" + "、".join(
        f"{r} {by_rel.get(r, 0)}" for r in EDGE_STYLE))
    add(f"- 条件记录 {counts['conditions']} 条，其中 P5 建议入图 "
        f"**{counts['conditions_recommended']}** 条（桥接 `recommended_for_graph=True`；"
        "3 条重复记录默认过滤）\n")
    add("## 2. 连通性\n")
    add(f"- 最大连通分量 **{conn['largest']}/{conn['nodes']}（{conn['ratio']:.1%}）**；"
        f"分量大小 {conn['components'][:6]}")
    add(f"- 各景区节点数：" + "、".join(f"{a} {n}" for a, n in conn["area_nodes"].items()))
    add(f"- **去掉跨景区共享节点后**，各景区内部最大分量：" + "、".join(
        f"{a} {n}" for a, n in conn["area_largest_without_shared"].items()))
    add(f"- **反证**：若去掉跨景区共享的 `TRANSPORT` 节点，最大分量降为 "
        f"{conn['largest_without_shared']}/{conn['nodes']}（{conn['ratio_without_shared']:.1%}），"
        "三个景区会分裂成各自子图——这正是共享交通节点存在的理由。")
    add("")
    add("> 说明：三景区能连成一张网，靠的是 `TRANSPORT` 节点按**方式**跨景区共享"
        "（如 `TRANSPORT|步行` 同时挂在长隆、白云山、武功山的 POI 上）。这是**概念层共享**，"
        "表示\"到这些景点可以步行\"，**不代表景区之间可以步行互通**。图谱是知识网络，不是路网。\n")
    add("## 3. 融合规则与命中（为什么合并 / 为什么保留）\n")
    add("| 规则 | 说明 | 命中 |")
    add("|---|---|---|")
    add(f"| R1 同名合并 | 同景区内 P2 `normalized_name` 与 P3 `poi` 完全相同 | {fusion['rule_counts'].get('R1_exact', 0)} 对 |")
    add(f"| R2 别名表 | P3 `config/alias.csv` 归一后再比 | {len(fusion['alias_hits'])} 对 |")
    add(f"| R3 交通归一 | `游览观光车→观光车`、`免费巴士/大巴/公交→巴士`、`地铁N号线→地铁` | "
        f"{len(fusion['transport_raw_to_canon'])} 个规范名（原始 "
        f"{sum(len(v) for v in fusion['transport_raw_to_canon'].values())} 个写法） |")
    add(f"| R4 父子/层级不合并 | 如 `摩星岭` vs `摩星岭景区`，保留双节点 + SIMILAR_TO | {fusion['similar_edges']} 对 |")
    add(f"| P2 独有 | 只在实体识别里出现、不在任何路线步骤里 | {sum(len(v) for v in fusion['p2_only'].values())} 个 |")
    add(f"| P3 独有 | 只在路线里出现、P2 未识别 | {sum(len(v) for v in fusion['p3_only'].values())} 个 |")
    add("")
    if fusion["alias_hits"]:
        add("R2 命中明细：")
        for hit in fusion["alias_hits"]:
            add(f"- {hit['area']}：{hit['p2']} → {hit['p3']}")
        add("")
    else:
        add("> R2 实测命中 **0 对**：P2 的 `normalized_name` 已是规范写法，P3 的 `poi` 也已按 "
            "`alias.csv` 归一，两侧没有需要靠别名才对上的名字。规则保留，命中数如实记 0。\n")
    add("R4 保留双节点的明细（`SIMILAR_TO`）：\n")
    for item in fusion["similar_pairs"]:
        add(f"- `POI|{item['area']}|{item['a']}` ↔ `POI|{item['area']}|{item['b']}`：{item['basis']}")
    add("")
    add("## 4. 核心节点（按无向度）\n")
    add("| 节点 | 类型 | 度 | 说明 |")
    add("|---|---|---|---|")
    for node in top:
        add(f"| `{node.node_id}` | {node.node_type} | {len(adj[node.node_id])} | {node.name} |")
    add("")
    add("## 5. 缺失的关系（缺失 ≠ 没有）\n")
    add(f"- **AT_TIME 只在长隆**：P3 显式时间 {time_stats['explicit_steps']} 步、"
        f"{time_stats['unique_values']} 个时间值，按景区分布 {time_stats['by_area']}。"
        "白云山、武功山没有显式时间，**不推断、不补**。")
    add("- **P2/P3 对齐**：P3 的 POI 中约一半在 P2 找不到同名字面，已保留为独立 POI 节点，"
        "不硬合并；P2 独有 POI 只挂 `CONTAINS`，没有 `NEXT`/`BY_TRANSPORT`。")
    add("- **P5 条件覆盖**：只有 13/28 篇文档抽出条件，没有条件边的景区/POI 不代表\"无条件\"。")
    add("- **BY_TRANSPORT 只认同句共现**：同一段落但不同句的交通方式不连，避免把\"全文提到索道\""
        "错误挂到每个 POI 上。")
    add("")
    add("## 6. 可执行查询（复制即可跑）\n")
    add("```python")
    add("import pandas as pd, networkx as nx")
    add("nodes = pd.read_csv('analysis/p06_graph/outputs/graph_nodes.csv', encoding='utf-8-sig')")
    add("edges = pd.read_csv('analysis/p06_graph/outputs/graph_edges.csv', encoding='utf-8-sig')")
    add("G = nx.from_pandas_edgelist(edges, 'src', 'dst', edge_attr=['rel', 'weight'],")
    add("                            create_using=nx.MultiDiGraph)")
    add("")
    add("# Q1 长隆有哪些 POI（P7 场景：\"长隆有什么好玩的\"）")
    add('print(nodes.query("node_type==\'POI\' and scenic_area==\'长隆\'").name.tolist())')
    add("")
    add("# Q2 从长隆北门出发的下一步（P7 场景：路线顺序）")
    add('print(edges.query("src==\'POI|长隆|北门\' and rel==\'NEXT\'"))')
    add("")
    add("# Q3 哪些景点可以坐索道到（跨景区，P7 场景：交通方式）")
    add('print(edges.query("dst==\'TRANSPORT|索道\' and rel==\'BY_TRANSPORT\'").src.tolist())')
    add("")
    add("# Q4 某个景区的条件建议（P7 场景：带老人/小孩怎么办）")
    add('print(edges.query("src==\'SCENIC_AREA|武功山\' and rel==\'HAS_CONDITION\'"))')
    add("```")
    add("")
    add("## 7. 数据质量问题与处理\n")
    add(f"- **P3 伪 POI {len(quality['drop_poi']) + len(quality['reclass_activity']) + len(KEEP_POI_NOTE)} 条**：")
    add(f"  - 过滤 {len(quality['drop_poi'])} 条（句子片段/动作）：" + "、".join(f"`{x}`" for x in quality["drop_poi"]))
    add(f"  - 转 ACTIVITY {len(quality['reclass_activity'])} 条：" + "、".join(
        f"`{k}→{v}`" for k, v in quality["reclass_activity"].items()))
    add(f"  - 保留 {len(KEEP_POI_NOTE)} 条并注明：" + "、".join(f"`{x}`" for x in KEEP_POI_NOTE))
    add(f"- **无 POI 的步骤 {quality['activity_only_steps']} 个**（不含 12 条"
        "\"整篇路线概述\"散文路线）：有活动名的建成 ACTIVITY 节点，只有概述的直接跳过。")
    add(f"- **条件目标缺失 {len(quality['condition_missing_targets'])} 条**："
        + ("无" if not quality["condition_missing_targets"] else "、".join(quality["condition_missing_targets"]))
        + "（缺失时回退到景区节点）")
    add("- **CRLF/BOM**：输出 CSV 一律 UTF-8-SIG + `lineterminator='\\n'`，JSONL/GraphML 为 UTF-8。")
    add("")
    add("## 8. 给 P7 的接口\n")
    add("- 只读 `outputs/graph_nodes.csv`、`outputs/graph_edges.csv`；`node_id` 稳定，"
        "`POI|<景区>|<标准名>` 与 P5 桥接键一致。")
    add("- 条件节点的 id 是 `CONDITION|<cond_id>`，挂载方向 `POI/SCENIC_AREA -> CONDITION`。")
    add("- `TRANSPORT` 节点是**跨景区共享**的，`scenic_area` 可能是 `跨景区`；按景区过滤时"
        "请把 `跨景区` 一起带上，否则会漏掉交通方式。")
    add("- `TIME` 节点没有 `scenic_area`（时间值是跨景区概念），需要按边反查所属 POI。")
    add("")
    add("## 9. 图\n")
    add("> 图内不写标题（标题由图题承担）；中文用 `C:\\Windows\\Fonts\\msyh.ttc`。\n")
    for area in B.areas:
        add(f"![{area}知识图谱](figures/graph_{AREA_SLUG[area]}.png)\n")
        add(f"*图 · {area}知识图谱（红线为该景区步数最多的路线）*\n")
    if len(B.areas) == 3:
        add("![三景区知识图谱总览](figures/graph_overview.png)\n")
        add("*图 · 三景区知识图谱总览（颜色区分景区；共享的交通/时间节点连接三个景区）*\n")
    with (out_dir / "graph_qa.md").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="P6 知识图谱构建")
    parser.add_argument("--areas", nargs="*", default=None,
                        help="景区：changlong/baiyunshan/wugongshan 或 长隆/广州白云山/武功山")
    parser.add_argument("--out", default=str(PROJECT_DIR / "outputs"))
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()

    areas = tuple(AREA_ORDER)
    if args.areas:
        mapped = []
        for raw in args.areas:
            key = raw.strip().lower()
            if key not in AREA_ALIASES:
                raise SystemExit(f"未知景区：{raw}（可选 {sorted(AREA_ALIASES)}）")
            if AREA_ALIASES[key] not in mapped:
                mapped.append(AREA_ALIASES[key])
        areas = tuple(a for a in AREA_ORDER if a in mapped)

    B, stats = build(areas)
    conn = connectivity(B)
    out_dir = Path(args.out)
    write_graph_files(B, out_dir, stats)
    if not args.no_figures:
        made = draw_figures(B, out_dir, stats)
        print("图：" + "、".join(made))
    write_qa(B, stats, conn, out_dir)

    print(f"节点 {stats['counts']['nodes']} / 边 {stats['counts']['edges']}")
    print(f"类型 {stats['counts']['by_type']}")
    print(f"关系 {stats['counts']['by_rel']}")
    print(f"最大连通分量 {conn['largest']}/{conn['nodes']}（{conn['ratio']:.1%}）")
    print(f"输出目录 {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
