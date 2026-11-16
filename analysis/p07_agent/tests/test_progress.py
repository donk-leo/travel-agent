# -*- coding: utf-8 -*-
"""T3.7 任务化提交流程：303 → 进度页 → 结果 / 错误页 + 进度 JSON。

只 mock ``web_app.run_agent``，不调用模型；用 Flask test client 走真实路由。
"""

import json
import os
import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 与 test_workflow 一致：本模块只测 Web 接线，关闭 agent 内部结果缓存。
os.environ["P07_RESULT_CACHE"] = "0"

import web_app  # noqa: E402

QUERY = "我想去长隆欢乐世界玩一天，喜欢刺激项目。"

PROGRESS_LABELS = {
    "intent": "解析需求",
    "tools": "查询图谱",
    "route": "规划路线",
    "verify": "核验行程",
}


def _event(stage, status, elapsed_ms):
    return {
        "stage": stage,
        "label": PROGRESS_LABELS[stage],
        "status": status,
        "elapsed_ms": elapsed_ms,
    }


def _result(**overrides):
    result = {
        "query": QUERY,
        "status": "verified",
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
        "trace_json": "",
        "trace_error": "",
        "alternatives": [],
        "itinerary": None,
        "needs_followup": False,
        "what_verified": None,
        "reasons": [],
    }
    result.update(overrides)
    return result


def _gate_runner(result, events, gate):
    """发完给定事件后阻塞在 gate 上，保证测试能在运行中读进度页。"""
    def runner(query, progress=None):
        for event in events:
            if progress is not None:
                progress(dict(event))
        gate.wait(5.0)
        return dict(result)
    return runner


def _csrf_token(client):
    """T5.2：POST 前先 GET 首页，取服务端注入的 hidden token（无 JS）。"""
    html = client.get("/").get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not match:
        raise AssertionError("首页缺少服务端注入的 csrf_token")
    return match.group(1)


def _post(client, data):
    payload = dict(data)
    payload["csrf_token"] = _csrf_token(client)
    return client.post("/", data=payload)


def _job_id(response):
    location = response.headers.get("Location", "")
    match = re.search(r"/run/([0-9a-f]{32})", location)
    if not match:
        raise AssertionError(f"Location 不是任务进度页：{location!r}")
    return match.group(1)


def _wait_done(testcase, client, job_id, timeout=5.0):
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


def _flatten_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _flatten_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_keys(item)


class ProgressFlowTests(unittest.TestCase):
    def setUp(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()
        # T5.2：限流是进程内状态，逐用例清空，避免与 T3.7 断言互相干扰。
        web_app._reset_rate_limiter()

    def tearDown(self):
        web_app._clear_jobs()
        web_app._clear_result_cache()
        web_app._reset_rate_limiter()

    def assert_no_external_resources(self, html):
        self.assertNotRegex(html, r'(?:src|href)=["\']https?://')
        self.assertNotRegex(html, r"<script[^>]+src=")
        self.assertIn("/static/style.css", html)

    # 1）POST 不再阻塞：303 + Location；线程仍在跑时进度页已返回四阶段。
    def test_post_returns_303_without_waiting_for_agent(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        events = [
            _event("intent", "start", 0),
            _event("intent", "done", 80),
            _event("tools", "start", 90),
        ]
        with patch.object(
            web_app, "run_agent", side_effect=_gate_runner(_result(), events, gate)
        ):
            with web_app.app.test_client() as client:
                token = _csrf_token(client)
                started = time.monotonic()
                response = client.post(
                    "/", data={"query": QUERY, "csrf_token": token}
                )
                elapsed = time.monotonic() - started
                self.assertEqual(response.status_code, 303)
                self.assertLess(elapsed, 1.0, "POST 仍在等模型结束")
                location = response.headers.get("Location", "")
                self.assertRegex(location, r"^/run/[0-9a-f]{32}\?view=visitor$")
                job_id = _job_id(response)

                page = client.get(location)
                self.assertEqual(page.status_code, 200)
                html = page.get_data(as_text=True)
                flat = re.sub(r"\s+", " ", html)
                self.assertIn("<ol class=\"stepper stepper--progress\"", html)
                for label in PROGRESS_LABELS.values():
                    self.assertIn(label, html)
                self.assertEqual(html.count('<li class="stepper__step stepper__step--'), 4)
                self.assertIn('<meta http-equiv="refresh" content="2">', html)
                self.assertIn('aria-live="polite"', html)
                self.assertIn('aria-current="step"', html)
                self.assertIn('id="progress-current-label">查询图谱', flat)
                self.assertIn("已用", flat)
                self.assert_no_external_resources(html)

                gate.set()
                _wait_done(self, client, job_id)

    # 2）verify 会重复出现：按 stage 合并，只渲染一个「核验行程」。
    def test_repeated_verify_events_are_merged_by_stage(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        events = [
            _event("intent", "start", 0),
            _event("intent", "done", 100),
            _event("tools", "start", 120),
            _event("tools", "done", 500),
            _event("route", "start", 520),
            _event("route", "done", 1500),
            _event("verify", "start", 1600),
            _event("verify", "done", 1800),
            _event("verify", "start", 1900),
            _event("verify", "done", 2100),
            {"stage": "unknown_stage", "label": "未知", "status": "done", "elapsed_ms": 2200},
        ]
        with patch.object(
            web_app, "run_agent", side_effect=_gate_runner(_result(), events, gate)
        ):
            with web_app.app.test_client() as client:
                response = _post(client, {"query": QUERY})
                job_id = _job_id(response)
                page = client.get(response.headers["Location"])
                html = page.get_data(as_text=True)
                self.assertEqual(html.count('data-stage="verify"'), 1)
                self.assertIn("核验行程", html)
                self.assertNotIn("未知", html)
                gate.set()
                payload = _wait_done(self, client, job_id)

        self.assertEqual(len(payload["stages"]), 4)
        self.assertEqual(
            [item["stage"] for item in payload["stages"]],
            ["intent", "tools", "route", "verify"],
        )
        verify = payload["stages"][3]
        self.assertEqual(verify["status"], "done")
        self.assertEqual(verify["label"], "核验行程")
        self.assertGreaterEqual(verify["elapsed_ms"], 2100)

    # 3）T2.7 的 verify 会在解析需求后先做一次需求预检；不能把「核验行程」提前点亮。
    def test_out_of_order_verify_does_not_finish_before_route(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        events = [
            _event("intent", "start", 0),
            _event("intent", "done", 100),
            _event("verify", "start", 110),
            _event("verify", "done", 200),
            _event("tools", "start", 210),
        ]
        with patch.object(
            web_app, "run_agent", side_effect=_gate_runner(_result(), events, gate)
        ):
            with web_app.app.test_client() as client:
                response = _post(client, {"query": QUERY})
                job_id = _job_id(response)
                html = client.get(response.headers["Location"]).get_data(as_text=True)
                verify_li = re.search(
                    r'<li[^>]*data-stage="verify"[^>]*>', html
                ).group(0)
                self.assertIn("stepper__step--waiting", verify_li)
                self.assertNotIn("stepper__step--done", verify_li)
                self.assertNotIn('aria-current="step"', verify_li)
                gate.set()
                _wait_done(self, client, job_id)

    # 4）完成 → 结果页；view / alt 保留；结果同时进入旧缓存路径。
    def test_completed_job_renders_result_with_view_alt_and_cache(self):
        result = _result(
            alternatives=[{
                "alt_id": "alt-1",
                "source_doc_id": "CL-T-01",
                "source_title": "示例来源",
                "node_names": ["北门", "小火车游览区"],
                "status": "partial",
                "reason": "跨来源",
                "segments": [],
            }],
        )
        with patch.object(web_app, "run_agent", return_value=result):
            with web_app.app.test_client() as client:
                response = _post(client, {"query": QUERY, "view": "auditor"})
                self.assertEqual(response.status_code, 303)
                self.assertIn("view=auditor", response.headers["Location"])
                job_id = _job_id(response)
                _wait_done(self, client, job_id)

                html = client.get(
                    f"/run/{job_id}?view=auditor&alt=alt-1"
                ).get_data(as_text=True)
                self.assertIn('data-status="verified"', html)
                self.assertIn("图谱连接核验通过", html)
                self.assertIn("评审视图", html)
                self.assertIn('data-alt-id="alt-1"', html)
                self.assertIn("当前高亮", html)
                self.assert_no_external_resources(html)

                visitor = client.get(f"/run/{job_id}?view=visitor").get_data(as_text=True)
                self.assertNotIn("intent JSON", visitor)
                self.assertIn('data-status="verified"', visitor)

                cached = client.get(
                    "/", query_string={"query": QUERY, "view": "auditor"}
                ).get_data(as_text=True)
                self.assertIn("复用上次结果（未重新调用模型）", cached)

    # 4）线程异常 → 200 错误页 + 重试表单，query 回填，不泄露原始异常。
    def test_thread_exception_renders_retry_form(self):
        with patch.object(web_app, "run_agent", side_effect=RuntimeError("boom-secret")):
            with web_app.app.test_client() as client:
                response = _post(client, {"query": QUERY})
                job_id = _job_id(response)
                payload = _wait_done(self, client, job_id)
                self.assertEqual(payload["status"], "error")
                self.assertTrue(payload["error"])

                page = client.get(response.headers["Location"])
                html = page.get_data(as_text=True)
                self.assertEqual(page.status_code, 200)
                self.assertIn("处理失败", html)
                self.assertIn("重新提交", html)
                self.assertIn('name="query"', html)
                self.assertIn(QUERY, html)
                self.assertNotIn("boom-secret", html)
                self.assert_no_external_resources(html)

    # 5）后端返回 status=error → 同样走错误页，不 500。
    def test_result_status_error_renders_retry_form(self):
        result = _result(
            status="error",
            message="模型暂时不可用，请稍后重试。",
            reasons=[{"code": "model_error", "text": "本次没有生成行程。"}],
        )
        with patch.object(web_app, "run_agent", return_value=result):
            with web_app.app.test_client() as client:
                response = _post(client, {"query": QUERY})
                job_id = _job_id(response)
                _wait_done(self, client, job_id)
                page = client.get(response.headers["Location"])
                html = page.get_data(as_text=True)
                self.assertEqual(page.status_code, 200)
                self.assertIn("处理失败", html)
                self.assertIn("模型暂时不可用", html)
                self.assertIn("本次没有生成行程。", html)
                self.assertIn(QUERY, html)

    # 6）未知 job → 回首页 + notice，不 500。
    def test_unknown_job_redirects_home_with_notice(self):
        with web_app.app.test_client() as client:
            response = client.get("/run/" + "0" * 32, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn("任务已过期，请重新提交", html)
            self.assertIn("说说你的行程", html)
            self.assert_no_external_resources(html)

    # 7）TTL 过期任务同样回首页 + notice。
    def test_expired_job_is_purged(self):
        job_id = web_app._create_job(QUERY, "visitor")
        web_app._JOBS[job_id]["created_at"] -= web_app.JOB_TTL_SECONDS + 1
        with web_app.app.test_client() as client:
            response = client.get(f"/run/{job_id}")
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.headers["Location"].startswith("/"))
            page = client.get(response.headers["Location"])
            self.assertIn("任务已过期，请重新提交", page.get_data(as_text=True))
            self.assertEqual(client.get(f"/run/{job_id}/json").status_code, 404)

    # 8）JSON 结构固定，且不含 intent / trace / 工具决策 / 路线明细。
    def test_json_endpoint_structure_and_no_leak(self):
        events = [
            _event("intent", "start", 0),
            _event("intent", "done", 10),
            _event("tools", "start", 20),
            _event("tools", "done", 30),
            _event("route", "start", 40),
            _event("route", "done", 50),
            _event("verify", "start", 60),
            _event("verify", "done", 70),
        ]
        with patch.object(web_app, "run_agent", return_value=_result()):
            with web_app.app.test_client() as client:
                response = _post(client, {"query": QUERY})
                job_id = _job_id(response)
                payload = _wait_done(self, client, job_id)

                self.assertEqual(
                    set(payload),
                    {"status", "stages", "elapsed_s", "done", "error"},
                )
                self.assertEqual(len(payload["stages"]), 4)
                for item in payload["stages"]:
                    self.assertEqual(
                        set(item), {"stage", "label", "status", "elapsed_ms"}
                    )
                self.assertIsInstance(payload["elapsed_s"], (int, float))
                self.assertTrue(payload["done"])
                self.assertIsNone(payload["error"])

                raw = client.get(f"/run/{job_id}/json").get_data(as_text=True)
                keys = set(_flatten_keys(json.loads(raw)))
                self.assertFalse(
                    {"intent", "trace_json", "tool_decisions", "route", "result"} & keys
                )
                self.assertNotIn("scenic_area", raw)

                unknown = client.get("/run/" + "f" * 32 + "/json")
                self.assertEqual(unknown.status_code, 404)
                self.assertIn("error", unknown.get_json())

    # 9）无外部资源：首页 / 进度页 / 错误页都只引用本地样式。
    def test_pages_have_no_external_resources(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        with patch.object(
            web_app, "run_agent",
            side_effect=_gate_runner(_result(status="error"), [], gate),
        ):
            with web_app.app.test_client() as client:
                home = client.get("/")
                self.assertEqual(home.status_code, 200)
                self.assert_no_external_resources(home.get_data(as_text=True))

                response = _post(client, {"query": QUERY})
                job_id = _job_id(response)
                progress = client.get(response.headers["Location"])
                self.assertEqual(progress.status_code, 200)
                self.assert_no_external_resources(progress.get_data(as_text=True))

                gate.set()
                _wait_done(self, client, job_id)
                error_page = client.get(response.headers["Location"])
                self.assertEqual(error_page.status_code, 200)
                self.assert_no_external_resources(error_page.get_data(as_text=True))

    # 10）任务表最多 16 条，超出淘汰最旧。
    def test_job_store_is_capped(self):
        job_ids = [web_app._create_job(f"{QUERY} #{index}", "visitor") for index in range(20)]
        self.assertLessEqual(web_app._job_count(), 16)
        self.assertNotIn(job_ids[0], web_app._JOBS)
        self.assertIn(job_ids[-1], web_app._JOBS)


if __name__ == "__main__":
    unittest.main()
