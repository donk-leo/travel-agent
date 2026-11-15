"""证据服务：把图谱节点/边的 ``source_doc_ids`` 还原成可点回原文的证据卡。

职责与边界
----------
- 只读项目 1 的 ``scenic/<area>/data/processed/<area>_guides.csv``（32 篇，
  ``clean_content`` 为冻结文本）与项目 6 的 ``graph_nodes.csv`` / ``graph_edges.csv``；
  不写文件、不联网、不调用模型、不装包；
- 只做确定性查找：同一个输入永远得到同一个结果；CSV 只读一次并缓存在模块级变量里；
- 不改写、不截断、不重排 ``clean_content``。``quote`` 的 ``char_start`` / ``char_end``
  是 ``clean_content`` 上的原始字符位置（起点 0 计，结束位置不含），并且始终满足
  ``text == clean_content[char_start:char_end]``；
- 查不到就返回 ``None`` / ``found=False``，**绝不补写** URL、日期或摘句。
  数据缺口如实暴露给 ``scan_coverage()``，不在本模块里“修数据”。

导入方式
--------
项目内测试直接 ``import evidence``（``tests`` 会把 ``src`` 加进 ``sys.path``），
命令行复核则用 ``from analysis.p07_agent.src import evidence``。为让两种方式都复用
``tools.load_graph()`` 的读图实现（与 Agent 看到的是同一份图），模块导入时把自身所在
的 ``src`` 目录放进 ``sys.path``，再 ``import tools``。

接口
----
``doc_meta(doc_id)``
    文档元数据；不存在 / 空 ``doc_id`` → ``None``。
``quote_for(doc_id, node_id=None, span=None)``
    按显式 span 或节点名首次出现取原文片段；越界 / 找不到 → ``None``。
``segment_evidence(segment)``
    为一段路线（``from_name`` / ``to_name`` / ``source_doc_ids``）生成证据卡；
    摘句缺失时卡片保留，``quote=None`` 且 ``found=False``。
``scan_coverage()``
    对全部节点 / 边的 ``source_doc_ids`` 逐条解析，供测试与父 Agent 复核覆盖率。
"""

import csv
import sys
from pathlib import Path

# 兼容 ``import evidence``（src 在 sys.path）与 ``from analysis.p07_agent.src import evidence``：
# 后者不会把 src 放进 sys.path，而 tools.py 依赖同目录的 scenic_aliases 模块。
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tools import load_graph  # noqa: E402  （必须在上面的 sys.path 调整之后导入）


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENIC_DIR = PROJECT_ROOT / "scenic"

#: 项目 1 已交付的三个景区（目录名与 ``<area>_guides.csv`` 前缀一致）。
AREAS = ("baiyunshan", "changlong", "wugongshan")

# 模块级缓存：doc_id -> CSV 行；图谱行与 node_id -> 行。只读，调用方不得修改。
_DOCS = None
_NODES = None
_EDGES = None
_NODES_BY_ID = None

#: ``scan_coverage()`` 的 ``missing_examples`` 最多列出的条数。
MISSING_EXAMPLE_LIMIT = 10


def _guides_path(area):
    return SCENIC_DIR / area / "data" / "processed" / f"{area}_guides.csv"


def _load_docs():
    """读入 32 篇攻略并建 ``doc_id -> row`` 索引（首次调用后缓存）。

    ``clean_content`` 按 CSV 原值保存，不 strip、不做换行归一，否则字符位置会整体错位。
    """
    global _DOCS
    if _DOCS is None:
        docs = {}
        for area in AREAS:
            with _guides_path(area).open(encoding="utf-8-sig", newline="") as file:
                for row in csv.DictReader(file):
                    docs[row["doc_id"]] = row
        _DOCS = docs
    return _DOCS


def _graph():
    """复用 ``tools.load_graph()`` 读图，并缓存 ``node_id -> node`` 索引。"""
    global _NODES, _EDGES, _NODES_BY_ID
    if _NODES is None:
        _NODES, _EDGES = load_graph()
        _NODES_BY_ID = {node["node_id"]: node for node in _NODES}
    return _NODES, _EDGES


def _doc_id(value):
    """把 doc_id 收敛成可查找的字符串；None / 非字符串 / 空白 → ``""``。"""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _doc_row(doc_id):
    """按 doc_id 取 CSV 行；不存在或空 doc_id 返回 ``None``。"""
    key = _doc_id(doc_id)
    if not key:
        return None
    return _load_docs().get(key)


def _node_row(node_id):
    """按 node_id 取图谱节点行；不存在或空 node_id 返回 ``None``。"""
    key = _doc_id(node_id)
    if not key:
        return None
    nodes, _ = _graph()
    return _NODES_BY_ID.get(key)


def _content(row):
    """取一篇文档的冻结正文；缺失时按空串处理（不 strip）。"""
    return row.get("clean_content") or ""


def _is_true(value):
    """CSV 里的布尔列是字符串（``True`` / ``False``），这里按项目惯例解析。"""
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _split_doc_ids(value):
    """把图谱里的 ``A;B;C`` 拆成 doc_id 列表；空段丢弃。"""
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def _checked_span(span, length):
    """校验 ``(start, end)``：两个整数、``0 <= start < end <= len(content)``。

    不合法返回 ``None``；合法返回 ``(start, end)``。``bool`` 虽然继承 ``int``，
    但不是合法的字符位置，按非法处理。
    """
    if not isinstance(span, (tuple, list)) or len(span) != 2:
        return None
    start, end = span
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if start < 0 or end <= start or end > length:
        return None
    return start, end


def _quote(row, start, end):
    """用已校验的位置构造 quote；``text`` 永远取自原文切片，不另行拼写。"""
    return {
        "text": _content(row)[start:end],
        "char_start": start,
        "char_end": end,
        "doc_id": row["doc_id"],
    }


def _quote_by_name(doc_id, name):
    """按名称在文档正文里找**首次**出现，返回 quote；找不到返回 ``None``。

    名称必须是原文里的连续子串（不做别名、繁简、异体字替换），这样
    ``char_start`` / ``char_end`` 才能原样指回 ``clean_content``。
    """
    row = _doc_row(doc_id)
    if row is None or not isinstance(name, str) or not name:
        return None
    start = _content(row).find(name)
    if start < 0:
        return None
    return _quote(row, start, start + len(name))


def doc_meta(doc_id):
    """返回文档元数据；``doc_id`` 不存在 / 为空 / 非字符串时返回 ``None``。

    返回字段：``doc_id, title, source_url, publish_date, source_site, doc_type,
    scenic_area, is_valid, clean_chars``。字段值取自项目 1 的 CSV 原值（``is_valid``
    由字符串解析为布尔，``clean_chars`` 为 ``len(clean_content)``），不补写缺失的
    URL 或日期——原始数据写的是「未知」就返回「未知」。
    """
    row = _doc_row(doc_id)
    if row is None:
        return None
    return {
        "doc_id": row["doc_id"],
        "title": row.get("title", ""),
        "source_url": row.get("source_url", ""),
        "publish_date": row.get("publish_date", ""),
        "source_site": row.get("source_site", ""),
        "doc_type": row.get("doc_type", ""),
        "scenic_area": row.get("scenic_area", ""),
        "is_valid": _is_true(row.get("is_valid")),
        "clean_chars": len(_content(row)),
    }


def quote_for(doc_id, node_id=None, span=None):
    """取一段可核验的原文摘句。

    - ``span=(start, end)``：校验 ``0 <= start < end <= len(clean_content)``，
      合法则返回 ``clean_content[start:end]``；越界、负数、``start >= end``、
      非整数或长度不足 2 的一律返回 ``None``；
    - ``node_id``：用 ``graph_nodes.csv`` 里该节点的 ``name`` 原文在正文中查找
      **首次出现**，返回该处的 span；节点不存在 / 名称不在正文里返回 ``None``；
    - 两者都传时以 ``span`` 为准（显式位置优先）；两者都不传返回 ``None``。

    返回 ``{text, char_start, char_end, doc_id}``，其中
    ``text == clean_content[char_start:char_end]``。文档不存在直接返回 ``None``。
    """
    row = _doc_row(doc_id)
    if row is None:
        return None

    if span is not None:
        bounds = _checked_span(span, len(_content(row)))
        if bounds is None:
            return None
        return _quote(row, bounds[0], bounds[1])

    if node_id is not None:
        node = _node_row(node_id)
        if node is None:
            return None
        return _quote_by_name(doc_id, node.get("name") or "")

    return None


def segment_evidence(segment):
    """为一段路线生成证据卡列表（顺序与 ``source_doc_ids`` 一致）。

    ``segment`` 形如 ``{"from_name": ..., "to_name": ..., "source_doc_ids": [...]}``
    （见 ``tools.validate_route()`` 的 ``validation.segments``）。每个能在项目 1
    CSV 里找到的 doc_id 返回一张卡::

        {doc_id, title, source_url, publish_date, source_site, quote, found}

    摘句先按 ``from_name`` 在正文里找首次出现，找不到再试 ``to_name``；两者都
    找不到时卡片仍然保留，``quote=None`` 且 ``found=False``，让 UI 能显示
    “未找到来源”，而不是把这段证据整条藏起来。空 segment、无 ``source_doc_ids``、
    或 doc_id 不在 CSV 里（无法给出标题/URL）时不产出卡片。
    """
    if not isinstance(segment, dict):
        return []

    raw_doc_ids = segment.get("source_doc_ids") or []
    if isinstance(raw_doc_ids, str):
        raw_doc_ids = [raw_doc_ids]
    if not isinstance(raw_doc_ids, (list, tuple)):
        return []

    names = [
        name for name in (segment.get("from_name"), segment.get("to_name"))
        if isinstance(name, str) and name
    ]

    cards = []
    seen = set()
    for value in raw_doc_ids:
        doc_id = _doc_id(value)
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)

        row = _doc_row(doc_id)
        if row is None:
            continue

        quote = None
        for name in names:
            quote = _quote_by_name(doc_id, name)
            if quote is not None:
                break

        cards.append({
            "doc_id": row["doc_id"],
            "title": row.get("title", ""),
            "source_url": row.get("source_url", ""),
            "publish_date": row.get("publish_date", ""),
            "source_site": row.get("source_site", ""),
            "quote": quote,
            "found": quote is not None,
        })
    return cards


def scan_coverage():
    """全量扫描节点与边的 ``source_doc_ids``，统计证据可达性。

    计数单位是**每条引用**（一个节点 × 一篇来源文档、一条边 × 一篇来源文档），
    不是节点/边本身的条数；``nodes`` / ``edges`` 才是行数。返回::

        {
          "nodes": 247,                  # graph_nodes.csv 行数
          "node_doc_refs": 535,          # 节点来源引用总数
          "nodes_missing_meta": 0,       # 引用里找不到文档元数据的条数
          "nodes_missing_quote": 31,     # 引用里节点名不在正文中的条数
          "edges": 577,
          "edge_doc_refs": 852,
          "edges_missing_meta": 0,
          "edges_missing_quote": 5,      # 两端名称都不在正文中的条数
          "nodes_without_source": 0,     # source_doc_ids 为空的节点
          "edges_without_source": 7,     # source_doc_ids 为空的边
          "missing_examples": [...],     # 前 10 条缺口，供定位
        }

    边的摘句取 ``src`` / ``dst`` 任一端的节点名首次出现；两端都找不到才算
    ``edges_missing_quote``。``source_doc_ids`` 为空的边（当前 7 条 ``SIMILAR_TO``，
    由项目 6 后处理生成、本来就没有来源）不计入 ``missing_meta`` / ``missing_quote``，
    而是记在 ``edges_without_source`` 并在 ``missing_examples`` 里标
    ``reason="no_source"``，避免把“没有来源”误算成“来源无法解析”。
    """
    nodes, edges = _graph()
    docs = _load_docs()

    nodes_missing_meta = 0
    nodes_missing_quote = 0
    node_doc_refs = 0
    nodes_without_source = 0
    edges_missing_meta = 0
    edges_missing_quote = 0
    edge_doc_refs = 0
    edges_without_source = 0
    examples = []

    def note(kind, identifier, doc_id, reason):
        if len(examples) < MISSING_EXAMPLE_LIMIT:
            examples.append({
                "kind": kind,
                "id": identifier,
                "doc_id": doc_id,
                "reason": reason,
            })

    for node in nodes:
        doc_ids = _split_doc_ids(node.get("source_doc_ids"))
        if not doc_ids:
            nodes_without_source += 1
            note("node", node["node_id"], "", "no_source")
            continue
        for doc_id in doc_ids:
            node_doc_refs += 1
            if doc_id not in docs:
                nodes_missing_meta += 1
                note("node", node["node_id"], doc_id, "missing_meta")
                continue
            if _quote_by_name(doc_id, node.get("name") or "") is None:
                nodes_missing_quote += 1
                note("node", node["node_id"], doc_id, "missing_quote")

    for edge in edges:
        doc_ids = _split_doc_ids(edge.get("source_doc_ids"))
        if not doc_ids:
            edges_without_source += 1
            note(
                "edge",
                f"{edge['src']} -[{edge['rel']}]-> {edge['dst']}",
                "",
                "no_source",
            )
            continue

        names = [
            (_NODES_BY_ID.get(edge["src"]) or {}).get("name") or "",
            (_NODES_BY_ID.get(edge["dst"]) or {}).get("name") or "",
        ]
        names = [name for name in names if name]

        for doc_id in doc_ids:
            edge_doc_refs += 1
            if doc_id not in docs:
                edges_missing_meta += 1
                note(
                    "edge",
                    f"{edge['src']} -[{edge['rel']}]-> {edge['dst']}",
                    doc_id,
                    "missing_meta",
                )
                continue
            if not any(_quote_by_name(doc_id, name) for name in names):
                edges_missing_quote += 1
                note(
                    "edge",
                    f"{edge['src']} -[{edge['rel']}]-> {edge['dst']}",
                    doc_id,
                    "missing_quote",
                )

    return {
        "nodes": len(nodes),
        "node_doc_refs": node_doc_refs,
        "nodes_missing_meta": nodes_missing_meta,
        "nodes_missing_quote": nodes_missing_quote,
        "edges": len(edges),
        "edge_doc_refs": edge_doc_refs,
        "edges_missing_meta": edges_missing_meta,
        "edges_missing_quote": edges_missing_quote,
        "nodes_without_source": nodes_without_source,
        "edges_without_source": edges_without_source,
        "missing_examples": examples,
    }
