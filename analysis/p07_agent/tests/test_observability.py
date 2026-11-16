# -*- coding: utf-8 -*-
"""T5.1 可观测性：request-id、JSONL 日志、脱敏边界与模型交互计数。

全部离线、确定性：只 mock ``web_app.run_agent``，不调用模型/网络；
日志写临时目录，用例结束由 ``TemporaryDirectory`` + ``shutdown_logging`` 清理。
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 与其他 Web 测试一致：这里只测日志接线，关闭 agent 结果缓存避免串用例。
os.environ["P07_RESULT_CACHE"] = "0"

import observability  # noqa: E402
import web_app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
QUERY = "我想去长隆欢乐世界玩一天，带六岁孩子，少走路。"
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def _event(event_type, **fields):
    return {"turn": 1, "event_type": event_type, **fields}


def _result(trace_events=None, status="verified"):
    return {
        "query": QUERY,
        "status": status,
        "intent": {"scenic_area": "长隆", "duration_days": 1},
        "decision": None,
        "tool_selection": None,
        "tool_decisions": [],
        "suggestions": [],
        "route": None,
        "poi_results": None,
        "poi_list_all": False,
        "message": "",
        "error": "",
        "trace_file": "",
        "trace_json": json.dumps(trace_events or [], ensure_ascii=False),
        "trace_error": "",
        "alternatives": [],
        "itinerary": None,
        "needs_followup": False,
        "what_verified": None,
        "reasons": [],
    }


def _log_path(directory):
    return Path(directory) / observability.LOG_FILENAME


def _read_events(directory):
    path = _log_path(directory)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _log_text(directory):
    path = _log_path(directory)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _wait_for_event(directory, event_name, timeout=5.0):
    """等后台 job 线程写完事件；测试只依赖轮询，不依赖固定 sleep。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = _read_events(directory)
        matches = [event for event in events if event.get("event") == event_name]
        if matches:
            return matches[-1], events
        time.sleep(0.01)
    raise AssertionError(f"{timeout}s 内没有等到日志事件 {event_name!r}")


def _job_id(location):
    match = re.search(r"/run/([0-9a-f]{32})", location or "")
    if not match:
        raise AssertionError(f"Location 不是任务进度页：{location!r}")
    return match.group(1)


def _wait_done(client, location, timeout=5.0):
    job_id = _job_id(location)
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/run/{job_id}/json")
        if response.status_code == 200 and (response.get_json() or {}).get("done"):
            return job_id
        time.sleep(0.01)
    raise AssertionError(f"任务 {job_id} 在 {timeout}s 内没有完成")


class _TempLogTestCase(unittest.TestCase):
    """每个用例独立日志目录；先关 handler 再删目录（Windows 文件占用）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)
        observability.configure_logging(self.log_dir, retention_days=2, max_bytes=64 * 1024)
        web_app._clear_jobs()
        web_app._clear_result_cache()
        # cleanup 按后进先出执行：先关 handler，再删目录（Windows 文件占用）。
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(web_app._clear_result_cache)
        self.addCleanup(web_app._clear_jobs)
        self.addCleanup(observability.shutdown_logging)


class RequestIdTests(_TempLogTestCase):
    def test_new_request_id_is_unique_and_url_safe(self):
        request_ids = {observability.new_request_id() for _ in range(50)}
        self.assertEqual(len(request_ids), 50)
        for request_id in request_ids:
            self.assertRegex(request_id, REQUEST_ID_RE)

    def test_set_request_id_rejects_unsafe_header(self):
        accepted = observability.set_request_id("abc-123-XYZ")
        self.assertEqual(accepted, "abc-123-XYZ")
        self.assertEqual(observability.get_request_id(), "abc-123-XYZ")

        generated = observability.set_request_id("bad id! <script>")
        self.assertNotEqual(generated, "bad id! <script>")
        self.assertRegex(generated, REQUEST_ID_RE)

        generated_again = observability.set_request_id(None)
        self.assertNotEqual(generated_again, generated)
        self.assertRegex(generated_again, REQUEST_ID_RE)


class ModelCallCountTests(unittest.TestCase):
    def test_counts_known_model_events(self):
        events = [
            _event("user_input", user_request="x"),
            _event("intent", observation={}),
            _event("decision", decision={}),
            _event("tool_call", tool="select_tools", observation={}),
            _event("tool_call", tool="get_conditions", observation={}),
            _event("requirement_check", observation={}),
            _event("plan_check", observation={}),
            _event("final_answer", final_answer={}),
        ]
        self.assertEqual(observability.count_model_calls(events), 5)
        self.assertEqual(observability.count_model_calls(json.dumps(events)), 5)

    def test_fast_paths_do_not_count_as_model_calls(self):
        events = [
            _event("intent", observation={}),
            _event("fast_decision", decision={}),
            _event("decision", decision={}),
            _event("tool_call", tool="select_tools", observation={}),
            _event("fast_requirement_check", observation={}),
            _event("requirement_check", observation={}),
            _event("fast_plan_check", observation={}),
            _event("plan_check", observation={}),
        ]
        # intent + 一轮 select_tools；fast_* 分支是确定性规则，不计模型调用。
        self.assertEqual(observability.count_model_calls(events), 2)

    def test_fallback_events_count_as_one_attempt_each(self):
        events = [
            _event("intent_call_error", observation={}),
            _event("decision", decision={}),
            _event("requirement_check_fallback", observation={}),
            _event("requirement_check", observation={}),
            _event("plan_check_fallback", observation={}),
            _event("plan_check", observation={}),
        ]
        # intent 失败 1 + decision 1 + requirement 1 + plan 1。
        self.assertEqual(observability.count_model_calls(events), 4)

    def test_empty_or_invalid_trace_returns_zero(self):
        self.assertEqual(observability.count_model_calls(None), 0)
        self.assertEqual(observability.count_model_calls([]), 0)
        self.assertEqual(observability.count_model_calls("not-json"), 0)


class LoggingConfigTests(_TempLogTestCase):
    def test_default_log_dir_is_outside_repo(self):
        default = observability.default_log_dir()
        self.assertFalse(observability.is_within_repo(default))
        self.assertEqual(default.parent, REPO_ROOT.parent)

    def test_env_log_dir_is_used_and_outside_repo(self):
        with patch.dict(os.environ, {"P07_LOG_DIR": str(self.log_dir)}):
            observability.shutdown_logging()
            resolved = observability.configure_logging()
        self.assertIsNotNone(resolved)
        self.assertEqual(Path(resolved).resolve(), self.log_dir.resolve())
        self.assertFalse(observability.is_within_repo(resolved))

    def test_repo_internal_log_dir_falls_back_outside_repo(self):
        inside = REPO_ROOT / "runtime" / "_p07_logs_should_not_exist"
        resolved = observability.configure_logging(log_dir=inside)
        self.assertIsNotNone(resolved)
        self.assertFalse(observability.is_within_repo(resolved))
        self.assertFalse(inside.exists(), "仓库内不应创建日志目录")

    def test_rotation_and_retention_are_configurable(self):
        observability.configure_logging(self.log_dir, retention_days=3, max_bytes=4096)
        status = observability.logging_status()
        self.assertEqual(Path(status["log_dir"]).resolve(), self.log_dir.resolve())
        self.assertEqual(status["when"], "midnight")
        self.assertEqual(status["backup_count"], 3)
        self.assertEqual(status["max_bytes"], 4096)
        self.assertTrue(status["utc"])

    def test_size_cap_actually_rotates_file(self):
        observability.configure_logging(self.log_dir, retention_days=2, max_bytes=220)
        for index in range(20):
            observability.log_event(
                "rotation_probe", index=index, padding="x" * 40)
        backups = sorted(self.log_dir.glob(observability.LOG_FILENAME + ".*"))
        self.assertTrue(backups, "超过 max_bytes 后应产生轮转备份文件")
        self.assertTrue(_log_path(self.log_dir).exists())

    def test_log_event_never_raises(self):
        with patch.object(observability._logger, "log", side_effect=RuntimeError("boom")):
            observability.log_event("never_raises", value=1)


class LogEventPrivacyTests(_TempLogTestCase):
    def test_sensitive_fields_are_redacted_and_hashes_only(self):
        observability.set_request_id("abcdef1234567890")
        observability.log_event(
            "http_request", method="POST", path="/", status=303, duration_ms=7,
            error_type=None, query_sha256_12="a" * 12, query_len=len(QUERY))
        observability.log_event(
            "bad_payload",
            query=QUERY,
            user_text=QUERY,
            trace_json=json.dumps([{"user_request": QUERY}], ensure_ascii=False),
            cookie="session=demo-cookie",
            authorization="Bearer demo-token",
            api_key="sk-demo",
        )

        events = _read_events(self.log_dir)
        self.assertEqual(events[0]["request_id"], "abcdef1234567890")
        self.assertEqual(events[0]["event"], "http_request")
        self.assertEqual(events[0]["query_sha256_12"], "a" * 12)
        self.assertEqual(events[0]["query_len"], len(QUERY))

        second = events[1]
        for key in ("query", "user_text", "trace_json", "cookie", "authorization", "api_key"):
            self.assertNotIn(key, second)
        self.assertIn("redacted_fields", second)
        text = _log_text(self.log_dir)
        self.assertNotIn(QUERY, text)
        self.assertNotIn("sk-demo", text)
        self.assertNotIn("session=demo-cookie", text)


class WebObservabilityTests(_TempLogTestCase):
    def setUp(self):
        super().setUp()
        self._client = web_app.app.test_client()
        self.addCleanup(self._client.__exit__, None, None, None)
        self._client.__enter__()

    def test_request_id_header_is_unique_per_request(self):
        with patch.object(web_app, "run_agent", return_value=_result()):
            first = self._client.get("/")
            second = self._client.get("/")
            custom = self._client.get("/", headers={"X-Request-ID": "client-request-123"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_id = first.headers.get("X-Request-ID")
        second_id = second.headers.get("X-Request-ID")
        self.assertRegex(first_id, REQUEST_ID_RE)
        self.assertRegex(second_id, REQUEST_ID_RE)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(custom.headers.get("X-Request-ID"), "client-request-123")
        custom_events = [
            event for event in _read_events(self.log_dir)
            if event.get("request_id") == "client-request-123"
        ]
        self.assertTrue(custom_events)

    def test_post_logs_fingerprint_but_never_query_text(self):
        with patch.object(web_app, "run_agent", return_value=_result()):
            response = self._client.post("/", data={"query": QUERY})
            self.assertEqual(response.status_code, 303)
            request_id = response.headers.get("X-Request-ID")
            self.assertRegex(request_id, REQUEST_ID_RE)
            _wait_done(self._client, response.headers["Location"])

        events = _read_events(self.log_dir)
        requests = [
            event for event in events
            if event.get("event") == "http_request" and event.get("method") == "POST"
        ]
        self.assertEqual(len(requests), 1)
        event = requests[0]
        self.assertEqual(event["request_id"], request_id)
        self.assertEqual(event["path"], "/")
        self.assertEqual(event["status"], 303)
        self.assertIsInstance(event["duration_ms"], int)
        self.assertGreaterEqual(event["duration_ms"], 0)
        self.assertEqual(
            event["query_sha256_12"],
            hashlib.sha256(QUERY.encode("utf-8")).hexdigest()[:12],
        )
        self.assertEqual(event["query_len"], len(QUERY))
        self.assertNotIn(QUERY, _log_text(self.log_dir))

    def test_job_events_share_request_id_and_model_calls(self):
        trace_events = [
            _event("user_input", user_request=QUERY),
            _event("intent", observation={}),
            _event("decision", decision={}),
            _event("tool_call", tool="select_tools", observation={}),
            _event("final_answer", final_answer={}),
        ]
        with patch.object(web_app, "run_agent", return_value=_result(trace_events)):
            response = self._client.post("/", data={"query": QUERY})
            self.assertEqual(response.status_code, 303)
            request_id = response.headers.get("X-Request-ID")
            job_id = _wait_done(self._client, response.headers["Location"])

        started, _ = _wait_for_event(self.log_dir, "job_started")
        finished, events = _wait_for_event(self.log_dir, "job_finished")
        self.assertEqual(started["request_id"], request_id)
        self.assertEqual(started["job_id"], job_id)
        self.assertEqual(finished["request_id"], request_id)
        self.assertEqual(finished["job_id"], job_id)
        self.assertIsInstance(finished["model_calls"], int)
        self.assertEqual(finished["model_calls"], 3)
        self.assertEqual(finished["status"], "done")
        self.assertEqual(finished["result_status"], "verified")
        self.assertIsInstance(finished["duration_ms"], int)
        self.assertGreaterEqual(finished["duration_ms"], 0)
        self.assertNotIn(QUERY, _log_text(self.log_dir))

    def test_error_path_logs_request_id_and_error_type(self):
        with patch.object(web_app, "_resolve_view", side_effect=RuntimeError("boom")):
            response = self._client.get("/", query_string={"query": QUERY})

        self.assertEqual(response.status_code, 500)
        request_id = response.headers.get("X-Request-ID")
        self.assertRegex(request_id, REQUEST_ID_RE)

        events = _read_events(self.log_dir)
        errors = [
            event for event in events
            if event.get("event") == "http_request" and event.get("status") == 500
        ]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["request_id"], request_id)
        self.assertEqual(errors[0]["error_type"], "RuntimeError")
        text = _log_text(self.log_dir)
        self.assertNotIn(QUERY, text)
        self.assertNotIn("boom", text)

    def test_job_exception_logs_error_type_and_request_id(self):
        with patch.object(web_app, "run_agent", side_effect=RuntimeError("job boom")):
            response = self._client.post("/", data={"query": QUERY})
            self.assertEqual(response.status_code, 303)
            request_id = response.headers.get("X-Request-ID")
            _wait_done(self._client, response.headers["Location"])

        finished, events = _wait_for_event(self.log_dir, "job_finished")
        self.assertEqual(finished["request_id"], request_id)
        self.assertEqual(finished["status"], "error")
        self.assertEqual(finished["result_status"], "error")
        self.assertEqual(finished["error_type"], "RuntimeError")
        self.assertEqual(finished["model_calls"], 0)
        self.assertFalse(finished["model_calls_known"])
        self.assertNotIn(QUERY, _log_text(self.log_dir))
        self.assertNotIn("job boom", _log_text(self.log_dir))

    def test_existing_303_contract_still_holds(self):
        with patch.object(web_app, "run_agent", return_value=_result()):
            response = self._client.post("/", data={"query": QUERY})
            self.assertEqual(response.status_code, 303)
            self.assertRegex(
                response.headers.get("Location", ""),
                r"^/run/[0-9a-f]{32}\?view=visitor$",
            )
            self.assertRegex(response.headers.get("X-Request-ID", ""), REQUEST_ID_RE)
            _wait_done(self._client, response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
