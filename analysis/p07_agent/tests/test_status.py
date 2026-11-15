"""四状态契约测试：PRODUCT_SPEC.md §5（HappinessJo 2026-11-15 按建议默认签字，
见 travel-agent-run/optimization/state/G0_GATE.md §9）。

覆盖：四个状态词、§5.4 迁移映射、非法值兜底、reasons 形状、
what_verified 固定免责句，以及 run_agent() 四条返回路径。
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# T2.7 结果缓存默认开启；本模块用 patch 替换模型/路线夹具，必须关闭缓存避免跨用例串结果。
os.environ["P07_RESULT_CACHE"] = "0"

import agent
import status
import trace_log


def _verified_route():
    return {
        "proposal": {"node_ids": ["a", "b", "c"], "explanation": "路线", "uncertainties": []},
        "validation": {
            "valid": True,
            "fully_verified": True,
            "segments": [
                {"from_name": "A", "to_name": "B", "source_doc_ids": ["CL-T-01"]},
                {"from_name": "B", "to_name": "C", "source_doc_ids": ["CL-T-01"]},
            ],
            "missing_connections": [],
            "cross_doc_transitions": 0,
        },
        "message": "路线连接已通过图谱核验。",
    }


def _partial_route():
    return {
        "proposal": {"node_ids": ["a", "b"], "explanation": "路线", "uncertainties": []},
        "validation": {
            "valid": False,
            "fully_verified": False,
            "segments": [],
            "missing_connections": [{"from_node_id": "a", "to_node_id": "b"}] * 2,
            "cross_doc_transitions": 0,
        },
        "message": "路线连接缺失",
    }


class StatusContractTests(unittest.TestCase):
    def test_contract_has_exactly_four_statuses(self):
        self.assertEqual(
            set(status.STATUS_VALUES),
            {"verified", "partial", "clarify", "error"},
        )
        self.assertEqual(len(status.STATUS_VALUES), 4)
        for forbidden in ("complete", "working", "reply", "success", "failed"):
            self.assertNotIn(forbidden, status.STATUS_SET)

    def test_normalize_status_accepts_contract_values(self):
        for value in status.STATUS_VALUES:
            with self.subTest(value=value):
                self.assertEqual(status.normalize_status(value), value)
                self.assertFalse(status.is_contract_violation(value))

    def test_normalize_status_migrates_legacy_success_to_verified(self):
        legacy = "complete"
        self.assertEqual(status.normalize_status(legacy), "verified")
        self.assertFalse(status.is_contract_violation(legacy))

    def test_normalize_status_migrates_legacy_greeting_to_clarify(self):
        self.assertEqual(status.normalize_status("reply"), "clarify")
        self.assertFalse(status.is_contract_violation("reply"))

    def test_normalize_status_falls_back_to_error_and_flags_violation(self):
        for value in (None, "", "working", "success", "failed", "Verified", 3):
            with self.subTest(value=value):
                self.assertEqual(status.normalize_status(value), "error")
                self.assertTrue(status.is_contract_violation(value))

    def test_reason_code_must_be_contract_code_and_text_non_empty(self):
        reason = status.make_reason("missing_slot", "请补充游玩天数。")
        self.assertEqual(set(reason), {"code", "text"})
        self.assertEqual(reason["code"], "missing_slot")
        self.assertEqual(reason["text"], "请补充游玩天数。")
        with self.assertRaises(ValueError):
            status.make_reason("not_a_contract_code", "未知原因")
        with self.assertRaises(ValueError):
            status.make_reason("missing_slot", "   ")

    def test_reasons_shape_from_pairs(self):
        reasons = status.build_reasons([
            ("missing_connection", "第 1 段没有找到来源"),
            ("cross_doc", "有 1 处跨来源文档跳转"),
        ])
        self.assertEqual(len(reasons), 2)
        for reason in reasons:
            self.assertEqual(set(reason), {"code", "text"})
            self.assertIsInstance(reason["code"], str)
            self.assertIsInstance(reason["text"], str)
            self.assertIn(reason["code"], status.REASON_CODES)
        self.assertEqual(status.build_reasons([]), [])

    def test_what_verified_reports_real_segments(self):
        payload = status.build_what_verified("verified", _verified_route())
        self.assertEqual(payload["scope"], "segment_connectivity")
        self.assertEqual(payload["segments_checked"], 2)
        self.assertEqual(payload["source_doc_ids"], ["CL-T-01"])
        self.assertIn(status.DISCLAIMER, payload["note"])

    def test_what_verified_clarify_has_none_scope(self):
        payload = status.build_what_verified("clarify", None)
        self.assertEqual(payload["scope"], "none")
        self.assertEqual(payload["segments_checked"], 0)
        self.assertEqual(payload["source_doc_ids"], [])
        self.assertEqual(payload["note"], status.CLARIFY_NOTE)

    def test_what_verified_error_has_none_scope(self):
        payload = status.build_what_verified("error", {"proposal": {"node_ids": []}})
        self.assertEqual(payload["scope"], "none")
        self.assertEqual(payload["segments_checked"], 0)
        self.assertEqual(payload["source_doc_ids"], [])
        self.assertEqual(payload["note"], status.ERROR_NOTE)

    def test_what_verified_verified_without_route_is_none_scope(self):
        # 迁移口径：旧 complete 的纯地点查询也归 verified，但没有路线分段可核验。
        payload = status.build_what_verified("verified", None)
        self.assertEqual(payload["scope"], "none")
        self.assertEqual(payload["segments_checked"], 0)
        self.assertEqual(payload["source_doc_ids"], [])
        self.assertIn(status.DISCLAIMER, payload["note"])

    def test_what_verified_partial_keeps_fixed_sentence(self):
        payload = status.build_what_verified("partial", _partial_route())
        self.assertIn(status.DISCLAIMER, payload["note"])
        # 只有真的核验过的分段才计数；缺失段只在 reasons 里计数。
        self.assertEqual(payload["segments_checked"], 0)


class AgentStatusIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = patch.object(trace_log, "SESSION_DIR", Path(self.temp.name))
        directory.start()
        self.addCleanup(directory.stop)
        self.ok = {"status": "ok", "explanation": "", "question": ""}
        self.plan = {"decision": "query_graph", "request_type": "plan",
                     "reason": "需要规划", "response": ""}
        self.selection = {"tools": ["get_conditions"], "search_mode": "none",
                          "search_keyword": "", "reason": "查建议"}
        self.stop = {"tools": [], "search_mode": "none",
                     "search_keyword": "", "reason": "结束"}

    def _intent(self, **overrides):
        intent = {"scenic_area": "长隆", "duration_days": 1,
                  "traveler_profiles": [], "preferences": [], "constraints": []}
        intent.update(overrides)
        return intent

    def _run_plan(self, route, intent=None):
        with patch.object(agent, "parse_intent", return_value=intent or self._intent()), \
             patch.object(agent, "decide_next_step", return_value=self.plan), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[self.selection, self.stop]), \
             patch.object(agent, "find_relevant_conditions", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route):
            return agent.run_agent("我和父母去长隆玩一天")

    def assert_contract_result(self, result):
        self.assertIn(result["status"], status.STATUS_SET)
        self.assertIn("reasons", result)
        self.assertIsInstance(result["reasons"], list)
        self.assertIsInstance(result["what_verified"], dict)
        self.assertEqual(
            set(result["what_verified"]),
            {"scope", "segments_checked", "source_doc_ids", "note"},
        )

    def test_run_agent_verified_path(self):
        result = self._run_plan(_verified_route())
        self.assert_contract_result(result)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["what_verified"]["scope"], "segment_connectivity")
        self.assertEqual(result["what_verified"]["segments_checked"], 2)
        self.assertEqual(result["what_verified"]["source_doc_ids"], ["CL-T-01"])
        self.assertIn(status.DISCLAIMER, result["what_verified"]["note"])
        events = [json.loads(line) for line in
                  (Path(self.temp.name) / result["trace_file"])
                  .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[-1]["final_answer"]["status"], "verified")

    def test_run_agent_partial_path(self):
        result = self._run_plan(_partial_route())
        self.assert_contract_result(result)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["reasons"])
        self.assertEqual(result["reasons"][0]["code"], "missing_connection")
        self.assertIn("2 处缺失", result["reasons"][0]["text"])
        self.assertIn("2 处缺失", result["message"])
        self.assertIn(result["what_verified"]["scope"],
                      {"segment_connectivity", "none"})
        self.assertIn(status.DISCLAIMER, result["what_verified"]["note"])

    def test_run_agent_poi_list_does_not_claim_segment_verification(self):
        decision = {"decision": "query_graph", "request_type": "info",
                    "reason": "查询景点", "response": ""}
        selection = {"tools": ["search_poi"], "search_mode": "all_pois",
                     "search_keyword": "", "reason": "列出地点"}
        poi = [{"name": "熊猫村", "node_id": "P", "scenic_area": "长隆"}]
        with patch.object(agent, "parse_intent",
                          return_value=self._intent(duration_days=None)), \
             patch.object(agent, "decide_next_step", return_value=decision), \
             patch.object(agent, "select_tools", side_effect=[selection, self.stop]), \
             patch.object(agent, "search_poi", return_value=poi):
            result = agent.run_agent("长隆有哪些景点")
        self.assert_contract_result(result)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["what_verified"]["scope"], "none")
        self.assertEqual(result["what_verified"]["segments_checked"], 0)
        self.assertIn(status.DISCLAIMER, result["what_verified"]["note"])

    def test_run_agent_clarify_missing_slot(self):
        decision = dict(self.plan)
        with patch.object(agent, "parse_intent",
                          return_value=self._intent(duration_days=None)), \
             patch.object(agent, "decide_next_step", return_value=decision), \
             patch.object(agent, "select_tools") as selector:
            result = agent.run_agent("我去长隆玩")
        self.assert_contract_result(result)
        self.assertEqual(result["status"], "clarify")
        self.assertEqual(result["reasons"][0]["code"], "missing_slot")
        self.assertEqual(result["what_verified"]["scope"], "none")
        self.assertIn("未做连接核验", result["what_verified"]["note"])
        selector.assert_not_called()

    def test_run_agent_clarify_unsupported_area(self):
        with patch.object(agent, "parse_intent",
                          return_value=self._intent(scenic_area="华山")), \
             patch.object(agent, "decide_next_step", return_value=self.plan), \
             patch.object(agent, "select_tools") as selector:
            result = agent.run_agent("去华山玩一天")
        self.assert_contract_result(result)
        self.assertEqual(result["status"], "clarify")
        self.assertEqual(result["reasons"][0]["code"], "unsupported_area")
        self.assertEqual(result["what_verified"]["scope"], "none")
        selector.assert_not_called()

    def test_run_agent_greeting_is_clarify(self):
        reply = {"decision": "reply", "request_type": "other",
                 "reason": "普通问候，不需要查询图谱", "response": "你好！我可以帮你规划游览路线。"}
        with patch.object(agent, "parse_intent",
                          return_value=self._intent(scenic_area=None, duration_days=None)), \
             patch.object(agent, "decide_next_step", return_value=reply), \
             patch.object(agent, "select_tools") as selector:
            result = agent.run_agent("你好")
        self.assert_contract_result(result)
        self.assertEqual(result["status"], "clarify")
        self.assertTrue(result["reasons"])
        self.assertIn(result["reasons"][0]["code"], status.REASON_CODES)
        self.assertIn("问候", result["reasons"][0]["text"])
        self.assertEqual(result["what_verified"]["scope"], "none")
        selector.assert_not_called()

    def test_run_agent_error_path(self):
        with patch.object(agent, "parse_intent", side_effect=RuntimeError("模型服务不可达")):
            result = agent.run_agent("去长隆玩一天")
        self.assert_contract_result(result)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reasons"][0]["code"], "model_error")
        self.assertIn("模型服务不可达", result["reasons"][0]["text"])
        self.assertEqual(result["what_verified"]["scope"], "none")
        self.assertNotIn("contract_violation", result)

    def test_missing_status_is_contract_violation(self):
        result = {"status": None, "message": "", "error": "", "route": None,
                  "reasons": [], "what_verified": None}
        agent._finalize_result_status(result)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["contract_violation"], 1)
        self.assertTrue(result["reasons"])

    def test_legacy_status_is_migrated_not_treated_as_violation(self):
        result = {"status": "complete", "message": "", "error": "", "route": None,
                  "reasons": [], "what_verified": None}
        agent._finalize_result_status(result)
        self.assertEqual(result["status"], "verified")
        self.assertNotIn("contract_violation", result)
        self.assertEqual(result["reasons"], [])


if __name__ == "__main__":
    unittest.main()
