"""可离线运行的流程检查；模型相关场景在交付测试记录中另行实测。"""

import json
import inspect
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent
import condition_selector
import constraint_checker
import trace_log
import web_app
import tools
from agent import _keep_sub_area_suggestions
from intent_parser import _merge_profiles
from route_planner import _coerce_days, _normalize_day_plan
from tools import get_route_candidates, neighbors, repair_route, validate_route


class GraphToolTests(unittest.TestCase):
    def assert_contract_value(self, schema, value):
        """检查项目接口中使用的 type、required、properties 和 enum 子集。"""
        kind = schema.get("type")
        if kind == "object":
            self.assertIsInstance(value, dict)
            for field in schema.get("required", []):
                self.assertIn(field, value)
            for field, field_schema in schema.get("properties", {}).items():
                if field in value:
                    self.assert_contract_value(field_schema, value[field])
        elif kind == "array":
            self.assertIsInstance(value, list)
            for item in value:
                self.assert_contract_value(schema["items"], item)
        elif kind == "string":
            self.assertIsInstance(value, str)
        elif kind == "integer":
            self.assertIsInstance(value, int)
            self.assertNotIsInstance(value, bool)
        if "enum" in schema:
            self.assertIn(value, schema["enum"])

    def test_documented_tool_contracts(self):
        root = Path(__file__).resolve().parents[3]
        spec = json.loads((root / "standards/schema_tools.json").read_text(encoding="utf-8"))
        examples = {
            "search_poi": {"keyword": "熊猫", "scenic_area": "长隆"},
            "get_route": {"scenic_area": "长隆", "source_doc_id": "CL-T-02"},
            "get_route_candidates": {"scenic_area": "长隆"},
            "get_conditions": {"condition_type": "人群", "scenic_area": "长隆"},
            "neighbors": {"node_id": "SCENIC_AREA|广州白云山", "rel": "CONTAINS"},
        }
        self.assertEqual({item["name"] for item in spec["tools"]}, set(examples))
        for item in spec["tools"]:
            with self.subTest(tool=item["name"]):
                function = getattr(tools, item["name"])
                inspect.signature(function).bind(**examples[item["name"]])
                self.assert_contract_value(item["parameters"], examples[item["name"]])
                self.assert_contract_value(item["returns"], function(**examples[item["name"]]))

    def test_neighbors_and_absent_node(self):
        results = neighbors("SCENIC_AREA|广州白云山", rel="CONTAINS")
        self.assertTrue(any(item["name"] == "摩星岭" for item in results))
        self.assertTrue(all(item["rel"] == "CONTAINS" for item in results))
        self.assertEqual(neighbors("不存在的节点"), [])

    def test_route_repair_preserves_evidence(self):
        candidates = get_route_candidates("广州白云山")
        start = "POI|广州白云山|白云山南门"
        end = "POI|广州白云山|黄婆洞水库"
        self.assertFalse(validate_route([start, end], candidates)["valid"])
        repaired = repair_route([start, end], candidates)
        self.assertTrue(repaired["repaired"])
        self.assertEqual(repaired["node_ids"][0], start)
        self.assertEqual(repaired["node_ids"][-1], end)
        self.assertTrue(all(s["source_doc_ids"] for s in repaired["validation"]["segments"]))


class RouteDayPlanTests(unittest.TestCase):
    def test_days_are_coerced_to_positive_integer(self):
        self.assertEqual(_coerce_days("3"), 3)
        self.assertEqual(_coerce_days(2), 2)
        self.assertIsNone(_coerce_days(0))
        self.assertIsNone(_coerce_days("abc"))
        self.assertIsNone(_coerce_days(None))

    def test_model_day_plan_is_kept_when_valid(self):
        node_ids = ["a", "b", "c", "d", "e"]
        raw = [
            {"day": 1, "node_ids": ["a", "b"]},
            {"day": 2, "node_ids": ["c", "d", "e"]},
        ]
        plan, fallback = _normalize_day_plan(node_ids, raw, 2)
        self.assertFalse(fallback)
        self.assertEqual([group["node_ids"] for group in plan], [["a", "b"], ["c", "d", "e"]])

    def test_invalid_day_plan_falls_back_to_even_split(self):
        node_ids = ["a", "b", "c", "d", "e"]
        raw = [{"day": 1, "node_ids": ["a"]}, {"day": 2, "node_ids": ["b"]}]
        plan, fallback = _normalize_day_plan(node_ids, raw, 3)
        self.assertTrue(fallback)
        self.assertEqual([group["node_ids"] for group in plan], [["a", "b"], ["c", "d"], ["e"]])

    def test_one_day_is_a_single_group(self):
        plan, fallback = _normalize_day_plan(["a", "b"], None, 1)
        self.assertFalse(fallback)
        self.assertEqual(plan, [{"day": 1, "node_ids": ["a", "b"]}])


class AgentFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = patch.object(trace_log, "SESSION_DIR", Path(self.temp.name))
        directory.start()
        self.addCleanup(directory.stop)
        self.ok = {"status": "ok", "explanation": "", "question": ""}
        self.intent = {"scenic_area": "长隆", "duration_days": None}
        self.decision = {"decision": "query_graph", "request_type": "info", "reason": "查地点", "response": ""}

    def test_empty_result_can_trigger_followup_query(self):
        decisions = [
            {"tools": ["search_poi"], "search_mode": "keyword", "search_keyword": "原名", "reason": "查找"},
            {"tools": ["search_poi"], "search_mode": "keyword", "search_keyword": "熊猫", "reason": "补查"},
            {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"},
        ]
        with patch.object(agent, "parse_intent", return_value=self.intent), \
             patch.object(agent, "decide_next_step", return_value=self.decision), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=decisions) as selector, \
             patch.object(agent, "search_poi", side_effect=[[], [{"name": "熊猫村", "node_id": "P", "scenic_area": "长隆"}]]):
            result = agent.run_agent("长隆熊猫景点")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["poi_results"][0]["name"], "熊猫村")
        self.assertEqual(selector.call_args_list[1].kwargs["observations"][0]["count"], 0)
        events = [json.loads(line) for line in (Path(self.temp.name) / result["trace_file"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[0]["event_type"], "user_input")
        self.assertEqual(events[-1]["event_type"], "final_answer")
        self.assertEqual(sum(e.get("tool") == "search_poi" for e in events), 2)

    def test_conflicting_request_stops_before_graph(self):
        conflict = {"status": "conflict", "explanation": "限制冲突", "question": "请调整"}
        with patch.object(agent, "parse_intent", return_value={**self.intent, "duration_days": 1}), \
             patch.object(agent, "decide_next_step", return_value={**self.decision, "request_type": "plan"}), \
             patch.object(agent, "check_constraints", return_value=conflict), \
             patch.object(agent, "select_tools") as selector:
            result = agent.run_agent("冲突要求")
        self.assertEqual(result["status"], "clarify")
        self.assertTrue(result["needs_followup"])
        selector.assert_not_called()

    def test_plan_request_queries_route_if_model_omits_it(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "需要规划", "response": ""}
        selection = {"tools": ["get_conditions", "search_poi"], "search_mode": "all_pois",
                     "search_keyword": "", "reason": "查询建议和景点"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": ["a", "b"], "explanation": "路线", "uncertainties": []},
                 "validation": {"valid": True, "segments": [], "missing_connections": []}, "message": "通过"}
        with patch.object(agent, "parse_intent", return_value={
                 **self.intent, "duration_days": 1,
                 "traveler_profiles": ["父母"], "preferences": ["轻松"],
                 "constraints": ["少走路"]}), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "find_relevant_conditions", return_value=[]), \
             patch.object(agent, "search_poi", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route) as planner:
            result = agent.run_agent("我和父母去长隆玩一天")
        self.assertEqual(result["status"], "complete")
        self.assertIsNotNone(result["route"])
        planner.assert_called_once()
        self.assertEqual(planner.call_args.kwargs["days"], 1)
        self.assertEqual(planner.call_args.kwargs["profiles"], ["父母"])
        self.assertEqual(planner.call_args.kwargs["preferences"], ["轻松"])
        self.assertEqual(planner.call_args.kwargs["constraints"], ["少走路"])
        events = [json.loads(line) for line in (Path(self.temp.name) / result["trace_file"]).read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(e.get("event_type") == "decision_adjustment" for e in events))

    def test_plan_request_passes_multi_day_count_to_route_planner(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "需要规划", "response": ""}
        selection = {"tools": ["get_conditions"], "search_mode": "all_pois",
                     "search_keyword": "", "reason": "查询建议"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": ["a", "b", "c"], "explanation": "路线",
                              "uncertainties": [], "day_plan": []},
                 "validation": {"valid": True, "segments": [], "missing_connections": []}, "message": "通过"}
        with patch.object(agent, "parse_intent", return_value={**self.intent, "duration_days": 3}), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "find_relevant_conditions", return_value=[]), \
             patch.object(agent, "search_poi", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route) as planner:
            result = agent.run_agent("带孩子去武功山玩三天")
        self.assertEqual(result["status"], "complete")
        self.assertIsNotNone(result["route"])
        self.assertEqual(planner.call_args.kwargs["days"], 3)


    def test_unknown_place_is_checked_against_graph(self):
        choices = [
            {"tools": ["search_poi"], "search_mode": "keyword", "search_keyword": "虚构地点", "reason": "查询"},
            {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "无匹配"},
        ]
        with patch.object(agent, "parse_intent", return_value=self.intent), \
             patch.object(agent, "decide_next_step", return_value=self.decision), \
             patch.object(agent, "check_constraints") as precheck, \
             patch.object(agent, "check_plan") as plancheck, \
             patch.object(agent, "select_tools", side_effect=choices), \
             patch.object(agent, "search_poi", return_value=[]) as search:
            result = agent.run_agent("长隆有没有叫虚构地点的景点？")
        self.assertEqual(result["poi_results"], [])
        self.assertIn("图谱中没有找到", result["message"])
        precheck.assert_not_called()
        plancheck.assert_not_called()
        search.assert_called_once()

    def test_loop_stops_and_explains_limit(self):
        decisions = [
            {"tools": ["search_poi"], "search_mode": "keyword", "search_keyword": str(i), "reason": "补查"}
            for i in range(agent.MAX_DECISION_ROUNDS)
        ]
        with patch.object(agent, "parse_intent", return_value=self.intent), \
             patch.object(agent, "decide_next_step", return_value=self.decision), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=decisions), \
             patch.object(agent, "search_poi", return_value=[]):
            result = agent.run_agent("查景点")
        self.assertIn("轮次上限", result["message"])

    def test_plan_poi_keyword_falls_back_to_area_pois(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "规划", "response": ""}
        selection = {"tools": ["search_poi"], "search_mode": "keyword",
                     "search_keyword": "不存在", "reason": "查地点"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": ["a", "b"], "explanation": "路线", "uncertainties": []},
                 "validation": {"valid": True, "segments": [], "missing_connections": []}, "message": "通过"}
        fallback = [{"name": "熊猫村", "node_id": "P", "scenic_area": "长隆"}]
        with patch.object(agent, "parse_intent", return_value={**self.intent, "duration_days": 1}), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "search_poi", side_effect=[[], fallback]) as search, \
             patch.object(agent, "plan_route", return_value=route):
            result = agent.run_agent("带孩子去长隆玩一天")
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["poi_list_all"])
        self.assertEqual([item["name"] for item in result["poi_results"]], ["熊猫村"])
        self.assertIn("当前范围全部地点", result["message"])
        self.assertEqual(search.call_count, 2)

    def test_preference_keyword_uses_all_pois_without_name_search(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "规划", "response": ""}
        selection = {"tools": ["search_poi"], "search_mode": "keyword",
                     "search_keyword": "儿童", "reason": "查儿童项目"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": ["a", "b"], "explanation": "路线", "uncertainties": []},
                 "validation": {"valid": True, "segments": [], "missing_connections": []}, "message": "通过"}
        all_pois = [{"name": "熊猫村", "node_id": "P", "scenic_area": "长隆"}]
        with patch.object(agent, "parse_intent", return_value={**self.intent, "duration_days": 3}), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "search_poi", return_value=all_pois) as search, \
             patch.object(agent, "plan_route", return_value=route):
            result = agent.run_agent("带孩子去长隆欢乐世界玩三天")
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["poi_list_all"])
        self.assertEqual(search.call_args.kwargs["keyword"], "")
        self.assertEqual(search.call_args.kwargs["limit"], 10000)
        self.assertEqual(search.call_count, 1)
        self.assertIn("偏好", result["message"])
        self.assertIn("未按偏好过滤", result["message"])

    def test_invalid_route_is_partial_not_complete(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "规划", "response": ""}
        selection = {"tools": ["get_conditions", "search_poi"], "search_mode": "all_pois",
                     "search_keyword": "", "reason": "查建议和地点"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": ["a", "b"], "explanation": "路线", "uncertainties": []},
                 "validation": {"valid": False, "segments": [],
                                "missing_connections": [{"from": "a", "to": "b"}] * 12},
                 "message": "路线连接缺失"}
        with patch.object(agent, "parse_intent", return_value={**self.intent, "duration_days": 1}), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "find_relevant_conditions",
                          return_value=[{"condition": "带孩子", "suggestion": "去熊猫村"}]), \
             patch.object(agent, "search_poi", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route):
            result = agent.run_agent("带孩子去长隆玩一天")
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["needs_followup"])
        self.assertIsNotNone(result["route"])
        self.assertEqual(len(result["suggestions"]), 1)
        self.assertIn("12 处缺失", result["message"])
        self.assertIn("未通过图谱核验", result["message"])

    def test_day_plan_is_rendered_by_day(self):
        result = {
            "query": "武功山两天", "intent": {"scenic_area": "武功山", "duration_days": 2},
            "decision": None, "tool_decisions": [], "suggestions": [],
            "route": {
                "proposal": {
                    "node_ids": ["a", "b", "c"],
                    "node_names": {"a": "金顶", "b": "吊马桩", "c": "发云界"},
                    "duration_days": 2,
                    "day_plan": [
                        {"day": 1, "node_ids": ["a", "b"]},
                        {"day": 2, "node_ids": ["c"]},
                    ],
                    "explanation": "按两天安排", "uncertainties": []
                },
                "validation": {"valid": True, "segments": [], "missing_connections": []},
                "message": "通过"
            },
            "poi_results": None, "poi_list_all": False, "needs_followup": False,
            "message": "", "error": "", "trace_file": "", "trace_json": ""
        }
        with patch.object(web_app, "run_agent", return_value=result), web_app.app.test_client() as client:
            response = client.post("/", data={"query": "武功山两天"})
            html = response.get_data(as_text=True)
        html = re.sub(r"\s+", " ", html)
        self.assertIn("游玩天数：2 天", html)
        self.assertIn("第 1 天", html)
        self.assertIn("第 2 天", html)
        self.assertIn("金顶 → 吊马桩", html)
        self.assertIn("发云界", html)

    def test_poi_list_heading_does_not_claim_name_match(self):
        result = {
            "query": "孩子在长隆", "intent": {"scenic_area": "长隆", "duration_days": 1},
            "decision": None, "tool_decisions": [], "suggestions": [], "route": None,
            "poi_results": [{"name": "熊猫村", "scenic_area": "长隆"}],
            "poi_list_all": True, "needs_followup": False,
            "message": "“儿童”是人群或体验偏好，不是地点名称；已改为列出当前范围全部地点，未按偏好过滤。",
            "error": "", "trace_file": "", "trace_json": ""
        }
        with patch.object(web_app, "run_agent", return_value=result), web_app.app.test_client() as client:
            response = client.post("/", data={"query": "孩子在长隆"})
            html = response.get_data(as_text=True)
        self.assertIn("当前范围地点", html)
        self.assertIn("未按“儿童/亲子/老人”等偏好过滤", html)
        self.assertNotIn("图谱名称匹配结果", html)

    def test_followup_context_is_preserved(self):
        first = {"query": "和父母轻松出游", "intent": None, "decision": None, "tool_decisions": [],
                 "suggestions": [], "route": None, "poi_results": None, "poi_list_all": False,
                 "message": "请补充景区和天数", "error": "", "trace_file": "", "trace_json": "", "needs_followup": True}
        second = {**first, "query": "和父母轻松出游\n广州白云山，一天", "message": "完成", "needs_followup": False}
        with patch.object(web_app, "run_agent", side_effect=[first, second]) as runner, web_app.app.test_client() as client:
            client.post("/", data={"query": "和父母轻松出游"})
            client.post("/", data={"query": "广州白云山，一天"})
        self.assertEqual(runner.call_args_list[1].args[0], "和父母轻松出游\n广州白云山，一天")


class HardeningTests(unittest.TestCase):
    def test_cross_document_route_is_valid_but_not_fully_verified(self):
        candidates = [
            {"source_doc_id": "CL-T-01", "connections": [{
                "from_node_id": "a", "to_node_id": "b",
                "from_name": "A", "to_name": "B", "source_doc_ids": ["CL-T-01"],
            }]},
            {"source_doc_id": "CL-T-02", "connections": [{
                "from_node_id": "b", "to_node_id": "c",
                "from_name": "B", "to_name": "C", "source_doc_ids": ["CL-T-02"],
            }]},
        ]
        validation = validate_route(["a", "b", "c"], candidates)
        self.assertTrue(validation["valid"])
        self.assertFalse(validation["fully_verified"])
        self.assertEqual(validation["cross_doc_transitions"], 1)

    def test_agent_marks_missing_route_as_partial(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "规划", "response": ""}
        selection = {"tools": ["get_conditions"], "search_mode": "none",
                     "search_keyword": "", "reason": "查建议"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": [], "explanation": "", "uncertainties": []},
                 "validation": None, "message": "该景区没有查询到路线连接。"}
        intent = {"scenic_area": "长隆", "duration_days": 1}
        ok = {"status": "ok", "explanation": "", "question": ""}
        with patch.object(agent, "parse_intent", return_value=intent), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=ok), \
             patch.object(agent, "check_plan", return_value=ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "find_relevant_conditions", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route):
            result = agent.run_agent("我和父母去长隆玩一天")
        self.assertEqual(result["status"], "partial")
        self.assertIn("没有查询到路线连接", result["message"])

    def test_agent_marks_cross_document_route_as_partial(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "规划", "response": ""}
        selection = {"tools": ["get_conditions"], "search_mode": "none",
                     "search_keyword": "", "reason": "查建议"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": ["a", "b"], "explanation": "", "uncertainties": []},
                 "validation": {"valid": True, "fully_verified": False, "segments": [],
                                "missing_connections": [], "cross_doc_transitions": 2},
                 "message": "跨来源"}
        intent = {"scenic_area": "长隆", "duration_days": 1}
        ok = {"status": "ok", "explanation": "", "question": ""}
        with patch.object(agent, "parse_intent", return_value=intent), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=ok), \
             patch.object(agent, "check_plan", return_value=ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "find_relevant_conditions", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route):
            result = agent.run_agent("我和父母去长隆玩一天")
        self.assertEqual(result["status"], "partial")
        self.assertIn("跨来源文档", result["message"])

    def test_agent_marks_day_plan_fallback_as_partial(self):
        plan = {"decision": "query_graph", "request_type": "plan", "reason": "规划", "response": ""}
        selection = {"tools": ["get_conditions"], "search_mode": "none",
                     "search_keyword": "", "reason": "查建议"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {"proposal": {"node_ids": ["a", "b"], "explanation": "", "uncertainties": [],
                              "day_plan_fallback": True},
                 "validation": {"valid": True, "fully_verified": True, "segments": [],
                                "missing_connections": [], "cross_doc_transitions": 0},
                 "message": "通过"}
        intent = {"scenic_area": "长隆", "duration_days": 2}
        ok = {"status": "ok", "explanation": "", "question": ""}
        with patch.object(agent, "parse_intent", return_value=intent), \
             patch.object(agent, "decide_next_step", return_value=plan), \
             patch.object(agent, "check_constraints", return_value=ok), \
             patch.object(agent, "check_plan", return_value=ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "find_relevant_conditions", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route):
            result = agent.run_agent("我和父母去长隆玩两天")
        self.assertEqual(result["status"], "partial")
        self.assertIn("按节点数均分", result["message"])

    def test_condition_selection_dedupes_caps_and_drops_wrong_season(self):
        conditions = [
            {"condition_text": "冬天来武功山", "suggestion_text": "带冰爪"},
            {"condition_text": "带孩子", "suggestion_text": "带儿童证件"},
            {"condition_text": "带孩子", "suggestion_text": "带儿童证件"},
            {"condition_text": "看日出", "suggestion_text": "带厚衣服"},
            {"condition_text": "体力一般", "suggestion_text": "坐索道"},
            {"condition_text": "预算有限", "suggestion_text": "自带干粮"},
            {"condition_text": "自驾", "suggestion_text": "停北门"},
            {"condition_text": "雨天", "suggestion_text": "带雨衣"},
        ]
        selections = [
            {"index": index, "needs_verification": False}
            for index in range(len(conditions))
        ]
        selected = condition_selector.apply_selection(
            conditions, selections, user_text="带孩子去武功山玩两天")
        self.assertEqual(len(selected), 5)
        self.assertNotIn("冬天", [item["condition"]["condition_text"] for item in selected])
        pairs = {
            (item["condition"]["condition_text"], item["condition"]["suggestion_text"])
            for item in selected
        }
        self.assertEqual(len(pairs), len(selected))

    def test_condition_season_aliases_match(self):
        conditions = [{"condition_text": "冬季上山", "suggestion_text": "带冰爪"}]
        selections = [{"index": 0, "needs_verification": False}]
        kept = condition_selector.apply_selection(
            conditions, selections, user_text="冬天去武功山")
        dropped = condition_selector.apply_selection(
            conditions, selections, user_text="夏天去武功山")
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 0)

    def test_profile_keywords_fill_missing_friend(self):
        self.assertIn("朋友", _merge_profiles("我和朋友去白云山", []))
        merged = _merge_profiles("带孩子和老人", ["孩子"])
        self.assertIn("孩子", merged)
        self.assertIn("老人", merged)

    def test_check_plan_receives_full_route_and_day_plan(self):
        route = {
            "proposal": {
                "node_ids": ["a", "b", "a"],
                "day_plan": [{"day": 1, "node_ids": ["a", "b", "a"]}],
                "day_plan_fallback": False,
            },
            "validation": {"valid": True, "fully_verified": False,
                           "missing_connections": [], "cross_doc_transitions": 2},
            "metrics": {"steps": 2, "repeats": 1},
        }
        ok = {"status": "ok", "explanation": "", "question": ""}
        with patch.object(constraint_checker, "_check", return_value=ok) as check:
            constraint_checker.check_plan("少走路", route, [])
        payload = json.loads(check.call_args.args[0][1]["content"])
        self.assertEqual(payload["route_nodes"], ["a", "b", "a"])
        self.assertEqual(payload["day_plan"][0]["day"], 1)
        self.assertEqual(payload["route_validation"]["cross_doc_transitions"], 2)
        self.assertFalse(payload["day_plan_fallback"])

    def test_default_session_dir_is_outside_repo(self):
        repo = Path(__file__).resolve().parents[3]
        self.assertNotIn(str(repo).lower(), str(trace_log.SESSION_DIR).lower())

    def test_single_destination_suggestions_are_scoped(self):
        suggestions = [
            {"condition": {"condition_text": "儿童",
                           "suggestion_text": "水上乐园有儿童戏水区"},
             "evidence": {"anchor_name": "长隆水上乐园"}},
            {"condition": {"condition_text": "小朋友",
                           "suggestion_text": "去梦幻童话世界和熊猫村"},
             "evidence": {"anchor_name": "长隆"}},
        ]
        kept = _keep_sub_area_suggestions(suggestions, "水上乐园")
        self.assertEqual(len(kept), 1)
        self.assertIn("水上乐园", json.dumps(kept[0], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
