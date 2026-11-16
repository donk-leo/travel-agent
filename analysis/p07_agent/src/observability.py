"""P7 可观测性：request-id、JSONL 运行日志与模型交互计数（T5.1）。

设计边界
--------
- 只记录**元数据**：路径、状态码、耗时、错误类型、query 的 SHA256 前缀与长度。
  不记录用户原文、query string、表单内容、``trace_json``、cookie、
  ``Authorization`` 或任何密钥。
- 日志默认写到**仓库外**（``<repo>/../p7_agent_logs``），可用 ``P07_LOG_DIR``
  覆盖；若显式/环境变量路径落在仓库内，自动回退到仓库外默认目录。
- 日志失败绝不影响请求/任务：``log_event`` 内部吞掉所有异常。
- 模型交互次数是按 ``trace.events`` 已知事件类型做的**事件近似计数**，
  不是 provider 账单级精确值；定义与边界见 ``docs/optimization/LOGGING.md``。

字段约定（一行一个 JSON）::

    {"ts": "...Z", "level": "info", "event": "http_request", "request_id": "..."}
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import logging.handlers
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

#: 仓库根（本文件位于 analysis/p07_agent/src/）。
REPO_ROOT = Path(__file__).resolve().parents[3]

#: 默认日志目录：仓库**外**的同级目录，避免误提交运行日志。
DEFAULT_LOG_DIR = REPO_ROOT.parent / "p7_agent_logs"
LOG_FILENAME = "p07_app.jsonl"

LOG_DIR_ENV = "P07_LOG_DIR"
RETENTION_DAYS_ENV = "P07_LOG_RETENTION_DAYS"
MAX_BYTES_ENV = "P07_LOG_MAX_BYTES"

DEFAULT_RETENTION_DAYS = 7
DEFAULT_MAX_BYTES = 10 * 1024 * 1024

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")

MAX_EVENT_LENGTH = 80
MAX_FIELD_LENGTH = 200
MAX_QUERY_HASH_CHARS = 12

#: 即使调用方误传，也不允许进入日志的字段（隐私红线）。
FORBIDDEN_FIELD_KEYS = frozenset({
    "query", "query_text", "user_text", "user_request", "form", "form_data",
    "trace_json", "cookie", "cookies", "authorization", "password",
    "secret", "token", "api_key", "apikey", "access_token", "refresh_token",
})

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_REQUEST_ID = contextvars.ContextVar("p07_request_id", default="")

_logger = logging.getLogger("p07.observability")
_logger.propagate = False
_logger.setLevel(logging.DEBUG)

_CONFIG_LOCK = threading.RLock()
_configured = False
_handler = None
_config_dir = None
_config_retention = None
_config_max_bytes = None


# ---------------------------------------------------------------------------
# request-id
# ---------------------------------------------------------------------------

def is_valid_request_id(value):
    """只接受 8–64 位 ``[A-Za-z0-9-]``，防止把任意请求头写进日志。"""
    return isinstance(value, str) and bool(REQUEST_ID_PATTERN.fullmatch(value))


def new_request_id():
    """生成不可猜测的 request-id（uuid4，32 位十六进制）。"""
    return uuid.uuid4().hex


def get_request_id():
    """取当前上下文 request-id；没有时返回空串。"""
    return _REQUEST_ID.get()


def set_request_id(request_id=None):
    """设置当前上下文 request-id；缺失或不合法时生成新的。

    返回实际生效的 id，便于 Web 层写入响应头或任务表。
    """
    value = request_id if is_valid_request_id(request_id) else new_request_id()
    _REQUEST_ID.set(value)
    return value


# ---------------------------------------------------------------------------
# 日志目录与轮转
# ---------------------------------------------------------------------------

def default_log_dir():
    """默认日志目录（仓库外，不创建）。"""
    return DEFAULT_LOG_DIR


def is_within_repo(path):
    """路径是否位于本仓库内（用于拒绝把运行日志写进仓库）。"""
    try:
        resolved = Path(path).resolve()
        resolved.relative_to(REPO_ROOT)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _coerce_int(value, default, minimum=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _writable_dir(path):
    """尝试创建目录并写探针文件；受限环境可能只有部分目录可写。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".p07_log_probe_{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _resolve_log_dir(log_dir=None):
    """按 显式参数 → ``P07_LOG_DIR`` → 仓库外默认目录 的顺序选可写目录。

    任何落在仓库内的候选都跳过，保证运行日志不会误入提交物。
    """
    candidates = []
    if log_dir is not None:
        try:
            candidates.append(Path(log_dir))
        except (TypeError, ValueError):
            pass
    env_value = (os.environ.get(LOG_DIR_ENV) or "").strip()
    if env_value:
        try:
            candidates.append(Path(env_value))
        except (TypeError, ValueError):
            pass
    candidates.append(DEFAULT_LOG_DIR)

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_within_repo(resolved):
            continue
        if _writable_dir(resolved):
            return resolved
    return None


class SizeCappedTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """按 UTC 午夜轮转，并额外在单文件超过 ``max_bytes`` 时提前轮转。

    标准库的 ``TimedRotatingFileHandler`` 只按时间轮转；这里补一个体积上限，
    避免一次长跑把单个文件写得过大。``backupCount`` 同时作为保留份数/天数。
    """

    def __init__(self, filename, max_bytes=DEFAULT_MAX_BYTES, **kwargs):
        self.max_bytes = max(_coerce_int(max_bytes, DEFAULT_MAX_BYTES, 0), 0)
        super().__init__(filename, **kwargs)

    def emit(self, record):
        try:
            if self.max_bytes and self.stream is not None:
                try:
                    size = os.path.getsize(self.baseFilename)
                except OSError:
                    size = 0
                if size >= self.max_bytes:
                    self.doRollover()
        except Exception:  # noqa: BLE001 - 轮转失败仍应尝试写当前行
            pass
        super().emit(record)


def configure_logging(log_dir=None, retention_days=None, max_bytes=None):
    """配置 JSONL 日志；返回实际日志目录（全部不可写时返回 ``None``）。

    - ``log_dir``：显式目录；``None`` 时读 ``P07_LOG_DIR``，再退回仓库外默认目录；
    - ``retention_days``：保留天数（轮转备份数），默认 7；
    - ``max_bytes``：单文件体积上限，默认 10 MiB。

    重复调用相同配置是幂等的；配置变更会替换旧 handler。本函数不抛异常。
    """
    global _configured, _handler, _config_dir, _config_retention, _config_max_bytes

    retention = _coerce_int(
        retention_days if retention_days is not None else os.environ.get(RETENTION_DAYS_ENV),
        DEFAULT_RETENTION_DAYS, 1,
    )
    cap = _coerce_int(
        max_bytes if max_bytes is not None else os.environ.get(MAX_BYTES_ENV),
        DEFAULT_MAX_BYTES, 0,
    )

    with _CONFIG_LOCK:
        try:
            target = _resolve_log_dir(log_dir)
        except Exception:  # noqa: BLE001 - 配置失败不得影响业务
            target = None
        if (_configured and target == _config_dir
                and retention == _config_retention and cap == _config_max_bytes):
            return target

        _remove_handler_locked()
        _configured = True
        _config_dir = target
        _config_retention = retention
        _config_max_bytes = cap
        if target is None:
            return None

        try:
            handler = SizeCappedTimedRotatingFileHandler(
                str(target / LOG_FILENAME),
                max_bytes=cap,
                when="midnight",
                interval=1,
                backupCount=retention,
                encoding="utf-8",
                delay=True,
                utc=True,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler.setLevel(logging.DEBUG)
            _logger.addHandler(handler)
            _handler = handler
        except Exception:  # noqa: BLE001 - 日志不可用不得影响业务
            _handler = None
            _config_dir = None
            return None
        return target


def logging_status():
    """返回当前 handler 的轮转/保留配置（测试与排错用）。"""
    with _CONFIG_LOCK:
        handler = _handler
        when = getattr(handler, "when", None)
        filename = None
        if _config_dir is not None:
            filename = str(Path(_config_dir) / LOG_FILENAME)
        return {
            "configured": handler is not None,
            "log_dir": str(_config_dir) if _config_dir is not None else None,
            "filename": filename,
            "when": when.lower() if isinstance(when, str) else None,
            "backup_count": getattr(handler, "backupCount", None),
            "max_bytes": getattr(handler, "max_bytes", None),
            "utc": getattr(handler, "utc", None),
        }


def _remove_handler_locked():
    global _handler
    if _handler is not None:
        try:
            _logger.removeHandler(_handler)
        except Exception:  # noqa: BLE001
            pass
        try:
            _handler.close()
        except Exception:  # noqa: BLE001
            pass
        _handler = None


def shutdown_logging():
    """关闭并移除 handler（测试清理用）；之后首次 ``log_event`` 会重新配置。"""
    global _configured, _config_dir, _config_retention, _config_max_bytes
    with _CONFIG_LOCK:
        _remove_handler_locked()
        _configured = False
        _config_dir = None
        _config_retention = None
        _config_max_bytes = None


def _ensure_configured():
    if not _configured:
        configure_logging()


# ---------------------------------------------------------------------------
# query 指纹
# ---------------------------------------------------------------------------

def query_fingerprint(text):
    """返回 ``(sha256 前 12 位, 字符长度)``；空文本返回 ``(None, 0)``。

    只用于日志关联，不可逆推出原文；长度按 Unicode 字符数计。
    """
    if text is None:
        return None, 0
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return None, 0
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return digest[:MAX_QUERY_HASH_CHARS], len(text)


# ---------------------------------------------------------------------------
# 事件写入
# ---------------------------------------------------------------------------

def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


def _clip(value, limit):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _safe_value(value):
    """日志字段只允许标量；容器降级成类型名，避免把整段原文字典写进去。"""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clip(value, MAX_FIELD_LENGTH)
    return f"<{type(value).__name__}>"


def _build_record(event, fields):
    level = str(fields.pop("level", "info") or "info").strip().lower()
    if level not in _LEVELS:
        level = "info"
    request_id = fields.pop("request_id", None) or get_request_id()
    record = {
        "ts": _utc_now(),
        "level": level,
        "event": _clip(event, MAX_EVENT_LENGTH),
        "request_id": request_id if is_valid_request_id(request_id) else "-",
    }
    redacted = []
    for key, value in fields.items():
        name = str(key)
        if name in ("ts", "level", "event", "request_id") or name.lower() in FORBIDDEN_FIELD_KEYS:
            redacted.append(name)
            continue
        record[name] = _safe_value(value)
    if redacted:
        record["redacted_fields"] = sorted(set(redacted))
    return record


def log_event(event, **fields):
    """写一条 JSONL 事件；任何异常都在内部吞掉，不影响调用方。

    字段约定：请求事件用 ``method/path/status/duration_ms/error_type``；
    任务事件用 ``job_id/duration_ms/status/model_calls/error_type``。
    ``query`` / ``trace_json`` / cookie 等敏感字段即使误传也会被丢弃。
    """
    try:
        _ensure_configured()
        handler = _handler
        if handler is None:
            return
        record = _build_record(event, dict(fields))
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        _logger.log(_LEVELS.get(record["level"], logging.INFO), payload)
    except Exception:  # noqa: BLE001 - 日志失败不得影响请求
        pass


# ---------------------------------------------------------------------------
# 模型交互次数（事件近似）
# ---------------------------------------------------------------------------

def _coerce_trace_events(trace_events):
    if isinstance(trace_events, str):
        try:
            trace_events = json.loads(trace_events)
        except (TypeError, ValueError):
            return []
    if not isinstance(trace_events, (list, tuple)):
        return []
    return [event for event in trace_events if isinstance(event, dict)]


def count_model_calls(trace_events):
    """从 ``trace.events`` 的已知事件类型估算模型交互次数（int）。

    计数规则（与 ``docs/optimization/LOGGING.md`` 一致）：

    - ``intent`` / ``intent_call_error``：意图解析最多一次模型调用，计 1；
    - ``decision``：只有非 ``fast_decision`` 路径才计 1；
    - ``tool_call`` 且 ``tool == "select_tools"``：每轮工具选择一次模型调用；
    - ``requirement_check``：有 ``fast_requirement_check`` 时是确定性规则，计 0；
      否则（含 ``requirement_check_fallback``）计 1；
    - ``plan_check``：有 ``fast_plan_check`` 时计 0；否则（含
      ``plan_check_fallback``）计 1。

    这是**事件近似计数 / 下限**：``condition_selector`` 的筛选与理由生成、
    ``route_planner`` 的首次规划与失败重规划没有逐次写入 trace，因此不会计入；
    不能当作 provider 账单级精确值。
    """
    events = _coerce_trace_events(trace_events)
    if not events:
        return 0

    event_types = {str(event.get("event_type") or "") for event in events}
    total = 0

    if "intent" in event_types or "intent_call_error" in event_types:
        total += 1

    if "fast_decision" not in event_types and "decision" in event_types:
        total += 1

    total += sum(
        1 for event in events
        if event.get("event_type") == "tool_call" and event.get("tool") == "select_tools"
    )

    if "fast_requirement_check" not in event_types:
        if "requirement_check_fallback" in event_types or "requirement_check" in event_types:
            total += 1

    if "fast_plan_check" not in event_types:
        if "plan_check_fallback" in event_types or "plan_check" in event_types:
            total += 1

    return total
