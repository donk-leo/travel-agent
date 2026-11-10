import csv
import json
from collections import Counter, deque
from heapq import heappop, heappush
from pathlib import Path

from scenic_aliases import canonicalize_scenic_area


# 从当前文件的位置找到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GRAPH_DIR = PROJECT_ROOT / "analysis" / "p06_graph" / "outputs"

# 路线重排的上限：地点数超过该值时改用贪心最近邻，避免指数级搜索。
ROUTE_STOP_LIMIT = 14
# 补全断开路线时，进入已访问节点要付出的代价（相当于“多走一步”之外再罚 20 步）。
REPEAT_PENALTY = 20


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
            "fully_verified": False,
            "segments": [],
            "missing_connections": [],
            "cross_doc_transitions": 0,
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
    cross_doc_transitions = 0
    previous_docs = None

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
            previous_docs = None
            continue

        source_docs = sorted({
            doc_id
            for match in matches
            for doc_id in match["source_doc_ids"]
        })
        current_docs = set(source_docs)

        # 同一段路可能同时被多篇文档支持。只有当前段与上一段完全没有
        # 共同来源文档时，才算一次“跨文档跳转”。这种跳转在图上看起来
        # 连续，实际可能是两篇游记的不同片段拼在一起，不能直接标为有效。
        if previous_docs is not None and not (previous_docs & current_docs):
            cross_doc_transitions += 1

        segments.append({
            "from_name": matches[0]["from_name"],
            "to_name": matches[0]["to_name"],
            "source_doc_ids": source_docs
        })
        previous_docs = current_docs

    if missing:
        message = f"{len(missing)} 段缺少图谱 NEXT 连接。"
    elif cross_doc_transitions:
        message = (
            f"路线有 {cross_doc_transitions} 处跨来源文档跳转，"
            "逐段连接存在，但无法证明属于同一条连续路线。"
        )
    else:
        message = "检查完成"

    return {
        # valid 只表示每一段都有 NEXT 证据；跨来源连续性是更严格的一层，
        # 由 fully_verified 表示。调用方展示“已完成”时应看 fully_verified。
        "valid": len(missing) == 0,
        "fully_verified": len(missing) == 0 and cross_doc_transitions == 0,
        "segments": segments,
        "missing_connections": missing,
        "cross_doc_transitions": cross_doc_transitions,
        "message": message
    }

def _next_edges(candidates):
    """把按文档分组的连接展开成 node_id -> {next_id: {来源文档}}。"""
    edges = {}
    for candidate in candidates:
        for connection in candidate["connections"]:
            edges.setdefault(connection["from_node_id"], {})
            targets = edges[connection["from_node_id"]]
            targets.setdefault(connection["to_node_id"], set()).update(
                connection["source_doc_ids"]
            )
    return edges


def _bfs_path(edges, start_id, end_id):
    """沿 NEXT 连接做不加权的 BFS，返回节点序列；不可达返回 None。"""
    if start_id == end_id:
        return [start_id]

    previous = {start_id: None}
    queue = deque([start_id])

    while queue:
        current = queue.popleft()
        for next_id in edges.get(current, {}):
            if next_id in previous:
                continue
            previous[next_id] = current
            if next_id == end_id:
                path = [end_id]
                node = end_id
                while previous[node] is not None:
                    node = previous[node]
                    path.append(node)
                return list(reversed(path))
            queue.append(next_id)

    return None


def _is_chain(node_ids, edges):
    """每一对相邻节点都必须有图谱 NEXT 证据。"""
    return all(next_id in edges.get(node_id, {})
               for node_id, next_id in zip(node_ids, node_ids[1:]))


def route_metrics(node_ids, candidates=None, edges=None):
    """统计路线的结构指标：步数、重复经过次数、缺失路段。

    这里的“步数”是图谱 NEXT 连接的段数，不是实际步行距离；图谱没有
    距离、坡度和通行情况字段，不能把它换算成体力消耗。
    """
    if edges is None:
        edges = _next_edges(candidates or [])

    duplicates = [node_id for node_id, count in Counter(node_ids).items() if count > 1]
    missing = sum(1 for start_id, end_id in zip(node_ids, node_ids[1:])
                  if end_id not in edges.get(start_id, {}))

    return {
        "visits": len(node_ids),
        "steps": max(len(node_ids) - 1, 0),
        "unique_nodes": len(set(node_ids)),
        "repeats": max(len(node_ids) - len(set(node_ids)), 0),
        "repeated_node_ids": duplicates,
        "missing_segments": missing,
        # 结构成本：多走一步记 1，重复经过一个地点记 2；不是实际体力消耗。
        "structural_score": max(len(node_ids) - 1, 0) + 2 * max(len(node_ids) - len(set(node_ids)), 0),
        "note": "图谱 NEXT 步数，不是实际步行距离。",
    }


def _pairwise_paths(stops, edges):
    """计算目标地点两两之间的最短 NEXT 路径。"""
    count = len(stops)
    lengths = [[None] * count for _ in range(count)]
    paths = [[None] * count for _ in range(count)]

    for index, stop in enumerate(stops):
        for other_index, other in enumerate(stops):
            if index == other_index:
                continue
            path = _bfs_path(edges, stop, other)
            if path:
                lengths[index][other_index] = len(path) - 1
                paths[index][other_index] = path

    return lengths, paths


def _held_karp_route(stops, edges, fixed_end, closed):
    """在固定起点（以及可选固定终点）的前提下，重排目标地点使总步数最少。

    使用 Held-Karp 动态规划；地点数超过 ROUTE_STOP_LIMIT 时由调用方改用贪心。
    """
    count = len(stops)
    if count <= 1:
        return list(stops)

    lengths, paths = _pairwise_paths(stops, edges)
    full = (1 << count) - 1
    best = {(1, 0): 0}
    parent = {}

    for mask in sorted((value for value in range(1 << count) if value & 1),
                       key=lambda value: bin(value).count("1")):
        for last in range(count):
            cost = best.get((mask, last))
            if cost is None:
                continue
            for next_index in range(count):
                if mask & (1 << next_index) or lengths[last][next_index] is None:
                    continue
                state = (mask | (1 << next_index), next_index)
                value = cost + lengths[last][next_index]
                if value < best.get(state, float("inf")):
                    best[state] = value
                    parent[state] = last

    if closed:
        finals = [
            (best[(full, index)] + lengths[index][0], index)
            for index in range(1, count)
            if (full, index) in best and lengths[index][0] is not None
        ]
        if not finals:
            return None
        _, end = min(finals)
    elif fixed_end:
        end = count - 1
        if (full, end) not in best:
            return None
    else:
        finals = [(best[(full, index)], index)
                  for index in range(count) if (full, index) in best]
        if not finals:
            return None
        _, end = min(finals)

    order = []
    mask, current = full, end
    while mask != 1 or current != 0:
        order.append(current)
        previous = parent[(mask, current)]
        mask ^= (1 << current)
        current = previous
    order.append(0)
    order.reverse()

    route = [stops[0]]
    for start_index, end_index in zip(order, order[1:]):
        route.extend(paths[start_index][end_index][1:])
    if closed:
        route.extend(paths[end][0][1:])
    return route


def _greedy_route(stops, edges, fixed_end):
    """贪心最近邻：每次挑最近、且能顺路覆盖的地点，用于地点较多时。"""
    route = [stops[0]]
    remaining = list(range(1, len(stops)))

    while remaining:
        choice = None
        for index in remaining:
            path = _bfs_path(edges, route[-1], stops[index])
            if path is None:
                continue
            key = (len(path) - 1, index)
            if choice is None or key < choice[0]:
                choice = (key, path)
        if choice is None:
            return None
        path = choice[1]
        route.extend(path[1:])
        covered = set(path)
        remaining = [index for index in remaining if stops[index] not in covered]

    if fixed_end and route[-1] != stops[-1]:
        path = _bfs_path(edges, route[-1], stops[-1])
        if path is None:
            return None
        route.extend(path[1:])

    return route


def optimize_route(node_ids, candidates):
    """按图谱 NEXT 连接重排目标地点，减少不必要的重复经过。

    保留模型的起点；如果模型最后停在之前走过的地点（通常表示返程），
    也保留这个终点。其余地点用 Held-Karp（地点 ≤14）或贪心求最短总步数。
    只在结构成本（步数 + 2×重复次数）下降且逐段核验通过时采用新路线。
    """
    edges = _next_edges(candidates)
    original = list(node_ids)
    original_metrics = route_metrics(original, edges=edges)
    base = {
        "optimized": False,
        "node_ids": original,
        "original_metrics": original_metrics,
        "metrics": original_metrics,
        "method": "none",
        "reordered": False,
        "validation": None,
        "note": "保留模型原顺序：没有找到更短且逐段可核验的整理方案。",
    }

    if len(original) < 3:
        return base

    stops = list(dict.fromkeys(original))
    first, last = original[0], original[-1]
    closed = last == first and len(stops) > 1
    fixed_end = (not closed) and last in original[:-1]

    if fixed_end:
        stops.remove(last)
        stops.append(last)
    if len(stops) < 2:
        return base

    options = [("original", original)]
    if len(stops) <= ROUTE_STOP_LIMIT:
        route = _held_karp_route(stops, edges, fixed_end, closed)
        if route:
            options.append(("held_karp", route))
    # 闭合路线（起点=终点）要求回到起点，贪心版本不保证这一点，直接跳过。
    if not closed:
        route = _greedy_route(stops, edges, fixed_end)
        if route:
            options.append(("greedy", route))

    best = None
    for method, route in options:
        if not _is_chain(route, edges):
            continue
        metrics = route_metrics(route, edges=edges)
        # 同等成本时保留原顺序，减少与模型意图的冲突。
        key = (metrics["structural_score"], 0 if method == "original" else 1)
        if best is None or key < best[0]:
            best = (key, method, route, metrics)

    if best is None:
        return base

    _, method, route, metrics = best
    if route == original:
        return {**base, "metrics": metrics, "method": method}

    validation = validate_route(route, candidates)
    if not validation["valid"]:
        return base

    return {
        "optimized": True,
        "node_ids": route,
        "original_metrics": original_metrics,
        "metrics": metrics,
        "method": method,
        "reordered": True,
        "validation": validation,
        "note": (
            f"已按图谱 NEXT 连接重排顺序：步数 {original_metrics['steps']} → "
            f"{metrics['steps']}，重复经过 {original_metrics['repeats']} → "
            f"{metrics['repeats']} 次。"
        ),
    }


def find_indirect_route(start_id, end_id, candidates, visited=None):
    """沿 NEXT 连接查找从起点到终点的路径。

    传入 ``visited``（已走过的节点）时，进入这些节点会有额外代价，从而优先
    选择不重复经过已访问地点的走法；确实没有别的路时才重复。
    """
    edges = _next_edges(candidates)
    blocked = set(visited or ()) - {start_id, end_id}
    infinity = (float("inf"), float("inf"))

    best = {start_id: (0, 0)}
    previous = {start_id: None}
    heap = [(0, 0, start_id)]

    while heap:
        cost, steps, node = heappop(heap)
        if best.get(node) != (cost, steps):
            continue
        if node == end_id:
            path = [node]
            current = node
            while previous[current] is not None:
                current = previous[current]
                path.append(current)
            return list(reversed(path))

        for next_id in edges.get(node, {}):
            penalty = REPEAT_PENALTY if next_id in blocked else 0
            value = (cost + 1 + penalty, steps + 1)
            if value < best.get(next_id, infinity):
                best[next_id] = value
                previous[next_id] = node
                heappush(heap, (value[0], value[1], next_id))

    return None

def repair_route(node_ids, candidates):
    """用图谱中的间接路径补全断开的路线。

    补全时把已走过的节点传给路径搜索，优先绕开它们，减少“补出来的重复绕行”。
    """
    if len(node_ids) < 2:
        return {
            "repaired": False,
            "message": "至少需要两个节点才能修复路线。"
        }

    repaired_nodes = [node_ids[0]]
    inserted_paths = []
    visited = {node_ids[0]}

    for start_id, end_id in zip(node_ids, node_ids[1:]):
        direct_check = validate_route([start_id, end_id], candidates)

        if direct_check["valid"]:
            path = [start_id, end_id]
        else:
            path = find_indirect_route(start_id, end_id, candidates, visited=visited)

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
        visited.update(path)

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

        optimized = optimize_route(result["node_ids"], candidates)
        print("整理后：", " → ".join(
            node_id.split("|")[-1] for node_id in optimized["node_ids"]
        ))
        print("指标：", json.dumps({
            "before": optimized["original_metrics"],
            "after": optimized["metrics"],
        }, ensure_ascii=False))
    else:
        print(result)
