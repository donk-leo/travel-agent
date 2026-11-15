"""证据服务测试（T1.6）：``doc_meta`` / ``quote_for`` / ``segment_evidence`` / ``scan_coverage``。

固定使用项目 1 冻结的 32 篇攻略 CSV 与项目 6 的图谱 CSV，只读、不联网、不调模型。
测试里另用一份独立的 CSV 读取与“名称是否在正文中”的判断来复核 ``scan_coverage()``，
避免只验证实现自己的口径。
"""

import csv
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import evidence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AREAS = ("baiyunshan", "changlong", "wugongshan")
GRAPH_DIR = PROJECT_ROOT / "analysis" / "p06_graph" / "outputs"
DOC_META_FIELDS = {
    "doc_id", "title", "source_url", "publish_date", "source_site",
    "doc_type", "scenic_area", "is_valid", "clean_chars",
}
CARD_FIELDS = {
    "doc_id", "title", "source_url", "publish_date", "source_site",
    "quote", "found",
}


def _load_raw_docs():
    docs = {}
    for area in AREAS:
        path = PROJECT_ROOT / "scenic" / area / "data" / "processed" / f"{area}_guides.csv"
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                docs[row["doc_id"]] = row
    return docs


def _load_graph_rows():
    with (GRAPH_DIR / "graph_nodes.csv").open(encoding="utf-8-sig", newline="") as file:
        nodes = list(csv.DictReader(file))
    with (GRAPH_DIR / "graph_edges.csv").open(encoding="utf-8-sig", newline="") as file:
        edges = list(csv.DictReader(file))
    return nodes, edges


RAW_DOCS = _load_raw_docs()
GRAPH_NODES, GRAPH_EDGES = _load_graph_rows()


class DocMetaTests(unittest.TestCase):
    def test_doc_meta_returns_documented_fields(self):
        meta = evidence.doc_meta("BYS-O-01")
        raw = RAW_DOCS["BYS-O-01"]

        self.assertIsInstance(meta, dict)
        self.assertEqual(set(meta), DOC_META_FIELDS)
        self.assertEqual(meta["doc_id"], "BYS-O-01")
        self.assertEqual(meta["title"], raw["title"])
        self.assertEqual(meta["source_url"], raw["source_url"])
        self.assertEqual(meta["publish_date"], "2020-06-29")
        self.assertEqual(meta["source_site"], "白云山官网")
        self.assertEqual(meta["doc_type"], "官方路线")
        self.assertEqual(meta["scenic_area"], "广州白云山")
        self.assertIs(meta["is_valid"], True)
        self.assertEqual(meta["clean_chars"], len(raw["clean_content"]))
        self.assertGreater(meta["clean_chars"], 0)

    def test_doc_meta_invalid_doc_id_returns_none(self):
        for value in (None, "", "   ", "CL-X-99", "不存在的文档", 123, [], True):
            with self.subTest(value=value):
                self.assertIsNone(evidence.doc_meta(value))

    def test_doc_meta_does_not_return_full_content(self):
        meta = evidence.doc_meta("CL-O-02")
        full = RAW_DOCS["CL-O-02"]["clean_content"]

        self.assertNotIn("clean_content", meta)
        self.assertNotIn("raw_content", meta)
        self.assertNotIn(full, meta.values())
        for value in meta.values():
            if isinstance(value, str):
                self.assertLess(len(value), len(full))
        # clean_chars 只是长度，不是正文本身
        self.assertEqual(meta["clean_chars"], len(full))

    def test_doc_meta_keeps_chinese_title_url_and_unknown_date_verbatim(self):
        self.assertEqual(evidence.doc_meta("BYS-T-01")["publish_date"], "未知")
        self.assertEqual(
            evidence.doc_meta("CL-T-03")["title"],
            "🐼🐨長隆野生動物園 | 無回頭路旅遊指南",
        )
        for doc_id, raw in RAW_DOCS.items():
            with self.subTest(doc_id=doc_id):
                meta = evidence.doc_meta(doc_id)
                self.assertEqual(meta["title"], raw["title"])
                self.assertEqual(meta["source_url"], raw["source_url"])
                self.assertEqual(meta["publish_date"], raw["publish_date"])
                self.assertEqual(meta["clean_chars"], len(raw["clean_content"]))

    def test_doc_meta_is_valid_is_boolean(self):
        self.assertIs(evidence.doc_meta("WGS-T-04")["is_valid"], False)
        self.assertIs(evidence.doc_meta("WGS-O-01")["is_valid"], True)


class QuoteForTests(unittest.TestCase):
    def test_span_returns_verbatim_slice(self):
        content = RAW_DOCS["BYS-O-01"]["clean_content"]
        quote = evidence.quote_for("BYS-O-01", span=(5, 25))

        self.assertEqual(quote, {
            "text": content[5:25],
            "char_start": 5,
            "char_end": 25,
            "doc_id": "BYS-O-01",
        })
        self.assertEqual(
            quote["text"],
            content[quote["char_start"]:quote["char_end"]],
        )

    def test_span_accepts_document_boundaries(self):
        content = RAW_DOCS["BYS-O-02"]["clean_content"]

        head = evidence.quote_for("BYS-O-02", span=(0, len(content)))
        self.assertEqual(head["text"], content)
        self.assertEqual((head["char_start"], head["char_end"]), (0, len(content)))

        tail = evidence.quote_for("BYS-O-02", span=(len(content) - 1, len(content)))
        self.assertEqual(tail["text"], content[-1:])

    def test_invalid_spans_return_none(self):
        length = len(RAW_DOCS["BYS-O-02"]["clean_content"])
        for span in (
            (-1, 5), (0, 0), (5, 5), (10, 9), (0, length + 1),
            (length, length), (length - 1, length + 1),
            "abc", (0,), (0, 1, 2), (None, 5), (0, "5"), (0.0, 5), (True, 5),
        ):
            with self.subTest(span=span):
                self.assertIsNone(evidence.quote_for("BYS-O-02", span=span))

    def test_node_id_uses_first_occurrence(self):
        content = RAW_DOCS["WGS-O-01"]["clean_content"]
        self.assertGreater(content.count("金顶"), 1)

        quote = evidence.quote_for("WGS-O-01", node_id="POI|武功山|金顶")

        self.assertEqual(quote["char_start"], content.find("金顶"))
        self.assertEqual(quote["text"], "金顶")
        self.assertEqual(
            quote["text"],
            content[quote["char_start"]:quote["char_end"]],
        )
        self.assertEqual(quote["doc_id"], "WGS-O-01")

    def test_unknown_doc_node_or_missing_arguments_return_none(self):
        self.assertIsNone(evidence.quote_for("CL-X-99", span=(0, 5)))
        self.assertIsNone(evidence.quote_for(None, span=(0, 1)))
        self.assertIsNone(evidence.quote_for("BYS-O-01", node_id="POI|不存在|也不存在"))
        # 图谱里的景区全称是「广州白云山」，BYS-O-01 正文只写「白云山」
        self.assertIsNone(evidence.quote_for("BYS-O-01", node_id="SCENIC_AREA|广州白云山"))
        self.assertIsNone(evidence.quote_for("BYS-O-01"))

    def test_span_takes_precedence_over_node_id(self):
        quote = evidence.quote_for(
            "BYS-O-01", node_id="POI|广州白云山|摩星岭", span=(1, 3)
        )
        self.assertEqual((quote["char_start"], quote["char_end"]), (1, 3))
        self.assertNotEqual(quote["text"], "摩星岭")


class SegmentEvidenceTests(unittest.TestCase):
    def test_multi_source_segment_produces_one_card_per_doc(self):
        segment = {
            "from_name": "黄婆洞水库",
            "to_name": "明珠楼",
            "source_doc_ids": ["BYS-T-02", "BYS-T-03"],
        }
        cards = evidence.segment_evidence(segment)

        self.assertEqual([card["doc_id"] for card in cards], ["BYS-T-02", "BYS-T-03"])
        for card, doc_id in zip(cards, ["BYS-T-02", "BYS-T-03"]):
            raw = RAW_DOCS[doc_id]
            content = raw["clean_content"]
            self.assertEqual(set(card), CARD_FIELDS)
            self.assertEqual(card["title"], raw["title"])
            self.assertEqual(card["source_url"], raw["source_url"])
            self.assertEqual(card["publish_date"], raw["publish_date"])
            self.assertEqual(card["source_site"], raw["source_site"])
            self.assertTrue(card["found"])
            self.assertEqual(card["quote"]["doc_id"], doc_id)
            self.assertEqual(card["quote"]["char_start"], content.find("黄婆洞水库"))
            self.assertEqual(
                card["quote"]["text"],
                content[card["quote"]["char_start"]:card["quote"]["char_end"]],
            )

    def test_missing_quote_keeps_card_for_ui(self):
        segment = {
            "from_name": "不存在的地点甲",
            "to_name": "不存在的地点乙",
            "source_doc_ids": ["BYS-O-01"],
        }
        cards = evidence.segment_evidence(segment)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["doc_id"], "BYS-O-01")
        self.assertEqual(cards[0]["title"], RAW_DOCS["BYS-O-01"]["title"])
        self.assertIsNone(cards[0]["quote"])
        self.assertFalse(cards[0]["found"])

    def test_empty_segment_or_missing_source_docs_returns_empty(self):
        for segment in (
            None, {}, [], {"from_name": "A", "to_name": "B"},
            {"source_doc_ids": []}, {"source_doc_ids": ""},
            {"source_doc_ids": "   "}, {"source_doc_ids": None},
        ):
            with self.subTest(segment=segment):
                self.assertEqual(evidence.segment_evidence(segment), [])

    def test_string_and_duplicate_source_docs_are_handled(self):
        base = {"from_name": "黄婆洞水库", "to_name": "明珠楼"}

        single = evidence.segment_evidence({**base, "source_doc_ids": "BYS-T-02"})
        self.assertEqual([card["doc_id"] for card in single], ["BYS-T-02"])

        cards = evidence.segment_evidence({
            **base,
            "source_doc_ids": ["BYS-T-02", "BYS-T-02", "CL-X-99", "BYS-T-03"],
        })
        self.assertEqual([card["doc_id"] for card in cards], ["BYS-T-02", "BYS-T-03"])

    def test_segment_without_names_keeps_card_without_quote(self):
        cards = evidence.segment_evidence({"source_doc_ids": ["BYS-O-01"]})

        self.assertEqual(len(cards), 1)
        self.assertIsNone(cards[0]["quote"])
        self.assertFalse(cards[0]["found"])


class ScanCoverageTests(unittest.TestCase):
    def test_metadata_coverage_is_complete(self):
        report = evidence.scan_coverage()

        self.assertEqual(report["nodes"], len(GRAPH_NODES))
        self.assertEqual(report["edges"], len(GRAPH_EDGES))
        self.assertEqual(report["nodes"], 247)
        self.assertEqual(report["edges"], 577)
        self.assertEqual(report["nodes_missing_meta"], 0)
        self.assertEqual(report["edges_missing_meta"], 0)
        self.assertGreater(report["node_doc_refs"], 0)
        self.assertGreater(report["edge_doc_refs"], 0)

    def test_all_source_docs_are_indexed(self):
        self.assertEqual(len(RAW_DOCS), 32)

        report = evidence.scan_coverage()
        self.assertEqual(
            report["nodes_missing_meta"] + report["edges_missing_meta"],
            0,
        )
        for example in report["missing_examples"]:
            with self.subTest(example=example):
                self.assertIsNotNone(evidence.doc_meta(example["doc_id"]))

    def test_counts_match_independent_recount(self):
        report = evidence.scan_coverage()
        node_by_id = {node["node_id"]: node for node in GRAPH_NODES}

        expected_node_quote = 0
        for node in GRAPH_NODES:
            for doc_id in filter(None, node["source_doc_ids"].split(";")):
                if node["name"] not in RAW_DOCS[doc_id]["clean_content"]:
                    expected_node_quote += 1

        expected_edge_quote = 0
        for edge in GRAPH_EDGES:
            names = [
                node_by_id[edge["src"]]["name"],
                node_by_id[edge["dst"]]["name"],
            ]
            for doc_id in filter(None, edge["source_doc_ids"].split(";")):
                content = RAW_DOCS[doc_id]["clean_content"]
                if not any(name in content for name in names):
                    expected_edge_quote += 1

        self.assertEqual(report["nodes_missing_quote"], expected_node_quote)
        self.assertEqual(report["edges_missing_quote"], expected_edge_quote)

    def test_quote_gaps_are_reported_honestly(self):
        report = evidence.scan_coverage()
        total = report["nodes_missing_quote"] + report["edges_missing_quote"]

        # 已知数据缺口：图谱节点名与原文写法不完全一致（全称/简称、繁简、异体字、
        # 以及 TIME/TRANSPORT 这类归一化后的抽象节点），不是取摘句失败。
        self.assertGreater(total, 0)
        self.assertEqual(report["nodes_missing_quote"], 31)
        self.assertEqual(report["edges_missing_quote"], 5)
        self.assertEqual(report["edges_without_source"], 7)
        self.assertEqual(report["nodes_without_source"], 0)
        self.assertEqual(
            len(report["missing_examples"]),
            min(evidence.MISSING_EXAMPLE_LIMIT, total),
        )
        for example in report["missing_examples"]:
            self.assertIn(example["kind"], {"node", "edge"})
            self.assertIn(
                example["reason"], {"missing_meta", "missing_quote", "no_source"}
            )
            self.assertTrue(example["id"])

    def test_scan_is_deterministic(self):
        self.assertEqual(evidence.scan_coverage(), evidence.scan_coverage())


if __name__ == "__main__":
    unittest.main()
