"""T4.5 失败分类回归测试（离线、确定性：不调用模型、不联网、不依赖时间）。

覆盖四组事实，全部从仓库内**已冻结**的产物读取或构造：

1. dev20 结果 JSON 的冻结事实：20 条、split=dev、15 verified / 4 partial / 1 clarify、
   5 条非 verified 全部 `status_correct=true` 且落在 golden `expected.status` 内；
2. 5 条非 verified 的 F 分类：`report.classify_case` 能判的（F5/F6）直接用，
   预期内但分类器按设计不覆盖的（CL-SUB-03、EDGE-MISS-01）按 FAILURES.md §2.2
   的确定性规则补标签——**不修改** `report.py` / runner；
3. F12/F13 兜底：超时、执行异常、status 不在四值内、schema_pass=false；
4. `FAILURES.md` 的关键断言（5 个 id、0 条未分类、P0=0、复现命令、无「已修复」），
   以及新增单案例工具 `eval/repro_case.py` 的选条/ dry-run 不调用模型。

这些测试刻意不读 `results/sessions/`（被 `.gitignore` 忽略的本地产物），
也不读仓库外路径；只依赖入库的 `results/*.json`、`golden_set.jsonl`、`FAILURES.md`。
"""

import copy
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
P07_DIR = TESTS_DIR.parent
EVAL_DIR = P07_DIR / "eval"
RESULTS_PATH = EVAL_DIR / "results" / "dev-real-20261116T132849.json"
FAILURES_PATH = EVAL_DIR / "FAILURES.md"
REPRO_PATH = EVAL_DIR / "repro_case.py"

if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import report  # noqa: E402 - eval/ 下的只读报告模块
import repro_case  # noqa: E402 - T4.5 新增的单案例复现工具
import run_eval  # noqa: E402 - 评测 runner（只读复用其口径）

NON_VERIFIED_IDS = ("CL-SUB-03", "BYS-FRD-01", "WGS-FAM-01", "WGS-ELD-01", "EDGE-MISS-01")
EXPECTED_WITHIN_IDS = ("CL-SUB-03", "EDGE-MISS-01")
F_LABELS = {f"F{index}" for index in range(1, 14)}


def load_results():
    """读取入库的 dev20 结果 JSON（只读）。"""
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def result_cases():
    return load_results()["cases"]


def cases_by_id():
    return {case["id"]: case for case in result_cases()}


def t45_main_label(case):
    """T4.5 主类：优先自动分类，再按 FAILURES.md §2.2 的规则 A/B 补标签。

    规则 A（F4，预期内单点）：partial + expected 只允许 partial + 单点 + max_stops=1。
    规则 B（F2，预期内缺槽位）：clarify + expected 只允许 clarify + no_route_nodes。
    两条规则只用于**归类**，不改 status/summary；分类器返回 [] 的事实照样保留。
    """
    tags = report.dedupe(report.classify_case(case))
    if tags:
        return tags[0][0]
    route = case.get("route") or {}
    expected = case.get("expected") or {}
    reasons = case.get("route_reasons") or []
    if (
        case.get("status") == "partial"
        and expected.get("status") == ["partial"]
        and route.get("single_destination") is True
        and route.get("node_count") == 1
        and expected.get("max_stops") == 1
    ):
        return "F4"
    if (
        case.get("status") == "clarify"
        and expected.get("status") == ["clarify"]
        and "no_route_nodes" in reasons
    ):
        return "F2"
    return None


def is_expected_within(case):
    """FAILURES.md 的「是否预期内」：缺槽位 clarify 与单点园区 partial 两条。"""
    return case["id"] in EXPECTED_WITHIN_IDS


def failures_table_rows():
    """解析 FAILURES.md 总表：返回 {id: 单元格列表}。"""
    rows = {}
    for line in FAILURES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        case_id = cells[0].strip("`")
        # 只收 §3 总表（10 列：id/status/expected/F/现象/预期内/复现/日志/责任/状态），
        # §5 的「dev 中位置」表只有 3 列，不能拿来当失败分类行。
        if case_id in NON_VERIFIED_IDS and len(cells) == 10:
            rows[case_id] = cells
    return rows


class FrozenResultFactsTests(unittest.TestCase):
    """结果 JSON 的冻结事实：样本没被删、状态没被改写。"""

    def test_result_json_is_dev20_real_run(self):
        data = load_results()
        meta = data["meta"]
        self.assertEqual(meta["split"], "dev")
        self.assertEqual(meta["run_mode"], "real")
        self.assertEqual(meta["model"], "qwen3:8b")
        self.assertEqual(meta["timeout_s"], 180.0)
        self.assertEqual(meta["max_attempts"], 2)
        self.assertIsNone(meta["limit"])
        self.assertEqual(len(data["cases"]), 20)
        self.assertEqual(data["summary"]["n_cases"], 20)
        self.assertEqual(data["summary"]["split_counts"], {"dev": 20, "heldout": 0})

    def test_result_has_no_heldout_case(self):
        splits = {case["split"] for case in result_cases()}
        self.assertEqual(splits, {"dev"})

    def test_status_counts_match_cases(self):
        data = load_results()
        counts = {"verified": 0, "partial": 0, "clarify": 0, "error": 0}
        for case in data["cases"]:
            counts[case["status"]] += 1
        self.assertEqual(counts, {"verified": 15, "partial": 4, "clarify": 1, "error": 0})
        self.assertEqual(data["summary"]["status_counts"], counts)
        self.assertEqual(data["summary"]["status_other"], 0)

    def test_summary_recomputes_from_cases(self):
        data = load_results()
        computed = run_eval.compute_summary(data["cases"])
        self.assertEqual(computed, data["summary"])

    def test_exactly_five_non_verified(self):
        ids = {case["id"] for case in result_cases() if case["status"] != "verified"}
        self.assertEqual(ids, set(NON_VERIFIED_IDS))
        self.assertEqual(len(ids), 5)

    def test_all_non_verified_are_within_expected(self):
        for case in result_cases():
            if case["id"] not in NON_VERIFIED_IDS:
                continue
            with self.subTest(case=case["id"]):
                self.assertIs(case["status_correct"], True)
                self.assertIn(case["status"], case["expected"]["status"])

    def test_partial_was_not_rewritten_as_verified(self):
        by_id = cases_by_id()
        partial_ids = {case["id"] for case in result_cases() if case["status"] == "partial"}
        clarify_ids = {case["id"] for case in result_cases() if case["status"] == "clarify"}
        self.assertEqual(partial_ids, {"CL-SUB-03", "BYS-FRD-01", "WGS-FAM-01", "WGS-ELD-01"})
        self.assertEqual(clarify_ids, {"EDGE-MISS-01"})
        for case_id in NON_VERIFIED_IDS:
            self.assertNotEqual(by_id[case_id]["status"], "verified")

    def test_all_cases_schema_and_status_contract(self):
        for case in result_cases():
            with self.subTest(case=case["id"]):
                self.assertIs(case["schema_pass"], True)
                self.assertIs(case["executed"], True)
                self.assertIn(case["status"], run_eval.VALID_STATUSES)


class ClassifyCaseTests(unittest.TestCase):
    """F 分类：自动规则 + T4.5 补标签规则（不改 report.py）。"""

    def test_route_truncated_maps_to_f5(self):
        case = cases_by_id()["BYS-FRD-01"]
        self.assertIs(case["route"]["route_truncated"], True)
        tags = report.dedupe(report.classify_case(case))
        self.assertEqual([tag[0] for tag in tags], ["F5"])
        self.assertIn("route_truncated", tags[0][1])
        self.assertEqual(t45_main_label(case), "F5")

    def test_day_plan_fallback_maps_to_f6(self):
        by_id = cases_by_id()
        for case_id in ("WGS-FAM-01", "WGS-ELD-01"):
            with self.subTest(case=case_id):
                case = by_id[case_id]
                self.assertIs(case["route"]["day_plan_fallback"], True)
                tags = report.dedupe(report.classify_case(case))
                self.assertEqual([tag[0] for tag in tags], ["F6"])
                self.assertEqual(t45_main_label(case), "F6")

    def test_single_destination_guard_explains_empty_auto_label(self):
        """CL-SUB-03 自动分类为 []：max_stops=1 时 F4 分支被守卫挡掉，不是没数据。"""
        case = cases_by_id()["CL-SUB-03"]
        self.assertEqual(report.dedupe(report.classify_case(case)), [])
        self.assertIs(case["route"]["single_destination"], True)
        self.assertEqual(case["route"]["node_count"], 1)
        self.assertEqual(case["expected"]["max_stops"], 1)
        # 同一份记录把上限改成 8，F4 分支就应命中：证明守卫是唯一原因。
        widened = copy.deepcopy(case)
        widened["expected"]["max_stops"] = 8
        widened_tags = [tag[0] for tag in report.dedupe(report.classify_case(widened))]
        self.assertIn("F4", widened_tags)

    def test_clarify_expected_suppresses_f3_by_design(self):
        """EDGE-MISS-01：expected 含 clarify 时 classify_case 不打 F3（没有规划请求）。"""
        case = cases_by_id()["EDGE-MISS-01"]
        self.assertEqual(case["route_reasons"], ["no_route_nodes"])
        self.assertEqual(report.dedupe(report.classify_case(case)), [])
        # 把期望换成 verified，同一记录就应命中 F3：证明是 expected 决定了抑制。
        widened = copy.deepcopy(case)
        widened["expected"]["status"] = ["verified"]
        widened_tags = [tag[0] for tag in report.dedupe(report.classify_case(widened))]
        self.assertIn("F3", widened_tags)

    def test_t45_labels_cover_all_five_without_empty_class(self):
        by_id = cases_by_id()
        labels = {case_id: t45_main_label(by_id[case_id]) for case_id in NON_VERIFIED_IDS}
        self.assertEqual(
            labels,
            {
                "CL-SUB-03": "F4",
                "BYS-FRD-01": "F5",
                "WGS-FAM-01": "F6",
                "WGS-ELD-01": "F6",
                "EDGE-MISS-01": "F2",
            },
        )
        self.assertNotIn(None, labels.values())
        self.assertTrue(set(labels.values()) <= F_LABELS)

    def test_expected_within_flags_are_specific(self):
        by_id = cases_by_id()
        flags = {case_id: is_expected_within(by_id[case_id]) for case_id in NON_VERIFIED_IDS}
        self.assertTrue(flags["CL-SUB-03"])
        self.assertTrue(flags["EDGE-MISS-01"])
        self.assertFalse(flags["BYS-FRD-01"])
        self.assertFalse(flags["WGS-FAM-01"])
        self.assertFalse(flags["WGS-ELD-01"])

    def test_timeout_maps_to_f12(self):
        tags = report.classify_case(
            {"executed": False, "timeout": True, "error": None, "expected": {"status": ["verified"]}}
        )
        self.assertEqual([tag[0] for tag in tags], ["F12"])
        self.assertIn("超时", tags[0][1])

    def test_execution_error_maps_to_f13(self):
        tags = report.classify_case(
            {"executed": False, "timeout": False, "error": "RuntimeError: boom",
             "expected": {"status": ["verified"]}}
        )
        self.assertEqual([tag[0] for tag in tags], ["F13"])
        self.assertIn("RuntimeError: boom", tags[0][1])

    def test_status_none_and_schema_fail_map_to_f13(self):
        case = {
            "executed": True,
            "status": None,
            "raw_status": "complete",
            "schema_pass": False,
            "status_correct": False,
            "expected": {"status": ["verified"]},
            "route": {},
            "evidence": {},
            "route_reasons": [],
        }
        tags = report.dedupe(report.classify_case(case))
        self.assertEqual(tags[0][0], "F13")
        labels = [tag[0] for tag in tags]
        self.assertIn("F13", labels)
        self.assertIn("F2", labels)


class FailuresDocTests(unittest.TestCase):
    """FAILURES.md 是交付物：必须覆盖 5 条、声明 0 未分类 / P0=0、且不谎称已修复。"""

    def setUp(self):
        self.text = FAILURES_PATH.read_text(encoding="utf-8")
        self.rows = failures_table_rows()

    def test_failures_md_exists_and_mentions_scope(self):
        self.assertTrue(FAILURES_PATH.is_file())
        self.assertGreater(len(self.text), 2000)
        for needle in (RESULTS_PATH.name, "03_EVAL_SPEC.md", "f35bc7a431293dcadf08d0d9139724f8669fcc39",
                       "qwen3:8b", "F1–F13"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.text)

    def test_failures_md_has_all_five_rows(self):
        self.assertEqual(set(self.rows), set(NON_VERIFIED_IDS))
        self.assertEqual(len(self.rows), 5)

    def test_failures_md_rows_have_real_status_and_f_label(self):
        by_id = cases_by_id()
        for case_id, cells in self.rows.items():
            with self.subTest(case=case_id):
                self.assertEqual(cells[1], by_id[case_id]["status"])
                self.assertRegex(cells[3], r"\*\*F(?:[1-9]|1[0-3])\*\*")

    def test_failures_md_declares_zero_unclassified(self):
        self.assertIn("0 条未分类", self.text)
        self.assertIn("未分类 0", self.text)

    def test_failures_md_declares_p0_zero(self):
        self.assertRegex(self.text, r"P0\s*=\s*0")
        self.assertIn("未发现 P0", self.text)

    def test_failures_md_says_samples_are_not_hidden(self):
        self.assertIn("不是被隐藏的样本", self.text)
        self.assertIn("20 条", self.text)

    def test_failures_md_gives_real_repro_commands(self):
        self.assertTrue(REPRO_PATH.is_file())
        self.assertIn("repro_case.py", self.text)
        for case_id in NON_VERIFIED_IDS:
            with self.subTest(case=case_id):
                self.assertIn(f"--id {case_id}", self.text)

    def test_failures_md_does_not_claim_fixed(self):
        for case_id, cells in self.rows.items():
            with self.subTest(case=case_id):
                self.assertNotIn("已修复", "|".join(cells))
                self.assertRegex(cells[-1], r"`(?:known/accepted|open P[12])`")

    def test_failures_md_documents_auto_classifier_gap(self):
        self.assertIn("report.classify_case", self.text)
        self.assertIn("规则 A", self.text)
        self.assertIn("规则 B", self.text)


class GoldenSetGuardTests(unittest.TestCase):
    """golden 是只读输入：30 条 / 20 dev / 5 条的 expected 与结果记录一致。"""

    def test_golden_set_keeps_30_cases_and_20_dev(self):
        cases, problems = run_eval.load_golden_set(EVAL_DIR / "golden_set.jsonl")
        self.assertEqual(problems, [])
        self.assertEqual(len(cases), 30)
        self.assertEqual(sum(1 for case in cases if case["split"] == "dev"), 20)
        self.assertEqual(sum(1 for case in cases if case["split"] == "heldout"), 10)

    def test_golden_expected_matches_result_records(self):
        cases, _ = run_eval.load_golden_set(EVAL_DIR / "golden_set.jsonl")
        golden = {case["id"]: case for case in cases}
        by_id = cases_by_id()
        for case_id in NON_VERIFIED_IDS:
            with self.subTest(case=case_id):
                self.assertEqual(golden[case_id]["expected"], by_id[case_id]["expected"])
        self.assertEqual(golden["CL-SUB-03"]["expected"]["max_stops"], 1)
        self.assertEqual(golden["EDGE-MISS-01"]["boundary_kind"], "missing_slot")
        self.assertEqual(golden["CL-SUB-03"]["expected"]["status"], ["partial"])
        self.assertEqual(golden["EDGE-MISS-01"]["expected"]["status"], ["clarify"])


class ReproCaseTests(unittest.TestCase):
    """repro_case.py：按 id 选 1 条；dry-run 不 import agent / 不调用模型。"""

    def test_find_case_selects_one_by_id(self):
        case, problems = repro_case.find_case("CL-SUB-03")
        self.assertEqual(problems, [])
        self.assertEqual(case["id"], "CL-SUB-03")
        self.assertEqual(case["expected"]["status"], ["partial"])
        self.assertEqual(case["split"], "dev")

    def test_find_case_unknown_id_returns_problem(self):
        case, problems = repro_case.find_case("NOPE-99")
        self.assertIsNone(case)
        self.assertEqual(len(problems), 1)
        self.assertIn("NOPE-99", problems[0])

    def test_dry_run_does_not_call_load_agent_or_model(self):
        buffer = io.StringIO()
        with mock.patch.object(repro_case.run_eval, "load_agent", side_effect=AssertionError("dry-run 不许加载 agent")):
            with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
                code = repro_case.main(["--id", "CL-SUB-03", "--dry-run"])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["id"], "CL-SUB-03")
        self.assertEqual(payload["mode"], "dry-run")
        self.assertIs(payload["executed"], False)
        self.assertIsNone(payload["status"])

    def test_unknown_id_main_exits_2_without_model(self):
        with mock.patch.object(repro_case.run_eval, "load_agent", side_effect=AssertionError("不许加载 agent")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = repro_case.main(["--id", "NOPE-99", "--dry-run"])
        self.assertEqual(code, 2)

    def test_real_path_reuses_run_case_and_never_calls_model_here(self):
        fake_record = {"id": "BYS-FRD-01", "mode": "real", "executed": True, "status": "partial"}
        buffer = io.StringIO()
        with mock.patch.object(repro_case.run_eval, "load_agent", return_value=("fake_run_agent", "fake_model", "fake_url")):
            with mock.patch.object(repro_case.run_eval, "run_case", return_value=fake_record) as fake_run_case:
                with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
                    code = repro_case.main(["--id", "BYS-FRD-01"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue()), fake_record)
        self.assertEqual(fake_run_case.call_count, 1)
        called_case, called_agent = fake_run_case.call_args.args
        self.assertEqual(called_case["id"], "BYS-FRD-01")
        self.assertEqual(called_agent, "fake_run_agent")

    def test_dry_run_out_writes_only_given_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "case.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = repro_case.main(["--id", "EDGE-MISS-01", "--dry-run", "--out", str(out_path)])
            self.assertEqual(code, 0)
            self.assertTrue(out_path.is_file())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["id"], "EDGE-MISS-01")
            self.assertEqual(payload["mode"], "dry-run")


if __name__ == "__main__":
    unittest.main()
