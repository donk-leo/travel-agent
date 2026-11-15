"""T2.3 分时行程 v2 测试：显式时间、未知时间、餐饮/休息、时长来源与兼容性。

覆盖 DoD 1–4：
- ``time_range`` 只来自 P6 ``AT_TIME`` 的显式钟点；没有资料钟点时
  ``time_range=None`` / ``time_source="absent"`` 且文案写「资料未给出」；
- 中午 11:30–13:30 一定有餐饮/休息块，没有餐饮节点时写「未找到餐饮点」；
- 时长只给模板区间并标 ``duration_source="模板估算"``，同时写进 ``unknowns``；
- 人群提示只来自传入的 feasibility，不写成资料事实；
- 多日分天、旧字段兼容、两次调用结果相同、节点顺序不被改动。
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from itinerary import build_itinerary


CLOCK_RANGE_RE = re.compile(r"^\d{2}:\d{2}(?:-\d{2}:\d{2})?$")

#: 禁止作为“事实”出现的编造内容（免责句里的词不算，故只匹配带数值的写法）。
FORBIDDEN_PATTERNS = (
    re.compile(r"\d+(?:\.\d+)?\s*(?:公里|千米|km|KM)"),
    re.compile(r"\d+\s*元"),
    re.compile(r"(?:经度|纬度|经纬度)\s*[:：]?\s*\d"),
    re.compile(r"(?:开放时间|营业时间)\s*[:：]\s*\d"),
    re.compile(r"合计\s*\d+(?:\.\d+)?\s*小时"),
)


def _route(node_ids, names=None, day_plan=None):
    """构造与 plan_route() 返回值同形的最小路线（只读字段）。"""
    node_ids = list(node_ids)
    if names is None:
        names = {node_id: node_id.split("|")[-1] for node_id in node_ids}
    proposal = {
        "node_ids": node_ids,
        "node_names": dict(names),
        "explanation": "测试路线",
        "uncertainties": [],
    }
    if day_plan is not None:
        proposal["day_plan"] = day_plan
    return {"proposal": proposal, "scope": {}}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _feasibility(persona="老人", max_stops=6, meal_inserted=False):
    return {
        "caps": {"persona": persona, "max_stops": max_stops},
        "meal": {
            "inserted": meal_inserted,
            "slot": "11:30–13:30",
            "note": "测试用餐饮判断。",
        },
        "warnings": [],
        "uncertainties": ["测试用可行性假设。"],
    }


class ExplicitTimeTests(unittest.TestCase):
    def test_explicit_time_is_preserved_verbatim(self):
        """P6 AT_TIME 里的显式钟点原样进入 time_range，不被模板改写。"""
        node_ids = [
            "ACTIVITY|刺激项目",
            "ACTIVITY|错峰午餐",
            "ACTIVITY|沉浸体验",
        ]
        names = {
            "ACTIVITY|刺激项目": "刺激项目",
            "ACTIVITY|错峰午餐": "错峰午餐",
            "ACTIVITY|沉浸体验": "沉浸体验",
        }
        result = build_itinerary(_route(node_ids, names))
        periods = result["days"][0]["periods"]

        self.assertEqual([item["period"] for item in periods], ["上午", "中午", "下午"])
        self.assertEqual(
            [item["time_range"] for item in periods],
            ["09:00-12:00", "12:00-13:30", "13:30-17:30"],
        )
        self.assertTrue(all(item["time_source"] == "explicit" for item in periods))

    def test_absent_time_is_not_filled(self):
        """没有资料钟点时 time_range 必须为 None，文案必须写「资料未给出」。"""
        node_ids = ["a", "b", "c"]
        result = build_itinerary(_route(
            node_ids, {"a": "北门", "b": "熊猫乐园", "c": "4D影院"}
        ))
        for period in result["days"][0]["periods"]:
            self.assertIsNone(period["time_range"])
            self.assertEqual(period["time_source"], "absent")
            self.assertIn("资料未给出", period["text"])
            # 中午的 11:30–13:30 是显式标注的规划用餐时段，不是资料钟点；
            # 其余文案里不得出现任何模板钟点。
            remaining = period["text"].replace("11:30–13:30", "")
            self.assertNotRegex(remaining, r"\d{1,2}:\d{2}")

    def test_time_range_only_appears_for_explicit(self):
        """所有时段都满足：有 time_range 必有 explicit，absent 必为 None。"""
        result = build_itinerary(_route(
            ["a", "b", "c", "d"],
            {"a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院"},
        ))
        for period in result["days"][0]["periods"]:
            if period["time_source"] == "explicit":
                self.assertRegex(period["time_range"], CLOCK_RANGE_RE)
            else:
                self.assertEqual(period["time_source"], "absent")
                self.assertIsNone(period["time_range"])


class MealAndRestTests(unittest.TestCase):
    def test_meal_is_inserted_when_food_node_exists(self):
        node_ids = ["a", "b", "c", "d"]
        result = build_itinerary(_route(node_ids, {
            "a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院",
        }))
        noon = result["days"][0]["periods"][1]
        self.assertEqual(noon["period"], "中午")
        self.assertTrue(noon["meal"]["inserted"])
        self.assertIn("熊猫餐厅", noon["meal"]["note"])
        self.assertIn("营业时间", noon["meal"]["note"])
        self.assertTrue(noon["rest"]["inserted"])

    def test_meal_fallback_when_no_food_node(self):
        node_ids = ["a", "b", "c"]
        result = build_itinerary(_route(node_ids, {
            "a": "北门", "b": "熊猫乐园", "c": "4D影院",
        }))
        noon = result["days"][0]["periods"][1]
        self.assertFalse(noon["meal"]["inserted"])
        self.assertIn("未找到餐饮点，请以现场为准", noon["meal"]["note"])
        self.assertIn("11:30–13:30", noon["meal"]["note"])
        self.assertTrue(noon["rest"]["inserted"])

    def test_hotel_is_not_used_as_meal_name(self):
        node_ids = ["a", "hotel", "c"]
        result = build_itinerary(_route(node_ids, {
            "a": "北门", "hotel": "长隆酒店", "c": "4D影院",
        }))
        noon = result["days"][0]["periods"][1]
        self.assertFalse(noon["meal"]["inserted"])
        self.assertNotIn("在「长隆酒店」用餐", noon["meal"]["note"])


class DurationAndUnknownTests(unittest.TestCase):
    def test_duration_has_source_label(self):
        """模板时长必须标「模板估算」，并进 unknowns。"""
        result = build_itinerary(_route(
            ["a", "b", "c", "d"],
            {"a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院"},
        ))
        for period in result["days"][0]["periods"]:
            self.assertTrue(period["duration_hint"])
            self.assertEqual(period["duration_source"], "模板估算")
            self.assertIn("小时", period["duration_hint"])
            self.assertIn(
                "时长为模板估算，不是资料给出的实际游玩时长。",
                period["unknowns"],
            )

    def test_evening_duration_is_unknown(self):
        """晚上没有模板区间：duration_hint=None、来源「未给出」、写进 unknowns。"""
        node_ids = ["ACTIVITY|安检入口", "ACTIVITY|午餐休息", "ACTIVITY|夜场演出"]
        names = {
            "ACTIVITY|安检入口": "安检入口",
            "ACTIVITY|午餐休息": "午餐休息",
            "ACTIVITY|夜场演出": "夜场演出",
        }
        result = build_itinerary(_route(node_ids, names))
        periods = result["days"][0]["periods"]
        self.assertEqual([item["period"] for item in periods], ["上午", "中午", "晚上"])
        evening = periods[-1]
        self.assertIsNone(evening["duration_hint"])
        self.assertEqual(evening["duration_source"], "未给出")
        self.assertTrue(any("未做估算" in item for item in evening["unknowns"]))

    def test_every_period_has_unknowns(self):
        result = build_itinerary(_route(
            ["a", "b", "c", "d"],
            {"a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院"},
        ))
        for day in result["days"]:
            for period in day["periods"]:
                self.assertIsInstance(period["unknowns"], list)
                self.assertGreaterEqual(len(period["unknowns"]), 1)
                self.assertTrue(all(isinstance(item, str) and item for item in period["unknowns"]))


class DayGroupingAndCompatibilityTests(unittest.TestCase):
    def test_multi_day_keeps_day_groups(self):
        node_ids = ["a", "b", "c", "d"]
        day_plan = [
            {"day": 1, "node_ids": ["a", "b"]},
            {"day": 2, "node_ids": ["c", "d"]},
        ]
        result = build_itinerary(_route(node_ids, {
            "a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院",
        }, day_plan=day_plan))
        self.assertEqual([day["day"] for day in result["days"]], [1, 2])
        first = [stop["node_id"] for period in result["days"][0]["periods"]
                 for stop in period["stops"]]
        second = [stop["node_id"] for period in result["days"][1]["periods"]
                  for stop in period["stops"]]
        self.assertEqual(first, ["a", "b"])
        self.assertEqual(second, ["c", "d"])
        for day in result["days"]:
            self.assertIn("资料未给出", day["plan_note"])

    def test_legacy_fields_are_present(self):
        result = build_itinerary(_route(
            ["a", "b", "c"],
            {"a": "北门", "b": "熊猫餐厅", "c": "4D影院"},
        ))
        day = result["days"][0]
        self.assertIn("plan_note", day)
        self.assertIn("note", result)
        self.assertIn("开放时间", result["note"])
        for period in day["periods"]:
            self.assertIsInstance(period["text"], str)
            self.assertTrue(period["text"])
            self.assertIn("duration_hint", period)
            self.assertIn("period", period)
        self.assertIn("熊猫餐厅", day["periods"][1]["text"])

    def test_node_order_is_not_changed(self):
        node_ids = ["a", "b", "c", "d", "e"]
        names = {"a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院", "e": "火烈鸟"}
        result = build_itinerary(_route(node_ids, names))
        flattened = [
            stop["node_id"]
            for day in result["days"]
            for period in day["periods"]
            for stop in period["stops"]
        ]
        self.assertEqual(flattened, node_ids)

    def test_result_is_deterministic(self):
        route = _route(
            ["a", "b", "c", "d"],
            {"a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院"},
        )
        feasibility = _feasibility()
        first = build_itinerary(route, profiles=["老人"], feasibility=feasibility)
        second = build_itinerary(route, profiles=["老人"], feasibility=feasibility)
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )

    def test_route_is_not_mutated(self):
        """行程生成只读路线：node_ids / day_plan / node_names 原样不动。"""
        route = _route(
            ["a", "b", "c", "d"],
            {"a": "北门", "b": "熊猫乐园", "c": "熊猫餐厅", "d": "4D影院"},
            day_plan=[{"day": 1, "node_ids": ["a", "b", "c", "d"]}],
        )
        before = json.dumps(route, ensure_ascii=False, sort_keys=True)
        build_itinerary(route, feasibility=_feasibility())
        self.assertEqual(before, json.dumps(route, ensure_ascii=False, sort_keys=True))


class HonestyTests(unittest.TestCase):
    def test_fatigue_note_comes_from_feasibility(self):
        node_ids = [f"POI|长隆|点{index}" for index in range(1, 8)]
        result = build_itinerary(
            _route(node_ids), feasibility=_feasibility("老人", 6)
        )
        first = result["days"][0]["periods"][0]
        self.assertIn("老人", first["fatigue_note"])
        self.assertIn("6", first["fatigue_note"])
        self.assertIn("未做硬性过滤", first["fatigue_note"])
        self.assertIn("超过建议上限", first["fatigue_note"])
        self.assertNotIn("已为老人优化", " ".join(_strings(result)))
        self.assertIn("可行性", result["note"])

    def test_no_distance_price_coordinate_or_opening_hours_facts(self):
        result = build_itinerary(
            _route(
                ["ACTIVITY|刺激项目", "ACTIVITY|错峰午餐", "ACTIVITY|沉浸体验"],
                {
                    "ACTIVITY|刺激项目": "刺激项目",
                    "ACTIVITY|错峰午餐": "错峰午餐",
                    "ACTIVITY|沉浸体验": "沉浸体验",
                },
            ),
            feasibility=_feasibility("成人", 8, meal_inserted=True),
        )
        text = " ".join(_strings(result))
        for pattern in FORBIDDEN_PATTERNS:
            self.assertIsNone(pattern.search(text), pattern.pattern)

    def test_note_states_time_source_policy(self):
        result = build_itinerary(_route(["a", "b", "c"]))
        self.assertIn("不用模板时间冒充", result["note"])
        self.assertIn("模板估算", result["note"])
        self.assertIn("未找到餐饮点，请以现场为准", result["note"])


if __name__ == "__main__":
    unittest.main()
