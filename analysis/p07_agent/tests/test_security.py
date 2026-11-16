# -*- coding: utf-8 -*-
"""T5.2 安全与隐私：默认绑定、CSRF（无 JS）、昂贵接口限流、保留期。

只 mock ``web_app.run_agent``，不调用模型/网络；用 Flask test client 走真实
GET → 表单隐藏字段 → POST → 303 流程。模板不在本任务白名单内，token 由
``web_app`` 在 HTML 响应中服务端注入，因此这里不依赖任何前端脚本。
"""

import os
import re
import sys
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 与 test_workflow / test_progress 一致：只测 Web 接线，关闭 agent 内部结果缓存。
os.environ["P07_RESULT_CACHE"] = "0"

import security  # noqa: E402
import web_app  # noqa: E402

QUERY = "带孩子去长隆玩一天，少走路。"
CSRF_INPUT_RE = re.compile(
    r'<input type="hidden" name="csrf_token" value="([^"]+)">'
)
JOB_PATH_RE = re.compile(r"^/run/[0-9a-f]{32}\?view=visitor$")


def _result(**overrides):
    result = {
        "query": QUERY,
        "status": "verified",
        "intent": {"scenic_area": "长隆", "duration_days": 1},
        "decision": None,
        "tool_decisions": [],
        "suggestions": [],
        "route": None,
        "poi_results": None,
        "poi_list_all": False,
        "message": "",
        "error": "",
        "trace_file": "",
        "trace_json": "",
        "needs_followup": False,
        "reasons": [],
    }
    result.update(overrides)
    return result


def _csrf_token(client):
    """模拟无 JS 浏览器：GET 首页，读出服务端注入的隐藏字段。"""
    html = client.get("/").get_data(as_text=True)
    match = CSRF_INPUT_RE.search(html)
    if not match:
        raise AssertionError("首页没有服务端渲染的 csrf_token 隐藏字段")
    return match.group(1)


def _post(client, data):
    payload = dict(data)
    payload["csrf_token"] = _csrf_token(client)
    return client.post("/", data=payload)


def _wait_done(testcase, client, location, timeout=5.0):
    match = re.search(r"/run/([0-9a-f]{32})", location or "")
    if not match:
        testcase.fail(f"Location 不是任务进度页：{location!r}")
    job_id = match.group(1)
    deadline = time.time() + timeout
    payload = None
    while time.time() < deadline:
        response = client.get(f"/run/{job_id}/json")
        if response.status_code == 200:
            payload = response.get_json()
            if payload and payload.get("done"):
                return payload
        time.sleep(0.01)
    testcase.fail(f"任务 {job_id} 在 {timeout}s 内没有完成：{payload!r}")


class SecurityConfigTests(unittest.TestCase):
    def test_default_host_is_loopback_and_debug_is_off(self):
        self.assertEqual(web_app.DEFAULT_HOST, "127.0.0.1")
        with patch.object(web_app.app, "run") as run:
            web_app._serve()
        run.assert_called_once()
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs.get("host"), "127.0.0.1")
        self.assertIs(kwargs.get("debug"), False)
        self.assertNotEqual(kwargs.get("host"), "0.0.0.0")

    def test_session_cookie_flags_and_lifetime(self):
        self.assertIs(web_app.app.config["SESSION_COOKIE_HTTPONLY"], True)
        self.assertEqual(web_app.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertEqual(
            web_app.app.config["PERMANENT_SESSION_LIFETIME"],
            timedelta(minutes=30),
        )
        with web_app.app.test_client() as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Expires=", cookie)
        # 不额外下发明文 CSRF cookie；token 只在签名 session 与表单隐藏字段里。
        cookies = response.headers.getlist("Set-Cookie")
        cookie_names = [item.split("=", 1)[0].strip() for item in cookies]
        self.assertNotIn("csrf_token", cookie_names)

    def test_get_home_has_exactly_one_hidden_csrf_token(self):
        with web_app.app.test_client() as client:
            html = client.get("/").get_data(as_text=True)
        self.assertEqual(html.count('name="csrf_token"'), 1)
        self.assertEqual(len(CSRF_INPUT_RE.findall(html)), 1)
        token = CSRF_INPUT_RE.search(html).group(1)
        self.assertGreaterEqual(len(token), 32)
        self.assertNotIn("<", token)
        self.assertNotIn(">", token)

    def test_csrf_token_is_stable_per_session_and_differs_between_clients(self):
        with web_app.app.test_client() as first_client:
            first = _csrf_token(first_client)
            second = _csrf_token(first_client)
        with web_app.app.test_client() as another_client:
            other = _csrf_token(another_client)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)


class CsrfProtectionTests(unittest.TestCase):
    def setUp(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()
        web_app._reset_rate_limiter()

    def tearDown(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()
        web_app._reset_rate_limiter()

    def test_post_without_token_is_rejected_without_job(self):
        with patch.object(web_app, "run_agent") as runner:
            with web_app.app.test_client() as client:
                response = client.post("/", data={"query": QUERY})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.mimetype, "text/html")
        self.assertIn("提交校验失败", response.get_data(as_text=True))
        runner.assert_not_called()
        self.assertEqual(web_app._job_count(), 0)

    def test_post_with_wrong_token_is_rejected_without_job(self):
        with patch.object(web_app, "run_agent") as runner:
            with web_app.app.test_client() as client:
                response = client.post(
                    "/",
                    data={"query": QUERY, "csrf_token": "not-the-real-token"},
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn("提交校验失败", response.get_data(as_text=True))
        runner.assert_not_called()
        self.assertEqual(web_app._job_count(), 0)

    def test_no_js_flow_get_token_then_post_returns_303_and_progress(self):
        with patch.object(web_app, "run_agent", return_value=_result()) as runner:
            with web_app.app.test_client() as client:
                token = _csrf_token(client)
                response = client.post(
                    "/", data={"query": QUERY, "csrf_token": token}
                )
                self.assertEqual(response.status_code, 303)
                location = response.headers["Location"]
                self.assertRegex(location, JOB_PATH_RE)
                self.assertNotIn(token, location)
                self.assertNotIn("csrf_token", location)
                _wait_done(self, client, location)
                page = client.get(location)
        self.assertEqual(page.status_code, 200)
        self.assertIn("图谱连接核验通过", page.get_data(as_text=True))
        runner.assert_called_once()

    def test_reset_action_also_requires_token(self):
        with web_app.app.test_client() as client:
            rejected = client.post("/", data={"action": "reset"})
            self.assertEqual(rejected.status_code, 400)
            token = _csrf_token(client)
            accepted = client.post(
                "/", data={"action": "reset", "csrf_token": token}
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertIn("已开始新需求", accepted.get_data(as_text=True))
        self.assertEqual(web_app._job_count(), 0)


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()
        web_app._configure_rate_limit(None)
        web_app._reset_rate_limiter()

    def tearDown(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()
        web_app._configure_rate_limit(None)
        web_app._reset_rate_limiter()

    def test_expensive_post_is_rate_limited_but_get_is_not(self):
        web_app._configure_rate_limit(1)
        with patch.object(web_app, "run_agent", return_value=_result()) as runner:
            with web_app.app.test_client() as client:
                first = _post(client, {"query": QUERY})
                self.assertEqual(first.status_code, 303)
                _wait_done(self, client, first.headers["Location"])

                second = _post(client, {"query": QUERY})
                self.assertEqual(second.status_code, 429)
                self.assertEqual(second.mimetype, "text/html")
                self.assertIn("提交太频繁", second.get_data(as_text=True))
                self.assertIn("Retry-After", second.headers)
                self.assertGreaterEqual(int(second.headers["Retry-After"]), 1)

                # GET 不消耗也不受限额影响；被拒的 POST 不创建任务。
                home = client.get("/")
                self.assertEqual(home.status_code, 200)
                self.assertIn('name="csrf_token"', home.get_data(as_text=True))
        self.assertEqual(web_app._job_count(), 1)
        runner.assert_called_once()

    def test_fixed_window_limiter_is_deterministic(self):
        limiter = security.FixedWindowRateLimiter(limit=2, window_seconds=60)
        self.assertEqual(limiter.consume("ip", now=0.0), (True, 0))
        self.assertEqual(limiter.consume("ip", now=1.0), (True, 0))
        allowed, retry_after = limiter.consume("ip", now=2.0)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)
        self.assertEqual(limiter.consume("other-ip", now=2.0), (True, 0))
        self.assertEqual(limiter.consume("ip", now=61.0), (True, 0))

    def test_rate_limit_env_override_and_fallback(self):
        with patch.dict(os.environ, {security.RATE_LIMIT_ENV: "3"}):
            self.assertEqual(security._env_rate_limit(), 3)
        for raw in ("0", "-1", "abc", ""):
            with patch.dict(os.environ, {security.RATE_LIMIT_ENV: raw}):
                self.assertEqual(
                    security._env_rate_limit(), security.RATE_LIMIT_PER_MINUTE
                )


class RetentionTests(unittest.TestCase):
    def setUp(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()

    def tearDown(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()

    def test_job_store_ttl_cleanup(self):
        job_id = web_app._create_job(QUERY, "visitor")
        self.assertIsNotNone(web_app._job_get(job_id))
        with web_app._JOBS_LOCK:
            web_app._JOBS[job_id]["created_at"] -= web_app.JOB_TTL_SECONDS + 1
            web_app._purge_jobs_locked()
        self.assertNotIn(job_id, web_app._JOBS)
        self.assertIsNone(web_app._job_get(job_id))
        self.assertEqual(web_app._job_count(), 0)

    def test_result_cache_ttl_cleanup(self):
        web_app._store_result(QUERY, {"status": "verified"})
        key = web_app._cache_key(QUERY)
        self.assertIsNotNone(web_app._get_cached_result(QUERY))
        with web_app._RESULT_CACHE_LOCK:
            stored_at, payload = web_app._RESULT_CACHE[key]
            web_app._RESULT_CACHE[key] = (
                stored_at - web_app.RESULT_CACHE_TTL_SECONDS - 1,
                payload,
            )
        self.assertIsNone(web_app._get_cached_result(QUERY))
        self.assertEqual(web_app._cache_size(), 0)


if __name__ == "__main__":
    unittest.main()
