"""备选路线（T2.4）：按来源文档从 P6 图谱 NEXT 边还原单一来源的备选路线。

口径
----
- 输入只来自 ``tools.get_route_candidates()``：每个候选就是「一份来源文档 + 该文档
  自己的 NEXT 连接」，所以每条备选只允许一个 ``source_doc_id``，不跨文档拼路线；
- 节点链复用 ``route_planner._candidate_chain()``（与 ``plan_route`` 的兜底路线同一
  实现），不另写一套链还原；
- 逐段核验复用 ``tools.validate_route()``，不自写 NEXT 判定：同一文档内、方向正确
  的每一段都成立才判 ``verified``；缺段或某段只有其它文档的证据（跨文档拼接）判
  ``partial`` 并写明原因；
- 去重：与主路线、备选之间节点集合相同（含只有顺序不同）的一律丢弃；
- 不编造节点或连接：节点全部来自候选连接，名称缺失时回退 ``node_id`` 末段，
  不补写标题/来源。

输出契约见 ``analysis/p07_agent/web/README.md`` §9.7；``node_ids`` / ``scenic_area``
是内部复核字段，渲染层 ``web_app._normalize_alternatives()`` 会忽略未知字段。
"""

from evidence import doc_meta
from route_planner import _candidate_chain
from tools import get_route_candidates, validate_route


#: 状态排序：verified 在前，partial 在后。
STATUS_ORDER = {"verified": 0, "partial": 1}

#: 一条备选至少要有的停靠点数；少于两个点无法核验任何一段连接。
MIN_STOPS = 2


def _source_title(doc_id):
    """取来源文档标题；查不到时返回空串，不补写标题（证据模块是可选依赖）。"""
    try:
        meta = doc_meta(doc_id)
    except Exception:
        return ""
    return str((meta or {}).get("title") or "").strip()


def _fallback_name(node_id):
    """节点名缺失时回退 ``node_id`` 末段（图谱 node_id 为 ``类型|景区|名称``）。"""
    return str(node_id).split("|")[-1]


def _node_name_map(connections):
    """从候选连接里收集 ``node_id -> 名称``；名称全部取自图谱原值。"""
    names = {}
    for connection in connections or []:
        from_id = connection.get("from_node_id")
        to_id = connection.get("to_node_id")
        if from_id and from_id not in names:
            names[from_id] = connection.get("from_name") or _fallback_name(from_id)
        if to_id and to_id not in names:
            names[to_id] = connection.get("to_name") or _fallback_name(to_id)
    return names


def validate_alternative(alt, candidates=None):
    """逐段核验一条备选路线，返回 ``(status, segments, reasons)``。

    ``segments`` 直接取 ``tools.validate_route()`` 的结果，不自写 NEXT 判定。
    只有每一段都命中、且该段 ``source_doc_ids`` 包含本备选的 ``source_doc_id``
    时才判 ``verified``；缺段、或某段只有其它来源文档的证据（跨文档拼接）判
    ``partial``，原因写进 ``reasons``（列表，可能多条）。

    ``candidates`` 不传时按 ``alt["scenic_area"]`` 重新读取图谱候选；生成备选时
    由调用方传入当前候选，避免重复读图。
    """
    alt = alt if isinstance(alt, dict) else {}
    node_ids = [
        str(node_id) for node_id in (alt.get("node_ids") or [])
        if str(node_id).strip()
    ]
    doc_id = str(alt.get("source_doc_id") or "").strip()
    area = str(alt.get("scenic_area") or "").strip()

    if len(node_ids) < MIN_STOPS:
        return "partial", [], ["备选路线不足两个停靠点，无法核验连接。"]
    if not doc_id:
        return "partial", [], ["备选路线缺少来源文档，无法核验来源。"]

    if candidates is None:
        candidates = get_route_candidates(area) if area else []

    group = [
        item for item in (candidates or [])
        if item.get("source_doc_id") == doc_id
    ]
    # 有本文档的候选就只按它核验：备选只能使用这一个来源文档的连接。
    validation = validate_route(node_ids, group or candidates or [])
    segments = validation.get("segments") or []
    missing = validation.get("missing_connections") or []

    reasons = []
    if missing:
        reasons.append(f"{len(missing)} 段缺少图谱 NEXT 连接。")
    foreign = [
        segment for segment in segments
        if doc_id not in (segment.get("source_doc_ids") or [])
    ]
    if foreign:
        reasons.append(
            f"{len(foreign)} 段只有其它来源文档的 NEXT 证据，属跨文档拼接，"
            f"不能证明与 {doc_id} 是同一条连续路线。"
        )

    if reasons:
        return "partial", segments, reasons
    return "verified", segments, []


def _sort_key(alt):
    """确定性排序：verified 优先 → 停靠点多者优先 → ``source_doc_id`` 升序。"""
    return (
        STATUS_ORDER.get(alt.get("status"), len(STATUS_ORDER)),
        -len(alt.get("node_ids") or []),
        alt.get("source_doc_id") or "",
    )


def build_alternatives(scenic_area, days=1, primary_doc_id=None,
                       primary_node_ids=None, max_alts=3):
    """按来源文档生成 0–``max_alts`` 条备选路线，返回列表（同输入结果稳定）。

    - ``primary_doc_id``：主路线所用的来源文档，直接跳过（主路线已展示它）；
    - ``primary_node_ids``：主路线节点序列，节点集合与之一致（含仅顺序不同）的
      备选丢弃；备选之间同样按节点集合去重；
    - ``days``：保留参数与 ``plan_route`` 对齐；图谱 NEXT 边没有时长/距离数据，
      不能按天数切分或截断路线，因此不参与节点选择（截断会变成假备选）；
    - 每条备选的节点链是该来源文档内的连续链，至少 ``MIN_STOPS`` 个停靠点；
      逐段状态由 ``validate_alternative()`` 给出；
    - 排序键 ``(status, 停靠点数, source_doc_id)``：verified 在前、停靠点多者在前、
      再按 ``source_doc_id`` 升序，保证两次调用结果一致。
    """
    if max_alts is None or max_alts < 1:
        return []

    candidates = get_route_candidates(scenic_area) or []
    primary_doc_id = str(primary_doc_id or "").strip()
    primary_ids = [
        str(node_id) for node_id in (primary_node_ids or [])
        if str(node_id).strip()
    ]
    primary_set = frozenset(primary_ids)

    alternatives = []
    seen_docs = set()
    for candidate in candidates:
        doc_id = str(candidate.get("source_doc_id") or "").strip()
        connections = candidate.get("connections") or []
        if not doc_id or doc_id in seen_docs or not connections:
            continue
        seen_docs.add(doc_id)
        if primary_doc_id and doc_id == primary_doc_id:
            continue

        node_ids = _candidate_chain([candidate])
        if len(node_ids) < MIN_STOPS:
            continue
        if primary_set and frozenset(node_ids) == primary_set:
            continue

        names = _node_name_map(connections)
        alt = {
            "alt_id": f"alt-{doc_id}",
            "source_doc_id": doc_id,
            "source_title": _source_title(doc_id),
            "node_names": [
                names.get(node_id) or _fallback_name(node_id)
                for node_id in node_ids
            ],
            "status": "partial",
            "reason": "",
            "segments": [],
            # 内部字段：供 validate_alternative() 复核，不进入渲染契约。
            "node_ids": list(node_ids),
            "scenic_area": scenic_area,
        }
        status, segments, reasons = validate_alternative(
            alt, candidates=[candidate]
        )
        alt["status"] = status
        alt["reason"] = " ".join(reasons) if reasons else (
            f"共 {len(segments)} 段，均由 {doc_id} 的 NEXT 连接逐段支持。"
        )
        alt["segments"] = segments
        alternatives.append(alt)

    alternatives.sort(key=_sort_key)

    selected = []
    seen_sets = {primary_set} if primary_set else set()
    for alt in alternatives:
        node_set = frozenset(alt["node_ids"])
        if node_set in seen_sets:
            continue
        seen_sets.add(node_set)
        selected.append(alt)
        if len(selected) >= max_alts:
            break
    return selected
