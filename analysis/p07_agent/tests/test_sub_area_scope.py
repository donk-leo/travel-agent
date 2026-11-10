"""子园区范围与景点归属的回归测试。"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent
import sub_area_scope
import trace_log
from sub_area_scope import (
    DOC_SUB_AREA,
    filter_poi_results,
    filter_route_candidates,
    poi_sub_area,
    detect_sub_area,
)
from tools import get_route_candidates, search_poi


class SubAreaDetectionTests(unittest.TestCase):
    def test_single_sub_area_names(self):
        cases = {
            "我想去长隆欢乐世界玩一天": "欢乐世界",
            "广州长隆野生动物世界怎么走": "野生动物世界",
            "长隆野生动物园一日游": "野生动物世界",
            "广州长隆水上乐园": "水上乐园",
            "长隆国际大马戏好看吗": "国际大马戏",
            "长隆飞鸟乐园": "飞鸟乐园",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detect_sub_area(text), (expected, ""))

    def test_multiple_sub_areas_are_not_guessed(self):
        name, note = detect_sub_area("长隆欢乐世界和野生动物世界都想去")
        self.assertIsNone(name)
        self.assertIn("多个子园区", note)

    def test_no_or_empty_text(self):
        self.assertEqual(detect_sub_area("带孩子去长隆玩一天"), (None, ""))
        self.assertEqual(detect_sub_area(""), (None, ""))
        self.assertEqual(detect_sub_area(None), (None, ""))


class DocSubAreaTests(unittest.TestCase):
    def test_mapping_matches_p1_subtype(self):
        root = Path(__file__).resolve().parents[3]
        path = root / "scenic/changlong/data/processed/changlong_guides.csv"
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))

        expected = {}
        for row in rows:
            subtype = row["subtype"]
            expected[row["doc_id"]] = (
                sub_area_scope.MULTI_SUB_AREA
                if "多园区" in subtype
                else subtype
            )

        self.assertEqual(set(DOC_SUB_AREA), set(expected))
        self.assertEqual(DOC_SUB_AREA, expected)

    def test_multi_park_doc_with_one_mentioned_park_is_refined(self):
        # CL-T-02 的 subtype 是“度假区（多园区）”，但图谱里只被欢乐世界节点提及。
        self.assertEqual(sub_area_scope.doc_sub_area("CL-T-02"), "欢乐世界")
        self.assertEqual(sub_area_scope.doc_sub_area("CL-O-01"),
                         sub_area_scope.MULTI_SUB_AREA)


class PoiAttributionTests(unittest.TestCase):
    def test_wildlife_pois(self):
        self.assertEqual(poi_sub_area("POI|长隆|熊猫乐园"), "野生动物世界")
        self.assertEqual(poi_sub_area("POI|长隆|考拉园"), "野生动物世界")
        self.assertEqual(poi_sub_area("POI|长隆|4D影院"), "野生动物世界")

    def test_amusement_pois(self):
        self.assertEqual(poi_sub_area("POI|长隆|垂直过山车"), "欢乐世界")
        self.assertEqual(poi_sub_area("POI|长隆|十环过山车"), "欢乐世界")
        self.assertEqual(poi_sub_area("POI|长隆|超级大摆锤"), "欢乐世界")

    def test_shared_or_resort_level_pois_stay_unknown(self):
        # 出入口被多个园区提到，不能强行归到某一个园区。
        self.assertIsNone(poi_sub_area("POI|长隆|南门"))
        self.assertIsNone(poi_sub_area("POI|长隆|北门"))
        self.assertIsNone(poi_sub_area("POI|长隆|长隆旅游度假区"))

    def test_counts_cover_both_major_parks(self):
        counts = sub_area_scope.scope_counts()
        self.assertGreaterEqual(counts.get("欢乐世界", 0), 20)
        self.assertGreaterEqual(counts.get("野生动物世界", 0), 20)


class CandidateScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = get_route_candidates("长隆")

    def _kept_docs(self, scope):
        return {item["source_doc_id"] for item in scope["candidates"]}

    def test_amusement_scope_excludes_other_parks(self):
        scope = filter_route_candidates(self.candidates, "欢乐世界", "长隆")
        self.assertTrue(scope["applied"])
        self.assertIn("CL-T-02", self._kept_docs(scope))
        self.assertNotIn("CL-O-02", self._kept_docs(scope))
        self.assertNotIn("CL-T-03", self._kept_docs(scope))

    def test_wildlife_scope_excludes_amusement_routes(self):
        scope = filter_route_candidates(self.candidates, "野生动物世界", "长隆")
        self.assertTrue(scope["applied"])
        self.assertEqual(self._kept_docs(scope), {"CL-O-02", "CL-T-03"})
        self.assertNotIn("CL-T-02", self._kept_docs(scope))

    def test_insufficient_scope_falls_back_with_note(self):
        scope = filter_route_candidates(self.candidates, "水上乐园", "长隆")
        self.assertFalse(scope["applied"])
        self.assertTrue(scope["fallback"])
        self.assertEqual(scope["requested"], "水上乐园")
        self.assertIn("不足", scope["note"])
        self.assertEqual(scope["candidates"], self.candidates)

    def test_missing_anchor_falls_back_with_note(self):
        scope = filter_route_candidates(self.candidates, "飞鸟乐园", "长隆")
        self.assertFalse(scope["applied"])
        self.assertTrue(scope["fallback"])
        self.assertEqual(scope["requested"], "飞鸟乐园")
        self.assertIn("没有", scope["note"])

    def test_other_scenic_area_is_untouched(self):
        candidates = get_route_candidates("广州白云山")
        scope = filter_route_candidates(candidates, "欢乐世界", "广州白云山")
        self.assertFalse(scope["applied"])
        self.assertEqual(scope["candidates"], candidates)

    def test_no_sub_area_keeps_everything(self):
        scope = filter_route_candidates(self.candidates, None, "长隆")
        self.assertFalse(scope["applied"])
        self.assertIsNone(scope["requested"])
        self.assertEqual(scope["candidates"], self.candidates)


class PoiFilterTests(unittest.TestCase):
    def test_amusement_scope_filters_pois(self):
        results = search_poi("", "长隆", limit=1000)
        filtered, note = filter_poi_results(results, "欢乐世界", "长隆")
        names = {item["name"] for item in filtered}
        self.assertIn("垂直过山车", names)
        self.assertNotIn("熊猫乐园", names)
        self.assertIn("子园区", note)

    def test_wildlife_scope_filters_pois(self):
        results = search_poi("", "长隆", limit=1000)
        filtered, _ = filter_poi_results(results, "野生动物世界", "长隆")
        names = {item["name"] for item in filtered}
        self.assertIn("熊猫乐园", names)
        self.assertNotIn("垂直过山车", names)


class AgentScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = patch.object(trace_log, "SESSION_DIR", Path(self.temp.name))
        directory.start()
        self.addCleanup(directory.stop)
        self.ok = {"status": "ok", "explanation": "", "question": ""}

    def test_agent_detects_sub_area_and_filters_poi_list(self):
        intent = {"scenic_area": "长隆", "duration_days": None,
                  "traveler_profiles": [], "preferences": [], "constraints": []}
        decision = {"decision": "query_graph", "request_type": "info",
                    "reason": "查地点", "response": ""}
        selection = {"tools": ["search_poi"], "search_mode": "all_pois",
                     "search_keyword": "", "reason": "列出地点"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        mixed = [
            {"node_id": "POI|长隆|熊猫乐园", "name": "熊猫乐园", "scenic_area": "长隆"},
            {"node_id": "POI|长隆|垂直过山车", "name": "垂直过山车", "scenic_area": "长隆"},
            {"node_id": "POI|长隆|南门", "name": "南门", "scenic_area": "长隆"},
        ]
        with patch.object(agent, "parse_intent", return_value=intent), \
             patch.object(agent, "decide_next_step", return_value=decision), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "search_poi", return_value=mixed):
            result = agent.run_agent("长隆欢乐世界有哪些景点？")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["intent"]["sub_area"], "欢乐世界")
        self.assertEqual(result["scope"]["sub_area"], "欢乐世界")
        self.assertEqual([item["name"] for item in result["poi_results"]], ["垂直过山车"])
        self.assertIn("子园区", result["message"])

    def test_agent_passes_sub_area_to_route_planner(self):
        intent = {"scenic_area": "长隆", "duration_days": 1,
                  "traveler_profiles": [], "preferences": [], "constraints": []}
        decision = {"decision": "query_graph", "request_type": "plan",
                    "reason": "规划", "response": ""}
        selection = {"tools": ["get_route_candidates"], "search_mode": "none",
                     "search_keyword": "", "reason": "路线"}
        stop = {"tools": [], "search_mode": "none", "search_keyword": "", "reason": "结束"}
        route = {
            "proposal": {"node_ids": ["a", "b"], "explanation": "路线", "uncertainties": []},
            "validation": {"valid": True, "segments": [], "missing_connections": []},
            "message": "通过",
            "scope": {"requested": "欢乐世界", "applied": True,
                      "note": "已按子园区范围「欢乐世界」查询。", "kept_docs": [], "dropped_docs": []},
        }
        with patch.object(agent, "parse_intent", return_value=intent), \
             patch.object(agent, "decide_next_step", return_value=decision), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools", side_effect=[selection, stop]), \
             patch.object(agent, "find_relevant_conditions", return_value=[]), \
             patch.object(agent, "plan_route", return_value=route) as planner:
            result = agent.run_agent("我和朋友去长隆欢乐世界玩一天")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(planner.call_args.kwargs["sub_area"], "欢乐世界")
        self.assertIn("子园区", result["message"])


if __name__ == "__main__":
    unittest.main()
