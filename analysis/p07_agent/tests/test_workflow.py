"""可离线运行的流程检查；模型相关场景在交付测试记录中另行实测。"""

import json
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent
import trace_log
import web_app
import tools
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

    def test_followup_context_is_preserved(self):
        first = {"query": "和父母轻松出游", "intent": None, "decision": None, "tool_decisions": [],
                 "suggestions": [], "route": None, "poi_results": None, "poi_list_all": False,
                 "message": "请补充景区和天数", "error": "", "trace_file": "", "trace_json": "", "needs_followup": True}
        second = {**first, "query": "和父母轻松出游\n广州白云山，一天", "message": "完成", "needs_followup": False}
        with patch.object(web_app, "run_agent", side_effect=[first, second]) as runner, web_app.app.test_client() as client:
            client.post("/", data={"query": "和父母轻松出游"})
            client.post("/", data={"query": "广州白云山，一天"})
        self.assertEqual(runner.call_args_list[1].args[0], "和父母轻松出游\n广州白云山，一天")


if __name__ == "__main__":
    unittest.main()
