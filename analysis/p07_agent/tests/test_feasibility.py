"""T2.2b 可行性闸测试：人群点数上限、按上限裁剪停留点、用餐未知、时长模板与 guard 开关。

覆盖 DoD 1–3：老人/0–6 岁 ≤6、成人 ≤8、边界 6/7 与 8/9、多日分摊、
11:30–13:30 无餐饮标未知、总时长 >8h 警告、``FEASIBILITY_GUARD=0`` 完全跳过、
裁剪只读（不改 ``node_ids``）、裁剪后逐段重核验、以及所有假设都写进 uncertainties。
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

# T2.7 结果缓存默认开启；本模块用 patch 替换模型/路线夹具，必须关闭缓存避免跨用例串结果。
os.environ["P07_RESULT_CACHE"] = "0"

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


def _name(node_id):
    return str(node_id).split("|")[-1]


def _connection(from_id, to_id, doc_id="CL-O-01"):
    return {
        "from_node_id": from_id,
        "to_node_id": to_id,
        "from_name": _name(from_id),
        "to_name": _name(to_id),
        "source_doc_ids": [doc_id],
    }


def _candidates(node_ids, extra_pairs=()):
    """按单一来源文档构造 NEXT 连接；``extra_pairs`` 用于补跨天衔接的新连接。"""
    pairs = list(zip(node_ids, node_ids[1:])) + list(extra_pairs)
    return [{
        "source_doc_id": "CL-O-01",
        "connections": [_connection(from_id, to_id) for from_id, to_id in pairs],
    }]


def _route(node_ids=None, count=0, day_plan=None, days=None,
           candidates=None, validation=None, metrics=None):
    node_ids = list(node_ids) if node_ids is not None else _node_ids(count)
    proposal = {
        "node_ids": node_ids,
        "node_names": {node_id: _name(node_id) for node_id in node_ids},
        "explanation": "路线",
        "uncertainties": [],
    }
    if day_plan is not None:
        proposal["day_plan"] = day_plan
    if days is not None:
        proposal["duration_days"] = days
    route = {
        "proposal": proposal,
        "validation": validation if validation is not None else {
            "valid": True, "fully_verified": True, "segments": [],
            "missing_connections": [], "cross_doc_transitions": 0,
        },
        "message": "路线连接已通过图谱核验。",
    }
    if candidates is not None:
        route["candidates"] = candidates
    if metrics is not None:
        route["metrics"] = metrics
    return route


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _is_subsequence(small, large):
    """只判断顺序：``small`` 是否由 ``large`` 删点得到（不改序、不新增）。"""
    iterator = iter(large)
    return all(node_id in iterator for node_id in small)


class FeasibilityReportTests(unittest.TestCase):
    def test_senior_single_day_is_cropped_to_cap(self):
        node_ids = _node_ids(7)
        report = apply_feasibility(_route(node_ids=node_ids), ["老人"], [], 1)
        crop = report["crop"]
        self.assertTrue(crop["applied"])
        self.assertEqual(crop["node_ids"], node_ids[:6])
        self.assertEqual(crop["removed"], [
            {"node_id": node_ids[6], "name": "点7", "day": 1},
        ])
        self.assertEqual(crop["day_counts_before"], [7])
        self.assertEqual(crop["day_counts_after"], [6])
        self.assertIsNone(report["status_override"])
        self.assertEqual(report["caps"], {"max_stops": 6, "persona": "老人"})
        # 报告描述交付的计划：6 个停留点，不再保留「超限」警告。
        self.assertEqual(report["stop_count"], 6)
        self.assertEqual(report["day_counts"], [6])
        self.assertEqual(report["warnings"], [])
        self.assertIn("点7", crop["note"])
        self.assertIn("6", crop["note"])

    def test_senior_at_cap_keeps_status(self):
        report = apply_feasibility(_route(count=6), ["老人"], [], 1)
        self.assertIsNone(report["status_override"])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["day_counts"], [6])
        self.assertFalse(report["crop"]["applied"])
        self.assertIsNone(report["crop"]["node_ids"])
        self.assertEqual(report["crop"]["removed"], [])

    def test_child_under_six_uses_family_cap(self):
        report = apply_feasibility(_route(count=7), ["孩子"], [], 1)
        self.assertEqual(report["caps"], {"max_stops": 6, "persona": "0–6 岁儿童"})
        self.assertTrue(report["crop"]["applied"])

        # 关键词之外的年龄写法也要能识别；6 个不超、7 个超（超的那个被裁到 6）。
        at_cap = apply_feasibility(_route(count=6), [], ["带 3 岁小孩"], 1)
        self.assertIsNone(at_cap["status_override"])
        self.assertFalse(at_cap["crop"]["applied"])
        over = apply_feasibility(_route(count=7), [], ["带 3 岁小孩"], 1)
        self.assertTrue(over["crop"]["applied"])
        self.assertIsNone(over["status_override"])
        # 不带老人/幼儿的人群仍按成人上限，7 个不超、不用裁剪。
        adult = apply_feasibility(_route(count=7), ["朋友"], [], 1)
        self.assertIsNone(adult["status_override"])
        self.assertFalse(adult["crop"]["applied"])

    def test_adult_cap_boundary_eight_and_nine(self):
        at_cap = apply_feasibility(_route(count=8), [], [], 1)
        self.assertIsNone(at_cap["status_override"])
        self.assertEqual(at_cap["caps"], {"max_stops": 8, "persona": "成人"})
        self.assertFalse(at_cap["crop"]["applied"])

        node_ids = _node_ids(9)
        over_cap = apply_feasibility(_route(node_ids=node_ids), [], [], 1)
        self.assertIsNone(over_cap["status_override"])
        self.assertTrue(over_cap["crop"]["applied"])
        self.assertEqual(over_cap["crop"]["node_ids"], node_ids[:8])
        self.assertEqual([item["name"] for item in over_cap["crop"]["removed"]], ["点9"])
        self.assertEqual(over_cap["stop_count"], 8)

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
        self.assertFalse(ok["crop"]["applied"])

        # 第 1 天 7 个、第 2 天 4 个：裁剪第 1 天尾部会新建「点6 → 点8」这一段，
        # 没有候选连接可核验，因此不交付裁剪方案，仍按超限判 partial。
        bad_plan = [
            {"day": 1, "node_ids": ids[:7]},
            {"day": 2, "node_ids": ids[7:]},
        ]
        bad = apply_feasibility(
            _route(node_ids=ids, day_plan=bad_plan, days=2), ["老人"], [], 2)
        self.assertEqual(bad["day_counts"], [7, 4])
        self.assertEqual(bad["status_override"], "partial")
        self.assertFalse(bad["crop"]["applied"])
        self.assertIn("第 1 天", bad["warnings"][0]["text"])

    def test_multi_day_even_split_counts(self):
        even = apply_feasibility(_route(count=12, days=2), ["老人"], [], 2)
        self.assertEqual(even["day_counts"], [6, 6])
        self.assertIsNone(even["status_override"])
        self.assertTrue(any("均分" in item for item in even["uncertainties"]))

        uneven = apply_feasibility(_route(count=14, days=2), ["老人"], [], 2)
        self.assertEqual(uneven["day_counts"], [7, 7])
        self.assertEqual(uneven["status_override"], "partial")
        # 没有合法分天方案时不裁剪（计数只是均分假设）。
        self.assertFalse(uneven["crop"]["applied"])

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
        route = _route(count=9, candidates=_candidates(_node_ids(9)))
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
                self.assertFalse(report["crop"]["applied"])
                self.assertIsNone(report["crop"]["node_ids"])
                self.assertEqual(report["crop"]["removed"], [])

    def test_single_node_route_is_not_cropped(self):
        route = _route(node_ids=["POI|长隆|长隆水上乐园"])
        route["single_destination"] = True
        before = copy.deepcopy(route)
        report = apply_feasibility(route, ["孩子"], [], 1)
        self.assertFalse(report["crop"]["applied"])
        self.assertIsNone(report["status_override"])
        self.assertEqual(route, before)


class CropTests(unittest.TestCase):
    """T2.2b：裁剪只删点、保留前缀、逐段重核验；不能核验就不交付裁剪方案。"""

    def test_single_day_crop_with_candidates(self):
        node_ids = _node_ids(12)
        report = apply_feasibility(
            _route(node_ids=node_ids, candidates=_candidates(node_ids)),
            ["孩子"], [], 1)
        crop = report["crop"]
        self.assertTrue(crop["applied"])
        self.assertEqual(len(crop["node_ids"]), 6)
        self.assertEqual(crop["node_ids"], node_ids[:6])
        self.assertTrue(_is_subsequence(crop["node_ids"], node_ids))
        # 每天至少 1 个点，且被裁点在原文里逐个列出（node_id + 展示名 + 第几天）。
        self.assertGreaterEqual(min(crop["day_counts_after"]), 1)
        self.assertEqual(len(crop["removed"]), 6)
        self.assertEqual([item["name"] for item in crop["removed"]],
                         ["点7", "点8", "点9", "点10", "点11", "点12"])
        self.assertTrue(all(item["day"] == 1 for item in crop["removed"]))
        self.assertTrue(all(item["node_id"] in node_ids for item in crop["removed"]))
        self.assertIsNone(report["status_override"])
        # 裁剪后仍按候选连接重算逐段证据。
        self.assertEqual(report["stop_count"], 6)

    def test_adult_nine_cropped_to_eight(self):
        node_ids = _node_ids(9)
        report = apply_feasibility(
            _route(node_ids=node_ids, candidates=_candidates(node_ids)), [], [], 1)
        self.assertTrue(report["crop"]["applied"])
        self.assertEqual(report["crop"]["node_ids"], node_ids[:8])
        self.assertEqual(len(report["crop"]["removed"]), 1)
        self.assertIsNone(report["status_override"])

    def test_crop_does_not_add_or_reorder_nodes(self):
        node_ids = _node_ids(10)
        report = apply_feasibility(
            _route(node_ids=node_ids, candidates=_candidates(node_ids)),
            ["孩子"], [], 1)
        cropped = report["crop"]["node_ids"]
        self.assertEqual(cropped, node_ids[:6])
        self.assertEqual(cropped, [node_id for node_id in node_ids if node_id in set(cropped)])

    def test_no_candidates_but_verified_subsequence_is_cropped(self):
        # 从尾部删点不会产生新分段：没有候选连接时按原路线的已核验证据推断。
        node_ids = _node_ids(7)
        report = apply_feasibility(_route(node_ids=node_ids), ["老人"], [], 1)
        self.assertTrue(report["crop"]["applied"])
        self.assertEqual(report["crop"]["node_ids"], node_ids[:6])

    def test_unverified_route_without_candidates_is_not_cropped(self):
        node_ids = _node_ids(9)
        validation = {
            "valid": True, "fully_verified": False, "segments": [],
            "missing_connections": [], "cross_doc_transitions": 2,
        }
        report = apply_feasibility(
            _route(node_ids=node_ids, validation=validation), ["老人"], [], 1)
        self.assertFalse(report["crop"]["applied"])
        self.assertIsNone(report["crop"]["node_ids"])
        self.assertEqual(report["crop"]["removed"], [])
        self.assertEqual(report["status_override"], "partial")
        self.assertIn("上限为 6 个", report["warnings"][0]["text"])

    def test_cross_doc_crop_is_not_claimed_verified(self):
        node_ids = _node_ids(9)
        pairs = list(zip(node_ids, node_ids[1:]))
        candidates = [
            {"source_doc_id": "CL-O-01",
             "connections": [_connection(a, b) for a, b in pairs[:4]]},
            {"source_doc_id": "CL-T-02",
             "connections": [_connection(a, b, "CL-T-02") for a, b in pairs[4:]]},
        ]
        report = apply_feasibility(
            _route(node_ids=node_ids, candidates=candidates), [], [], 1)
        self.assertFalse(report["crop"]["applied"])
        self.assertEqual(report["status_override"], "partial")
        self.assertIn("跨来源文档", report["warnings"][0]["text"])

    def test_multi_day_crop_verified_with_new_boundary_edge(self):
        node_ids = _node_ids(16)
        day_plan = [
            {"day": 1, "node_ids": node_ids[:8]},
            {"day": 2, "node_ids": node_ids[8:]},
        ]
        # 每天 8 个裁到 6 个后，第 1 天最后一点「点6」要与第 2 天起点「点9」相连。
        candidates = _candidates(node_ids, extra_pairs=[(node_ids[5], node_ids[8])])
        report = apply_feasibility(
            _route(node_ids=node_ids, day_plan=day_plan, days=2,
                   candidates=candidates),
            ["老人"], [], 2)
        crop = report["crop"]
        self.assertTrue(crop["applied"])
        self.assertEqual(crop["day_counts_before"], [8, 8])
        self.assertEqual(crop["day_counts_after"], [6, 6])
        self.assertEqual(crop["node_ids"], node_ids[:6] + node_ids[8:14])
        self.assertEqual([item["day"] for item in crop["removed"]], [1, 1, 2, 2])
        self.assertIsNone(report["status_override"])

    def test_multi_day_new_boundary_without_evidence_is_partial(self):
        node_ids = _node_ids(16)
        day_plan = [
            {"day": 1, "node_ids": node_ids[:8]},
            {"day": 2, "node_ids": node_ids[8:]},
        ]
        # 候选连接里没有「点6 → 点9」，裁剪后这一段失去证据，不能交付。
        report = apply_feasibility(
            _route(node_ids=node_ids, day_plan=day_plan, days=2,
                   candidates=_candidates(node_ids)),
            ["老人"], [], 2)
        crop = report["crop"]
        self.assertFalse(crop["applied"])
        self.assertIsNone(crop["node_ids"])
        self.assertEqual(crop["removed"], [])
        self.assertEqual(report["status_override"], "partial")
        warning = report["warnings"][0]["text"]
        self.assertIn("第 1 天", warning)
        self.assertIn("点6", warning)
        self.assertIn("点9", warning)

    def test_crop_note_explains_removed_points(self):
        node_ids = _node_ids(7)
        report = apply_feasibility(_route(node_ids=node_ids), ["老人"], [], 1)
        note = report["crop"]["note"]
        self.assertIn("点7", note)
        self.assertIn("被裁", note)
        self.assertTrue(any("被裁" in item or "点7" in item
                            for item in report["uncertainties"]))


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

    def test_agent_crops_over_cap_route_to_cap(self):
        node_ids = _node_ids(7)
        route = _route(node_ids=node_ids)
        result = self._run(route, profiles=["老人"], days=1)
        proposal = result["route"]["proposal"]
        self.assertEqual(result["status"], "verified")
        self.assertEqual(proposal["node_ids"], node_ids[:6])
        self.assertEqual(proposal["day_plan"][0]["node_ids"], node_ids[:6])
        self.assertEqual(list(proposal["node_names"]), node_ids[:6])
        self.assertTrue(result["route"]["validation"]["fully_verified"])
        self.assertEqual(result["feasibility"]["crop"]["applied"], True)
        self.assertLessEqual(len(proposal["node_ids"]),
                             result["feasibility"]["caps"]["max_stops"])
        self.assertIn("裁", result["message"])
        self.assertTrue(any("点7" in item for item in proposal["uncertainties"]))
        # 裁剪事件进入 trace，供审计复算。
        self.assertTrue(any(event.get("event_type") == "feasibility_crop"
                            for event in self._trace_events(result)))

    def test_agent_crop_rewrites_validation_segments(self):
        node_ids = _node_ids(12)
        route = _route(node_ids=node_ids, candidates=_candidates(node_ids))
        result = self._run(route, profiles=["老人"], days=1)
        validation = result["route"]["validation"]
        self.assertEqual(result["status"], "verified")
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["fully_verified"])
        self.assertEqual(len(validation["segments"]), 5)
        self.assertTrue(all(segment["source_doc_ids"] for segment in validation["segments"]))
        self.assertEqual(len(result["route"]["proposal"]["node_ids"]), 6)

    def test_agent_crop_updates_metrics_when_present(self):
        node_ids = _node_ids(12)
        metrics = {
            "visits": 12, "steps": 11, "unique_nodes": 12, "repeats": 0,
            "repeated_node_ids": [], "missing_segments": 0,
            "structural_score": 11, "note": "图谱 NEXT 步数，不是实际步行距离。",
        }
        route = _route(node_ids=node_ids, candidates=_candidates(node_ids),
                       metrics=metrics)
        result = self._run(route, profiles=["老人"], days=1)
        updated = result["route"]["metrics"]
        self.assertEqual(updated["visits"], 6)
        self.assertEqual(updated["steps"], 5)
        self.assertEqual(updated["unique_nodes"], 6)
        self.assertEqual(updated["missing_segments"], 0)

    def test_agent_multi_day_without_day_plan_keeps_partial(self):
        route = _route(count=14, days=2)
        result = self._run(route, profiles=["老人"], days=2)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["feasibility"]["crop"]["applied"])
        self.assertEqual(len(result["route"]["proposal"]["node_ids"]), 14)
        codes = [item["code"] for item in result["reasons"]]
        self.assertIn("constraint_conflict", codes)
        self.assertTrue(any("上限为 6 个" in item["text"] for item in result["reasons"]))

    def test_agent_under_cap_stays_verified(self):
        result = self._run(_route(count=6), profiles=["老人"], days=1)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["reasons"], [])
        self.assertIsNotNone(result["feasibility"])
        self.assertIsNone(result["feasibility"]["status_override"])
        self.assertFalse(result["feasibility"]["crop"]["applied"])

    def test_agent_adult_boundary_matches_report(self):
        self.assertEqual(
            self._run(_route(count=8))["status"], "verified")
        nine = self._run(_route(count=9))
        self.assertEqual(nine["status"], "verified")
        self.assertEqual(len(nine["route"]["proposal"]["node_ids"]), 8)

    def test_assumptions_reach_proposal_uncertainties(self):
        node_ids = _node_ids(7)
        route = _route(node_ids=node_ids)
        result = self._run(route, profiles=["老人"], days=1)
        uncertainties = route["proposal"]["uncertainties"]
        self.assertTrue(uncertainties)
        self.assertEqual(len(uncertainties), len(set(uncertainties)))
        self.assertTrue(any("上限" in item for item in uncertainties))
        self.assertTrue(any("模板" in item for item in uncertainties))
        self.assertTrue(any("点7" in item for item in uncertainties))
        self.assertEqual(result["route"]["proposal"]["node_ids"], node_ids[:6])

    def test_guard_zero_skips_gate_completely(self):
        for guard in ("0", "false", "off", "no"):
            with self.subTest(guard=guard):
                route = _route(count=7)
                result = self._run(route, profiles=["老人"], days=1, guard=guard)
                self.assertEqual(result["status"], "verified")
                self.assertIsNone(result["feasibility"])
                self.assertEqual(route["proposal"]["node_ids"], _node_ids(7))
                self.assertEqual(route["proposal"]["uncertainties"], [])
                self.assertFalse(any(event.get("event_type") == "feasibility"
                                     for event in self._trace_events(result)))

    def test_guard_default_is_on(self):
        route = _route(count=7)
        result = self._run(route, profiles=["老人"], days=1, guard="1")
        self.assertEqual(result["status"], "verified")
        self.assertIsNotNone(result["feasibility"])
        self.assertTrue(result["feasibility"]["crop"]["applied"])


if __name__ == "__main__":
    unittest.main()
