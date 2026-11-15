"""P7 评测 golden set 的 schema 单测（标准库 unittest，无新依赖）。

T4.1：golden set 扩到 30 条（20 dev / 10 held-out），并删除评测侧
``complete→verified`` 临时映射，因此这里同步断言四值、split 分布、边界计数。

运行：
    .\\.venv\\Scripts\\python.exe -m unittest analysis.p07_agent.eval.tests.test_eval_schema -q
"""

import collections
import sys
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_DIR))

import run_eval  # noqa: E402  （测试需要先插入 eval 目录）


# 03_EVAL_SPEC.md §2.2 的 30 条，顺序与表一致。
GOLDEN_IDS = [
    "CL-FAM-01", "CL-FAM-02", "CL-CPL-01", "CL-FRD-01", "CL-ELD-01",
    "CL-SUB-01", "CL-SUB-02", "CL-SUB-03", "CL-2D-01", "CL-INFO-01",
    "BYS-ELD-01", "BYS-FAM-01", "BYS-FRD-01", "BYS-CPL-01", "BYS-SOLO-01",
    "BYS-2D-01", "BYS-INFO-01", "BYS-CONFLICT-01",
    "WGS-FRD-01", "WGS-FAM-01", "WGS-CPL-01", "WGS-SOLO-01", "WGS-ELD-01",
    "WGS-3D-01", "WGS-INFO-01", "WGS-BUDGET-01",
    "EDGE-MISS-01", "EDGE-FOLLOW-01", "EDGE-UNSUP-01", "EDGE-NOMATCH-01",
]


def _valid_case(status=("verified",), split="dev"):
    """构造一条通过 schema 的最小 case，供断言负例时改字段。"""
    return {
        "id": "X", "area": None, "days": None, "persona": [],
        "preferences": [], "constraints": [], "query": "x", "split": split,
        "expected": {
            "status": list(status), "must_include": [], "must_not": [],
            "evidence_required": True, "max_stops": None,
        },
    }


class GoldenSetTest(unittest.TestCase):
    def test_golden_set_is_30_cases_20_dev_10_heldout(self):
        cases, problems = run_eval.load_golden_set()
        self.assertEqual(problems, [])
        self.assertEqual(len(cases), 30)
        self.assertEqual([case["id"] for case in cases], GOLDEN_IDS)
        self.assertEqual(len({case["id"] for case in cases}), 30)
        self.assertEqual(
            collections.Counter(case["split"] for case in cases),
            {"dev": 20, "heldout": 10},
        )
        for case in cases:
            self.assertIn("expected", case)
            self.assertIn("query", case)
            self.assertIsInstance(case["boundary"], bool, case["id"])
            self.assertIsInstance(case["boundary_kind"], str, case["id"])

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
        # T4.1 新增条目同样逐字照抄 §2.2（抽查含全角标点/数字边界）
        self.assertEqual(
            by_id["CL-SUB-01"]["query"],
            "我想去长隆欢乐世界玩一天，喜欢刺激项目。",
        )
        self.assertEqual(
            by_id["BYS-SOLO-01"]["query"],
            "我一个人去白云山，只有3小时，怎么走？",
        )
        self.assertEqual(
            by_id["WGS-3D-01"]["query"],
            "我想带孩子去武功山玩三天。",
        )
        self.assertEqual(
            by_id["EDGE-NOMATCH-01"]["query"],
            "白云山有火星大峡谷吗？",
        )

    def test_expected_status_uses_four_values_only(self):
        cases, _ = run_eval.load_golden_set()
        allowed = set(run_eval.VALID_STATUSES)
        for case in cases:
            self.assertTrue(case["expected"]["status"], case["id"])
            self.assertTrue(set(case["expected"]["status"]) <= allowed, case["id"])

    def test_validate_case_rejects_bad_status(self):
        case = _valid_case(status=("success",))
        problems = run_eval.validate_case(case)
        self.assertTrue(any("expected.status" in problem for problem in problems))

    def test_validate_case_rejects_legacy_complete_status(self):
        # T4.1：complete 不再是合法状态，评测侧也不再有别名。
        case = _valid_case(status=("complete",))
        problems = run_eval.validate_case(case)
        self.assertTrue(any("expected.status" in problem for problem in problems))

    def test_validate_case_rejects_bad_split(self):
        case = _valid_case(split="test")
        problems = run_eval.validate_case(case)
        self.assertTrue(any("split" in problem for problem in problems))

    def test_select_cases_by_split(self):
        cases, _ = run_eval.load_golden_set()
        self.assertEqual(len(run_eval.select_cases(cases, "heldout")), 10)
        self.assertEqual(len(run_eval.select_cases(cases, "dev")), 20)
        self.assertEqual(len(run_eval.select_cases(cases, "all")), 30)
        self.assertEqual(len(run_eval.select_cases(cases, "dev", 1)), 1)

    def test_boundary_cases_at_least_8(self):
        cases, _ = run_eval.load_golden_set()
        boundary = [case for case in cases if case["boundary"]]
        self.assertGreaterEqual(len(boundary), 8)
        for case in boundary:
            self.assertTrue(case["boundary_kind"], case["id"])
        for case in cases:
            if not case["boundary"]:
                self.assertEqual(case["boundary_kind"], "", case["id"])

    def test_max_stops_single_day_policy(self):
        cases, _ = run_eval.load_golden_set()
        by_id = {case["id"]: case for case in cases}
        # Q4（已签字）：带 0–6 岁儿童/老人单日 ≤6；普通成人单日 ≤8。
        self.assertEqual(by_id["CL-FAM-01"]["expected"]["max_stops"], 6)
        self.assertEqual(by_id["CL-ELD-01"]["expected"]["max_stops"], 6)
        self.assertEqual(by_id["BYS-FAM-01"]["expected"]["max_stops"], 6)
        self.assertEqual(by_id["CL-CPL-01"]["expected"]["max_stops"], 8)
        self.assertEqual(by_id["WGS-SOLO-01"]["expected"]["max_stops"], 8)
        # D0 冻结种子保持 8，是否收紧到 6 列为待人类确认（REVIEW_T4.1.md）。
        self.assertEqual(by_id["CL-FAM-02"]["expected"]["max_stops"], 8)

    def test_cl_info_01_follows_spec_heldout_ruling(self):
        cases, _ = run_eval.load_golden_set()
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(by_id["CL-INFO-01"]["split"], "heldout")
        self.assertIn("T4.1", by_id["CL-INFO-01"]["notes"])


class StatusAndTurnTest(unittest.TestCase):
    def test_normalize_status_only_accepts_four_values(self):
        for status in ("verified", "partial", "clarify", "error"):
            self.assertEqual(run_eval.normalize_status(status), status)
        # T2.1 已把 complete 改成 verified；T4.1 删除别名后旧值不再被接受。
        self.assertIsNone(run_eval.normalize_status("complete"))
        self.assertIsNone(run_eval.normalize_status("reply"))
        self.assertIsNone(run_eval.normalize_status("success"))
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
            "raw_status": "verified",
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
        self.assertEqual(summary["status_other"], 0)
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

    def test_summary_counts_unmapped_status_as_other(self):
        cases, _ = run_eval.load_golden_set()
        record = run_eval.dry_run_record(cases[0])
        record.update({
            "executed": True, "model_calls": 1,
            "status": None, "raw_status": "complete",
            "status_correct": None, "schema_pass": True,
            "latency_s": 1.0,
            "route": {"node_count": 1, "validation_valid": None},
            "evidence": {"segments_total": 0, "segments_with_source": 0},
        })
        summary = run_eval.compute_summary([record])
        self.assertEqual(summary["status_other"], 1)
        self.assertEqual(summary["status_counts"],
                         {"verified": 0, "partial": 0, "clarify": 0, "error": 0})
        self.assertEqual(summary["status_correct"]["numerator"], 0)

    def test_empty_summary_uses_null_rates(self):
        summary = run_eval.compute_summary([])
        self.assertEqual(summary["n_cases"], 0)
        self.assertIsNone(summary["status_correct"]["rate"])
        self.assertIsNone(summary["evidence_coverage"]["rate"])
        self.assertIsNone(summary["latency_s"]["p50"])


if __name__ == "__main__":
    unittest.main()
