import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from itinerary import build_itinerary
from route_planner import _candidate_chain


class ItineraryTests(unittest.TestCase):
    def test_one_day_has_morning_noon_afternoon(self):
        route = {
            "proposal": {
                "node_ids": ["a", "b", "c", "d"],
                "node_names": {
                    "a": "北门", "b": "熊猫乐园",
                    "c": "熊猫餐厅", "d": "4D影院",
                },
                "day_plan": [{"day": 1, "node_ids": ["a", "b", "c", "d"]}],
            },
            "scope": {},
        }
        result = build_itinerary(route)
        periods = [item["period"] for item in result["days"][0]["periods"]]
        self.assertEqual(periods, ["上午", "中午", "下午"])
        self.assertIn("熊猫餐厅", result["days"][0]["periods"][1]["text"])
        self.assertIn("开放时间", result["note"])

    def test_three_days_keep_day_groups(self):
        route = {
            "proposal": {
                "node_ids": ["a", "b", "c"],
                "node_names": {"a": "金顶", "b": "吊马桩", "c": "发云界"},
                "day_plan": [
                    {"day": 1, "node_ids": ["a"]},
                    {"day": 2, "node_ids": ["b"]},
                    {"day": 3, "node_ids": ["c"]},
                ],
                "day_plan_fallback": True,
            },
            "scope": {},
        }
        result = build_itinerary(route)
        self.assertEqual([day["day"] for day in result["days"]], [1, 2, 3])
        self.assertIn("均分", result["note"])

    def test_sub_area_fallback_filters_unrelated_nodes(self):
        route = {
            "proposal": {
                "node_ids": ["wild", "water"],
                "node_names": {
                    "wild": "长隆野生动物世界",
                    "water": "长隆水上乐园",
                },
                "day_plan": [{"day": 1, "node_ids": ["wild", "water"]}],
            },
            "scope": {"requested": "水上乐园", "applied": False},
        }
        result = build_itinerary(route, sub_area="水上乐园")
        periods = result["days"][0]["periods"]
        self.assertEqual(len(periods), 3)
        self.assertIn("水上乐园", periods[0]["text"])
        self.assertNotIn("野生动物世界", " ".join(item["text"] for item in periods))
        self.assertIn("没有独立的连续路线", result["note"])

    def test_candidate_chain_returns_longest_path(self):
        candidates = [{
            "source_doc_id": "WGS-O-05",
            "connections": [
                {"from_node_id": "a", "to_node_id": "b"},
                {"from_node_id": "b", "to_node_id": "c"},
                {"from_node_id": "c", "to_node_id": "d"},
                {"from_node_id": "b", "to_node_id": "x"},
            ],
        }]
        self.assertEqual(_candidate_chain(candidates), ["a", "b", "c", "d"])


if __name__ == "__main__":
    unittest.main()