"""请求级结果缓存（T2.7）：进程内 LRU + TTL，读写隔离，不共享会话文件。

设计约束（T2.7 验收口径）：
- 键 = ``normalize_user_text(query)`` + 口径（模型、``MAX_TOKENS``、
  ``ROUTE_MAX_TOKENS``、``ROUTE_NUM_CTX``、图谱计数）+ intent 里的
  area / sub_area / days / profiles / preferences / constraints；
- TTL 1800s、LRU 8、线程锁；读写都 deepcopy，调用方改返回值不会污染缓存；
- 不缓存 error / 空结果；缓存值剔除 ``trace_file / trace_json / trace_error``，
  会话记录永远按请求重新落盘，不跨请求共享；
- ``stats()`` 暴露 hits / misses / evictions（另附 expired / stores）；
  ``clear()`` 清空；
- 冷启动评测：每条 query 在同进程内首次出现，所以 cache_hits 必须为 0。

开关：``P07_RESULT_CACHE=0``（或 false/off/no）时禁用，读写都直接跳过。
``P07_CACHE_STATS_FILE`` 指向文件时，进程退出会把 ``stats()`` 写到该文件，
供评测复跑时机器核对缓存命中数（不是手写指标）。
"""

import atexit
import copy
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from config import MAX_TOKENS, MODEL, ROUTE_MAX_TOKENS, ROUTE_NUM_CTX
from text_normalize import normalize_user_text


CACHE_ENV = "P07_RESULT_CACHE"
CACHE_OFF_VALUES = frozenset({"0", "false", "off", "no"})
CACHE_STATS_ENV = "P07_CACHE_STATS_FILE"

TTL_SECONDS = 1800.0
MAX_ENTRIES = 8

#: 会话文件字段不随缓存跨请求共享，写入缓存前统一剔除。
TRACE_KEYS = ("trace_file", "trace_json", "trace_error")
#: 只有这三态可缓存；error 与空结果一律不缓存。
CACHEABLE_STATUSES = frozenset({"verified", "partial", "clarify"})

_GRAPH_STATS_PATH = (
    Path(__file__).resolve().parents[3]
    / "analysis" / "p06_graph" / "outputs" / "graph_stats.json"
)


def _normalize_query(user_text):
    try:
        return str(normalize_user_text(user_text))
    except Exception:  # noqa: BLE001 - 归一失败时退回原文，不影响主流程
        return str(user_text or "")


def graph_signature():
    """图谱口径：优先用 graph_stats 的计数，缺失时退回文件 mtime/size。"""
    try:
        payload = json.loads(_GRAPH_STATS_PATH.read_text(encoding="utf-8"))
        counts = payload.get("counts") or {}
        by_rel = counts.get("by_rel") or {}
        return (
            f"graph:{counts.get('nodes')}/{counts.get('edges')}"
            f"/NEXT:{by_rel.get('NEXT')}"
        )
    except Exception:  # noqa: BLE001 - 统计文件不可用时用文件指纹
        try:
            stat = _GRAPH_STATS_PATH.stat()
            return f"graph-file:{int(stat.st_mtime)}/{stat.st_size}"
        except Exception:  # noqa: BLE001 - 图谱缺失时仍给出稳定占位
            return "graph:unknown"


def _sorted_strings(values):
    if not isinstance(values, (list, tuple, set)):
        return ()
    return tuple(sorted(str(value).strip() for value in values if str(value).strip()))


def build_key(user_text, intent=None):
    """构造缓存键；同 query + 同口径 + 同 intent 才可能命中。"""
    intent = intent if isinstance(intent, dict) else {}
    return (
        "query", _normalize_query(user_text),
        "model", str(MODEL),
        "max_tokens", int(MAX_TOKENS),
        "route_max_tokens", int(ROUTE_MAX_TOKENS),
        "route_num_ctx", int(ROUTE_NUM_CTX),
        "graph", graph_signature(),
        "area", str(intent.get("scenic_area") or ""),
        "sub_area", str(intent.get("sub_area") or ""),
        "days", intent.get("duration_days"),
        "profiles", _sorted_strings(intent.get("traveler_profiles")),
        "preferences", _sorted_strings(intent.get("preferences")),
        "constraints", _sorted_strings(intent.get("constraints")),
    )


def is_cacheable(result):
    """error / 空结果不缓存；有路线、建议或地点结果的成功结果可缓存。"""
    if not isinstance(result, dict):
        return False
    if str(result.get("error") or "").strip():
        return False
    if result.get("status") not in CACHEABLE_STATUSES:
        return False
    if result.get("status") == "clarify":
        # 追问没有路线/建议，只有文案；文案为空才算空结果。
        return bool(str(result.get("message") or "").strip())
    return bool(
        result.get("route") or result.get("suggestions") or result.get("poi_results")
    )


def _cache_value(value):
    """写入/读出都用 deepcopy；剔除会话文件字段，避免跨请求共享。"""
    payload = copy.deepcopy(value)
    if isinstance(payload, dict):
        for key in TRACE_KEYS:
            payload.pop(key, None)
    return payload


class ResultCache:
    """线程安全的 TTL + LRU 缓存；``clock`` 可注入，便于单测 TTL。"""

    def __init__(self, ttl=TTL_SECONDS, max_entries=MAX_ENTRIES, clock=time.monotonic):
        self.ttl = float(ttl)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expired = 0
        self._stores = 0

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if self._clock() - entry["stored_at"] > self.ttl:
                self._entries.pop(key, None)
                self._expired += 1
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return _cache_value(entry["value"])

    def set(self, key, value):
        if not is_cacheable(value):
            return False
        stored = _cache_value(value)
        with self._lock:
            self._entries[key] = {"value": stored, "stored_at": self._clock()}
            self._entries.move_to_end(key)
            self._stores += 1
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1
        return True

    def clear(self):
        with self._lock:
            self._entries.clear()

    def stats(self):
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "expired": self._expired,
                "stores": self._stores,
                "entries": len(self._entries),
                "ttl_s": self.ttl,
                "max_entries": self.max_entries,
            }


_default_cache = ResultCache()


def enabled():
    """``P07_RESULT_CACHE=0``（或 false/off/no）时关闭缓存。"""
    value = os.environ.get(CACHE_ENV, "1")
    return str(value).strip().lower() not in CACHE_OFF_VALUES


def lookup(user_text, intent=None):
    """按 query + intent 取缓存；未启用时返回 ``None``。"""
    return lookup_key(build_key(user_text, intent))


def lookup_key(key):
    """按已经构造好的键取缓存；未启用时返回 ``None``。"""
    if not enabled():
        return None
    return _default_cache.get(key)


def store(user_text, intent, result):
    """写入缓存；未启用 / 不可缓存时返回 ``False``。"""
    return store_key(build_key(user_text, intent), result)


def store_key(key, result):
    """按已经构造好的键写入缓存；未启用 / 不可缓存时返回 ``False``。"""
    if not enabled():
        return False
    return _default_cache.set(key, result)


def stats():
    return _default_cache.stats()


def clear():
    _default_cache.clear()


def _dump_stats_if_configured():
    """评测用：``P07_CACHE_STATS_FILE`` 存在时把统计写到仓库外文件。"""
    path = os.environ.get(CACHE_STATS_ENV)
    if not path:
        return
    try:
        payload = {
            "stats": stats(),
            "pid": os.getpid(),
            "cache_enabled": enabled(),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - 统计落盘失败不影响主流程
        pass


atexit.register(_dump_stats_if_configured)
