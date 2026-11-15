"""T0.3 评测骨架的 schema 单测（标准库 unittest，无新依赖）。

运行：
    .\\.venv\\Scripts\\python.exe analysis\\p07_agent\\eval\\tests\\test_eval_schema.py -v
"""

import sys
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_DIR))

import run_eval  # noqa: E402  （测试需要先插入 eval 目录）


SEED_IDS = {
    "CL-FAM-02", "CL-SUB-03", "BYS-ELD-01", "BYS-FRD-01", "WGS-FRD-01",
    "WGS-FAM-01", "WGS-ELD-01", "EDGE-MISS-01", "EDGE-FOLLOW-01", "CL-INFO-01",
}


class GoldenSetTest(unittest.TestCase):
    def test_golden_set_is_10_dev_cases(self):
        cases, problems = run_eval.load_golden_set()
        self.assertEqual(problems, [])
        self.assertEqual(len(cases), 10)
        self.assertEqual({case["id"] for case in cases}, SEED_IDS)
        self.assertEqual({case["split"] for case in cases}, {"dev"})
        self.assertEqual(len({case["id"] for case in cases}), 10)
        for case in cases:
            self.assertIn("expected", case)
            self.assertIn("query", case)

    def test_queries_are_not_rewritten(self):
        cases, _ = run_eval.load_golden_set()
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(
            by_id["CL-FAM-02"]["query"],
            "我想带孩子和老人去长隆玩一天，喜欢游乐项目，尽量少走路。",
        )
        self.assertEqual(
            by_id["EDGE-FOLLOW-01"]["query"],
            "我想出去玩一天 → 白云山，轻松一点。",
        )
        self.assertEqual(
            by_id["CL-INFO-01"]["query"],
            "长隆有哪些适合3岁孩子玩的项目？",
        )

    def test_expected_status_uses_four_values_only(self):
        cases, _ = run_eval.load_golden_set()
        allowed = set(run_eval.VALID_STATUSES)
        for case in cases:
            self.assertTrue(case["expected"]["status"], case["id"])
            self.assertTrue(set(case["expected"]["status"]) <= allowed, case["id"])

    def test_validate_case_rejects_bad_status(self):
        case = {
            "id": "X", "area": None, "days": None, "persona": [],
            "preferences": [], "constraints": [], "query": "x", "split": "dev",
            "expected": {
                "status": ["complete"], "must_include": [], "must_not": [],
                "evidence_required": True, "max_stops": None,
            },
        }
        problems = run_eval.validate_case(case)
        self.assertTrue(any("expected.status" in problem for problem in problems))

    def test_validate_case_rejects_duplicate_and_bad_split(self):
        case = {
            "id": "X", "area": "长隆", "days": 1, "persona": [],
            "preferences": [], "constraints": [], "query": "x", "split": "test",
            "expected": {
                "status": ["clarify"], "must_include": [], "must_not": [],
                "evidence_required": False, "max_stops": None,
            },
        }
        problems = run_eval.validate_case(case)
        self.assertTrue(any("split" in problem for problem in problems))

    def test_select_cases_handles_empty_heldout(self):
        cases, _ = run_eval.load_golden_set()
        self.assertEqual(run_eval.select_cases(cases, "heldout"), [])
        self.assertEqual(len(run_eval.select_cases(cases, "dev")), 10)
        self.assertEqual(len(run_eval.select_cases(cases, "all")), 10)
        self.assertEqual(len(run_eval.select_cases(cases, "dev", 1)), 1)


class StatusAndTurnTest(unittest.TestCase):
    def test_status_mapping(self):
        self.assertEqual(run_eval.normalize_status("complete"), "verified")
        self.assertEqual(run_eval.normalize_status("partial"), "partial")
        self.assertEqual(run_eval.normalize_status("clarify"), "clarify")
        self.assertEqual(run_eval.normalize_status("error"), "error")
        self.assertIsNone(run_eval.normalize_status("reply"))
        self.assertIsNone(run_eval.normalize_status(None))

    def test_multi_turn_submission_reuses_accumulated_text(self):
        case = {
            "query": "我想出去玩一天 → 白云山，轻松一点。",
            "turns": ["我想出去玩一天", "白云山，轻松一点。"],
        }
        self.assertEqual(
            run_eval.submission_texts(case),
            ["我想出去玩一天", "我想出去玩一天，白云山，轻松一点。"],
        )

    def test_single_turn_uses_query(self):
        self.assertEqual(run_eval.submission_texts({"query": "你好"}), ["你好"])


class SummaryTest(unittest.TestCase):
    def test_dry_run_record_has_no_metrics(self):
        cases, _ = run_eval.load_golden_set()
        record = run_eval.dry_run_record(cases[0])
        self.assertFalse(record["executed"])
        self.assertEqual(record["model_calls"], 0)
        self.assertIsNone(record["status"])
        self.assertIsNone(record["latency_s"])
        self.assertEqual(record["evidence"]["segments_total"], None)

    def test_summary_is_recomputable_from_cases(self):
        cases, _ = run_eval.load_golden_set()
        record = run_eval.dry_run_record(cases[0])
        record.update({
            "executed": True,
            "model_calls": 1,
            "status": "verified",
            "raw_status": "complete",
            "status_correct": True,
            "schema_pass": True,
            "latency_s": 12.5,
            "route": {
                "node_count": 3, "segment_count": 2,
                "validation_valid": True, "fully_verified": True,
            },
            "evidence": {
                "segments_total": 2, "segments_with_source": 2,
                "coverage": 1.0, "segments": [],
            },
        })
        record["expected"] = dict(record["expected"], max_stops=8)
        summary = run_eval.compute_summary([record])
        self.assertEqual(summary["n_cases"], 1)
        self.assertEqual(summary["n_executed_cases"], 1)
        self.assertEqual(summary["status_counts"]["verified"], 1)
        self.assertEqual(summary["status_correct"],
                         {"numerator": 1, "denominator": 1, "rate": 1.0})
        self.assertEqual(summary["evidence_coverage"],
                         {"numerator": 2, "denominator": 2, "rate": 1.0})
        self.assertEqual(summary["partial_rate"],
                         {"numerator": 0, "denominator": 1, "rate": 0.0})
        self.assertEqual(summary["latency_s"],
                         {"n": 1, "p50": 12.5, "p95": 12.5})
        self.assertEqual(summary["stop_cap_ok"],
                         {"numerator": 1, "denominator": 1, "rate": 1.0})

    def test_empty_summary_uses_null_rates(self):
        summary = run_eval.compute_summary([])
        self.assertEqual(summary["n_cases"], 0)
        self.assertIsNone(summary["status_correct"]["rate"])
        self.assertIsNone(summary["evidence_coverage"]["rate"])
        self.assertIsNone(summary["latency_s"]["p50"])


if __name__ == "__main__":
    unittest.main()
