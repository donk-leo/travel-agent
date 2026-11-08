"""景区名称归一化与主流程回退的回归测试。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent
import trace_log
from scenic_aliases import canonicalize_scenic_area
from tools import get_conditions, get_route_candidates, search_poi


class ScenicAliasTests(unittest.TestCase):
    def test_official_full_names(self):
        cases = {
            "广州长隆旅游度假区": "长隆",
            "长隆欢乐世界": "长隆",
            "广州市白云山风景区": "广州白云山",
            "白云山风景名胜区": "广州白云山",
            "武功山国家级风景名胜区": "武功山",
            "江西省萍乡市武功山景区": "武功山",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonicalize_scenic_area(raw), expected)

    def test_unknown_names_are_not_guessed(self):
        for raw in ("洛阳白云山", "珠海长隆", "华山", ""):
            with self.subTest(raw=raw):
                self.assertIsNone(canonicalize_scenic_area(raw))

    def test_graph_tools_accept_official_names(self):
        self.assertGreater(len(get_route_candidates("广州长隆旅游度假区")), 0)
        self.assertEqual(
            len(get_route_candidates("广州长隆旅游度假区")),
            len(get_route_candidates("长隆")),
        )
        self.assertEqual(
            len(search_poi("", "白云山风景区", limit=1000)),
            len(search_poi("", "广州白云山", limit=1000)),
        )
        self.assertEqual(
            get_conditions("人群", "武功山风景名胜区"),
            get_conditions("人群", "武功山"),
        )


class AgentAliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = patch.object(trace_log, "SESSION_DIR", Path(self.temp.name))
        directory.start()
        self.addCleanup(directory.stop)
        self.ok = {"status": "ok", "explanation": "", "question": ""}

    def _intent(self, area):
        return {
            "scenic_area": area,
            "duration_days": 1,
            "traveler_profiles": ["孩子"],
            "preferences": ["游乐项目"],
            "constraints": ["少走路"],
        }

    def test_unknown_area_asks_for_confirmation(self):
        decision = {"decision": "query_graph", "request_type": "plan",
                    "reason": "规划", "response": ""}
        with patch.object(agent, "parse_intent", return_value=self._intent("华山")), \
             patch.object(agent, "decide_next_step", return_value=decision), \
             patch.object(agent, "select_tools") as selector:
            result = agent.run_agent("去华山玩一天")

        self.assertEqual(result["status"], "clarify")
        self.assertTrue(result["needs_followup"])
        self.assertIn("只覆盖", result["message"])
        selector.assert_not_called()

    def test_alias_is_canonicalized_before_planning(self):
        decision = {"decision": "query_graph", "request_type": "plan",
                    "reason": "规划", "response": ""}
        selection = {"tools": ["get_route_candidates"], "search_mode": "none",
                     "search_keyword": "", "reason": "路线"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {
            "proposal": {"node_ids": ["a", "b"], "explanation": "路线", "uncertainties": []},
            "validation": {"valid": True, "segments": [], "missing_connections": []},
            "message": "通过",
        }
        with patch.object(agent, "parse_intent",
                          return_value=self._intent("广州长隆旅游度假区")), \
             patch.object(agent, "decide_next_step", return_value=decision), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "plan_route", return_value=route) as planner:
            result = agent.run_agent("带孩子去广州长隆旅游度假区一天")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["intent"]["scenic_area"], "长隆")
        self.assertEqual(planner.call_args.args[1], "长隆")


if __name__ == "__main__":
    unittest.main()