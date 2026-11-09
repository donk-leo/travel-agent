"""路线整理（减少重复绕行）的离线回归测试。"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import route_planner
from tools import (
    get_route_candidates,
    optimize_route,
    repair_route,
    route_metrics,
    validate_route,
)

# 2026-11-03 真实模型在“亲子与老人一日游”里给出的路线（见 outputs/evaluation_results.json）。
DEMO_ROUTE = [
    "POI|长隆|熊猫乐园",
    "POI|长隆|熊猫餐厅",
    "POI|长隆|4D影院",
    "POI|长隆|亚洲象园",
    "POI|长隆|长颈鹿广场",
    "POI|长隆|考拉园",
    "POI|长隆|亚洲象园",
    "POI|长隆|长颈鹿广场",
    "POI|长隆|考拉园",
    "POI|长隆|熊猫乐园",
    "POI|长隆|熊猫餐厅",
    "POI|长隆|4D影院",
    "POI|长隆|花果山",
    "POI|长隆|金猴王国",
    "POI|长隆|青龙山",
    "POI|长隆|百虎山",
    "POI|长隆|天鹅湖站",
    "POI|长隆|动物幼儿园",
    "POI|长隆|花车大巡游",
]

WUGONGSHAN_RETURN = [
    "POI|武功山|观音宕",
    "POI|武功山|吊马桩",
    "POI|武功山|金顶",
    "POI|武功山|中庵索道",
    "POI|武功山|石鼓寺",
    "POI|武功山|中庵索道",
]


class FakeResponse:
    """模拟 urllib 的响应对象，供 plan_route 的模型调用使用。"""

    def __init__(self, payload):
        self._data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._data


def fake_model(node_ids):
    """返回一个可替换 urlopen 的函数，同时记录请求体。"""
    calls = []

    def urlopen(request, timeout=180):
        calls.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse({
            "message": {
                "content": json.dumps(
                    {"node_ids": node_ids, "explanation": "模型原始路线",
                     "uncertainties": []},
                    ensure_ascii=False,
                )
            }
        })

    return urlopen, calls


class RouteMetricsTests(unittest.TestCase):
    def test_counts_repeated_visits(self):
        metrics = route_metrics(DEMO_ROUTE, get_route_candidates("长隆"))
        self.assertEqual(metrics["visits"], 19)
        self.assertEqual(metrics["unique_nodes"], 13)
        self.assertEqual(metrics["repeats"], 6)
        self.assertEqual(metrics["missing_segments"], 0)


class OptimizeRouteTests(unittest.TestCase):
    def test_removes_repeated_loop_and_keeps_evidence(self):
        candidates = get_route_candidates("长隆")
        optimized = optimize_route(DEMO_ROUTE, candidates)

        self.assertTrue(optimized["optimized"])
        self.assertLess(optimized["metrics"]["repeats"],
                        optimized["original_metrics"]["repeats"])
        self.assertLessEqual(optimized["metrics"]["steps"],
                             optimized["original_metrics"]["steps"])
        self.assertEqual(optimized["node_ids"][0], DEMO_ROUTE[0])
        self.assertTrue(optimized["validation"]["valid"])
        self.assertTrue(all(segment["source_doc_ids"]
                            for segment in optimized["validation"]["segments"]))

        # 目标地点集合不变，只是顺序和连接方式被整理过。
        self.assertEqual(set(optimized["node_ids"]), set(DEMO_ROUTE))

    def test_keeps_return_leg_to_cable_car(self):
        candidates = get_route_candidates("武功山")
        optimized = optimize_route(WUGONGSHAN_RETURN, candidates)
        self.assertEqual(optimized["node_ids"][-1], "POI|武功山|中庵索道")

    def test_short_route_is_left_alone(self):
        candidates = get_route_candidates("长隆")
        short = ["POI|长隆|尖叫地带", "POI|长隆|椰林餐厅"]
        optimized = optimize_route(short, candidates)
        self.assertFalse(optimized["optimized"])
        self.assertEqual(optimized["node_ids"], short)

    def test_repair_prefers_fresh_nodes(self):
        candidates = get_route_candidates("广州白云山")
        start = "POI|广州白云山|白云山南门"
        end = "POI|广州白云山|回归林"
        repaired = repair_route([start, end], candidates)
        self.assertTrue(repaired["repaired"])
        self.assertEqual(repaired["node_ids"][0], start)
        self.assertEqual(repaired["node_ids"][-1], end)
        self.assertEqual(repaired["repeated_nodes"], [])


class PlanRouteIntegrationTests(unittest.TestCase):
    def test_plan_route_optimizes_model_route(self):
        candidates = get_route_candidates("长隆")
        urlopen, _ = fake_model(DEMO_ROUTE)
        with patch.object(route_planner.urllib.request, "urlopen", urlopen):
            result = route_planner.plan_route(
                "我想带孩子和老人去长隆玩一天，喜欢游乐项目，尽量少走路。",
                "长隆", conditions=[])

        self.assertTrue(result["validation"]["valid"])
        self.assertLess(result["metrics"]["repeats"], 6)
        self.assertNotEqual(result["proposal"]["node_ids"], DEMO_ROUTE)
        uncertainties = " ".join(result["proposal"]["uncertainties"])
        self.assertIn("重排", uncertainties)
        self.assertIn("距离", uncertainties)
        self.assertEqual(result["message"], "路线连接已通过图谱核验。")

    def test_plan_route_limits_candidates_to_sub_area(self):
        route = ["POI|长隆|尖叫地带", "POI|长隆|椰林餐厅", "POI|长隆|律动天地"]
        urlopen, calls = fake_model(route)
        with patch.object(route_planner.urllib.request, "urlopen", urlopen):
            result = route_planner.plan_route(
                "去长隆欢乐世界玩一天", "长隆", conditions=[], sub_area="欢乐世界")

        self.assertTrue(result["scope"]["applied"])
        self.assertEqual(result["message"], "路线连接已通过图谱核验。（查询范围：长隆 · 欢乐世界）")

        payload = json.loads(calls[0]["messages"][1]["content"])
        docs = {item["source_doc_id"] for item in payload["route_candidates"]}
        self.assertIn("CL-T-02", docs)
        self.assertNotIn("CL-O-02", docs)
        self.assertNotIn("CL-T-03", docs)
        self.assertEqual(payload["scope"]["sub_area"], "欢乐世界")

    def test_plan_route_falls_back_when_sub_area_has_no_route(self):
        route = ["POI|长隆|尖叫地带", "POI|长隆|椰林餐厅", "POI|长隆|律动天地"]
        urlopen, calls = fake_model(route)
        with patch.object(route_planner.urllib.request, "urlopen", urlopen):
            result = route_planner.plan_route(
                "去长隆水上乐园玩一天", "长隆", conditions=[], sub_area="水上乐园")

        self.assertFalse(result["scope"]["applied"])
        self.assertIn("不足", result["scope"]["note"])
        payload = json.loads(calls[0]["messages"][1]["content"])
        self.assertIsNone(payload["scope"]["sub_area"])


if __name__ == "__main__":
    unittest.main()
