"""备选路线（T2.4）离线回归测试：只读 P6 图谱，不调用模型、不联网。"""

import json
import os
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# T2.7 结果缓存默认开启；本模块用 patch 替换模型/路线夹具，必须关闭缓存避免跨用例串结果。
os.environ["P07_RESULT_CACHE"] = "0"

import agent
import alternatives
import trace_log
from alternatives import build_alternatives, validate_alternative
from route_planner import _candidate_chain, select_primary_candidate
from tools import get_route_candidates, load_graph


#: 三个景区的代表查询。主路线用确定性兜底链代替模型输出，保证测试离线可复现。
AREAS = (
    ("长隆", "带孩子和老人玩一天"),
    ("广州白云山", "想去摩星岭看日落"),
    ("武功山", "想去金顶看日出"),
)


def primary_route(area, user_text):
    """返回 ``(主来源候选, 主路线节点链)``；不调用模型，走同一份候选连接。"""
    candidates = get_route_candidates(area)
    primary = select_primary_candidate(candidates, user_text)
    return primary, _candidate_chain([primary])


def edge(from_id, to_id, doc_ids):
    """构造与 ``tools.get_route()`` 同形状的一条连接。"""
    return {
        "from_node_id": from_id,
        "from_name": from_id.split("|")[-1],
        "to_node_id": to_id,
        "to_name": to_id.split("|")[-1],
        "source_doc_ids": list(doc_ids),
    }


class BuildAlternativesOnGraphTests(unittest.TestCase):
    """直接读真实 P6 图谱，验证 DoD 1–3 的硬性约束。"""

    def test_each_area_has_two_or_three_single_source_alternatives(self):
        for area, text in AREAS:
            with self.subTest(area=area):
                primary, chain = primary_route(area, text)
                alts = build_alternatives(
                    area, days=1,
                    primary_doc_id=primary["source_doc_id"],
                    primary_node_ids=chain,
                )
                self.assertGreaterEqual(len(alts), 2)
                self.assertLessEqual(len(alts), 3)
                doc_ids = [alt["source_doc_id"] for alt in alts]
                self.assertEqual(len(doc_ids), len(set(doc_ids)))
                for alt in alts:
                    self.assertTrue(alt["source_doc_id"])
                    self.assertNotIn(";", alt["source_doc_id"])
                    self.assertNotEqual(alt["source_doc_id"],
                                        primary["source_doc_id"])
                    self.assertGreaterEqual(len(alt["node_ids"]), 2)
                    self.assertEqual(len(alt["node_names"]),
                                     len(alt["node_ids"]))
                    self.assertIn(alt["status"], {"verified", "partial"})
                    if alt["status"] == "verified":
                        self.assertTrue(alt["reason"])
                        self.assertEqual(len(alt["segments"]),
                                         len(alt["node_ids"]) - 1)

    def test_verified_alternatives_only_use_their_own_document(self):
        for area, text in AREAS:
            primary, chain = primary_route(area, text)
            alts = build_alternatives(area, primary_doc_id=primary["source_doc_id"],
                                      primary_node_ids=chain)
            for alt in alts:
                with self.subTest(area=area, doc=alt["source_doc_id"]):
                    self.assertTrue(alt["segments"])
                    for segment in alt["segments"]:
                        self.assertEqual(segment["source_doc_ids"],
                                         [alt["source_doc_id"]])
                        self.assertTrue(segment["from_name"])
                        self.assertTrue(segment["to_name"])

    def test_primary_document_and_node_set_are_excluded(self):
        for area, text in AREAS:
            with self.subTest(area=area):
                primary, chain = primary_route(area, text)
                alts = build_alternatives(area, primary_doc_id=primary["source_doc_id"],
                                          primary_node_ids=chain)
                for alt in alts:
                    self.assertNotEqual(alt["source_doc_id"],
                                        primary["source_doc_id"])
                    self.assertNotEqual(frozenset(alt["node_ids"]),
                                        frozenset(chain))
                # 只给节点集合、不给主来源文档时，同样不能拿同集合充备选。
                same_set = build_alternatives(area, primary_node_ids=chain)
                for alt in same_set:
                    self.assertNotEqual(frozenset(alt["node_ids"]),
                                        frozenset(chain))

    def test_alternatives_are_deterministic(self):
        area, text = AREAS[0]
        primary, chain = primary_route(area, text)
        kwargs = dict(primary_doc_id=primary["source_doc_id"],
                      primary_node_ids=chain, max_alts=3)
        first = build_alternatives(area, days=1, **kwargs)
        second = build_alternatives(area, days=1, **kwargs)
        self.assertEqual(json.dumps(first, ensure_ascii=False),
                         json.dumps(second, ensure_ascii=False))

    def test_alternative_nodes_exist_in_graph(self):
        nodes, edges = load_graph()
        names_by_id = {node["node_id"]: node["name"] for node in nodes}
        next_docs = defaultdict(set)
        for item in edges:
            if item["rel"] == "NEXT":
                next_docs[(item["src"], item["dst"])].update(
                    doc_id for doc_id in item["source_doc_ids"].split(";") if doc_id
                )

        for area, text in AREAS:
            primary, chain = primary_route(area, text)
            alts = build_alternatives(area, primary_doc_id=primary["source_doc_id"],
                                      primary_node_ids=chain)
            for alt in alts:
                with self.subTest(area=area, doc=alt["source_doc_id"]):
                    # 不编造节点：每个节点都来自图谱，名称与图谱原值一致。
                    self.assertEqual(
                        alt["node_names"],
                        [names_by_id[node_id] for node_id in alt["node_ids"]],
                    )
                    # 不编造连接：每一段都是该来源文档的图谱 NEXT 有向边。
                    for start_id, end_id in zip(alt["node_ids"],
                                                alt["node_ids"][1:]):
                        self.assertIn((start_id, end_id), next_docs)
                        self.assertIn(alt["source_doc_id"],
                                      next_docs[(start_id, end_id)])

    def test_max_alts_is_respected(self):
        area, text = AREAS[0]
        primary, chain = primary_route(area, text)
        kwargs = dict(primary_doc_id=primary["source_doc_id"],
                      primary_node_ids=chain)
        self.assertEqual(len(build_alternatives(area, max_alts=1, **kwargs)), 1)
        self.assertEqual(build_alternatives(area, max_alts=0, **kwargs), [])

    def test_validate_alternative_on_graph_alt(self):
        area, text = AREAS[0]
        primary, chain = primary_route(area, text)
        alts = build_alternatives(area, primary_doc_id=primary["source_doc_id"],
                                  primary_node_ids=chain)
        status, segments, reasons = validate_alternative(alts[0])
        self.assertEqual(status, "verified")
        self.assertEqual(reasons, [])
        self.assertEqual(len(segments), len(alts[0]["node_ids"]) - 1)


class BuildAlternativesMockTests(unittest.TestCase):
    """用构造的候选覆盖去重与跨文档/缺段标记，不依赖真实图谱。"""

    N1 = "POI|长隆|甲"
    N2 = "POI|长隆|乙"
    N3 = "POI|长隆|丙"
    MAIN = "POI|长隆|主路线起点"

    def test_same_node_set_in_different_order_is_dropped(self):
        candidates = [
            # 同一组节点，一篇顺走、一篇倒着写：只能保留一条，不能算两条备选。
            {"source_doc_id": "DOC-A", "connections": [
                edge(self.N1, self.N2, ["DOC-A"]),
                edge(self.N2, self.N3, ["DOC-A"]),
            ]},
            {"source_doc_id": "DOC-B", "connections": [
                edge(self.N3, self.N2, ["DOC-B"]),
                edge(self.N2, self.N1, ["DOC-B"]),
            ]},
        ]
        with patch.object(alternatives, "get_route_candidates",
                          return_value=candidates):
            alts = build_alternatives("长隆", primary_doc_id="DOC-MAIN",
                                      primary_node_ids=[self.MAIN])
        self.assertEqual([alt["source_doc_id"] for alt in alts], ["DOC-A"])

    def test_same_node_set_as_primary_is_dropped(self):
        candidates = [{
            "source_doc_id": "DOC-A",
            "connections": [
                edge(self.N3, self.N2, ["DOC-A"]),
                edge(self.N2, self.N1, ["DOC-A"]),
            ],
        }]
        with patch.object(alternatives, "get_route_candidates",
                          return_value=candidates):
            alts = build_alternatives(
                "长隆", primary_node_ids=[self.N1, self.N2, self.N3])
        self.assertEqual(alts, [])

    def test_cross_document_segment_is_partial(self):
        # 候选标记为 DOC-A，但连接证据只挂在 DOC-B 上：这是跨文档拼接，不能判 verified。
        candidates = [{
            "source_doc_id": "DOC-A",
            "connections": [
                edge(self.N1, self.N2, ["DOC-B"]),
                edge(self.N2, self.N3, ["DOC-B"]),
            ],
        }]
        with patch.object(alternatives, "get_route_candidates",
                          return_value=candidates):
            alts = build_alternatives("长隆", primary_doc_id="DOC-MAIN",
                                      primary_node_ids=[self.MAIN])
        self.assertEqual(len(alts), 1)
        self.assertEqual(alts[0]["status"], "partial")
        self.assertIn("跨文档", alts[0]["reason"])
        self.assertTrue(all(segment["source_doc_ids"] == ["DOC-B"]
                            for segment in alts[0]["segments"]))

    def test_missing_segment_is_partial(self):
        alt = {"source_doc_id": "DOC-A", "scenic_area": "长隆",
               "node_ids": [self.N1, self.N2, self.N3]}
        candidates = [{
            "source_doc_id": "DOC-A",
            "connections": [edge(self.N1, self.N2, ["DOC-A"])],
        }]
        status, segments, reasons = validate_alternative(
            alt, candidates=candidates)
        self.assertEqual(status, "partial")
        self.assertEqual(len(segments), 1)
        self.assertTrue(any("缺少" in reason for reason in reasons))

    def test_no_candidates_returns_empty_list(self):
        with patch.object(alternatives, "get_route_candidates", return_value=[]):
            self.assertEqual(build_alternatives("长隆"), [])

    def test_too_few_stops_is_not_an_alternative(self):
        alt = {"source_doc_id": "DOC-A", "scenic_area": "长隆",
               "node_ids": [self.N1]}
        status, segments, _ = validate_alternative(alt, candidates=[])
        self.assertEqual(status, "partial")
        self.assertEqual(segments, [])


class AgentAlternativesTests(unittest.TestCase):
    """run_agent 接线：alternatives 字段存在、异常不影响主流程。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = patch.object(trace_log, "SESSION_DIR", Path(self.temp.name))
        directory.start()
        self.addCleanup(directory.stop)

        self.intent = {"scenic_area": "长隆", "duration_days": 1}
        self.plan = {"decision": "query_graph", "request_type": "plan",
                     "reason": "需要规划", "response": ""}
        self.ok = {"status": "ok", "explanation": "", "question": ""}
        self.selection = {"tools": ["get_route_candidates"], "search_mode": "none",
                          "search_keyword": "", "reason": "查询路线"}
        self.stop = {"tools": [], "search_mode": "none",
                     "search_keyword": "", "reason": "结束"}
        primary, chain = primary_route("长隆", "带孩子和老人玩一天")
        self.primary_doc = primary["source_doc_id"]
        self.chain = chain
        self.route = {
            "proposal": {"node_ids": chain, "explanation": "路线",
                         "uncertainties": [], "source_doc_id": self.primary_doc},
            "validation": {"valid": True, "fully_verified": True,
                           "segments": [], "missing_connections": [],
                           "cross_doc_transitions": 0},
            "message": "路线连接已通过图谱核验。",
            "scope": {"requested": None, "applied": False, "note": "",
                      "kept_docs": [], "dropped_docs": []},
            "metrics": {},
            "source_doc_id": self.primary_doc,
        }

    def _run(self):
        with patch.object(agent, "parse_intent", return_value=self.intent), \
             patch.object(agent, "decide_next_step", return_value=self.plan), \
             patch.object(agent, "check_constraints", return_value=self.ok), \
             patch.object(agent, "check_plan", return_value=self.ok), \
             patch.object(agent, "select_tools",
                          side_effect=[self.selection, self.stop]), \
             patch.object(agent, "plan_route", return_value=self.route):
            return agent.run_agent("带孩子去长隆玩一天")

    def test_run_agent_attaches_alternatives_list(self):
        result = self._run()
        # T2.2b 可行性闸：这条夹具是 12 个节点的一天（成人上限 8），
        # 已裁剪为 8 个且逐段核验通过，因此状态保持 verified；本用例只验证
        # alternatives 接线，不验证状态判定本身。
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["route"]["proposal"]["node_ids"]), 8)
        self.assertIs(result["route"], self.route)
        self.assertIsInstance(result["alternatives"], list)
        self.assertTrue(result["alternatives"])
        self.assertLessEqual(len(result["alternatives"]), 3)
        for alt in result["alternatives"]:
            self.assertNotEqual(alt["source_doc_id"], self.primary_doc)
            expected = {"alt_id", "source_doc_id", "source_title",
                        "node_names", "status", "reason", "segments"}
            self.assertTrue(expected.issubset(alt.keys()))

    def test_alternative_failure_does_not_break_main_flow(self):
        with patch.object(agent, "build_alternatives",
                          side_effect=RuntimeError("备选生成失败")):
            result = self._run()
        # 同上：12 个节点的一天超过成人上限 8，已裁剪到 8 个并保持 verified；
        # 备选生成失败不能把主流程变成 error。
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["alternatives"], [])
        self.assertEqual(result["route"], self.route)

    def test_non_route_flow_still_returns_alternatives_list(self):
        # 没有路线时（这里因缺天数转 clarify）字段仍存在且为空列表。
        with patch.object(agent, "parse_intent",
                          return_value={"scenic_area": "长隆",
                                        "duration_days": None}), \
             patch.object(agent, "decide_next_step", return_value=self.plan):
            result = agent.run_agent("去长隆")
        self.assertEqual(result["status"], "clarify")
        self.assertIsNone(result["route"])
        self.assertEqual(result["alternatives"], [])


if __name__ == "__main__":
    unittest.main()
