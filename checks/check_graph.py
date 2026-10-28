# -*- coding: utf-8 -*-
"""项目 6 自检：知识图谱节点/边是否符合契约。

用法：
    python checks/check_graph.py [analysis/p06_graph/outputs]

检查：节点/边文件存在、必填字段、类型枚举、边端点均存在于节点表、
是否有明显孤岛、按类型统计。
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks._common import Report, not_ready  # noqa: E402
from lib.paths import ANALYSIS  # noqa: E402
from lib.io_utils import read_csv_sig  # noqa: E402

DEFAULT = ANALYSIS / "p06_graph" / "outputs"
NODE_TYPES = {"POI", "TRANSPORT", "TIME", "ACTIVITY", "SCENIC_AREA", "CONDITION"}
EDGE_TYPES = {"NEXT", "CONTAINS", "AT_TIME", "BY_TRANSPORT", "HAS_CONDITION", "SIMILAR_TO"}


def largest_component(nodes: set[str], edges: list[tuple[str, str]]) -> int:
    adj: dict[str, list[str]] = defaultdict(list)
    for s, d in edges:
        adj[s].append(d)
        adj[d].append(s)
    seen: set[str] = set()
    best = 0
    for n in nodes:
        if n in seen:
            continue
        q, size = deque([n]), 0
        seen.add(n)
        while q:
            cur = q.popleft()
            size += 1
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        best = max(best, size)
    return best


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    nodes_path, edges_path = out_dir / "graph_nodes.csv", out_dir / "graph_edges.csv"
    if not nodes_path.exists() or not edges_path.exists():
        return not_ready("p06_graph", [nodes_path, edges_path])

    n_rows, n_cols = read_csv_sig(nodes_path)
    e_rows, e_cols = read_csv_sig(edges_path)
    rep = Report(f"p06_graph · 节点 {len(n_rows)} · 边 {len(e_rows)}")

    for col in ("node_id", "node_type", "name"):
        if col not in n_cols:
            rep.error(f"graph_nodes.csv 缺列：{col}")
    for col in ("src", "rel", "dst"):
        if col not in e_cols:
            rep.error(f"graph_edges.csv 缺列：{col}")
    if rep.errors:
        return rep.finish()

    node_ids, node_types = set(), Counter()
    for i, row in enumerate(n_rows, start=1):
        nid = (row.get("node_id") or "").strip()
        if not nid:
            rep.error(f"节点第 {i} 行 node_id 为空")
        elif nid in node_ids:
            rep.error(f"节点 node_id 重复：{nid}")
        node_ids.add(nid)
        nt = (row.get("node_type") or "").strip()
        node_types[nt] += 1
        if nt not in NODE_TYPES:
            rep.error(f"节点 {nid} 类型非法：{nt}")

    edge_types, pairs = Counter(), []
    for i, row in enumerate(e_rows, start=1):
        src, rel, dst = ((row.get(k) or "").strip() for k in ("src", "rel", "dst"))
        edge_types[rel] += 1
        if rel not in EDGE_TYPES:
            rep.error(f"边第 {i} 行 rel 非法：{rel}")
        for endpoint, value in (("src", src), ("dst", dst)):
            if value not in node_ids:
                rep.error(f"边第 {i} 行 {endpoint} 不在节点表：{value}")
        pairs.append((src, dst))

    comp = largest_component(node_ids, pairs) if node_ids else 0
    ratio = comp / max(1, len(node_ids))
    rep.note(f"节点类型 {dict(node_types)}；边类型 {dict(edge_types)}")
    rep.note(f"最大连通分量 {comp}/{len(node_ids)}（{ratio:.0%}）")
    if ratio < 0.5:
        rep.error("最大连通分量不足 50%，图谱呈碎片化（评审要求“较完整的知识网络”）")

    if not (out_dir / "graph_qa.md").exists():
        rep.warn("缺少 outputs/graph_qa.md（查询验证与缺失关系分析）")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
