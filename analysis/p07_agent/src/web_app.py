"""P7 Web 入口：访客 / 评审双视图（T3.2）。

职责边界
--------
本模块只做**路由、状态归一与渲染**：

- 状态仍由 ``agent.run_agent()`` 判定，这里只调用 ``status.normalize_status()``
  把缺失/未定义值收敛成 ``error``（PRODUCT_SPEC §5.4），不参与任何业务判定；
- 访客视图（``result.html``）不渲染 intent / trace / 工具决策 / 图谱指标；
  这些只出现在评审视图（``auditor.html``）；
- 模板与静态文件用绝对路径注册，避免工作目录变化导致找不到文件。

启动时从三个景区的 ``*_guides.csv`` 行数统计文档数（T1.5 后为 32 篇），
不再在模板里硬编码篇数。
"""

import csv
import json
import os
from pathlib import Path

from flask import Flask, render_template, render_template_string, request, session

from agent import run_agent
from status import is_contract_violation, normalize_status

BASE_DIR = Path(__file__).resolve().parents[1]      # analysis/p07_agent
REPO_ROOT = BASE_DIR.parents[1]                      # 仓库根
GUIDES_GLOB = "scenic/*/data/processed/*_guides.csv"

VIEWS = ("visitor", "auditor")
DEFAULT_VIEW = "visitor"

#: 访客视图首页的 3 个示例；用 GET 链接回填输入框，不依赖 JS。
EXAMPLES = (
    {"label": "长隆亲子一日", "query": "带孩子去长隆玩一天，游玩为主，少走路"},
    {"label": "白云山老人一日", "query": "陪父母去白云山玩一天，想少爬坡，节奏慢一点"},
    {"label": "武功山两日", "query": "和朋友去武功山玩两天，喜欢自然风景和拍照"},
)

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "web" / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.secret_key = os.urandom(32)


def _count_documents():
    """按三个景区 guides CSV 的数据行数统计已采集文档数（不硬编码篇数）。"""
    total = 0
    for path in sorted(REPO_ROOT.glob(GUIDES_GLOB)):
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    if (row.get("doc_id") or "").strip():
                        total += 1
        except OSError:
            continue
    return total


DOC_COUNT = _count_documents()


@app.context_processor
def inject_globals():
    """所有模板都可用的全局值：覆盖篇数由启动时统计。"""
    return {"doc_count": DOC_COUNT}


def _resolve_view():
    """视图白名单：只认 visitor / auditor，其他值一律回退访客视图。"""
    raw = request.form.get("view") or request.args.get("view") or DEFAULT_VIEW
    view = str(raw).strip().lower()
    return view if view in VIEWS else DEFAULT_VIEW


def _safe_text(value):
    return str(value).strip() if value is not None else ""


def _normalize_reasons(raw):
    """只保留 ``{"code", "text"}`` 形状的原因；未知形状丢弃，不渲染原始对象。"""
    reasons = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        text = _safe_text(item.get("text"))
        if not text:
            continue
        reasons.append({"code": _safe_text(item.get("code")), "text": text})
    return reasons


def _normalize_alternatives(raw):
    """把备选路线整理成模板契约（T2.4 预留）。

    契约（每项）::

        {alt_id, source_doc_id, source_title, node_names: [str],
         status: "verified"|"partial", reason: str,
         segments: [{from_name, to_name, source_doc_ids: [str]}]}

    未传 / 空列表时返回 ``[]``，模板整块不渲染，不做假数据占位。
    """
    alternatives = []
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        segments = []
        for segment in item.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            doc_ids = segment.get("source_doc_ids") or []
            if isinstance(doc_ids, str):
                doc_ids = [doc_ids]
            segments.append({
                "from_name": _safe_text(segment.get("from_name")),
                "to_name": _safe_text(segment.get("to_name")),
                "source_doc_ids": [_safe_text(doc_id) for doc_id in doc_ids if _safe_text(doc_id)],
            })
        node_names = item.get("node_names") or []
        if isinstance(node_names, str):
            node_names = [node_names]
        alternatives.append({
            "alt_id": _safe_text(item.get("alt_id")) or f"alt-{index + 1}",
            "source_doc_id": _safe_text(item.get("source_doc_id")),
            "source_title": _safe_text(item.get("source_title")),
            "node_names": [_safe_text(name) for name in node_names if _safe_text(name)],
            "status": normalize_status(item.get("status")),
            "reason": _safe_text(item.get("reason")),
            "segments": segments,
        })
    return alternatives


def _status_note(status, contract_violation, result):
    """给访客看的一句状态说明；不泄露原始异常/未知状态值。"""
    if contract_violation:
        return "后端没有返回合法的状态值，本次已按处理失败展示。"
    if status == "error":
        message = _safe_text(result.get("message"))
        return message or "本次处理失败，请稍后重试。"
    return ""


def _build_context(result, view, query, selected_alt=""):
    """把 ``run_agent`` 返回值整理成模板上下文；只归一，不改判定。"""
    result = result if isinstance(result, dict) else {}
    raw_status = result.get("status")
    contract_violation = is_contract_violation(raw_status)
    status = normalize_status(raw_status)

    reasons = _normalize_reasons(result.get("reasons"))
    if status == "verified":
        # 契约要求 verified 的原因清单为空；后端已保证，这里再兜一层。
        reasons = []

    intent = result.get("intent")
    intent_json = ""
    if intent is not None:
        try:
            intent_json = json.dumps(intent, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            intent_json = ""

    trace_file = _safe_text(result.get("trace_file"))
    return {
        "view": view,
        "query": _safe_text(result.get("query")) or _safe_text(query),
        "status": status,
        "contract_violation": contract_violation,
        "status_note": _status_note(status, contract_violation, result),
        "reasons": reasons,
        "what_verified": result.get("what_verified"),
        "intent_json": intent_json,
        "decision": result.get("decision"),
        "tool_selection": result.get("tool_selection"),
        "tool_decisions": result.get("tool_decisions") or [],
        "route": result.get("route"),
        "itinerary": result.get("itinerary"),
        "suggestions": result.get("suggestions") or [],
        "poi_results": result.get("poi_results"),
        "poi_list_all": bool(result.get("poi_list_all")),
        "message": _safe_text(result.get("message")),
        "error": _safe_text(result.get("error")),
        "trace_file": trace_file,
        "trace_file_name": os.path.basename(trace_file) if trace_file else "",
        "trace_json": _safe_text(result.get("trace_json")),
        "trace_error": _safe_text(result.get("trace_error")),
        "alternatives": _normalize_alternatives(result.get("alternatives")),
        "selected_alt": _safe_text(selected_alt),
    }


def _render_result(result, view, query, selected_alt=""):
    """渲染结果页；模板异常时返回 error 页而不是 500。"""
    context = _build_context(result, view, query, selected_alt)
    template = "auditor.html" if view == "auditor" else "result.html"
    try:
        return render_template(template, **context)
    except Exception:  # 模板错误不能把访客留在 500 白屏上
        return _render_failure_page()


def _render_failure_page():
    """最后的兜底 error 页：纯服务端 HTML，不依赖可能出错的子模板。"""
    page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>处理失败 · 可核验的景区行程助手</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <div class="page">
    <header class="site-header"><div class="wrap site-header__inner"><div>
      <h1 class="site-title">可核验的景区行程助手</h1>
    </div></div></header>
    <main id="main-content" class="wrap">
      <div class="status-area">
        <p class="status-badge status-badge--error" data-status="error">
          <span class="status-badge__icon" aria-hidden="true">❌</span>
          <span class="status-badge__text"><span class="visually-hidden">状态：</span>处理失败</span>
        </p>
        <p class="status-badge__desc">这次没有生成行程，下面的内容都不是规划结果。</p>
        <p>页面渲染失败，请返回首页重试；如果反复出现，请把这次查询告诉维护者。</p>
        <p><a href="{{ url_for('home') }}">返回首页</a></p>
      </div>
    </main>
  </div>
</body>
</html>
"""
    return render_template_string(page)


def _run_agent_safely(query):
    """调用一次 ``run_agent``；异常兜成 error 结果，不让路由抛 500。"""
    try:
        return run_agent(query)
    except Exception as exc:
        return {
            "query": query,
            "status": "error",
            "message": "服务暂时不可用，请稍后重试。",
            "error": str(exc),
            "reasons": [{
                "code": "model_error",
                "text": "服务暂时不可用，本次没有生成行程。",
            }],
        }


@app.route("/", methods=["GET", "POST"])
def home():
    view = _resolve_view()

    if request.method == "GET":
        return render_template(
            "index.html",
            view=view,
            query=_safe_text(request.args.get("query")),
            examples=EXAMPLES,
        )

    if request.form.get("action") == "reset":
        session.pop("pending_query", None)
        return render_template(
            "index.html",
            view=view,
            query="",
            examples=EXAMPLES,
            notice="已开始新需求。",
        )

    new_query = _safe_text(request.form.get("query"))
    previous = session.get("pending_query", "")
    if previous and new_query.startswith(previous):
        query = new_query
    elif previous and new_query:
        query = previous + "\n" + new_query
    else:
        query = new_query

    if not query:
        return render_template(
            "index.html",
            view=view,
            query="",
            examples=EXAMPLES,
            notice="请输入旅行需求。",
        )

    result = _run_agent_safely(query)
    if isinstance(result, dict) and result.get("needs_followup"):
        session["pending_query"] = query
    else:
        session.pop("pending_query", None)

    return _render_result(result, view, query, request.args.get("alt", ""))


if __name__ == "__main__":
    app.run(debug=True)
