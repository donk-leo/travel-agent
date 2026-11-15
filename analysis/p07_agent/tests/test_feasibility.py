"""T2.2 可行性闸测试：人群点数上限、用餐未知、时长模板与 guard 开关。

覆盖 DoD 1–3：老人/0–6 岁 ≤6、成人 ≤8、边界 6/7 与 8/9、多日分摊、
11:30–13:30 无餐饮标未知、总时长 >8h 警告、``FEASIBILITY_GUARD=0`` 完全跳过、
不改 ``node_ids``，以及所有假设都写进 uncertainties。
"""

import copy
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent
import feasibility
import status
import trace_log
from feasibility import MEAL_SLOT, apply_feasibility


AREA = "长隆"

#: 禁止出现在可行性判断里的编造内容：距离、票价、坐标、开放/营业时间。
FORBIDDEN_PATTERNS = (
    r"\d+(?:\.\d+)?\s*(?:公里|千米|km|KM)",
    r"\d+\s*元",
    r"(?:经度|纬度|经纬度)\s*[:：]?\s*\d",
    r"(?:开放时间|营业时间)\s*[:：]\s*(?:\d{1,2}[:：]\d{2}|\d{1,2}\s*点)",
)


def _node_ids(count):
    return [f"POI|{AREA}|点{index}" for index in range(1, count + 1)]


def _route(node_ids=None, count=0, day_plan=None, days=None):
    node_ids = list(node_ids) if node_ids is not None else _node_ids(count)
    proposal = {
        "node_ids": node_ids,
        "node_names": {node_id: node_id.split("|")[-1] for node_id in node_ids},
        "explanation": "路线",
        "uncertainties": [],
    }
    if day_plan is not None:
        proposal["day_plan"] = day_plan
    if days is not None:
        proposal["duration_days"] = days
    return {
        "proposal": proposal,
        "validation": {
            "valid": True, "fully_verified": True, "segments": [],
            "missing_connections": [], "cross_doc_transitions": 0,
        },
        "message": "路线连接已通过图谱核验。",
    }


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


class FeasibilityReportTests(unittest.TestCase):
    def test_senior_over_cap_becomes_partial(self):
        report = apply_feasibility(_route(count=7), ["老人"], [], 1)
        self.assertEqual(report["status_override"], "partial")
        self.assertEqual(report["caps"], {"max_stops": 6, "persona": "老人"})
        self.assertEqual(report["stop_count"], 7)
        self.assertEqual(report["day_counts"], [7])
        warning = report["warnings"][0]
        self.assertEqual(warning["code"], "constraint_conflict")
        self.assertIn(warning["code"], status.REASON_CODES)
        self.assertIn("上限为 6 个", warning["text"])
        self.assertIn("第 1 天", warning["text"])

    def test_senior_at_cap_keeps_status(self):
        report = apply_feasibility(_route(count=6), ["老人"], [], 1)
        self.assertIsNone(report["status_override"])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["day_counts"], [6])

    def test_child_under_six_uses_family_cap(self):
        report = apply_feasibility(_route(count=7), ["孩子"], [], 1)
        self.assertEqual(report["status_override"], "partial")
        self.assertEqual(report["caps"], {"max_stops": 6, "persona": "0–6 岁儿童"})

        # 关键词之外的年龄写法也要能识别；6 个不超、7 个超。
        self.assertIsNone(
            apply_feasibility(_route(count=6), [], ["带 3 岁小孩"], 1)["status_override"])
        self.assertEqual(
            apply_feasibility(_route(count=7), [], ["带 3 岁小孩"], 1)["status_override"],
            "partial",
        )
        # 不带老人/幼儿的人群仍按成人上限，不能滥杀。
        self.assertIsNone(
            apply_feasibility(_route(count=7), ["朋友"], [], 1)["status_override"])

    def test_adult_cap_boundary_eight_and_nine(self):
        at_cap = apply_feasibility(_route(count=8), [], [], 1)
        self.assertIsNone(at_cap["status_override"])
        self.assertEqual(at_cap["caps"], {"max_stops": 8, "persona": "成人"})

        over_cap = apply_feasibility(_route(count=9), [], [], 1)
        self.assertEqual(over_cap["status_override"], "partial")
        self.assertIn("超过 1 个", over_cap["warnings"][0]["text"])

    def test_day_plan_splits_cap_per_day(self):
        ids = _node_ids(11)
        ok_plan = [
            {"day": 1, "node_ids": ids[:6]},
            {"day": 2, "node_ids": ids[6:]},
        ]
        ok = apply_feasibility(
            _route(node_ids=ids, day_plan=ok_plan, days=2), ["老人"], [], 2)
        self.assertEqual(ok["day_counts"], [6, 5])
        self.assertIsNone(ok["status_override"])

        bad_plan = [
            {"day": 1, "node_ids": ids[:7]},
            {"day": 2, "node_ids": ids[7:]},
        ]
        bad = apply_feasibility(
            _route(node_ids=ids, day_plan=bad_plan, days=2), ["老人"], [], 2)
        self.assertEqual(bad["day_counts"], [7, 4])
        self.assertEqual(bad["status_override"], "partial")
        self.assertIn("第 1 天", bad["warnings"][0]["text"])

    def test_multi_day_even_split_counts(self):
        even = apply_feasibility(_route(count=12, days=2), ["老人"], [], 2)
        self.assertEqual(even["day_counts"], [6, 6])
        self.assertIsNone(even["status_override"])
        self.assertTrue(any("均分" in item for item in even["uncertainties"]))

        uneven = apply_feasibility(_route(count=14, days=2), ["老人"], [], 2)
        self.assertEqual(uneven["day_counts"], [7, 7])
        self.assertEqual(uneven["status_override"], "partial")

    def test_multiple_days_over_cap_are_all_listed(self):
        report = apply_feasibility(_route(count=14, days=2), ["老人"], [], 2)
        self.assertIn("另有 1 天也超过上限", report["warnings"][0]["text"])
        self.assertTrue(any("第 1 天 7 个、第 2 天 7 个" in item
                            for item in report["uncertainties"]))

    def test_lunch_window_without_food_node_is_unknown(self):
        ids = [
            "POI|长隆|长隆野生动物世界",
            "POI|长隆|熊猫村",
            "POI|长隆|4D影院",
        ]
        report = apply_feasibility(_route(node_ids=ids), [], [], 1)
        meal = report["meal"]
        self.assertFalse(meal["inserted"])
        self.assertEqual(meal["slot"], MEAL_SLOT)
        self.assertIn("没有图谱标注的餐饮节点", meal["note"])
        self.assertNotIn("熊猫餐厅", meal["note"])
        self.assertTrue(any(
            "餐饮" in item and "需现场确认" in item for item in report["uncertainties"]))

    @unittest.skipUnless(feasibility.CLASSIFICATION_CSV.exists(), "缺 P6 节点分类表")
    def test_food_node_fills_meal_slot_without_hours(self):
        ids = ["POI|长隆|南门", "POI|长隆|熊猫餐厅", "POI|长隆|熊猫村"]
        report = apply_feasibility(_route(node_ids=ids), [], [], 1)
        meal = report["meal"]
        self.assertTrue(meal["inserted"])
        self.assertEqual(meal["slot"], MEAL_SLOT)
        self.assertIn("熊猫餐厅", meal["note"])
        self.assertIn("未核验", meal["note"])
        self.assertTrue(any("营业时间" in item for item in report["uncertainties"]))

    def test_duration_over_eight_hours_is_warning_only(self):
        report = apply_feasibility(_route(count=8), [], [], 1)
        duration = report["duration"]
        self.assertGreater(duration["total_min"], 8 * 60)
        self.assertTrue(duration["over_budget"])
        # 只警告，不降级：连接核验与行程可行分开（PRODUCT_SPEC §5.6）。
        self.assertIsNone(report["status_override"])
        self.assertTrue(any("8 小时预算" in item["text"] for item in report["warnings"]))
        self.assertTrue(any("模板" in item and "假设" in item
                            for item in duration["assumptions"]))
        self.assertTrue(any("模板" in item for item in report["uncertainties"]))

    def test_duration_within_budget_has_no_warning(self):
        report = apply_feasibility(_route(count=4), [], [], 1)
        self.assertLessEqual(report["duration"]["total_min"], 8 * 60)
        self.assertFalse(report["duration"]["over_budget"])
        self.assertEqual(report["warnings"], [])

    def test_route_nodes_and_edges_are_not_modified(self):
        route = _route(count=9)
        before = copy.deepcopy(route)
        apply_feasibility(route, ["老人"], [], 1)
        self.assertEqual(route, before)
        self.assertEqual(
            route["proposal"]["node_ids"], before["proposal"]["node_ids"])
        self.assertEqual(route["validation"], before["validation"])

    def test_no_distance_price_or_opening_hours_are_invented(self):
        report = apply_feasibility(_route(count=9), ["老人"], [], 1)
        text = "\n".join(_strings(report))
        for pattern in FORBIDDEN_PATTERNS:
            self.assertIsNone(re.search(pattern, text), pattern)
        # 假设必须显式成文，不能把模板估算写成资料事实。
        self.assertTrue(report["duration"]["assumptions"])
        self.assertTrue(any("假设" in item or "未核验" in item
                            for item in report["uncertainties"]))

    def test_empty_route_reports_no_conclusion(self):
        for route in (None, {}, {"proposal": {"node_ids": []}}):
            with self.subTest(route=route):
                report = apply_feasibility(route, ["老人"], [], 1)
                self.assertIsNone(report["status_override"])
                self.assertEqual(report["warnings"], [])
                self.assertEqual(report["stop_count"], 0)
                self.assertEqual(report["day_counts"], [])
                self.assertTrue(report["uncertainties"])


class AgentFeasibilityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = patch.object(trace_log, "SESSION_DIR", Path(self.temp.name))
        directory.start()
        self.addCleanup(directory.stop)
        self.ok = {"status": "ok", "explanation": "", "question": ""}
        self.plan = {"decision": "query_graph", "request_type": "plan",
                     "reason": "需要规划", "response": ""}

    def _run(self, route, profiles=None, days=1, constraints=None, guard="1"):
        intent = {
            "scenic_area": AREA, "duration_days": days,
            "traveler_profiles": list(profiles or []),
            "preferences": [], "constraints": list(constraints or []),
        }
        selection = {"tools": ["get_conditions"], "search_mode": "none",
                     "search_keyword": "", "reason": "查建议"}
        stop = {"tools": [], "search_mode": "none",
                "search_keyword": "", "reason": "结束"}
        with patch.dict(os.environ, {agent.FEASIBILITY_GUARD_ENV: guard}):
            with patch.object(agent, "parse_intent", return_value=intent), \
                 patch.object(agent, "decide_next_step", return_value=self.plan), \
                 patch.object(agent, "check_constraints", return_value=self.ok), \
                 patch.object(agent, "check_plan", return_value=self.ok), \
                 patch.object(agent, "select_tools", side_effect=[selection, stop]), \
                 patch.object(agent, "find_relevant_conditions", return_value=[]), \
                 patch.object(agent, "plan_route", return_value=route):
                return agent.run_agent("带老人去长隆玩一天")

    def _trace_events(self, result):
        path = Path(self.temp.name) / result["trace_file"]
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_agent_over_cap_is_partial_with_reason(self):
        route = _route(count=7)
        before = copy.deepcopy(route)
        result = self._run(route, profiles=["老人"], days=1)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["needs_followup"])
        codes = [item["code"] for item in result["reasons"]]
        self.assertIn("constraint_conflict", codes)
        self.assertTrue(any("上限为 6 个" in item["text"] for item in result["reasons"]))
        self.assertIn("上限为 6 个", result["message"])
        self.assertIn(status.DISCLAIMER, result["what_verified"]["note"])
        # 只读：节点与连接不变，新增内容只写进 uncertainties。
        self.assertEqual(route["proposal"]["node_ids"], before["proposal"]["node_ids"])
        self.assertEqual(route["validation"], before["validation"])
        self.assertTrue(route["proposal"]["uncertainties"])
        # 可行性报告进入返回值与 trace，供 T2.3/T4 读取。
        self.assertEqual(result["feasibility"]["status_override"], "partial")
        self.assertTrue(any(event.get("event_type") == "feasibility"
                            for event in self._trace_events(result)))

    def test_agent_under_cap_stays_verified(self):
        result = self._run(_route(count=6), profiles=["老人"], days=1)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["reasons"], [])
        self.assertIsNotNone(result["feasibility"])
        self.assertIsNone(result["feasibility"]["status_override"])

    def test_agent_adult_boundary_matches_report(self):
        self.assertEqual(
            self._run(_route(count=8))["status"], "verified")
        self.assertEqual(
            self._run(_route(count=9))["status"], "partial")

    def test_assumptions_reach_proposal_uncertainties(self):
        route = _route(count=7)
        result = self._run(route, profiles=["老人"], days=1)
        uncertainties = route["proposal"]["uncertainties"]
        self.assertTrue(uncertainties)
        self.assertEqual(len(uncertainties), len(set(uncertainties)))
        self.assertTrue(any("上限" in item for item in uncertainties))
        self.assertTrue(any("模板" in item for item in uncertainties))
        self.assertEqual(result["route"]["proposal"]["node_ids"],
                         _node_ids(7))

    def test_guard_zero_skips_gate_completely(self):
        for guard in ("0", "false", "off", "no"):
            with self.subTest(guard=guard):
                route = _route(count=7)
                result = self._run(route, profiles=["老人"], days=1, guard=guard)
                self.assertEqual(result["status"], "verified")
                self.assertIsNone(result["feasibility"])
                self.assertEqual(route["proposal"]["uncertainties"], [])
                self.assertFalse(any(event.get("event_type") == "feasibility"
                                     for event in self._trace_events(result)))

    def test_guard_default_is_on(self):
        route = _route(count=7)
        result = self._run(route, profiles=["老人"], days=1, guard="1")
        self.assertEqual(result["status"], "partial")
        self.assertIsNotNone(result["feasibility"])


if __name__ == "__main__":
    unittest.main()
