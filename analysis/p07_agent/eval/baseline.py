#!/usr/bin/env python
"""P7 通用 LLM baseline（T4.3 / 03_EVAL_SPEC.md §5 的 B0）。

B0 定义：**同一个 Qwen3-8B、同一批 dev 查询、不给图谱/工具/证据/景区数据**，
system prompt 固定为「你是旅游规划助手。根据用户需求，给出一日或两日的行程建议。」，
直接 POST Ollama ``/api/chat``，输出自由文本。

设计约束：
- 只读 ``golden_set.jsonl`` 的 dev 条目，``query`` 逐字提交（不改写、不拼接）；
- 不 import ``agent`` / ``tools`` / ``evidence``，不读 P6 图谱与 ``clean_content``；
- ``temperature=0``、``num_predict=1200``，单条 180s、失败重试 1 次；
- 每条记录 ``id`` / ``query`` / ``response_text`` / ``latency_s`` / ``timeout`` /
  ``error`` / ``attempts``，超时与失败如实保留，不删样本；
- 成功率、编造次数等语义指标**不在本脚本计算**（需人工判据），本脚本只记录
  机器可复现的原始响应与延迟；汇总见 ``baseline_report.py`` 与 ``report.md``。

用法（仓库根）：
    .\\.venv\\Scripts\\python.exe analysis\\p07_agent\\eval\\baseline.py --split dev --limit 1 ^
        --out %TEMP%\\baseline-smoke.json
    .\\.venv\\Scripts\\python.exe analysis\\p07_agent\\eval\\baseline.py --split dev ^
        --out analysis\\p07_agent\\eval\\results\\baseline-dev-<ts>.json
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

RUNNER_DISPLAY = "analysis/p07_agent/eval/baseline.py"
GOLDEN_SET_DISPLAY = "analysis/p07_agent/eval/golden_set.jsonl"

# B0 的固定 system prompt：不得附加图谱/工具/证据/景区数据的任何提示。
SYSTEM_PROMPT = "你是旅游规划助手。根据用户需求，给出一日或两日的行程建议。"

# 与 src/config.py 的默认值同源（P07_OLLAMA_MODEL / P07_OLLAMA_URL）；
# T4.3 默认用 127.0.0.1 避开 localhost 的 IPv6 解析问题（eval/README.md §7）。
MODEL = os.environ.get("P07_OLLAMA_MODEL", "qwen3:8b")
OLLAMA_URL = os.environ.get(
    "P07_OLLAMA_URL", "http://127.0.0.1:11434/api/chat"
)

TEMPERATURE = 0
NUM_PREDICT = 1200
TIMEOUT_S = 180.0
MAX_ATTEMPTS = 2
VALID_SPLITS = ("dev",)  # T4.3 只跑 dev；held-out 不在本任务范围


# ---------------------------------------------------------------------------
# golden set
# ---------------------------------------------------------------------------

def load_cases(path=GOLDEN_PATH):
    """读取 JSONL 原文；只返回 dev 条目，保持文件顺序。"""
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"golden set 不存在：{path}")
    cases = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"第 {line_no} 行 JSON 解析失败：{exc}")
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) \
                or not isinstance(case.get("query"), str) or not case["query"].strip():
            raise SystemExit(f"第 {line_no} 行缺少合法 id/query")
        if case.get("split") != "dev":
            continue
        cases.append(case)
    return cases


def guard_dev_only(cases):
    """二次防线：任何非 dev 条目都直接拒绝，避免误跑 held-out。"""
    bad = sorted({case.get("id") for case in cases if case.get("split") != "dev"})
    if bad:
        raise SystemExit(f"拒绝：选中了非 dev 条目 {bad}；T4.3 只允许 dev")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise SystemExit("拒绝：dev 条目 id 有重复")
    return True


# ---------------------------------------------------------------------------
# Ollama 调用
# ---------------------------------------------------------------------------

def build_payload(query, model=MODEL):
    """B0 请求体：system prompt 固定，只有用户 query，无图谱/工具上下文。"""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        "stream": False,
        "options": {"temperature": TEMPERATURE, "num_predict": NUM_PREDICT},
    }


def post_chat(payload, url=OLLAMA_URL, timeout_s=TIMEOUT_S):
    """POST /api/chat，返回解析后的 JSON。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _call_with_timeout(function, timeout_s):
    """守护线程墙钟超时（与 run_eval 同法；线程无法强杀，属已知限制）。"""
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


def preflight(url, timeout_s=5.0):
    """探测 /api/tags 是否可达；只提示，不改变逐条真实调用。"""
    base = url.split("/api/")[0].rstrip("/")
    tags_url = f"{base}/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names = [model.get("name") for model in payload.get("models", [])]
        return True, f"模型服务可达：{tags_url}；可用模型：{names}"
    except Exception as exc:  # noqa: BLE001 - 探测失败只提示
        return False, f"模型服务探测失败：{tags_url}（{type(exc).__name__}: {exc}）"


def extract_text(payload):
    """Ollama /api/chat 返回的助手文本；兼容旧版 response 字段。"""
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(payload.get("response"), str):
        return payload["response"]
    return ""


def run_case(case, url=OLLAMA_URL, model=MODEL):
    """真实执行一条 B0 查询；所有失败如实记录，不抛出、不删样本。"""
    record = {
        "id": case["id"],
        "split": case["split"],
        "query": case["query"],
        "response_text": "",
        "response_chars": 0,
        "latency_s": 0.0,
        "timeout": False,
        "error": None,
        "attempts": 0,
        "attempt_log": [],
        "done_reason": None,
        "eval_count": None,
        "prompt_eval_count": None,
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        record["attempts"] = attempt
        payload = build_payload(case["query"], model)
        outcome = _call_with_timeout(lambda: post_chat(payload, url, TIMEOUT_S), TIMEOUT_S)
        record["latency_s"] = round(record["latency_s"] + outcome["elapsed"], 3)
        entry = {
            "attempt": attempt,
            "latency_s": round(outcome["elapsed"], 3),
            "ok": False,
            "timeout": bool(outcome["timed_out"]),
            "error": None,
        }

        if outcome["timed_out"]:
            record["timeout"] = True
            entry["error"] = f"超时（>{TIMEOUT_S:.0f}s）"
            record["error"] = entry["error"]
        elif outcome["error"] is not None:
            entry["error"] = f"{type(outcome['error']).__name__}: {outcome['error']}"
            record["error"] = entry["error"]
        else:
            text = extract_text(outcome["value"])
            if not text.strip():
                entry["error"] = "空响应（message.content 为空）"
                record["error"] = entry["error"]
            else:
                entry["ok"] = True
                record["error"] = None
                record["response_text"] = text
                record["response_chars"] = len(text)
                record["done_reason"] = (outcome["value"] or {}).get("done_reason")
                record["eval_count"] = (outcome["value"] or {}).get("eval_count")
                record["prompt_eval_count"] = (outcome["value"] or {}).get("prompt_eval_count")
                record["attempt_log"].append(entry)
                break

        record["attempt_log"].append(entry)

    return record


# ---------------------------------------------------------------------------
# 汇总（只含机器事实；语义指标由人工判据单独记录）
# ---------------------------------------------------------------------------

def percentile(values, percent):
    """nearest-rank 百分位，与 run_eval.percentile 同口径；空列表返回 null。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(percent / 100.0 * len(ordered)), 1)
    return round(ordered[rank - 1], 3)


def compute_summary(cases):
    attempted = [case for case in cases if (case.get("attempts") or 0) > 0]
    ok_cases = [
        case for case in cases
        if (case.get("response_text") or "").strip() and case.get("error") is None
    ]
    latencies = [case["latency_s"] for case in attempted if case.get("latency_s") is not None]
    chars = [case["response_chars"] for case in ok_cases]
    return {
        "n_cases": len(cases),
        "n_attempted_cases": len(attempted),
        "n_ok_cases": len(ok_cases),
        "n_timeout_cases": sum(1 for case in cases if case.get("timeout")),
        "n_error_cases": sum(1 for case in cases if case.get("error")),
        "n_retried_cases": sum(1 for case in cases if (case.get("attempts") or 0) > 1),
        "latency_s": {
            "n": len(latencies),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
        "response_chars": {
            "n": len(chars),
            "min": min(chars) if chars else None,
            "p50": percentile(chars, 50),
            "max": max(chars) if chars else None,
        },
        "note": (
            "本文件只记录原始响应、延迟与失败；成功率/证据正确率/编造次数需按 "
            "report.md 的人工判据另行标注，不在本文件计算"
        ),
    }


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


def _timestamp():
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")


def _iso_now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_payload(payload, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return out_path


def build_parser():
    parser = argparse.ArgumentParser(
        description="P7 通用 LLM baseline（B0：同模型、无图谱、自由文本）",
    )
    parser.add_argument("--split", choices=VALID_SPLITS, default="dev",
                        help="只允许 dev（T4.3 不跑 held-out）")
    parser.add_argument("--limit", type=int, default=None,
                        help="只跑前 N 条（dev 过滤之后截取，用于试通）")
    parser.add_argument("--out", default=None,
                        help="结果 JSON 路径；默认 eval/results/baseline-dev-<时间戳>.json")
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

    cases = load_cases(GOLDEN_PATH)
    guard_dev_only(cases)
    selected = cases[: args.limit] if args.limit is not None else cases
    print(f"golden set：{GOLDEN_SET_DISPLAY}，dev 共 {len(cases)} 条；"
          f"本次选中 {len(selected)} 条（split=dev，limit={args.limit}）")
    print(f"模型={MODEL}，地址={OLLAMA_URL}，temperature={TEMPERATURE}，"
          f"num_predict={NUM_PREDICT}，超时={TIMEOUT_S:.0f}s，最大尝试={MAX_ATTEMPTS}")
    print(f"system prompt：{SYSTEM_PROMPT}")

    commit, dirty = git_snapshot()
    preflight_ok, preflight_message = preflight(OLLAMA_URL)
    print(preflight_message)
    if not preflight_ok:
        print("警告：模型服务不可达；仍会逐条调用并按真实失败记录，不伪造结果。")

    records = []
    for index, case in enumerate(selected, 1):
        record = run_case(case)
        records.append(record)
        print(
            f"[{index}/{len(selected)}] {case['id']}："
            f"耗时={record['latency_s']:.2f}s，"
            f"字符={record['response_chars']}，"
            f"尝试={record['attempts']}，"
            f"超时={'是' if record['timeout'] else '否'}，"
            f"错误={record['error'] or '无'}"
        )

    summary = compute_summary(records)
    finished_at = _iso_now()
    duration = round(time.monotonic() - started_monotonic, 3)
    imported = [name for name in ("agent", "tools", "evidence") if name in sys.modules]
    meta = {
        "runner": RUNNER_DISPLAY,
        "task": "T4.3",
        "baseline": "B0 同模型无图谱（自由文本）",
        "spec": "03_EVAL_SPEC.md §5（B0 定义/公平性/对比维度）",
        "commit": commit,
        "git_dirty": dirty,
        "model": MODEL,
        "model_url": OLLAMA_URL,
        "temperature": TEMPERATURE,
        "num_predict": NUM_PREDICT,
        "options": {"temperature": TEMPERATURE, "num_predict": NUM_PREDICT},
        "timeout_s": TIMEOUT_S,
        "max_attempts": MAX_ATTEMPTS,
        "system_prompt": SYSTEM_PROMPT,
        "run_mode": "real",
        "split": args.split,
        "limit": args.limit,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_s": duration,
        "python_version": sys.version.split()[0],
        "golden_set": GOLDEN_SET_DISPLAY,
        "agent_imported": "agent" in sys.modules,
        "agent_tools_evidence_imported": imported,
        "graph_data_read": False,
        "model_preflight": {"ok": preflight_ok, "message": preflight_message},
        "notes": [
            "B0：同一模型 qwen3:8b、temperature=0、num_predict=1200，只给 system prompt 与 query，"
            "不提供图谱/工具/证据/景区数据，输出自由文本",
            "query 逐字取自 golden_set.jsonl 的 dev 条目，未改写；单轮提交（EDGE-FOLLOW-01 的 turns 不展开）",
            "本文件只记录原始响应/延迟/失败；成功率与编造次数为人工判据，见 "
            "results/baseline-dev-manual-labels.json 与 report.md 的「Baseline 对比」节",
        ],
    }
    payload = {"meta": meta, "cases": records, "summary": summary}
    out_path = Path(args.out) if args.out else (
        RESULTS_DIR / f"baseline-dev-{_timestamp()}.json"
    )
    out_path = write_payload(payload, out_path)

    print("汇总（只含机器事实）：")
    print(f"  条数={summary['n_cases']}，有响应={summary['n_ok_cases']}，"
          f"超时={summary['n_timeout_cases']}，错误={summary['n_error_cases']}，"
          f"重试={summary['n_retried_cases']}")
    print(f"  延迟={summary['latency_s']}，响应字符={summary['response_chars']}")
    print(f"结果已写入：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
