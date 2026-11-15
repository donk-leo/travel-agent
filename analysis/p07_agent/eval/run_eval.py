#!/usr/bin/env python
"""P7 评测骨架（T0.3）：读取 golden set，调用真实 run_agent，记录结果并计算指标。

设计约束（见 03_EVAL_SPEC.md §2/§3/§8）：
- 指标全部由 cases 计算，脚本里不写死任何成功率、延迟、证据覆盖率；
- ``--dry-run`` 不 import agent、不调用模型，只校验 golden set schema 并写出空骨架；
- 只有真实运行才把 ``analysis/p07_agent/src`` 插入 sys.path 并 import ``run_agent``；
- 每条查询超时 180s、失败重试 1 次；超时/异常如实记录，不删难样本；
- 多轮查询按 ``turns`` 顺序提交，后一轮复用前几轮拼接后的完整文本。

用法：
    python analysis/p07_agent/eval/run_eval.py --split dev --limit 1 --dry-run
    python analysis/p07_agent/eval/run_eval.py --split dev --limit 2
"""

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[2]
GOLDEN_PATH = EVAL_DIR / "golden_set.jsonl"
RESULTS_DIR = EVAL_DIR / "results"
SRC_DIR = EVAL_DIR.parent / "src"

# 当前 agent.py 返回 complete；T2.1 会改成 verified。评测侧只认四值，
# 这里做显式映射，映射关系写进 eval/README.md，不手改任何结果。
STATUS_ALIASES = {
    "verified": "verified",
    "complete": "verified",
    "partial": "partial",
    "clarify": "clarify",
    "error": "error",
}
VALID_STATUSES = ("verified", "partial", "clarify", "error")
VALID_SPLITS = ("dev", "heldout")
REQUIRED_RESULT_KEYS = (
    "status", "message", "route", "suggestions", "poi_results",
    "intent", "decision", "error",
)
TIMEOUT_S = 180.0
MAX_ATTEMPTS = 2
GOLDEN_SET_DISPLAY = "analysis/p07_agent/eval/golden_set.jsonl"
RUNNER_DISPLAY = "analysis/p07_agent/eval/run_eval.py"


# ---------------------------------------------------------------------------
# golden set 读取与 schema 校验
# ---------------------------------------------------------------------------

def _problem(prefix, message):
    return f"{prefix}: {message}" if prefix else message


def validate_case(case, line_no=None):
    """校验单条查询；返回问题列表，空列表表示通过。"""
    prefix = f"第 {line_no} 行" if line_no is not None else "未知条目"
    if not isinstance(case, dict):
        return [_problem(prefix, "不是 JSON 对象")]
    prefix = f"第 {line_no} 行" if line_no is not None else str(case.get("id") or "未知条目")
    problems = []

    def need(condition, message):
        if not condition:
            problems.append(_problem(prefix, message))

    case_id = case.get("id")
    need(isinstance(case_id, str) and bool(case_id.strip()), "id 必须是非空字符串")
    need(isinstance(case.get("query"), str) and bool(case["query"].strip()),
         "query 必须是非空字符串")
    need(case.get("split") in VALID_SPLITS, "split 必须是 dev 或 heldout")
    need(case.get("area") is None or isinstance(case.get("area"), str),
         "area 必须是字符串或 null")

    days = case.get("days")
    need(days is None or (
        isinstance(days, (int, float)) and not isinstance(days, bool) and days > 0
    ), "days 必须是正数或 null")

    for key in ("persona", "preferences", "constraints"):
        value = case.get(key)
        need(isinstance(value, list) and all(isinstance(item, str) for item in value),
             f"{key} 必须是字符串数组")

    turns = case.get("turns")
    if turns is not None:
        need(isinstance(turns, list) and len(turns) >= 2
             and all(isinstance(turn, str) and turn.strip() for turn in turns),
             "turns 必须是至少 2 条非空字符串的数组（多轮查询）")

    expected = case.get("expected")
    need(isinstance(expected, dict), "expected 必须是对象")
    if isinstance(expected, dict):
        status = expected.get("status")
        need(isinstance(status, list) and bool(status)
             and all(item in VALID_STATUSES for item in status),
             f"expected.status 必须是非空数组，且只含 {VALID_STATUSES}")
        for key in ("must_include", "must_not"):
            value = expected.get(key)
            need(isinstance(value, list) and all(isinstance(item, str) for item in value),
                 f"expected.{key} 必须是字符串数组")
        need(isinstance(expected.get("evidence_required"), bool),
             "expected.evidence_required 必须是布尔值")
        max_stops = expected.get("max_stops")
        need(max_stops is None or (
            isinstance(max_stops, int) and not isinstance(max_stops, bool) and max_stops > 0
        ), "expected.max_stops 必须是正整数或 null")

    return problems


def load_golden_set(path=GOLDEN_PATH):
    """读取 JSONL；返回 (cases, problems)。空行忽略，非法行记问题并跳过。"""
    path = Path(path)
    if not path.exists():
        return [], [f"golden set 不存在：{path}"]
    cases = []
    problems = []
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"第 {line_no} 行 JSON 解析失败：{exc}")
            continue
        problems.extend(validate_case(case, line_no))
        cases.append(case)

    seen = {}
    for case in cases:
        case_id = case.get("id")
        seen[case_id] = seen.get(case_id, 0) + 1
    for case_id, count in seen.items():
        if count > 1:
            problems.append(f"id 重复：{case_id}（出现 {count} 次）")
    if not cases and not problems:
        problems.append("golden set 为空")
    return cases, problems


def select_cases(cases, split, limit=None):
    """按 split 过滤，再截取前 limit 条。heldout 为空时返回空列表而不报错。"""
    if split == "all":
        selected = list(cases)
    else:
        selected = [case for case in cases if case.get("split") == split]
    if limit is not None:
        selected = selected[:limit]
    return selected


# ---------------------------------------------------------------------------
# 单条查询执行
# ---------------------------------------------------------------------------

def submission_texts(case):
    """返回每一轮实际提交的完整文本；无 turns 时只提交 query。

    多轮时把前面几轮拼进当前轮，复用同一段累积文本；turn 之间用中文逗号
    连接（仅当上一轮不以句末标点结尾）。query 字段保留规范原文，不用于提交。
    """
    turns = case.get("turns") or []
    if not turns:
        return [case["query"]]
    texts = []
    parts = []
    for turn in turns:
        turn = turn.strip()
        if parts and not parts[-1].endswith(("。", "！", "？", "!", "?", ".")):
            parts.append("，")
        parts.append(turn)
        texts.append("".join(parts))
    return texts


def normalize_status(raw_status):
    """把 agent 原始状态映射成规范四值；未知值返回 None（不猜）。"""
    if not isinstance(raw_status, str):
        return None
    return STATUS_ALIASES.get(raw_status.strip())


def check_schema(result):
    """检查 run_agent 返回值是否符合当前契约；不检查内容对错。"""
    if not isinstance(result, dict):
        return False
    if any(key not in result for key in REQUIRED_RESULT_KEYS):
        return False
    if not isinstance(result.get("status"), str) or not result["status"].strip():
        return False
    if not isinstance(result.get("route"), (dict, type(None))):
        return False
    if not isinstance(result.get("suggestions"), list):
        return False
    return True


def extract_route(result):
    """从 run_agent 结果中抽出路线节点数、逐段证据与结构问题。"""
    route = (result or {}).get("route") or {}
    proposal = route.get("proposal") or {}
    validation = route.get("validation") or {}
    node_ids = proposal.get("node_ids") or []
    segments = []
    for segment in validation.get("segments") or []:
        source_doc_ids = sorted(str(doc) for doc in (segment.get("source_doc_ids") or []))
        segments.append({
            "from_name": segment.get("from_name"),
            "to_name": segment.get("to_name"),
            "source_doc_ids": source_doc_ids,
            "has_source": bool(source_doc_ids),
        })
    evidence = {
        "segments_total": len(segments),
        "segments_with_source": sum(1 for segment in segments if segment["has_source"]),
        "coverage": (
            round(sum(1 for segment in segments if segment["has_source"]) / len(segments), 4)
            if segments else None
        ),
        "segments": segments,
    }
    route_info = {
        "node_count": len(node_ids),
        "segment_count": len(segments),
        "single_destination": bool(route.get("single_destination")),
        "validation_valid": validation.get("valid"),
        "fully_verified": validation.get("fully_verified"),
        "missing_connections": len(validation.get("missing_connections") or []),
        "cross_doc_transitions": validation.get("cross_doc_transitions") or 0,
        "route_truncated": bool(proposal.get("route_truncated")),
        "day_plan_fallback": bool(proposal.get("day_plan_fallback")),
    }
    return route_info, evidence


def route_reasons(result):
    """把 partial/结构问题的原因写成机器可读标签（不解析自然语言）。"""
    route = (result or {}).get("route") or {}
    proposal = route.get("proposal") or {}
    validation = route.get("validation") or {}
    reasons = []
    if not (proposal.get("node_ids") or []):
        reasons.append("no_route_nodes")
    if route.get("single_destination"):
        reasons.append("single_destination")
    missing = len(validation.get("missing_connections") or [])
    if missing:
        reasons.append(f"missing_connections:{missing}")
    cross_doc = validation.get("cross_doc_transitions") or 0
    if cross_doc:
        reasons.append(f"cross_doc_transitions:{cross_doc}")
    if proposal.get("route_truncated"):
        reasons.append("route_truncated")
    if proposal.get("day_plan_fallback"):
        reasons.append("day_plan_fallback")
    scope = route.get("scope") or {}
    if scope.get("requested") and not scope.get("applied"):
        reasons.append("sub_area_not_applied")
    return reasons


def _run_with_timeout(function, timeout_s):
    """在守护线程中执行 function，超时返回；无法强杀线程，见 README 限制。"""
    box = {}

    def target():
        try:
            box["value"] = function()
        except BaseException as exc:  # noqa: BLE001 - 评测需要记录所有失败
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(timeout_s)
    elapsed = time.monotonic() - started
    if thread.is_alive():
        return {"timed_out": True, "elapsed": elapsed, "value": None, "error": None}
    return {
        "timed_out": False,
        "elapsed": elapsed,
        "value": box.get("value"),
        "error": box.get("error"),
    }


def _base_record(case, mode):
    return {
        "id": case["id"],
        "split": case["split"],
        "query": case["query"],
        "turns": list(case.get("turns") or []),
        "expected": case["expected"],
        "mode": mode,
        "executed": False,
        "model_calls": 0,
        "status": None,
        "raw_status": None,
        "status_correct": None,
        "schema_pass": None,
        "route": None,
        "evidence": {
            "segments_total": None,
            "segments_with_source": None,
            "coverage": None,
            "segments": [],
        },
        "route_reasons": [],
        "partial_reasons": [],
        "message": None,
        "error": None,
        "latency_s": None,
        "timeout": False,
        "attempts": [],
        "turns_run": [],
    }


def dry_run_record(case):
    """dry-run 的空结果骨架：不执行、不填任何指标。"""
    record = _base_record(case, "dry-run")
    record["turns_run"] = [
        {"turn": index, "text": text, "executed": False}
        for index, text in enumerate(submission_texts(case), 1)
    ]
    return record


def run_case(case, run_agent, timeout_s=TIMEOUT_S, max_attempts=MAX_ATTEMPTS):
    """真实执行一条查询；所有失败都记录，不抛出、不删样本。"""
    record = _base_record(case, "real")
    texts = submission_texts(case)
    final_result = None
    case_error = None
    total_latency = 0.0
    any_timeout = False
    attempts = []

    for turn_index, text in enumerate(texts, 1):
        turn_ok = False
        turn_latency = 0.0
        turn_error = None
        for attempt in range(1, max_attempts + 1):
            outcome = _run_with_timeout(lambda text=text: run_agent(text), timeout_s)
            total_latency += outcome["elapsed"]
            record["model_calls"] += 1
            attempt_record = {
                "turn": turn_index,
                "attempt": attempt,
                "latency_s": round(outcome["elapsed"], 3),
                "ok": False,
                "timeout": bool(outcome["timed_out"]),
                "error": None,
            }
            turn_latency += outcome["elapsed"]
            if outcome["timed_out"]:
                any_timeout = True
                attempt_record["error"] = f"超时（>{timeout_s:.0f}s）"
                turn_error = attempt_record["error"]
            elif outcome["error"] is not None:
                attempt_record["error"] = (
                    f"{type(outcome['error']).__name__}: {outcome['error']}"
                )
                turn_error = attempt_record["error"]
            else:
                attempt_record["ok"] = True
                turn_ok = True
                final_result = outcome["value"]
                attempts.append(attempt_record)
                break
            attempts.append(attempt_record)

        record["turns_run"].append({
            "turn": turn_index,
            "text": text,
            "executed": True,
            "ok": turn_ok,
            "latency_s": round(turn_latency, 3),
            "status": (final_result or {}).get("status") if turn_ok else None,
            "error": turn_error,
        })
        if not turn_ok:
            case_error = f"第 {turn_index} 轮失败：{turn_error}"
            break

    record["attempts"] = attempts
    record["latency_s"] = round(total_latency, 3)
    record["timeout"] = any_timeout
    record["error"] = case_error

    if final_result is None:
        return record

    record["executed"] = True
    record["raw_status"] = final_result.get("status")
    record["status"] = normalize_status(final_result.get("status"))
    record["status_correct"] = (
        record["status"] in case["expected"]["status"]
        if record["status"] is not None else None
    )
    record["schema_pass"] = check_schema(final_result)
    record["message"] = final_result.get("message") or ""
    record["route"], record["evidence"] = extract_route(final_result)
    record["route_reasons"] = route_reasons(final_result)
    if record["status"] == "partial":
        record["partial_reasons"] = list(record["route_reasons"])
    return record


# ---------------------------------------------------------------------------
# 指标聚合（全部由 cases 重算）
# ---------------------------------------------------------------------------

def rate(numerator, denominator):
    """统一的比例结构，分母为 0 时 rate 为 null，避免伪造 0%。"""
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
    }


def percentile(values, percent):
    """nearest-rank 百分位；空列表返回 null。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(percent / 100.0 * len(ordered)), 1)
    return round(ordered[rank - 1], 3)


def compute_summary(cases):
    """只从 cases 计算汇总，不接收外部指标。"""
    executed = [case for case in cases if case.get("executed")]
    attempted = [case for case in cases if (case.get("model_calls") or 0) > 0]
    status_counts = {status: 0 for status in VALID_STATUSES}
    status_other = 0
    for case in executed:
        status = case.get("status")
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_other += 1

    evidence_segments = sum(
        (case.get("evidence") or {}).get("segments_total") or 0 for case in executed
    )
    evidence_with_source = sum(
        (case.get("evidence") or {}).get("segments_with_source") or 0
        for case in executed
    )
    route_cases = [
        case for case in executed
        if ((case.get("route") or {}).get("validation_valid") is not None)
    ]
    stop_cap_cases = [
        case for case in executed
        if (case.get("route") is not None
            and (case.get("expected") or {}).get("max_stops") is not None)
    ]
    latencies = [
        case["latency_s"] for case in attempted if case.get("latency_s") is not None
    ]

    summary = {
        "n_cases": len(cases),
        "split_counts": {
            split: sum(1 for case in cases if case.get("split") == split)
            for split in VALID_SPLITS
        },
        "n_attempted_cases": len(attempted),
        "n_executed_cases": len(executed),
        "n_timeout_cases": sum(1 for case in cases if case.get("timeout")),
        "n_error_cases": sum(1 for case in cases if case.get("error")),
        "status_counts": status_counts,
        "status_other": status_other,
        "status_correct": rate(
            sum(1 for case in executed if case.get("status_correct") is True),
            len(executed),
        ),
        "schema_pass": rate(
            sum(1 for case in executed if case.get("schema_pass") is True),
            len(executed),
        ),
        "evidence_coverage": rate(evidence_with_source, evidence_segments),
        "route_valid": rate(
            sum(1 for case in route_cases if case["route"].get("validation_valid") is True),
            len(route_cases),
        ),
        "stop_cap_ok": rate(
            sum(1 for case in stop_cap_cases
                if (case["route"].get("node_count") or 0)
                <= case["expected"]["max_stops"]),
            len(stop_cap_cases),
        ),
        "partial_rate": rate(status_counts["partial"], len(executed)),
        "latency_s": {
            "n": len(latencies),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
    }
    return summary


# ---------------------------------------------------------------------------
# 运行环境
# ---------------------------------------------------------------------------

def git_snapshot():
    """读取 HEAD 与工作区状态；失败时返回 unknown，不伪造 commit。"""
    def run(*args):
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, timeout=10,
        )

    commit = "unknown"
    dirty = None
    try:
        result = run("rev-parse", "--short", "HEAD")
        if result.returncode == 0 and result.stdout.strip():
            commit = result.stdout.strip()
        status = run("status", "--porcelain")
        if status.returncode == 0:
            dirty = bool(status.stdout.strip())
    except Exception:  # noqa: BLE001 - 环境信息缺失不影响评测记录
        pass
    return commit, dirty


def load_agent():
    """真实运行才 import；返回 (run_agent, model, url)。

    会话记录默认写到 eval/results/sessions（白名单内），避免在仓库其他目录
    留下未跟踪的用户原文；可用 P07_SESSION_DIR 覆盖。
    """
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    os.environ.setdefault("P07_SESSION_DIR", str(RESULTS_DIR / "sessions"))
    from agent import run_agent  # noqa: PLC0415 - 故意延迟到真实运行
    from config import MODEL, OLLAMA_URL  # noqa: PLC0415

    return run_agent, MODEL, OLLAMA_URL


def preflight_model(url, timeout_s=5.0):
    """探测 Ollama 兼容层是否可达；只用于提示，不改变评测流程。"""
    base = url.split("/api/")[0].rstrip("/")
    tags_url = f"{base}/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names = [model.get("name") for model in payload.get("models", [])]
        return True, f"模型服务可达：{tags_url}；可用模型：{names}"
    except Exception as exc:  # noqa: BLE001 - 探测失败只提示
        return False, f"模型服务探测失败：{tags_url}（{type(exc).__name__}: {exc}）"


def _timestamp():
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")


def _iso_now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_output_path(split, dry_run):
    mode = "dryrun" if dry_run else "real"
    return RESULTS_DIR / f"{split}-{mode}-{_timestamp()}.json"


def write_payload(payload, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="P7 评测骨架：读取 golden set，调用 run_agent 并记录机器指标。",
    )
    parser.add_argument("--split", choices=("dev", "heldout", "all"), default="dev",
                        help="dev=开发集；heldout=留出集；all=全部（默认 dev）")
    parser.add_argument("--limit", type=int, default=None,
                        help="只跑前 N 条（在 split 过滤之后截取）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不调用模型，只校验 golden set 并写出空骨架")
    parser.add_argument("--out", default=None,
                        help="结果 JSON 路径；默认 eval/results/<split>-<mode>-<时间戳>.json")
    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001 - 控制台编码差异不影响评测
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须是正整数")

    started_at = _iso_now()
    started_monotonic = time.monotonic()

    cases, problems = load_golden_set(GOLDEN_PATH)
    if problems:
        print(f"golden set 校验失败（{len(problems)} 处）：")
        for problem in problems:
            print(f"  - {problem}")
        return 2

    selected = select_cases(cases, args.split, args.limit)
    print(f"golden set：{GOLDEN_SET_DISPLAY}，共 {len(cases)} 条，全部通过 schema 校验")
    print(f"split={args.split}，limit={args.limit}，选中 {len(selected)} 条")
    if args.split == "heldout" and not selected:
        print("held-out 为空（0 条）：当前 10 条 seed 全部为 dev，按裁决不跑 held-out，"
              "本次写出空结果骨架（cases=[]）。")
    if not selected:
        print("选中的查询为 0 条，写出空骨架，不调用模型。")

    commit, dirty = git_snapshot()
    model = None
    model_url = None
    preflight_ok = None
    preflight_message = None
    session_dir = None

    if args.dry_run:
        print("dry-run：未 import agent，未调用模型；只写空结果骨架。")
        records = [dry_run_record(case) for case in selected]
    else:
        try:
            run_agent, model, model_url = load_agent()
        except Exception as exc:  # noqa: BLE001 - 环境不可用时明确报错退出
            print(f"无法加载 run_agent：{type(exc).__name__}: {exc}")
            return 2
        session_dir = os.environ.get("P07_SESSION_DIR")
        preflight_ok, preflight_message = preflight_model(model_url)
        print(preflight_message)
        if not preflight_ok:
            print("警告：模型服务不可达；仍会逐条调用并按真实失败记录，不伪造结果。")
        records = []
        for index, case in enumerate(selected, 1):
            record = run_case(case, run_agent)
            records.append(record)
            coverage = (record.get("evidence") or {}).get("coverage")
            print(
                f"[{index}/{len(selected)}] {case['id']}："
                f"status={record.get('status') or record.get('raw_status') or 'failed'}"
                f"（原始 {record.get('raw_status')}），"
                f"耗时={record.get('latency_s')}s，"
                f"节点={None if record.get('route') is None else record['route']['node_count']}，"
                f"证据覆盖={coverage}，"
                f"错误={record.get('error') or '无'}"
            )

    summary = compute_summary(records)
    finished_at = _iso_now()
    duration = round(time.monotonic() - started_monotonic, 3)
    meta = {
        "runner": RUNNER_DISPLAY,
        "spec": "03_EVAL_SPEC.md §2/§3/§8（v1）",
        "commit": commit,
        "git_dirty": dirty,
        "model": model,
        "model_url": model_url,
        "run_mode": "dry-run" if args.dry_run else "real",
        "split": args.split,
        "limit": args.limit,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_s": duration,
        "timeout_s": TIMEOUT_S,
        "max_attempts": MAX_ATTEMPTS,
        "python_version": sys.version.split()[0],
        "golden_set": GOLDEN_SET_DISPLAY,
        "agent_imported": "agent" in sys.modules,
        "session_dir": session_dir,
        "model_preflight": {
            "ok": preflight_ok,
            "message": preflight_message,
        },
        "notes": (
            ["dry-run：不 import agent、不调用模型；本文件是 schema 校验后的空骨架"]
            if args.dry_run else
            ["指标全部由 cases 计算；summary 不手写",
             "status 映射：complete→verified（T2.1 前）"]
        ),
    }
    payload = {"meta": meta, "cases": records, "summary": summary}

    out_path = Path(args.out) if args.out else default_output_path(args.split, args.dry_run)
    out_path = write_payload(payload, out_path)

    print("汇总（由 cases 计算）：")
    print(f"  条数={summary['n_cases']}，执行={summary['n_executed_cases']}，"
          f"状态计数={summary['status_counts']}")
    print(f"  status_correct={summary['status_correct']}，"
          f"evidence_coverage={summary['evidence_coverage']}")
    print(f"  latency_s={summary['latency_s']}")
    print(f"结果已写入：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
