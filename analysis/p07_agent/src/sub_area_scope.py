"""长隆子园区范围与景点归属。

解决的问题：用户说“长隆欢乐世界”时，景区名会被归一成“长隆”，此前的查询
仍然覆盖整个长隆，返回野生动物世界等其它园区的地点。

归属依据（不读取原文）：

- 文档级标签 ``DOC_SUB_AREA``：取自 P1 已入库的
  ``scenic/changlong/data/processed/changlong_guides.csv`` 的
  ``doc_id`` / ``subtype`` 两列（v0.1-p01，2026-10-28 版），只是文档元数据。
- 景点级归属：用 P6 图谱节点自带的 ``source_doc_ids`` 叠加上述标签。
  只有出处文档全部落在同一园区时才标记；出处跨园区或只有综述文档时标为
  ``None``（未知），不猜测。
- ``MULTI`` 文档（如三天两夜总览）若只被一个子园区节点提及，按该子园区收敛；
  仍被多个子园区提及时保持 ``MULTI``，不参与单园区筛选。

其它景区没有子园区概念，函数会直接返回未应用（``applied=False``）。
"""

from __future__ import annotations


MULTI_SUB_AREA = "多园区"

# 图谱中代表子园区的 POI 节点。飞鸟乐园在 P2/P3 中没有独立节点，只保留别名，
# 以便识别用户说法并给出“图谱未收录”的说明。
SUB_AREA_ANCHORS = {
    "欢乐世界": "POI|长隆|长隆欢乐世界",
    "野生动物世界": "POI|长隆|长隆野生动物世界",
    "水上乐园": "POI|长隆|长隆水上乐园",
    "国际大马戏": "POI|长隆|长隆国际大马戏",
}

# 用户写法 -> 标准子园区名。较长的写法同时保留，避免只匹配到短后缀。
SUB_AREA_ALIASES = {
    "欢乐世界": ("长隆欢乐世界", "欢乐世界"),
    "野生动物世界": (
        "长隆野生动物世界",
        "广州长隆野生动物世界",
        "野生动物世界",
        "长隆野生动物园",
        "野生动物园",
    ),
    "水上乐园": ("长隆水上乐园", "水上乐园"),
    "飞鸟乐园": ("长隆飞鸟乐园", "飞鸟乐园"),
    "国际大马戏": ("长隆国际大马戏", "广州长隆国际大马戏", "国际大马戏", "大马戏"),
}

# 长隆 8 篇文档的园区标签，来自 P1 的 subtype 列（不是人工推测）。
# tests/test_sub_area_scope.py 会与 P1 CSV 对照，防止手写漂移。
DOC_SUB_AREA = {
    "CL-O-01": MULTI_SUB_AREA,   # 官方三天两夜（多园区）
    "CL-O-02": "野生动物世界",     # 官方野生动物世界路线
    "CL-O-03": "欢乐世界",         # 官方欢乐世界路线
    "CL-T-01": "欢乐世界",
    "CL-T-02": MULTI_SUB_AREA,   # 标题为度假区总攻略，正文路线全在欢乐世界
    "CL-T-03": "野生动物世界",
    "CL-T-04": "欢乐世界",
    "CL-T-05": "水上乐园",
}

# 景区名 -> 是否支持子园区范围。
SUB_AREA_SCENIC = ("长隆",)

_INDEX = None


def sub_area_names():
    """返回可识别的子园区标准名（顺序稳定）。"""
    return tuple(SUB_AREA_ALIASES)


def detect_sub_area(text):
    """从用户文本识别子园区；返回 ``(标准名或 None, 说明)``。

    同时提到多个子园区时不做筛选，返回说明交给上层展示。
    """
    if not isinstance(text, str) or not text.strip():
        return None, ""

    found = []
    for name, aliases in SUB_AREA_ALIASES.items():
        if any(alias in text for alias in aliases):
            found.append(name)

    if len(found) == 1:
        return found[0], ""
    if len(found) > 1:
        return None, "同时提到多个子园区（" + "、".join(found) + "），按整个景区范围查询。"
    return None, ""


def _doc_set(node):
    return {doc for doc in (node.get("source_doc_ids") or "").split(";") if doc}


def _build_index():
    """从 P6 图谱构建文档/景点 -> 子园区索引，只在首次调用时读取。"""
    from tools import load_graph

    nodes, _ = load_graph()
    nodes_by_id = {node["node_id"]: node for node in nodes}

    # 1) 文档标签：先抄 P1 的 subtype，再把只被一个子园区提及的多园区文档收敛。
    anchor_docs = {
        name: _doc_set(nodes_by_id[node_id])
        for name, node_id in SUB_AREA_ANCHORS.items()
        if node_id in nodes_by_id
    }
    doc_scope = dict(DOC_SUB_AREA)
    for doc_id, value in DOC_SUB_AREA.items():
        if value != MULTI_SUB_AREA:
            continue
        mentioned = [name for name, docs in anchor_docs.items() if doc_id in docs]
        if len(mentioned) == 1:
            doc_scope[doc_id] = mentioned[0]

    # 2) 景点归属：景点级 source_doc_ids 全部指向同一园区才标记。
    poi_scope = {}
    anchor_ids = {node_id: name for name, node_id in SUB_AREA_ANCHORS.items()}
    for node in nodes:
        if node["node_type"] != "POI" or node["scenic_area"] != "长隆":
            continue
        node_id = node["node_id"]
        if node_id in anchor_ids:
            poi_scope[node_id] = anchor_ids[node_id]
            continue
        # “长隆旅游度假区”是景区级名称，不是园区景点，不给园区标签。
        if "度假区" in node["name"]:
            continue
        parks = {
            doc_scope.get(doc_id)
            for doc_id in _doc_set(node)
            if doc_scope.get(doc_id) not in (None, MULTI_SUB_AREA)
        }
        if len(parks) == 1:
            poi_scope[node_id] = parks.pop()

    counts = {}
    for name in poi_scope.values():
        counts[name] = counts.get(name, 0) + 1

    return {
        "nodes_by_id": nodes_by_id,
        "doc_scope": doc_scope,
        "poi_scope": poi_scope,
        "counts": counts,
    }


def _index():
    global _INDEX
    if _INDEX is None:
        _INDEX = _build_index()
    return _INDEX


def reset_cache():
    """测试或数据更新后清空缓存。"""
    global _INDEX
    _INDEX = None


def poi_sub_area(node_id):
    """返回景点的子园区；未知或跨园区返回 ``None``。"""
    return _index()["poi_scope"].get(node_id)


def scope_counts():
    """各子园区已标记的景点数量，供报告与测试复核。"""
    return dict(_index()["counts"])


def doc_sub_area(doc_id):
    """返回文档的园区标签；``MULTI`` 表示多园区总览。"""
    return _index()["doc_scope"].get(doc_id)


def filter_route_candidates(candidates, sub_area, scenic_area="长隆"):
    """按子园区筛选按文档分组的 NEXT 候选连接。

    返回 ``{"candidates", "applied", "note", "kept_docs", "dropped_docs"}``。
    候选不足以规划时回退到整个景区，并给出说明。
    """
    if not sub_area or scenic_area not in SUB_AREA_SCENIC:
        return {"candidates": candidates, "applied": False, "fallback": False, "note": "",
                "requested": sub_area, "kept_docs": [], "dropped_docs": []}

    if sub_area not in SUB_AREA_ANCHORS:
        return {
            "candidates": candidates,
            "applied": False,
            "fallback": True,
            "requested": sub_area,
            "note": f"图谱没有「{sub_area}」的独立节点，按整个景区范围查询。",
            "kept_docs": [],
            "dropped_docs": [],
        }

    scopes = _index()["doc_scope"]
    kept = [item for item in candidates if scopes.get(item["source_doc_id"]) == sub_area]
    kept_docs = [item["source_doc_id"] for item in kept]
    dropped = [item["source_doc_id"] for item in candidates
               if item["source_doc_id"] not in kept_docs]
    connections = sum(len(item["connections"]) for item in kept)

    if not kept or connections < 2:
        return {
            "candidates": candidates,
            "applied": False,
            "fallback": True,
            "requested": sub_area,
            "note": f"「{sub_area}」在图谱中的路线连接不足，已扩大到整个景区范围。",
            "kept_docs": [],
            "dropped_docs": dropped,
        }

    multi_docs = [doc_id for doc_id in dropped
                  if scopes.get(doc_id) == MULTI_SUB_AREA]
    note = (f"已按子园区范围「{sub_area}」查询：{len(kept)} 份来源、"
            f"{connections} 条 NEXT 连接。")
    if multi_docs:
        note += f"多园区总览路线（{'、'.join(multi_docs)}）未纳入本次规划。"

    return {
        "candidates": kept,
        "applied": True,
        "fallback": False,
        "requested": sub_area,
        "note": note,
        "kept_docs": kept_docs,
        "dropped_docs": dropped,
    }


def filter_poi_results(results, sub_area, scenic_area="长隆"):
    """按子园区筛选景点查询结果；园区内为空时回退整个景区。

    返回 ``(结果列表, 说明)``。
    """
    if not sub_area or scenic_area not in SUB_AREA_SCENIC or not results:
        return results, ""

    if sub_area not in SUB_AREA_ANCHORS:
        return results, f"图谱没有「{sub_area}」的独立节点，按整个景区范围查询。"

    scopes = _index()["poi_scope"]
    kept = [item for item in results if scopes.get(item["node_id"]) == sub_area]

    if kept:
        return kept, f"已按子园区「{sub_area}」筛选出 {len(kept)} 个地点。"
    return results, f"「{sub_area}」范围内没有匹配地点，已扩大到整个景区。"


def describe_scope(scenic_area, sub_area):
    """给页面/对话用的范围说明。"""
    if not sub_area or scenic_area not in SUB_AREA_SCENIC:
        return scenic_area
    return f"{scenic_area} · {sub_area}"
