# -*- coding: utf-8 -*-
"""P7 Web 安全边界：默认绑定、CSRF token、进程内固定窗口限流。

设计约束
--------
- 只用标准库（``secrets`` / ``threading`` / ``time``），不引 Flask-WTF、Redis
  等第三方依赖，也不改模板：CSRF 隐藏字段由 ``web_app`` 在 HTML 响应里注入；
- token 只存在 Flask 的签名 session 与表单隐藏字段中，不写日志、不进 URL
  query、不设独立的明文 CSRF cookie；
- 限流是**单进程内存**实现：重启清空、多 worker 不共享，边界见
  ``docs/optimization/SECURITY.md``；
- 本模块不 import ``web_app``，避免循环导入；Web 接线集中在 ``web_app.py``。
"""

import math
import os
import secrets
import threading
import time
from html import escape as _html_escape

#: 默认只监听回环地址；不要改成对外监听地址（见 SECURITY.md 部署建议）。
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

#: CSRF 表单字段名与 session key；模板/测试都从这里取，避免拼错。
CSRF_FIELD_NAME = "csrf_token"
CSRF_SESSION_KEY = "csrf_token"
CSRF_TOKEN_BYTES = 32
CSRF_INPUT_MARKER = 'name="%s"' % CSRF_FIELD_NAME
CSRF_INPUT_TEMPLATE = '<input type="hidden" name="%s" value="%s">'

#: 昂贵 POST 的默认限额：每 IP 每分钟 5 次；可用环境变量覆盖（正整数）。
RATE_LIMIT_PER_MINUTE = 5
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_ENV = "P07_RATE_LIMIT_PER_MIN"
_RATE_LIMIT_MAX_KEYS = 4096


def _env_rate_limit():
    """读取 ``P07_RATE_LIMIT_PER_MIN``；缺失/非法/非正数回退默认值。"""
    raw = os.environ.get(RATE_LIMIT_ENV, "")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return RATE_LIMIT_PER_MINUTE
    return value if value > 0 else RATE_LIMIT_PER_MINUTE


def new_csrf_token():
    """生成 URL-safe 的会话 token（默认 32 字节熵，约 43 字符）。"""
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def ensure_csrf_token(session_obj):
    """返回当前会话的 token；没有则生成并写入 Flask session。

    ``session.permanent = True`` 让浏览器端 cookie 遵循
    ``PERMANENT_SESSION_LIFETIME``（30 分钟，见 web_app 配置）。
    """
    token = session_obj.get(CSRF_SESSION_KEY)
    if isinstance(token, str) and token:
        return token
    token = new_csrf_token()
    session_obj[CSRF_SESSION_KEY] = token
    try:
        session_obj.permanent = True
    except AttributeError:  # 例如测试里传入普通 dict
        pass
    return token


def csrf_tokens_match(expected, submitted):
    """常量时间比较；缺失/类型不对/非 ASCII 一律不匹配。"""
    if not isinstance(expected, str) or not isinstance(submitted, str):
        return False
    if not expected or not submitted:
        return False
    try:
        return secrets.compare_digest(
            expected.encode("utf-8"), submitted.encode("utf-8")
        )
    except (TypeError, UnicodeEncodeError):
        return False


def inject_csrf_token(html, token):
    """在每个 ``</form>`` 前注入一次隐藏字段；已有 token 时不重复注入。

    服务端字符串替换，无 JS；对没有表单的页面（进度页/结果页的某些状态）
    原样返回。token 是 URL-safe 字符，仍做 HTML 转义以防未来实现变化。
    """
    if not isinstance(html, str) or not html or not isinstance(token, str):
        return html
    if not token or "</form>" not in html:
        return html
    if CSRF_INPUT_MARKER in html:
        return html
    field = CSRF_INPUT_TEMPLATE % (CSRF_FIELD_NAME, _html_escape(token, quote=True))
    return html.replace("</form>", field + "</form>")


class FixedWindowRateLimiter:
    """线程安全的固定窗口计数器：每 key 每个窗口最多 ``limit`` 次。

    ``now`` 参数用于测试注入单调时钟；生产调用默认 ``time.monotonic()``。
    """

    def __init__(self, limit=RATE_LIMIT_PER_MINUTE,
                 window_seconds=RATE_LIMIT_WINDOW_SECONDS):
        self._lock = threading.RLock()
        self.default_limit = max(int(limit), 1)
        self.default_window_seconds = max(int(window_seconds), 1)
        self.limit = self.default_limit
        self.window_seconds = self.default_window_seconds
        self._entries = {}

    def configure(self, limit=None, window_seconds=None):
        """改限额并清空计数；``None`` 恢复默认值。"""
        with self._lock:
            self.limit = (
                self.default_limit if limit is None else max(int(limit), 1)
            )
            self.window_seconds = (
                self.default_window_seconds
                if window_seconds is None
                else max(int(window_seconds), 1)
            )
            self._entries.clear()

    def reset(self):
        """只清空计数，保留当前限额（测试隔离用）。"""
        with self._lock:
            self._entries.clear()

    def consume(self, key, now=None):
        """记一次请求，返回 ``(allowed, retry_after_seconds)``。"""
        now = time.monotonic() if now is None else float(now)
        key = str(key or "unknown")
        with self._lock:
            window_start, count = self._entries.get(key, (now, 0))
            if now < window_start or now - window_start >= self.window_seconds:
                window_start, count = now, 0
            count += 1
            self._entries[key] = (window_start, count)
            if len(self._entries) > _RATE_LIMIT_MAX_KEYS:
                self._prune_locked(now)
            if count <= self.limit:
                return True, 0
            retry_after = int(
                math.ceil(window_start + self.window_seconds - now)
            )
            return False, max(retry_after, 1)

    def _prune_locked(self, now):
        stale = [
            key for key, (start, _count) in self._entries.items()
            if now - start >= self.window_seconds
        ]
        for key in stale:
            self._entries.pop(key, None)
        while len(self._entries) > _RATE_LIMIT_MAX_KEYS:
            self._entries.pop(next(iter(self._entries)))


#: 状态码与文案由 web_app 负责渲染；这里只给默认实例与测试钩子。
RATE_LIMITER = FixedWindowRateLimiter(limit=_env_rate_limit())


def configure_rate_limit(limit=None, window_seconds=None):
    """配置默认限流器（测试或部署脚本用；环境变量在导入时读取）。"""
    RATE_LIMITER.configure(limit=limit, window_seconds=window_seconds)


def reset_rate_limiter():
    """清空当前计数（测试用）。"""
    RATE_LIMITER.reset()
