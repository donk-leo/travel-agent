"""P7 Web 入口：访客 / 评审双视图（T3.2）+ 证据卡接线（T3.4）+ 任务化进度（T3.7）。

职责边界
--------
本模块只做**路由、状态归一、任务接线与渲染**：

- 状态仍由 ``agent.run_agent()`` 判定，这里只调用 ``status.normalize_status()``
  把缺失/未定义值收敛成 ``error``（PRODUCT_SPEC §5.4），不参与任何业务判定；
- 访客视图（``result.html``）不渲染 intent / trace / 工具决策 / 图谱指标；
  这些只出现在评审视图（``auditor.html``）；
- 模板与静态文件用绝对路径注册，避免工作目录变化导致找不到文件；
- 证据卡（T3.4）只**只读复用** ``evidence`` 模块（T1.6）：节点来源取
  ``graph_nodes.csv`` 的 ``source_doc_ids`` 前 2 篇，摘句一律由
  ``quote_sentence_for()`` / ``segment_evidence()`` 返回的原文切片，
  本模块不读 guides CSV、不拼句子、不补 URL/日期；任何异常都降级成空卡，
  由模板显示「未找到来源」，不让页面 500；
- T3.7 提交改成**进程内任务**：POST 建 job + 起 daemon 线程后立刻 303 到
  ``/run/<job_id>``，进度页四个阶段的状态全部来自 ``run_agent(progress=...)``
  的真实回调（按 stage 合并，不伪造完成）；进度 JSON 只暴露阶段状态，
  结果仍走原 ``_store_result`` 缓存，``?view=auditor`` / ``?alt=`` 行为不变。

启动时从三个景区的 ``*_guides.csv`` 行数统计文档数（T1.5 后为 32 篇），
不再在模板里硬编码篇数。
"""

import csv
import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path

from flask import (
    Flask, g, got_request_exception, jsonify, redirect, render_template,
    render_template_string, request, session, url_for,
)

import evidence
import observability
import security
import tools
from agent import run_agent
from status import is_contract_violation, normalize_status

BASE_DIR = Path(__file__).resolve().parents[1]      # analysis/p07_agent
REPO_ROOT = BASE_DIR.parents[1]                      # 仓库根
GUIDES_GLOB = "scenic/*/data/processed/*_guides.csv"

VIEWS = ("visitor", "auditor")
DEFAULT_VIEW = "visitor"

#: T5.2：默认只绑定回环地址；不要改成对外监听地址（部署建议见 SECURITY.md）。
DEFAULT_HOST = security.DEFAULT_HOST
DEFAULT_PORT = security.DEFAULT_PORT

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
# T5.2：会话 cookie 只走 HttpOnly + SameSite=Lax，30 分钟过期。
# secret_key 为进程内随机值（重启/多进程会换），本机单用户可接受；
# 不要让浏览器在 HTTPS 之外携带 Secure cookie，因此这里不设 SESSION_COOKIE_SECURE。
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)

#: 与 security 共享同一个限流器实例；测试通过下面的钩子配置/清空。
RATE_LIMITER = security.RATE_LIMITER


def _configure_rate_limit(limit=None, window_seconds=None):
    """配置昂贵 POST 限流（测试/部署脚本用）；``None`` 恢复默认值。"""
    security.configure_rate_limit(limit=limit, window_seconds=window_seconds)


def _reset_rate_limiter():
    """清空限流计数（测试隔离用，不改变当前限额）。"""
    security.reset_rate_limiter()

# T5.1：日志默认写仓库外；配置失败只静默降级，不影响 Web 启动。
observability.configure_logging()


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

#: 进程内结果缓存（T3.2 补丁）：让 GET 的视图切换 / 备选高亮复用上次结果。
#: - 只存在内存，不写盘、不进 session/cookie；
#: - 最多 8 条，超出按 LRU 淘汰；每条 TTL 30 分钟；
#: - key 为 strip 后的 query，重启进程即清空。
RESULT_CACHE_MAX = 8
RESULT_CACHE_TTL_SECONDS = 30 * 60
_RESULT_CACHE = OrderedDict()
_RESULT_CACHE_LOCK = threading.RLock()


def _cache_key(query):
    return _safe_text(query)


def _store_result(query, result):
    """把一次 POST 的返回值放进进程内 LRU 缓存；非 dict / 空 query 不存。"""
    key = _cache_key(query)
    if not key or not isinstance(result, dict):
        return
    now = time.monotonic()
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE.pop(key, None)
        _RESULT_CACHE[key] = (now, result)
        while len(_RESULT_CACHE) > RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)


def _get_cached_result(query):
    """取缓存结果；过期删除、命中移到队尾（LRU）。未命中返回 ``None``。"""
    key = _cache_key(query)
    if not key:
        return None
    now = time.monotonic()
    with _RESULT_CACHE_LOCK:
        item = _RESULT_CACHE.get(key)
        if item is None:
            return None
        stored_at, result = item
        if now - stored_at > RESULT_CACHE_TTL_SECONDS:
            _RESULT_CACHE.pop(key, None)
            return None
        _RESULT_CACHE.move_to_end(key)
        return result


def _cache_size():
    """当前缓存条数（测试与诊断用，不暴露给页面）。"""
    with _RESULT_CACHE_LOCK:
        return len(_RESULT_CACHE)


def _clear_result_cache():
    """清空缓存（测试用；页面不提供清空入口）。"""
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE.clear()


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


# ---------------------------------------------------------------------------
# T3.7 任务化提交：进程内 JobStore + 后台线程 + 进度事件
#
# 边界：
# - 只保存本进程内的一次请求状态，不落盘、不进 cookie；
# - 线程只调用 ``run_agent(query, progress=...)``，进度来自后端真实回调，
#   前端不推断、不伪造阶段完成；
# - 回调异常一律吞掉，绝不影响 ``run_agent`` 主流程。
# ---------------------------------------------------------------------------

#: 四阶段固定顺序（与 ``agent.PROGRESS_LABELS`` 同名，但不从 agent 导入：
#: 页面只认这四个阶段，未知阶段只按「等待」渲染，不伪造完成）。
PROGRESS_STAGES = (
    ("intent", "解析需求"),
    ("tools", "查询图谱"),
    ("route", "规划路线"),
    ("verify", "核验行程"),
)
PROGRESS_STAGE_LABELS = dict(PROGRESS_STAGES)
PROGRESS_STATE_TEXT = {"waiting": "等待", "active": "进行中", "done": "已完成"}
PROGRESS_STATE_ICONS = {"waiting": "○", "active": "▶", "done": "✔"}

JOB_TTL_SECONDS = 30 * 60
JOB_MAX_ENTRIES = 16

#: job_id -> 任务字典；``OrderedDict`` 用于按创建顺序淘汰最旧任务。
_JOBS = OrderedDict()
_JOBS_LOCK = threading.RLock()


def _job_elapsed_ms(job):
    """任务已用毫秒；完成后冻结在 ``finished_mono``，不随页面刷新继续增长。"""
    started = job.get("started_mono")
    if not isinstance(started, (int, float)):
        return 0
    finished = job.get("finished_mono")
    end = finished if isinstance(finished, (int, float)) else time.monotonic()
    return max(int((end - started) * 1000), 0)


def _purge_jobs_locked(now=None):
    """TTL 过期清理 + 超过上限时淘汰最旧任务；调用方必须持有 ``_JOBS_LOCK``。"""
    now = time.time() if now is None else now
    expired = [
        job_id for job_id, job in _JOBS.items()
        if now - job.get("created_at", now) > JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _JOBS.pop(job_id, None)
    while len(_JOBS) > JOB_MAX_ENTRIES:
        _JOBS.popitem(last=False)


def _create_job(query, view):
    """新建任务（``status=pending``）并返回 ``job_id``；不启动线程。"""
    job_id = uuid.uuid4().hex
    now = time.time()
    safe_query = _safe_text(query)
    query_sha256_12, query_len = observability.query_fingerprint(safe_query)
    with _JOBS_LOCK:
        _purge_jobs_locked(now)
        while len(_JOBS) >= JOB_MAX_ENTRIES:
            _JOBS.popitem(last=False)
        _JOBS[job_id] = {
            "job_id": job_id,
            "request_id": observability.get_request_id() or observability.new_request_id(),
            "query": safe_query,
            "query_sha256_12": query_sha256_12,
            "query_len": query_len,
            "view": view,
            "status": "pending",
            "stages": [],
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "started_mono": time.monotonic(),
            "finished_at": None,
            "finished_mono": None,
        }
    return job_id


def _job_get(job_id):
    """取任务快照（深拷贝阶段事件）；不存在或已过期返回 ``None``。"""
    key = _safe_text(job_id)
    if not key:
        return None
    with _JOBS_LOCK:
        _purge_jobs_locked()
        job = _JOBS.get(key)
        if job is None:
            return None
        snapshot = dict(job)
        snapshot["stages"] = [dict(event) for event in job.get("stages") or []]
    return snapshot


def _job_append_event(job_id, event):
    """追加一条真实进度事件；任何异常都吞掉（进度只是旁路数据面）。"""
    try:
        if not isinstance(event, dict):
            return
        stage = _safe_text(event.get("stage"))
        try:
            elapsed_ms = max(int(event.get("elapsed_ms") or 0), 0)
        except (TypeError, ValueError):
            elapsed_ms = 0
        entry = {
            "stage": stage,
            "label": _safe_text(event.get("label")) or PROGRESS_STAGE_LABELS.get(stage, ""),
            "status": _safe_text(event.get("status")),
            "elapsed_ms": elapsed_ms,
            "server_ts": time.time(),
        }
        with _JOBS_LOCK:
            job = _JOBS.get(_safe_text(job_id))
            if job is None or job.get("status") in ("done", "error"):
                return
            job["stages"].append(entry)
            job["status"] = "running"
            job["updated_at"] = entry["server_ts"]
    except Exception:  # noqa: BLE001 - 进度失败不得影响主流程
        pass


def _job_finish(job_id, result, error=None):
    """写入最终结果并标记 ``done`` / ``error``；状态只做归一，不改判定。"""
    with _JOBS_LOCK:
        job = _JOBS.get(_safe_text(job_id))
        if job is None:
            return
        payload = result if isinstance(result, dict) else {}
        job["result"] = payload
        job["error"] = _safe_text(error) or None
        job["status"] = (
            "error" if normalize_status(payload.get("status")) == "error" else "done"
        )
        now = time.time()
        job["updated_at"] = now
        job["finished_at"] = now
        job["finished_mono"] = time.monotonic()


def _job_mark_running(job_id):
    """线程启动后立刻标记 ``running``（首个事件通常也在 0ms 内到达）。"""
    with _JOBS_LOCK:
        job = _JOBS.get(_safe_text(job_id))
        if job is not None and job.get("status") == "pending":
            job["status"] = "running"
            job["updated_at"] = time.time()


def _job_error_text(job):
    """错误页/JSON 用的人话原因；不把原始异常文本暴露给访客。"""
    result = job.get("result") if isinstance(job, dict) else None
    result = result if isinstance(result, dict) else {}
    return (
        _safe_text(result.get("message"))
        or _safe_text(job.get("error") if isinstance(job, dict) else "")
        or "本次处理失败，请稍后重试。"
    )


def _merge_stages(job):
    """把真实事件按 stage 合并成固定四阶段（verify 重复出现也只渲染一次）。

    - 任一事件 ``status=done`` → 该阶段「已完成」；
    - 有 start 但无 done → 「进行中」（不假设阶段唯一、不伪造完成）；
    - 没有任何事件 → 「等待」；
    - 时间取该阶段最新事件的 ``elapsed_ms``（任务开始以来的累计毫秒），
      进行中的阶段按当前累计时间向上取整；
    - **按文档顺序点亮**：前序阶段未完成时，后序阶段保持「等待」。T2.7 的
      ``verify`` 会在解析需求后先做一次需求预检、之后规划路线完再重复出现；
      这里只推迟显示，不提前把「核验行程」标成完成（也不伪造任何阶段）。
    """
    events = job.get("stages") if isinstance(job, dict) else []
    by_stage = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        stage = _safe_text(event.get("stage"))
        if stage not in PROGRESS_STAGE_LABELS:
            continue
        by_stage.setdefault(stage, []).append(event)

    running = job.get("status") in ("pending", "running") if isinstance(job, dict) else False
    now_ms = _job_elapsed_ms(job if isinstance(job, dict) else {})
    current_ts = None
    current_stage = None
    prefix_done = True
    merged = []
    for stage, label in PROGRESS_STAGES:
        seq = by_stage.get(stage) or []
        done = any(_safe_text(event.get("status")) == "done" for event in seq)
        started = bool(seq)
        if prefix_done:
            state = "done" if done else ("active" if started and running else "waiting")
        else:
            # 前序阶段还没完成：后序事件（如 verify 的需求预检）不提前点亮。
            state = "waiting"
        elapsed_ms = max(
            (int(event.get("elapsed_ms") or 0) for event in seq), default=0
        )
        if state == "done":
            elapsed_ms = max(int(elapsed_ms), 0)
        elif state == "active":
            elapsed_ms = max(int(elapsed_ms), now_ms)
            latest_ts = max(
                (event.get("server_ts") or 0 for event in seq), default=0
            )
            if current_ts is None or latest_ts >= current_ts:
                current_ts = latest_ts
                current_stage = stage
        else:
            # 等待中的阶段不显示秒数：没有到达就不编造已用时间。
            elapsed_ms = 0
        if state != "done":
            prefix_done = False
        merged.append({
            "stage": stage,
            "label": label,
            "state": state,
            "state_text": PROGRESS_STATE_TEXT[state],
            "icon": PROGRESS_STATE_ICONS[state],
            "elapsed_ms": max(int(elapsed_ms), 0),
            "elapsed_s": f"{max(int(elapsed_ms), 0) / 1000:.1f}",
            "is_current": False,
        })

    if current_stage:
        for item in merged:
            item["is_current"] = item["stage"] == current_stage
    return merged


def _job_current_label(job, stages):
    """当前阶段文案：真实进行中的阶段；没开始则「准备开始」。"""
    if not isinstance(job, dict):
        return "准备开始"
    if job.get("status") == "pending":
        return "准备开始"
    for item in stages:
        if item.get("state") == "active" and item.get("is_current"):
            return item["label"]
    return "准备开始"


def _job_public(job):
    """JSON 端点的白名单结构：只有阶段进度，不含 intent / trace / 路线明细。"""
    stages = _merge_stages(job)
    return {
        "status": job.get("status"),
        "stages": [
            {
                "stage": item["stage"],
                "label": item["label"],
                "status": item["state"],
                "elapsed_ms": item["elapsed_ms"],
            }
            for item in stages
        ],
        "elapsed_s": round(_job_elapsed_ms(job) / 1000, 1),
        "done": job.get("status") in ("done", "error"),
        "error": _job_error_text(job) if job.get("status") == "error" else None,
    }


def _run_job(job_id):
    """后台线程：真实调用 ``run_agent``，把回调事件写进任务，结束后落结果缓存。

    T5.1：线程进入时恢复创建任务时的 request-id，使 ``job_started`` /
    ``job_finished`` 与 POST 请求共用同一个 id；只记录耗时、状态、模型交互
    次数与错误类型，不记录 query 原文。
    """
    job = _job_get(job_id)
    if job is None:
        return
    job_id = _safe_text(job_id)
    request_id = observability.set_request_id(job.get("request_id"))
    started = time.monotonic()
    fingerprint = job.get("query_sha256_12")
    query_len = int(job.get("query_len") or 0)
    _job_mark_running(job_id)
    observability.log_event(
        "job_started", job_id=job_id, request_id=request_id,
        query_sha256_12=fingerprint, query_len=query_len,
    )
    query = job["query"]

    def progress(event):
        try:
            _job_append_event(job_id, event)
        except Exception:  # noqa: BLE001 - 回调异常不影响主流程
            pass

    def log_finished(status, result_status, model_calls,
                     error_type=None, error_code=None, known=True):
        observability.log_event(
            "job_finished", job_id=job_id, request_id=request_id,
            duration_ms=max(int((time.monotonic() - started) * 1000), 0),
            status=status, result_status=result_status,
            model_calls=int(model_calls), model_calls_known=known,
            error_type=error_type, error_code=error_code,
            query_sha256_12=fingerprint, query_len=query_len,
        )

    try:
        result = run_agent(query, progress=progress)
    except Exception as exc:  # noqa: BLE001 - 线程异常落成 error 页，不让页面 500
        result = _error_result(query, exc)
        # 先落缓存再标记完成，确保 GET 看到 done 时旧缓存路径已可命中。
        _store_result(query, result)
        _job_finish(job_id, result, error=str(exc))
        log_finished("error", "error", 0,
                     error_type=type(exc).__name__, known=False)
        return
    model_calls = observability.count_model_calls(
        result.get("trace_json") if isinstance(result, dict) else None
    )
    result_status = (
        normalize_status(result.get("status")) if isinstance(result, dict) else "error"
    )
    status = "error" if result_status == "error" else "done"
    error_type = None
    error_code = None
    if status == "error":
        error_type = "agent_error"
        reasons = result.get("reasons") if isinstance(result, dict) else None
        if isinstance(reasons, list) and reasons and isinstance(reasons[0], dict):
            error_code = _safe_text(reasons[0].get("code")) or None
    # 与旧同步流程一致：结果进进程内缓存，供 ?view=auditor / ?alt= 复用。
    _store_result(query, result)
    _job_finish(job_id, result)
    log_finished(
        status, result_status, model_calls,
        error_type=error_type, error_code=error_code,
        known=isinstance(result, dict) and "trace_json" in result,
    )


def _start_job(job_id):
    thread = threading.Thread(
        target=_run_job,
        args=(job_id,),
        name=f"p07-job-{str(job_id)[:8]}",
        daemon=True,
    )
    thread.start()
    return thread


def _clear_jobs():
    """清空任务表（测试用；页面不提供清空入口）。"""
    with _JOBS_LOCK:
        _JOBS.clear()


def _job_count():
    """当前任务数（测试用）。"""
    with _JOBS_LOCK:
        return len(_JOBS)


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


#: T3.4 每个停留点最多展示的来源文档数（按 graph_nodes.source_doc_ids 顺序取）。
POINT_EVIDENCE_DOCS = 2


def _card_from_meta(meta, quote):
    """把 ``doc_meta()`` 的元数据与摘句合成一张模板卡；不自造任何字段。

    ``quote`` 为 ``None`` 时卡片仍保留（``found=False``），由模板显示
    「未找到来源」，避免把“没有摘句”整条藏起来。
    """
    return {
        "doc_id": meta.get("doc_id", ""),
        "title": meta.get("title", ""),
        "source_url": meta.get("source_url", ""),
        "publish_date": meta.get("publish_date", ""),
        "source_site": meta.get("source_site", ""),
        "quote": quote,
        "found": bool(quote and quote.get("text")),
    }


def _build_point_evidence(route):
    """构建「每个停留点 → 最多 2 张证据卡」的映射；失败返回空字典。

    只读复用 T1.6 的 ``evidence`` 模块：节点行（``_node_row``，T1.6 未提供
    公开的节点访问器）、doc_id 拆分（``_split_doc_ids``）、文档元数据
    （``doc_meta``）与句级摘句（``quote_sentence_for(doc_id, node_id=...)``）
    全部来自该模块，本模块不读 guides CSV、不拼句子、不补日期或 URL。

    每个 ``node_id`` 都出现在返回字典里（没有卡就是空列表），模板据此在
    停留点下显示「未找到来源」，不会留下空块。
    """
    point_evidence = {}
    try:
        proposal = (route or {}).get("proposal") if isinstance(route, dict) else None
        node_ids = (proposal or {}).get("node_ids") or []
        if not isinstance(node_ids, (list, tuple)):
            return {}
        for raw_node_id in node_ids:
            node_id = _safe_text(raw_node_id)
            if not node_id:
                continue
            cards = []
            try:
                node = evidence._node_row(node_id)
                doc_ids = evidence._split_doc_ids(node.get("source_doc_ids")) if node else []
                for doc_id in doc_ids[:POINT_EVIDENCE_DOCS]:
                    try:
                        meta = evidence.doc_meta(doc_id)
                        if not meta:
                            continue
                        quote = evidence.quote_sentence_for(doc_id, node_id=node_id)
                        cards.append(_card_from_meta(meta, quote))
                    except Exception:
                        continue
            except Exception:
                cards = []
            point_evidence[node_id] = cards
    except Exception:
        return {}
    return point_evidence


def _build_segment_evidence(route):
    """构建「每个路线段 → 证据卡列表」；失败返回空列表。

    段结构与 ``route.validation.segments`` 一一对应（``from_name`` /
    ``to_name`` / ``source_doc_ids``），摘句直接调用 T1.6 的
    ``segment_evidence()``；该函数在找不到摘句时也会保留卡片并给出
    ``found=False``，因此页面不会出现空块。
    """
    segments = []
    try:
        validation = (route or {}).get("validation") if isinstance(route, dict) else None
        raw_segments = (validation or {}).get("segments") or []
        if not isinstance(raw_segments, (list, tuple)):
            return []
        for segment in raw_segments:
            if not isinstance(segment, dict):
                continue
            try:
                cards = evidence.segment_evidence(segment)
            except Exception:
                cards = []
            doc_ids = segment.get("source_doc_ids") or []
            if isinstance(doc_ids, str):
                doc_ids = [doc_ids]
            segments.append({
                "from_name": _safe_text(segment.get("from_name")),
                "to_name": _safe_text(segment.get("to_name")),
                "source_doc_ids": [_safe_text(doc_id) for doc_id in doc_ids if _safe_text(doc_id)],
                "cards": cards,
                "found_count": sum(1 for card in cards if card.get("found")),
            })
    except Exception:
        return []
    return segments


def _point_nodes_in_text(text, node_ids, names, point_evidence):
    """找出该时段文案里出现的停留点（按名称，长名优先），供模板分组证据卡。

    行程的 ``itinerary`` 只有分时文案、没有 node_id，所以这里用**已展示的
    节点名**在**已展示的文案**里做确定性匹配：不新增句子、不推断地点。
    长名优先并遮蔽已命中片段，避免「熊猫乐园」误吃「熊猫乐园站」。
    返回顺序仍按 ``proposal.node_ids``，与路线顺序一致。
    """
    if not isinstance(text, str) or not text:
        return []
    name_of = {node_id: _safe_text(names.get(node_id)) for node_id in node_ids}
    ordered = sorted(node_ids, key=lambda node_id: len(name_of.get(node_id) or ""), reverse=True)
    remaining = text
    matched = []
    for node_id in ordered:
        name = name_of.get(node_id) or ""
        if name and name in remaining:
            matched.append(node_id)
            remaining = remaining.replace(name, "\u0000" * len(name), 1)
    order = {node_id: index for index, node_id in enumerate(node_ids)}
    matched.sort(key=lambda node_id: order.get(node_id, len(node_ids)))
    points = []
    for node_id in matched:
        cards = point_evidence.get(node_id) or []
        points.append({
            "node_id": node_id,
            "name": name_of.get(node_id) or node_id.split("|")[-1],
            "cards": cards,
            "found_count": sum(1 for card in cards if card.get("found")),
        })
    return points


def _timeline_stops(raw):
    """停留点列表：只保留 ``{node_id, name}``，缺名字时用节点 id 尾段，不补地点。"""
    stops = []
    try:
        for stop in raw or []:
            if not isinstance(stop, dict):
                continue
            node_id = _safe_text(stop.get("node_id"))
            name = _safe_text(stop.get("name"))
            if not name and not node_id:
                continue
            stops.append({
                "node_id": node_id,
                "name": name or node_id.split("|")[-1],
            })
    except Exception:
        return []
    return stops


def _timeline_block(raw):
    """餐饮/休息块：只收 ``inserted`` + 非空 ``note``；没有说明就当没数据。"""
    if not isinstance(raw, dict):
        return None
    note = _safe_text(raw.get("note"))
    if not note:
        return None
    return {"inserted": bool(raw.get("inserted")), "note": note}


def _timeline_unknowns(raw):
    """未核验项：只保留非空字符串，顺序不变。"""
    items = []
    try:
        for value in raw or []:
            text = _safe_text(value)
            if text:
                items.append(text)
    except Exception:
        return []
    return items


def _build_timeline(itinerary, route, point_evidence):
    """把分时行程（T2.3 v2）整理成模板可渲染的结构（只归一，不补造）。

    - v2 字段原样传：``period`` / ``title`` / ``text`` / ``stops`` /
      ``duration_hint`` / ``duration_source`` / ``meal`` / ``rest`` /
      ``fatigue_note`` / ``unknowns``；
    - 时间：只有 ``time_source == "explicit"`` 且 ``time_range`` 非空才算资料时间，
      其余一律降级为 ``time_range=None`` + ``time_source="absent"``，模板逐字显示
      「资料未给出」，**不补钟点**；
    - 时长：``duration_source`` 只认「模板估算」「资料」，且必须有 ``duration_hint``；
      否则标成「未给出」并清空区间，避免把没有来源的时长写成资料；
    - 餐饮/休息：没有 ``note`` 就当没数据（模板显示固定未知文案）；
    - ``point_nodes``：沿用 T3.4 的证据分组（按时段文案里出现的节点名匹配）；
    - 任何异常整体降级为空 ``days``（页面显示「资料未给出分时行程」），不 500。
    """
    if not isinstance(itinerary, dict):
        return None

    node_ids = []
    names = {}
    try:
        proposal = (route or {}).get("proposal") if isinstance(route, dict) else None
        node_ids = [
            _safe_text(node_id)
            for node_id in ((proposal or {}).get("node_ids") or [])
            if _safe_text(node_id)
        ]
        names = (proposal or {}).get("node_names") or {}
        if not isinstance(names, dict):
            names = {}
    except Exception:
        node_ids, names = [], {}

    try:
        days = []
        for index, day in enumerate(itinerary.get("days") or [], start=1):
            if not isinstance(day, dict):
                continue
            day_no = day.get("day")
            if not isinstance(day_no, int) or isinstance(day_no, bool) or day_no < 1:
                day_no = index
            periods = []
            for item in day.get("periods") or []:
                if not isinstance(item, dict):
                    continue
                # 渲染用副本：保留原字段，只覆盖下面这些“显示安全值”。
                period = dict(item)

                time_range = _safe_text(period.get("time_range"))
                time_source = _safe_text(period.get("time_source"))
                if time_range and time_source == "explicit":
                    period["time_range"] = time_range
                    period["time_source"] = "explicit"
                else:
                    period["time_range"] = None
                    period["time_source"] = "absent"

                duration_source = _safe_text(period.get("duration_source"))
                duration_hint = _safe_text(period.get("duration_hint"))
                if duration_source in ("模板估算", "资料") and duration_hint:
                    period["duration_hint"] = duration_hint
                    period["duration_source"] = duration_source
                else:
                    period["duration_hint"] = None
                    period["duration_source"] = "未给出"

                period["title"] = _safe_text(period.get("title"))
                period["text"] = _safe_text(period.get("text"))
                period["stops"] = _timeline_stops(period.get("stops"))
                period["meal"] = _timeline_block(period.get("meal"))
                period["rest"] = _timeline_block(period.get("rest"))
                period["fatigue_note"] = _safe_text(period.get("fatigue_note")) or None
                period["unknowns"] = _timeline_unknowns(period.get("unknowns"))
                try:
                    period["point_nodes"] = _point_nodes_in_text(
                        period["text"], node_ids, names, point_evidence
                    )
                except Exception:
                    period["point_nodes"] = []
                periods.append(period)
            if not periods:
                # 没有任何可渲染时段的天不占位，页面显示「资料未给出分时行程」。
                continue
            days.append({
                "day": day_no,
                "plan_note": _safe_text(day.get("plan_note")),
                "periods": periods,
            })
        return {"days": days, "note": _safe_text(itinerary.get("note"))}
    except Exception:
        return {"days": [], "note": ""}


#: 路线示意图只认图谱里的这一步关系，方向固定为 ``src → dst``。
NEXT_REL = "NEXT"

#: 图谱索引缓存：``(nodes_by_id, next_edges)``；读不到时为 ``None``。
_GRAPH_INDEX = None


def _graph_index():
    """只读 P6 图谱并建索引，供路线示意图查边。

    返回 ``(nodes_by_id, next_edges)``：

    - ``nodes_by_id``：``node_id → graph_nodes.csv 行``，用来判断节点是否存在；
    - ``next_edges``：``(src, dst) → [doc_id, ...]``，**只收 ``rel=NEXT`` 的边**，
      方向固定为 ``src → dst``；同一对节点若有多行 NEXT 边，doc_id 去重合并。

    只调用 ``tools.load_graph()``（P6 产出的唯一读取实现），本模块不重写
    图谱规则、不补边、不猜方向。读取失败返回 ``None``，页面退回文字顺序。
    """
    global _GRAPH_INDEX
    if _GRAPH_INDEX is not None:
        return _GRAPH_INDEX
    try:
        nodes, edges = tools.load_graph()
    except Exception:
        return None
    nodes_by_id = {}
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_id = _safe_text(node.get("node_id"))
        if node_id:
            nodes_by_id[node_id] = node
    next_edges = {}
    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        if _safe_text(edge.get("rel")) != NEXT_REL:
            continue
        src = _safe_text(edge.get("src"))
        dst = _safe_text(edge.get("dst"))
        if not src or not dst:
            continue
        doc_ids = next_edges.setdefault((src, dst), [])
        for doc_id in _safe_text(edge.get("source_doc_ids")).split(";"):
            doc_id = doc_id.strip()
            if doc_id and doc_id not in doc_ids:
                doc_ids.append(doc_id)
    _GRAPH_INDEX = (nodes_by_id, next_edges)
    return _GRAPH_INDEX


def _diagram_node(node_id, names, nodes_by_id):
    """把一个 node_id 变成示意图节点：名字取 route 的 ``node_names``，其次图谱。"""
    row = nodes_by_id.get(node_id) or {}
    name = (
        _safe_text(names.get(node_id))
        or _safe_text(row.get("name"))
        or node_id.split("|")[-1]
    )
    return {"node_id": node_id, "name": name, "in_graph": bool(row)}


def _build_diagram(route):
    """按 route 顺序 + P6 ``NEXT`` 边构建路线示意图数据；异常一律返回 ``None``。

    返回::

        {"days":    [{"day": int, "nodes": [{node_id, name, in_graph}]}],
         "edges":   [{from_id, to_id, from_name, to_name, doc_ids}],
         "missing": [{from_id, to_id, from_name, to_name}]}

    - 分天与天内顺序**只来自** ``route.proposal.day_plan`` / ``node_ids``；
    - ``edges`` 只收图谱里真实存在、且方向一致的 ``NEXT`` 边；
    - 查不到边的相邻两点记进 ``missing``，模板只画虚线并标注，不画箭头；
    - 跨天之间不连边，避免暗示资料支持跨天连接；
    - ``node_ids`` 为空或任何异常 → ``None``，页面退回文字顺序。
    """
    try:
        proposal = (route or {}).get("proposal") if isinstance(route, dict) else None
        proposal = proposal if isinstance(proposal, dict) else {}
        raw_ids = proposal.get("node_ids") or []
        if not isinstance(raw_ids, (list, tuple)):
            return None
        node_ids = [_safe_text(item) for item in raw_ids]
        node_ids = [node_id for node_id in node_ids if node_id]
        if not node_ids:
            return None

        names = proposal.get("node_names") or {}
        if not isinstance(names, dict):
            names = {}
        index = _graph_index()
        nodes_by_id = index[0] if index else {}

        def entry(node_id):
            return _diagram_node(node_id, names, nodes_by_id)

        days = []
        raw_plan = proposal.get("day_plan") or []
        if isinstance(raw_plan, (list, tuple)):
            for raw_day in raw_plan:
                if not isinstance(raw_day, dict):
                    continue
                day_ids = [_safe_text(item) for item in (raw_day.get("node_ids") or [])]
                day_ids = [node_id for node_id in day_ids if node_id]
                if not day_ids:
                    continue
                try:
                    day_number = int(raw_day.get("day"))
                except (TypeError, ValueError):
                    day_number = len(days) + 1
                days.append({
                    "day": day_number,
                    "nodes": [entry(node_id) for node_id in day_ids],
                })
        planned = [node["node_id"] for day in days for node in day["nodes"]]
        if planned != node_ids:
            # day_plan 缺失、为空，或与 node_ids 的顺序/覆盖对不上：退回单天顺序。
            days = [{"day": 1, "nodes": [entry(node_id) for node_id in node_ids]}]

        edges, missing = [], []
        for day in days:
            nodes = day["nodes"]
            for current, following in zip(nodes, nodes[1:]):
                pair = (current["node_id"], following["node_id"])
                doc_ids = (index[1].get(pair) if index else None)
                item = {
                    "from_id": current["node_id"],
                    "to_id": following["node_id"],
                    "from_name": current["name"],
                    "to_name": following["name"],
                }
                if doc_ids is None:
                    missing.append(item)
                else:
                    item["doc_ids"] = list(doc_ids)
                    edges.append(item)
        return {"days": days, "edges": edges, "missing": missing}
    except Exception:
        return None


def _status_note(status, contract_violation, result):
    """给访客看的一句状态说明；不泄露原始异常/未知状态值。"""
    if contract_violation:
        return "后端没有返回合法的状态值，本次已按处理失败展示。"
    if status == "error":
        message = _safe_text(result.get("message"))
        return message or "本次处理失败，请稍后重试。"
    return ""


def _build_context(result, view, query, selected_alt="", cache_hit=False):
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
    route = result.get("route")
    # T3.4：证据卡只由 evidence 模块产出；任何异常都降级为空，模板显示「未找到来源」。
    point_evidence = _build_point_evidence(route)
    segment_evidence_list = _build_segment_evidence(route)
    itinerary = _build_timeline(result.get("itinerary"), route, point_evidence)
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
        "route": route,
        "diagram": _build_diagram(route),
        "itinerary": itinerary,
        "point_evidence": point_evidence,
        "segment_evidence_list": segment_evidence_list,
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
        "cache_hit": bool(cache_hit),
    }


def _render_result(result, view, query, selected_alt="", cache_hit=False):
    """渲染结果页；模板异常时返回 error 页而不是 500。"""
    context = _build_context(result, view, query, selected_alt, cache_hit=cache_hit)
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
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <div class="page">
    <header class="site-header"><div class="wrap site-header__inner"><div>
      <h1 class="site-title">可核验的景区行程助手</h1>
    </div></div></header>
    <main id="main-content" class="wrap">
      <div class="status-area" aria-live="polite">
        <p class="status-badge status-badge--error" data-status="error">
          <span class="status-badge__icon" aria-hidden="true">❌</span>
          <span class="status-badge__text"><span class="visually-hidden">状态：</span>处理失败</span>
        </p>
        <p class="status-badge__desc">这次没有生成行程，下面的内容都不是规划结果。</p>
        <p>页面渲染失败，请返回首页重试；如果反复出现，请把这次查询告诉维护者。</p>
        <p><a href="{{ url_for('home') }}">返回首页</a></p>
      </div>
    </main>
    <footer class="site-footer">
      <div class="wrap">
        <p>不提供预订、支付、导航或叫车服务；资料版权归原站。</p>
      </div>
    </footer>
  </div>
</body>
</html>
"""
    return render_template_string(page)


_SECURITY_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · 可核验的景区行程助手</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <div class="page">
    <header class="site-header"><div class="wrap site-header__inner"><div>
      <h1 class="site-title">可核验的景区行程助手</h1>
    </div></div></header>
    <main id="main-content" class="wrap">
      <section aria-labelledby="security-title">
        <h2 id="security-title">{{ title }}</h2>
        <p>{{ message }}</p>
        <p><a class="btn btn--secondary" href="{{ url_for('home') }}">返回首页</a></p>
      </section>
    </main>
  </div>
</body>
</html>
"""


def _render_security_notice(title, message, status_code, retry_after=None):
    """T5.2：CSRF 校验失败 / 限流时的可读 HTML 页，不建任务、不调模型。"""
    response = app.response_class(
        render_template_string(_SECURITY_PAGE, title=title, message=message),
        status=status_code,
        mimetype="text/html",
    )
    if retry_after:
        response.headers["Retry-After"] = str(int(retry_after))
    return response


def _error_result(query, exc=None):
    """把线程/调用异常收敛成四值契约里的 error 结果（不泄露原始堆栈到页面）。"""
    return {
        "query": query,
        "status": "error",
        "message": "服务暂时不可用，请稍后重试。",
        "error": str(exc) if exc is not None else "",
        "reasons": [{
            "code": "model_error",
            "text": "服务暂时不可用，本次没有生成行程。",
        }],
    }


def _run_agent_safely(query):
    """调用一次 ``run_agent``；异常兜成 error 结果，不让路由抛 500。"""
    try:
        return run_agent(query)
    except Exception as exc:
        return _error_result(query, exc)


def _render_job_error(job, view):
    """失败页：四值徽标 + 原因 + 回填 query 的「重新提交」表单；模板异常也不 500。"""
    job = job if isinstance(job, dict) else {}
    result = job.get("result")
    result = result if isinstance(result, dict) else {}
    try:
        return render_template(
            "error.html",
            view=view,
            query=_safe_text(job.get("query")),
            status="error",
            reasons=_normalize_reasons(result.get("reasons")),
            message=_job_error_text(job),
        )
    except Exception:  # noqa: BLE001 - 模板失败仍要给访客一个 200 的错误页
        return _render_failure_page()


def _render_progress_page(job, view):
    """运行中进度页：四个固定阶段 + 真实阶段状态；模板异常回落错误页。"""
    stages = _merge_stages(job)
    try:
        return render_template(
            "progress.html",
            view=view,
            job_id=job.get("job_id", ""),
            query=_safe_text(job.get("query")),
            stages=stages,
            current_label=_job_current_label(job, stages),
            elapsed_s=f"{_job_elapsed_ms(job) / 1000:.1f}",
            job_status=_safe_text(job.get("status")),
        )
    except Exception:  # noqa: BLE001 - 进度页模板失败也要有可读页面
        return _render_failure_page()


def _sync_pending_query(result, query):
    """完成页才同步追问上下文（后台线程不能碰 session，只能在请求里做）。

    D5 hotfix：只有 ``clarify`` 才是真正的追问；``partial`` 虽然也可能带
    ``needs_followup=True``（路线问题/可行性裁剪），但它已经是可读结果，
    不能再把用户的下一条新需求拼到上一轮 query 后面。
    """
    try:
        status = normalize_status((result or {}).get("status")) if isinstance(result, dict) else None
        if isinstance(result, dict) and result.get("needs_followup") and status == "clarify":
            session["pending_query"] = query
        else:
            session.pop("pending_query", None)
    except Exception:  # noqa: BLE001 - 没有 session 上下文时忽略
        pass


# ---------------------------------------------------------------------------
# T5.1 请求级可观测性：request-id + JSONL 日志
#
# - 每个请求生成/接受合法 ``X-Request-ID``，并写回响应头；
# - 只记 method/path/status/duration_ms/error_type 与 query 的哈希+长度，
#   不记 query string、表单原文、trace_json、cookie 或 Authorization；
# - 日志失败由 observability.log_event 内部吞掉，不影响路由/模板/状态。
# ---------------------------------------------------------------------------

def _record_query_fingerprint(text):
    """把当前请求的 query 只以 SHA256 前缀 + 字符长度存进 ``g``。"""
    digest, length = observability.query_fingerprint(text)
    g.query_sha256_12 = digest
    g.query_len = length


def _current_query_fingerprint():
    return getattr(g, "query_sha256_12", None), int(getattr(g, "query_len", 0) or 0)


@app.before_request
def _observe_request_start():
    """生成 request-id，并预先计算 query 指纹（不保存原文）。"""
    request_id = observability.set_request_id(
        request.headers.get(observability.REQUEST_ID_HEADER)
    )
    g.request_id = request_id
    g.request_started = time.monotonic()
    g.error_type = None
    raw_query = ""
    try:
        raw_query = request.args.get("query") or ""
        if not raw_query and request.method in ("POST", "PUT", "PATCH"):
            raw_query = request.form.get("query") or ""
    except Exception:  # noqa: BLE001 - 读表单失败不能影响路由
        raw_query = ""
    _record_query_fingerprint(raw_query)


@app.before_request
def _enforce_csrf_token():
    """T5.2：所有 POST 必须带会话 token；失败返回可读 400，且不进入路由。

    在 ``_observe_request_start`` 之后注册，保证 request-id/日志仍先生成；
    这里只比较 token，不记录 token 原文。
    """
    if request.method != "POST":
        return None
    try:
        submitted = request.form.get(security.CSRF_FIELD_NAME, "")
    except Exception:  # noqa: BLE001 - 读表单失败按缺失处理
        submitted = ""
    expected = session.get(security.CSRF_SESSION_KEY)
    if security.csrf_tokens_match(expected, submitted):
        return None
    return _render_security_notice(
        "提交校验失败",
        "页面可能已过期，本次提交没有处理。请返回首页刷新后重新提交。",
        400,
    )


def _record_request_exception(sender, exception, **extra):
    """记录异常类型；不记录异常 message（可能夹带用户输入）。"""
    try:
        g.error_type = type(exception).__name__
    except Exception:  # noqa: BLE001 - 信号回调不得影响异常处理
        pass


got_request_exception.connect(_record_request_exception, app)


@app.after_request
def _observe_request_end(response):
    """写响应头 + 一条 ``http_request`` 事件；任何异常都不改变响应。"""
    try:
        request_id = (
            observability.get_request_id()
            or getattr(g, "request_id", "")
            or observability.new_request_id()
        )
        response.headers[observability.REQUEST_ID_HEADER] = request_id
        started = getattr(g, "request_started", None)
        duration_ms = (
            max(int((time.monotonic() - started) * 1000), 0)
            if isinstance(started, (int, float)) else 0
        )
        error_type = getattr(g, "error_type", None)
        if error_type is None and response.status_code >= 500:
            error_type = "internal_error"
        digest, length = _current_query_fingerprint()
        observability.log_event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=duration_ms,
            error_type=error_type,
            query_sha256_12=digest,
            query_len=length,
        )
    except Exception:  # noqa: BLE001 - 可观测性不得改变响应
        pass
    return response


@app.after_request
def _inject_csrf_token(response):
    """T5.2：给 HTML 表单服务端注入 hidden ``csrf_token``（无 JS）。

    在 ``_observe_request_end`` 之后注册，但 Flask 按注册逆序执行，因此注入
    先于日志；注入失败绝不改变原响应/状态码。已有 token 的页面不重复注入。
    """
    try:
        if response.mimetype != "text/html" or response.status_code >= 500:
            return response
        html = response.get_data(as_text=True)
        if "</form>" not in html:
            return response
        token = security.ensure_csrf_token(session)
        updated = security.inject_csrf_token(html, token)
        if updated != html:
            response.set_data(updated)
    except Exception:  # noqa: BLE001 - 安全注入不得把页面变成 500
        pass
    return response


@app.route("/", methods=["GET", "POST"])
def home():
    view = _resolve_view()

    if request.method == "GET":
        if request.args.get("new") == "1":
            # 明确的“开始新查询/清空”：丢掉上一轮追问上下文，避免新需求被追加。
            session.pop("pending_query", None)
        get_query = _safe_text(request.args.get("query"))
        _record_query_fingerprint(get_query)
        cached = _get_cached_result(get_query) if get_query else None
        if cached is not None:
            # 视图切换 / 备选高亮：复用上一次 POST 的结果，不重新调用模型。
            return _render_result(
                cached, view, get_query,
                request.args.get("alt", ""),
                cache_hit=True,
            )
        return render_template(
            "index.html",
            view=view,
            query=get_query,
            examples=EXAMPLES,
            notice=_safe_text(request.args.get("notice")),
        )

    if request.form.get("action") == "reset":
        session.pop("pending_query", None)
        _record_query_fingerprint("")
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

    _record_query_fingerprint(query)
    if not query:
        return render_template(
            "index.html",
            view=view,
            query="",
            examples=EXAMPLES,
            notice="请输入旅行需求。",
        )

    # T3.7：POST 不再等在模型结束；建任务 + 起后台线程后立刻 303 到进度页。
    # T5.2：昂贵 POST 每 IP 每分钟限流；GET / reset / 空输入不消耗限额。
    allowed, retry_after = RATE_LIMITER.consume(request.remote_addr or "local")
    if not allowed:
        return _render_security_notice(
            "提交太频繁",
            "每分钟最多 %d 次查询，本次提交没有处理。请约 %d 秒后再试。"
            % (RATE_LIMITER.limit, retry_after),
            429,
            retry_after=retry_after,
        )
    job_id = _create_job(query, view)
    _start_job(job_id)
    return redirect(url_for("run_progress", job_id=job_id, view=view), code=303)


@app.route("/run/<job_id>")
def run_progress(job_id):
    """进度页：运行中渲染四阶段；完成渲染结果页；失败渲染可重试错误页。"""
    view = _resolve_view()
    job = _job_get(job_id)
    if job is None:
        return redirect(
            url_for("home", view=view, notice="任务已过期，请重新提交"),
            code=303,
        )
    if job.get("status") == "error":
        return _render_job_error(job, view)
    if job.get("status") == "done":
        result = job.get("result")
        result = result if isinstance(result, dict) else {}
        # 与旧流程一致：完成后同步追问上下文，?view=auditor / ?alt= 走结果页。
        _sync_pending_query(result, job.get("query", ""))
        return _render_result(
            result, view, job.get("query", ""),
            request.args.get("alt", ""),
            cache_hit=False,
        )
    return _render_progress_page(job, view)


@app.route("/run/<job_id>/json")
def run_progress_json(job_id):
    """进度 JSON：只暴露阶段状态；不含 intent / trace / 工具决策 / 路线明细。"""
    job = _job_get(job_id)
    if job is None:
        return jsonify({"error": "任务不存在或已过期"}), 404
    return jsonify(_job_public(job))


def _serve():
    """启动本机 Web 服务：显式只绑定回环地址，关闭 debug/reloader。"""
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False)


if __name__ == "__main__":
    _serve()
