import csv
from pathlib import Path

from scenic_aliases import canonicalize_scenic_area


# 从当前文件的位置找到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GRAPH_DIR = PROJECT_ROOT / "analysis" / "p06_graph" / "outputs"


def _canonical_area(scenic_area):
    """查询前把“广州长隆旅游度假区”等写法归一化。"""
    if not scenic_area:
        return scenic_area
    return canonicalize_scenic_area(scenic_area) or scenic_area


def load_graph():
    """读取项目 6 的图谱节点和边。"""
    nodes_path = GRAPH_DIR / "graph_nodes.csv"
    edges_path = GRAPH_DIR / "graph_edges.csv"

    with nodes_path.open(encoding="utf-8-sig", newline="") as file:
        nodes = list(csv.DictReader(file))

    with edges_path.open(encoding="utf-8-sig", newline="") as file:
        edges = list(csv.DictReader(file))

    return nodes, edges

def get_route(scenic_area, source_doc_id=None, max_steps=20):
    """查询景区中有 NEXT 证据的路线连接。"""
    if max_steps < 1:
        raise ValueError("max_steps 必须大于 0")

    scenic_area = _canonical_area(scenic_area)
    nodes, edges = load_graph()
    nodes_by_id = {node["node_id"]: node for node in nodes}

    # 景区节点记录了属于该景区的来源文档
    scenic_node = next(
        (
            node for node in nodes
            if node["node_type"] == "SCENIC_AREA"
            and node["name"] == scenic_area
        ),
        None
    )

    if scenic_node is None:
        return []

    scenic_docs = set(scenic_node["source_doc_ids"].split(";"))

    if source_doc_id:
        scenic_docs &= {source_doc_id}

    results = []

    for edge in edges:
        if edge["rel"] != "NEXT":
            continue

        # 只保留属于所选景区和所选文档的来源
        edge_docs = set(edge["source_doc_ids"].split(";"))
        matched_docs = sorted(edge_docs & scenic_docs)

        if not matched_docs:
            continue

        from_node = nodes_by_id.get(edge["src"])
        to_node = nodes_by_id.get(edge["dst"])

        if not from_node or not to_node:
            continue

        results.append({
            "from_node_id": edge["src"],
            "from_name": from_node["name"],
            "to_node_id": edge["dst"],
            "to_name": to_node["name"],
            "source_doc_ids": matched_docs
        })

        if len(results) >= max_steps:
            break

    return results

def order_route(connections, source_doc_id):
    """整理同一来源文档的路线链接"""
    edges =[
        edge for edge in connections
        if source_doc_id in edge["source_doc_ids"]
    ]

    if not edges:
        return {"steps":[],"message":"do not find any route for this file"}

    destination_ids={edge["to_node_id"] for edge in edges}
    starts={
        edge["from_node_id"]
        for edge in edges
        if edge["from_node_id"]not in destination_ids
    }
    if len(starts)!=1:
        return{
            "steps":[],
            "message":"unable to determine the unique starting point, please check if there are multiple routes or cucles"

        }

    current_id=starts.pop()
    visited = set()
    steps=[]
    used_edges=0

    while True:
        if current_id in visited:
            return{"steps":steps,"messages":"there is a cycle stop"}
        visited.add(current_id)

        outgoing=[
            edge for edge in edges
            if edge["from_node_id"]==current_id
        ]

        if not outgoing:
            break
        if len(outgoing)>1:
            return{"steps":steps,"message":"find some route cascade,need to make a decision"}

        edge = outgoing[0]

        if not steps:
            steps.append(edge["from_name"])

        steps.append(edge["to_name"])
        current_id=edge["to_node_id"]
        used_edges+=1

    if used_edges < len(edges):
        message="已整理一段路线，还有未连接步骤需要检查"
    else:
        message="路线整理完成"
    return {"steps":steps,"message":message}


def search_poi(keyword, scenic_area="",
               node_type="POI",limit=10):
    if limit<1:
        raise ValueError("limit必须大于0")

    scenic_area = _canonical_area(scenic_area)
    nodes, _=load_graph()
    results=[]

    for node in nodes:
        if node["node_type"]!=node_type:
            continue
        if scenic_area and node["scenic_area"]!=scenic_area:
            continue
        if keyword.casefold() not in node["name"].casefold():
            continue

        results.append({
            "node_id":node["node_id"],
            "name":node["name"],
            "scenic_area":node["scenic_area"]
        })

        if len(results)>=limit:
            break
    return results

def neighbors(node_id, rel=None):
    """查询节点的出边邻居，可按关系类型筛选。"""
    nodes, edges = load_graph()
    nodes_by_id = {node["node_id"]: node for node in nodes}
    if node_id not in nodes_by_id:
        return []

    results = []
    for edge in edges:
        if edge["src"] != node_id or (rel and edge["rel"] != rel):
            continue
        target = nodes_by_id.get(edge["dst"])
        if target:
            results.append({
                "rel": edge["rel"],
                "node_id": edge["dst"],
                "name": target["name"]
            })
    return results


def get_conditions(condition_type, scenic_area=""):
    """查询图谱中指定类型的条件和建议。"""
    import json

    scenic_area = _canonical_area(scenic_area)
    nodes, _ = load_graph()
    results = []

    for node in nodes:
        if node["node_type"] != "CONDITION":
            continue

        if scenic_area and node["scenic_area"] != scenic_area:
            continue

        properties = json.loads(node["properties"])

        if properties.get("condition_type") != condition_type:
            continue

        results.append({
            "condition_text": node["name"],
            "suggestion_text": properties.get("suggestion", "")
        })

    return results

def get_condition_evidence(condition_text, suggestion_text, scenic_area):
    """查找一条条件建议对应的图谱来源。"""
    import json

    scenic_area = _canonical_area(scenic_area)
    nodes, edges = load_graph()
    nodes_by_id = {node["node_id"]: node for node in nodes}

    matching_ids = set()

    for node in nodes:
        if node["node_type"] != "CONDITION":
            continue

        if node["scenic_area"] != scenic_area:
            continue

        properties = json.loads(node["properties"])

        if (
            node["name"] == condition_text
            and properties.get("suggestion", "") == suggestion_text
        ):
            matching_ids.add(node["node_id"])

    evidence = []

    for edge in edges:
        if edge["rel"] != "HAS_CONDITION":
            continue

        if edge["dst"] not in matching_ids:
            continue

        anchor = nodes_by_id.get(edge["src"], {})
        edge_properties = json.loads(edge["properties"])

        evidence.append({
            "condition_node_id": edge["dst"],
            "anchor_node_id": edge["src"],
            "anchor_name": anchor.get("name", ""),
            "match_type": edge_properties.get("match_type", ""),
            "source_doc_ids": [
                doc_id for doc_id in edge["source_doc_ids"].split(";")
                if doc_id
            ]
        })

    return evidence

def list_route_sources(scenic_area):
    """列出景区中包含next连接的来源文档以及链接数量"""
    scenic_area = _canonical_area(scenic_area)
    nodes, edges=load_graph()

    scenic_node=next(
        (
            node for node in nodes
            if node["node_type"]=="SCENIC_AREA" and node["name"]==scenic_area
        ),
        None
    )

    if scenic_node is None:
        return []
    scenic_docs = set(scenic_node["source_doc_ids"].split(";"))
    counts={}

    for edge in edges:
        if edge["rel"]!="NEXT":
            continue
        edge_docs=set(edge["source_doc_ids"].split(";"))

        for doc_id in edge_docs & scenic_docs:
            counts[doc_id]=counts.get(doc_id,0)+1

    return [{"source_doc_id":doc_id,"connection_count":counts[doc_id]}
            for doc_id in sorted(counts)]


def get_route_candidates(scenic_area):
    """按来源文档整理景区路线链接"""
    scenic_area = _canonical_area(scenic_area)
    sources=list_route_sources(scenic_area)
    candidates=[]
    for source in sources:
        doc_id = source["source_doc_id"]
        connection_count=source["connection_count"]

        connections=get_route(
            scenic_area,
            source_doc_id=doc_id,
            max_steps=connection_count
        )

        candidates.append(
            {
                "source_doc_id":doc_id,
                "connections":connections
            }
        )
    return candidates



def validate_route(node_ids, candidates):
    """检查路线的每一段是否有图谱 NEXT 证据。"""
    if len(node_ids) < 2:
        return {
            "valid": False,
            "segments": [],
            "missing_connections": [],
            "message": "至少需要两个节点才能检查路线连接。"
        }

    # 把按文档分组的连接展开，供逐段查找
    connections = [
        connection
        for candidate in candidates
        for connection in candidate["connections"]
    ]

    segments = []
    missing = []

    for from_id, to_id in zip(node_ids, node_ids[1:]):
        matches = [
            connection for connection in connections
            if connection["from_node_id"] == from_id
            and connection["to_node_id"] == to_id
        ]

        if not matches:
            missing.append({
                "from_node_id": from_id,
                "to_node_id": to_id
            })
            continue

        source_docs = sorted({
            doc_id
            for match in matches
            for doc_id in match["source_doc_ids"]
        })

        segments.append({
            "from_name": matches[0]["from_name"],
            "to_name": matches[0]["to_name"],
            "source_doc_ids": source_docs
        })

    return {
        "valid": len(missing) == 0,
        "segments": segments,
        "missing_connections": missing,
        "message": "检查完成"
    }

def find_indirect_route(start_id, end_id, candidates):
    """沿 NEXT 连接查找从起点到终点的路径。"""
    from collections import defaultdict, deque

    # 建立每个节点可以前往哪些下一节点的表
    next_nodes = defaultdict(list)

    for candidate in candidates:
        for connection in candidate["connections"]:
            next_nodes[connection["from_node_id"]].append(
                connection["to_node_id"]
            )

    queue = deque([start_id])
    previous = {start_id: None}

    while queue:
        current = queue.popleft()

        if current == end_id:
            break

        for next_id in next_nodes[current]:
            if next_id not in previous:
                previous[next_id] = current
                queue.append(next_id)

    if end_id not in previous:
        return None

    # 从终点回溯，得到起点到终点的节点顺序
    path = []
    current = end_id

    while current is not None:
        path.append(current)
        current = previous[current]

    return list(reversed(path))

def repair_route(node_ids, candidates):
    """用图谱中的间接路径补全断开的路线。"""
    if len(node_ids) < 2:
        return {
            "repaired": False,
            "message": "至少需要两个节点才能修复路线。"
        }

    repaired_nodes = [node_ids[0]]
    inserted_paths = []

    for start_id, end_id in zip(node_ids, node_ids[1:]):
        direct_check = validate_route([start_id, end_id], candidates)

        if direct_check["valid"]:
            path = [start_id, end_id]
        else:
            path = find_indirect_route(start_id, end_id, candidates)

            if not path or len(path) < 2:
                return {
                    "repaired": False,
                    "message": "图谱中没有找到连接两个节点的路径。",
                    "missing_connection": {
                        "from_node_id": start_id,
                        "to_node_id": end_id
                    }
                }

            inserted_paths.append(path)

        # 路径起点已经在结果中，只追加后续节点
        repaired_nodes.extend(path[1:])

    validation = validate_route(repaired_nodes, candidates)

    seen = set()
    repeated = set()

    for node_id in repaired_nodes:
        if node_id in seen:
            repeated.add(node_id)
        seen.add(node_id)

    return {
        "repaired": validation["valid"],
        "node_ids": repaired_nodes,
        "inserted_paths": inserted_paths,
        "repeated_nodes": sorted(repeated),
        "validation": validation
    }

if __name__ == "__main__":
    candidates = get_route_candidates("广州白云山")

    node_ids = [
        "POI|广州白云山|白云山南门",
        "POI|广州白云山|黄婆洞水库",
        "POI|广州白云山|明珠楼",
        "POI|广州白云山|梅花谷",
        "POI|广州白云山|松涛别院",
        "POI|广州白云山|桃花涧",
        "POI|广州白云山|黄婆洞水库",
        "POI|广州白云山|回归林"
    ]

    result = repair_route(node_ids, candidates)

    if result["repaired"]:
        names = [node_id.split("|")[-1] for node_id in result["node_ids"]]
        repeated = [
            node_id.split("|")[-1]
            for node_id in result["repeated_nodes"]
        ]

        print("补全路线：", " → ".join(names))
        print("重复经过：", repeated)
    else:
        print(result)
