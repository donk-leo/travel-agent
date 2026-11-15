#!/usr/bin/env python
"""从 results JSON 生成 report.md（T4.2）。

设计约束（03_EVAL_SPEC.md §3/§7/§8/§9）：
- 纯标准库；只读 ``results/*.json``，不调用模型、不读 golden set 明细；
- 所有数字从 ``cases`` 复算，并与 runner 写入的 ``summary`` 逐项对账；
  对账不一致直接退出码 3，绝不手写/估算指标；
- 失败按 §7 的 F1–F13 固定分类（规则见 ``classify_case``），每条保留 id、
  现象、复现命令与建议责任任务，不删样本；
- 默认只接受 ``split=dev`` 的真实运行结果；``--allow-non-dev`` 仅供后续
  G4/G5 打开 held-out 时显式放宽，T4.2 不使用。

用法：
    python analysis/p07_agent/eval/report.py analysis/p07_agent/eval/results/dev-real-XXXX.json
    python analysis/p07_agent/eval/report.py <results.json> --out analysis/p07_agent/eval/report.md
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))
import run_eval  # noqa: E402 - 复用同一个指标实现，避免两套口径

F_NAMES = {
    "F1": "未覆盖/语言",
    "F2": "意图/槽位错误",
    "F3": "工具漏选/错选",
    "F4": "路线断段/方向错",
    "F5": "跨文档/截断",
    "F6": "分天兜底",
    "F7": "节奏不可行",
    "F8": "证据缺失/错误",
    "F9": "编造事实",
    "F10": "条件噪声",
    "F11": "UI 困惑",
    "F12": "延迟/超时",
    "F13": "输出格式/语言",
}

# 建议责任任务：来自 01_TASK_BOARD.md 的任务映射，最终由父 Agent/owner 确认。
F_RESP = {
    "F1": "T2.6",
    "F2": "T2.6",
    "F3": "T2.6",
    "F4": "T2.3",
    "F5": "T2.4",
    "F6": "T2.3",
    "F7": "T2.2",
    "F8": "T2.5 / T1.6",
    "F9": "T2.2",
    "F10": "T2.5",
    "F11": "T3.2",
    "F12": "T2.7",
    "F13": "T2.6",
}

AREA_ORDER = ("长隆", "白云山", "武功山", "边界（EDGE）")
AREA_PREFIX = {"CL": "长隆", "BYS": "白云山", "WGS": "武功山", "EDGE": "边界（EDGE）"}

TARGETS = {
    "schema_pass": "100%",
    "status_correct": "≥90%（§3）；dev 成功率 ≥60%（§10）",
    "route_valid": "≥95%",
    "single_source": "≥90%",
    "evidence_coverage": "100% 段；≥95% 点",
    "stop_cap_ok": "100%",
    "unknown_labeled": "100%",
    "fabrication_count": "0",
    "latency_p50": "≤45s",
    "latency_p95": "≤150s",
    "first_feedback": "≤3s",
    "partial_rate": "≤30%",
    "clarify_ok": "100%",
    "no_match_ok": "100%",
}


def load_results(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise SystemExit(f"结果文件结构不合法：{path}")
    return data


def rate_text(rate, digits=2):
    """把 runner 的 {numerator, denominator, rate} 渲染成 n/m（xx.xx%）。"""
    if not isinstance(rate, dict):
        return "N/A"
    numerator = rate.get("numerator")
    denominator = rate.get("denominator")
    if not denominator:
        return f"{numerator}/{denominator}（N/A，分母为 0）"
    value = rate.get("rate")
    if value is None:
        value = numerator / denominator
    return f"{numerator}/{denominator}（{value * 100:.{digits}f}%）"


def ratio_rate(numerator, denominator):
    return run_eval.rate(numerator, denominator)


def seconds(value):
    return "N/A" if value is None else f"{value:.2f}s"


def area_of(case):
    prefix = str(case.get("id") or "").split("-")[0]
    return AREA_PREFIX.get(prefix, "未分类")


def status_text(case):
    status = case.get("status")
    if status is None:
        return f"None（原始 {case.get('raw_status')!r}）"
    return status


def classify_case(case):
    """按 03_EVAL_SPEC.md §7 给单条失败打 F 标签，返回 [(F, 现象), ...]。

    规则（确定性、只看 runner 记录的结构化字段，不做自然语言判断）：
    - 未执行：超时→F12；其他执行异常→F13（taxonomy 无独立类，归输出/运行失败）；
    - status 不在四值内 / schema_pass=false → F13；
    - status_correct=false → F2（意图/槽位/状态判定错误）；
    - node_count > max_stops → F7；missing_connections>0 → F4；
    - cross_doc_transitions>0 或 route_truncated → F5；
    - day_plan_fallback → F6；no_route_nodes → F3；
    - single_destination 且 max_stops>1 → F4（单点未成路线）；
    - NEXT 段有缺来源 → F8。
    一条可命中多个标签，第一个为主类；现象只由上述字段拼接。
    """
    tags = []
    route = case.get("route") or {}
    evidence = case.get("evidence") or {}
    expected = case.get("expected") or {}
    reasons = case.get("route_reasons") or []

    if not case.get("executed"):
        if case.get("timeout"):
            return [("F12", "超时（超过 180s 上限）")]
        return [("F13", f"执行异常：{case.get('error') or '无错误详情'}")]

    if case.get("status") is None:
        tags.append(("F13", f"status={case.get('raw_status')!r} 不在四值内"))
    if case.get("schema_pass") is False:
        tags.append(("F13", "schema_pass=false"))
    if case.get("status_correct") is False:
        tags.append((
            "F2",
            f"status={status_text(case)}，期望={expected.get('status')}",
        ))

    max_stops = expected.get("max_stops")
    node_count = route.get("node_count")
    if isinstance(max_stops, int) and isinstance(node_count, int) and node_count > max_stops:
        tags.append(("F7", f"路线 {node_count} 点 > max_stops={max_stops}"))
    missing = route.get("missing_connections") or 0
    if missing:
        tags.append(("F4", f"{missing} 段缺 NEXT 连接"))
    cross_doc = route.get("cross_doc_transitions") or 0
    if cross_doc:
        tags.append(("F5", f"跨文档段 {cross_doc} 处"))
    if route.get("route_truncated"):
        tags.append(("F5", "route_truncated=true（路线截断）"))
    if route.get("day_plan_fallback"):
        tags.append(("F6", "day_plan_fallback=true（均分兜底）"))
    if "no_route_nodes" in reasons and "clarify" not in (expected.get("status") or []):
        tags.append(("F3", "no_route_nodes（规划请求未产出路线）"))
    if "single_destination" in reasons and isinstance(max_stops, int) and max_stops > 1:
        tags.append(("F4", f"single_destination（仅 {node_count} 点，未成路线）"))
    segments_total = evidence.get("segments_total") or 0
    segments_with_source = evidence.get("segments_with_source") or 0
    if segments_total and segments_with_source < segments_total:
        tags.append(("F8", f"证据 {segments_with_source}/{segments_total} 段有来源"))

    return tags


def dedupe(tags):
    seen = set()
    result = []
    for tag in tags:
        if tag[0] not in seen:
            seen.add(tag[0])
            result.append(tag)
    return result


def ratio_equal(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return (left.get("numerator") == right.get("numerator")
                and left.get("denominator") == right.get("denominator")
                and left.get("rate") == right.get("rate"))
    return left == right


def check_summary(data):
    """用 cases 复算 summary 并对账；返回 (computed, mismatches)。"""
    cases = data["cases"]
    computed = run_eval.compute_summary(cases)
    stored = data.get("summary") or {}
    mismatches = []
    for key, value in computed.items():
        if key not in stored:
            mismatches.append(f"summary 缺字段：{key}")
        elif not ratio_equal(value, stored[key]):
            mismatches.append(f"{key}: 复算 {value!r} != JSON {stored[key]!r}")
    for key in stored:
        if key not in computed:
            mismatches.append(f"summary 多出字段：{key}")
    return computed, mismatches


def aggregate_by_area(cases):
    groups = {name: [] for name in AREA_ORDER}
    for case in cases:
        groups.setdefault(area_of(case), []).append(case)
    rows = []
    for name in list(AREA_ORDER) + sorted(set(groups) - set(AREA_ORDER)):
        group = groups.get(name) or []
        if not group:
            continue
        executed = [case for case in group if case.get("executed")]
        attempted = [case for case in group if (case.get("model_calls") or 0) > 0]
        latencies = [case["latency_s"] for case in attempted
                     if case.get("latency_s") is not None]
        evidence_total = sum((case.get("evidence") or {}).get("segments_total") or 0
                             for case in executed)
        evidence_source = sum(
            (case.get("evidence") or {}).get("segments_with_source") or 0
            for case in executed
        )
        rows.append({
            "area": name,
            "n": len(group),
            "executed": len(executed),
            "success": sum(1 for case in executed if case.get("status_correct") is True),
            "success_rate": ratio_rate(
                sum(1 for case in executed if case.get("status_correct") is True),
                len(executed),
            ),
            "evidence_source": evidence_source,
            "evidence_total": evidence_total,
            "evidence_rate": ratio_rate(evidence_source, evidence_total),
            "partial": sum(1 for case in executed if case.get("status") == "partial"),
            "p50": run_eval.percentile(latencies, 50),
            "p95": run_eval.percentile(latencies, 95),
        })
    return rows


def md_cell(value):
    """表格单元格转义：竖线会截断 Markdown 表格。"""
    return str(value).replace("|", "\\|")


def build_environment_table(meta):
    preflight = meta.get("model_preflight") or {}
    rows = [
        ("commit（运行时 HEAD）", f"`{meta.get('commit')}`"),
        ("git_dirty（运行时工作区）", str(meta.get("git_dirty"))),
        ("模型", f"`{meta.get('model')}`"),
        ("模型地址", f"`{meta.get('model_url')}`"),
        ("run_mode / split / limit",
         f"`{meta.get('run_mode')}` / `{meta.get('split')}` / `{meta.get('limit')}`"),
        ("单条超时 / 最大尝试", f"{meta.get('timeout_s')}s / {meta.get('max_attempts')} 次"),
        ("开始 / 结束", f"{meta.get('started_at')} → {meta.get('finished_at')}"),
        ("总耗时", f"{meta.get('duration_s')}s"),
        ("Python / agent_imported",
         f"{meta.get('python_version')} / {meta.get('agent_imported')}"),
        ("model_preflight",
         f"ok={preflight.get('ok')}；{preflight.get('message') or ''}"),
        ("session_dir", f"`{meta.get('session_dir')}`（.gitignore 忽略）"),
        ("GPU", "未采集（Ollama 本机运行；结果 JSON 无该字段）"),
    ]
    lines = ["| 项 | 值 |", "|---|---|"]
    for key, value in rows:
        lines.append(f"| {key} | {md_cell(value)} |")
    return lines


def build_report(data, results_path):
    meta = data.get("meta") or {}
    cases = data["cases"]
    summary, mismatches = check_summary(data)
    if mismatches:
        print("summary 与 cases 复算不一致，拒绝生成报告：")
        for item in mismatches:
            print(f"  - {item}")
        raise SystemExit(3)

    n = len(cases)
    executed = [case for case in cases if case.get("executed")]
    attempted = [case for case in cases if (case.get("model_calls") or 0) > 0]
    status_counts = summary["status_counts"]
    status_other = summary["status_other"]
    status_total = len(executed) or 1

    strict_success = sum(
        1 for case in executed
        if case.get("status_correct") is True
        and case.get("schema_pass") is True
        and (
            ((case.get("evidence") or {}).get("coverage") == 1.0)
            or ((case.get("evidence") or {}).get("segments_total") or 0) == 0
        )
    )

    failures = []
    for case in cases:
        tags = dedupe(classify_case(case))
        if not tags:
            continue
        is_hard = (
            not case.get("executed")
            or case.get("status") is None
            or case.get("status_correct") is False
            or case.get("schema_pass") is False
        )
        failures.append({
            "case": case,
            "tags": tags,
            "primary": tags[0][0],
            "level": "失败" if is_hard else "警告",
        })
    failures.sort(key=lambda item: (
        0 if item["level"] == "失败" else 1,
        AREA_ORDER.index(area_of(item["case"])) if area_of(item["case"]) in AREA_ORDER else 99,
        item["case"]["id"],
    ))

    primary_counts = Counter(item["primary"] for item in failures)
    all_counts = Counter()
    for item in failures:
        for tag, _ in item["tags"]:
            all_counts[tag] += 1

    areas = aggregate_by_area(cases)
    overall_evidence = summary["evidence_coverage"]
    p50 = summary["latency_s"].get("p50")
    p95 = summary["latency_s"].get("p95")
    split_counts = summary["split_counts"]
    finished_date = str(meta.get("finished_at") or "")[:10] or "未知日期"

    lines = []
    add = lines.append
    add(f"# P7 评测报告（{finished_date} / split={meta.get('split')}，n={n}）")
    add("")
    add(f"> 本文件由 `analysis/p07_agent/eval/report.py` 从 `{results_path.name}` 确定性生成；")
    add("> 所有数字从结果 JSON 的 `cases` 复算，并与 runner 写入的 `summary` 逐项对账（不一致会拒绝生成）。")
    add("> 口径：`03_EVAL_SPEC.md` §3（自动指标）、§7（F1–F13 失败分类）、§8（执行流程）、§9（报告模板）。")
    add("")
    add("## 0. 摘要")
    add("")
    add(f"- **n = {n}**（split 分布：dev {split_counts.get('dev', 0)} / heldout {split_counts.get('heldout', 0)}）；"
        f"实际执行 {summary['n_executed_cases']} 条。")
    add(f"- 模型 `{meta.get('model')}`，temperature=0（src 固定），单条超时 {meta.get('timeout_s')}s、"
        f"失败重试 1 次；总耗时 {meta.get('duration_s')}s。")
    add(f"- **成功率（status_correct / executed）= {rate_text(summary['status_correct'])}**；"
        f"按全量 n 的保守口径 = {rate_text(ratio_rate(summary['status_correct']['numerator'], n))}"
        "（把未执行也计为不成功）。")
    add(f"- 严格成功（辅助口径，非 §3 指标：状态正确 + schema 通过 + 已有 NEXT 段证据全覆盖，0 段视为通过）"
        f"= {strict_success}/{summary['n_executed_cases']}。")
    add(f"- 证据覆盖率 = {rate_text(overall_evidence)}；partial 率 = {rate_text(summary['partial_rate'])}；"
        f"P50 / P95 = {seconds(p50)} / {seconds(p95)}。")
    primary_display = "、".join(f"{code}×{count}" for code, count in sorted(primary_counts.items())) or "无"
    add(f"- 超时 {summary['n_timeout_cases']} 条、执行错误 {summary['n_error_cases']} 条；"
        f"失败/警告 {len(failures)} 条（主类：{primary_display}）。")
    add(f"- **held-out 10 条未运行：held-out 成功率为未知，不是 0。** "
        f"本报告只覆盖本次运行的 dev {split_counts.get('dev', 0)} 条。")
    add("")
    add("## 1. 环境")
    add("")
    lines.extend(build_environment_table(meta))
    add("")
    add(f"- 说明：`meta.commit={meta.get('commit')}` 是运行时的 HEAD；结果文件与报告随后随 T4.2 提交入库，"
        "所以入库 commit 的父提交才是该值。`git_dirty` 记录运行开始时工作区是否干净。")
    add("")
    add("本次运行命令（退出码 0）：")
    add("")
    add("```powershell")
    add("$env:PYTHONIOENCODING='utf-8'; $py='.\\.venv\\Scripts\\python.exe'")
    add(f"& $py analysis\\p07_agent\\eval\\run_eval.py --split dev "
        f"--out analysis\\p07_agent\\eval\\results\\{results_path.name}")
    add("```")
    add("")
    add("## 2. 总览（指标 / 目标 / 实测）")
    add("")
    add("| 指标 | 目标（§3/§10） | 本次实测 | 说明 |")
    add("|---|---|---|---|")
    add(f"| `schema_pass` | {TARGETS['schema_pass']} | {rate_text(summary['schema_pass'])} | 返回结构符合契约 |")
    add(f"| `status_correct` | {TARGETS['status_correct']} | {rate_text(summary['status_correct'])} | 状态落在 `expected.status` 内 |")
    add(f"| dev 成功率（按全量 n） | ≥60% | {rate_text(ratio_rate(summary['status_correct']['numerator'], n))} | 未执行计为不成功，保守口径 |")
    add(f"| `route_valid` | {TARGETS['route_valid']} | {rate_text(summary['route_valid'])} | `validation_valid` 非 null 的条目 |")
    add(f"| `evidence_coverage` | {TARGETS['evidence_coverage']} | {rate_text(overall_evidence)} | 只覆盖 NEXT 段 |")
    add(f"| `stop_cap_ok` | {TARGETS['stop_cap_ok']} | {rate_text(summary['stop_cap_ok'])} | `node_count <= expected.max_stops` |")
    add(f"| `partial_rate` | {TARGETS['partial_rate']} | {rate_text(summary['partial_rate'])} | `status=partial` 占比 |")
    add(f"| `latency_p50` | {TARGETS['latency_p50']} | {seconds(p50)} | nearest-rank |")
    add(f"| `latency_p95` | {TARGETS['latency_p95']} | {seconds(p95)} | nearest-rank |")
    add(f"| 超时条数 | 0（§8 记录） | {summary['n_timeout_cases']} | `timeout=true` 的条数 |")
    add(f"| 执行错误条数 | 0（§8 记录） | {summary['n_error_cases']} | `error != null` 的条数 |")
    add("| `fabrication_count` | 0 | 未测 | runner 不采集编造事实，需人工/规则评分 |")
    add("| `unknown_labeled` | 100% | 未测 | runner 不采集 uncertainty 字段 |")
    add("| `first_feedback` | ≤3s | 未测 | runner 只记录端到端耗时 |")
    add("| `clarify_ok` / `no_match_ok` | 100% | 未测 | 需人工按 §3 判定 |")
    add("| `single_source` | ≥90% | 未测 | runner 只记录 `cross_doc_transitions`，不能等同 |")
    add("| 基线 B0 | — | 未运行（T4.3） | 同模型无图谱 baseline 另行执行 |")
    add("")
    add("状态分布（executed 为分母）：")
    add("")
    add("| verified | partial | clarify | error | status_other | 合计 |")
    add("|---|---|---|---|---|---|")
    add(f"| {status_counts.get('verified', 0)}（{status_counts.get('verified', 0) / status_total * 100:.2f}%） "
        f"| {status_counts.get('partial', 0)}（{status_counts.get('partial', 0) / status_total * 100:.2f}%） "
        f"| {status_counts.get('clarify', 0)}（{status_counts.get('clarify', 0) / status_total * 100:.2f}%） "
        f"| {status_counts.get('error', 0)}（{status_counts.get('error', 0) / status_total * 100:.2f}%） "
        f"| {status_other} | {len(executed)} |")
    add("")
    add(f"证据覆盖率复算：{overall_evidence['numerator']} / {overall_evidence['denominator']} 个 NEXT 段有来源文档；"
        "单点园区（0 段）不进入分母，其 `coverage` 为 `null` 而非 100%。")
    route_bearing = [
        case for case in executed
        if (case.get("route") or {}).get("node_count")
        and (case.get("expected") or {}).get("max_stops") is not None
    ]
    stop_cap_route_bearing = sum(
        1 for case in route_bearing
        if (case["route"].get("node_count") or 0) <= case["expected"]["max_stops"]
    )
    add("")
    add(f"`stop_cap_ok` 口径提醒：按 runner 定义 `node_count <= max_stops`，**0 节点的澄清/失败条目也会计为 true**；"
        f"若只看产出了路线的条目（`node_count > 0` 且有 `max_stops`），"
        f"stop_cap_ok = {stop_cap_route_bearing}/{len(route_bearing)}"
        f"（{stop_cap_route_bearing / len(route_bearing) * 100:.2f}%）。"
        if route_bearing else "`stop_cap_ok` 口径提醒：本次没有同时具备路线节点与 max_stops 的条目。")
    add("")
    add("## 3. 分景区")
    add("")
    add("| 景区 | n | 执行 | 成功 | 成功率 | 证据覆盖 | partial | P50 | P95 |")
    add("|---|---:|---:|---:|---|---:|---:|---:|---:|")
    for row in areas:
        add(f"| {row['area']} | {row['n']} | {row['executed']} | {row['success']} "
            f"| {rate_text(row['success_rate'])} | {rate_text(row['evidence_rate'])} "
            f"| {row['partial']} | {seconds(row['p50'])} | {seconds(row['p95'])} |")
    add(f"| **合计** | **{n}** | **{summary['n_executed_cases']}** | **{summary['status_correct']['numerator']}** "
        f"| **{rate_text(summary['status_correct'])}** | **{rate_text(overall_evidence)}** "
        f"| **{status_counts.get('partial', 0)}** | **{seconds(p50)}** | **{seconds(p95)}** |")
    add("")
    add("分组口径：按 id 前缀 CL / BYS / WGS / EDGE 映射到 长隆 / 白云山 / 武功山 / 边界（EDGE）；"
        "子园区（CL-SUB-*）仍归长隆。")
    add("")
    add("## 4. 失败清单（F1–F13）")
    add("")
    add("### 4.1 分类规则与复现")
    add("")
    add("分类只看 runner 记录的结构化字段（确定性规则，见 `report.py::classify_case`），不做自然语言判断；"
        "一条可命中多个 F 标签，表中「主类」取第一个。未执行超时记 F12；其他执行异常因 taxonomy 无独立类，记 F13；"
        "状态判定错误统一记 F2（taxonomy 无独立“状态”类）。")
    add("")
    add("**自动分类的覆盖范围**：F2–F8、F12、F13 可由结构化字段判定；F1（未覆盖/语言）、F9（编造事实）、"
        "F10（条件噪声）、F11（UI 困惑）需要语义/人工判断，本表**不会**自动命中——F9 计数为 0 "
        "**不代表没有编造**，见 §2 的「未测」指标与 §8 限制。")
    add("")
    add("单条复现（只跑该 id，不写 `results/`，不接触 held-out）：")
    add("")
    add("```powershell")
    add("$env:PYTHONIOENCODING='utf-8'; $py='.\\.venv\\Scripts\\python.exe'")
    add("function Repro($id) {")
    add("  & $py -c \"import sys;sys.path.insert(0,r'analysis\\p07_agent\\eval');import run_eval as R,json;"
        "cs,_=R.load_golden_set();c=[x for x in cs if x['id']=='$id'][0];a,_,_=R.load_agent();"
        "print(json.dumps(R.run_case(c,a),ensure_ascii=False,indent=2))\"")
    add("}")
    add("Repro <ID>   # 例：Repro CL-FAM-01")
    add("```")
    add("")
    add(f"完整日志：`analysis/p07_agent/eval/results/{results_path.name}` 的 `cases[]`（按 id 检索）；"
        "会话轨迹在 `eval/results/sessions/`，含用户原文，已被 `.gitignore` 忽略、不入库。")
    add("")
    if failures:
        add("| id | F 类 | 现象 | 复现 | 建议责任 | 状态 |")
        add("|---|---|---|---|---|---|")
        for item in failures:
            case = item["case"]
            primary = item["primary"]
            extra = "、".join(tag for tag, _ in item["tags"] if tag != primary)
            tags = "、".join(tag for tag, _ in item["tags"])
            phenomenon = "；".join(text for _, text in item["tags"]).replace("|", "\\|")
            suffix = f"（含 {extra}）" if extra else ""
            add(f"| `{case['id']}` | **{primary}** {F_NAMES[primary]}{suffix} | {phenomenon} "
                f"| `Repro {case['id']}`（见 §4.1） | {F_RESP.get(primary, '待定')} | 未修（T4.2 仅记录） |")
        add("")
        add("级别说明：状态错误/未执行/schema 失败为**失败**；状态正确但结构、点数或证据有问题的记为**警告**"
            "（全部条目均保留在结果 JSON，不删难样本）。")
    else:
        add("本次没有命中 F1–F13 的条目。")
    add("")
    add("## 5. 失败分类计数")
    add("")
    add("| F 类 | 类别 | 主类计数 | 全部标签计数 | id（主类） |")
    add("|---|---|---:|---:|---|")
    for code in [f"F{i}" for i in range(1, 14)]:
        ids = [f"`{item['case']['id']}`" for item in failures if item["primary"] == code]
        add(f"| {code} | {F_NAMES[code]} | {primary_counts.get(code, 0)} "
            f"| {all_counts.get(code, 0)} | {'、'.join(ids) or '—'} |")
    add("")
    add("## 6. 人工评分")
    add("")
    add("本轮**未做**人工评分（03_EVAL_SPEC.md §4 的 6 维 0–2 分，需至少 1 名人类 + REV Agent）；"
        "机器指标不能替代人工评分。人工评分 CSV 属 T4.3/T4.5。")
    add("")
    add("## 7. 结论")
    add("")
    dev_rate = summary["status_correct"]["rate"]
    evidence_rate = overall_evidence["rate"]
    partial_rate = summary["partial_rate"]["rate"]
    checks = [
        ("dev 成功率 ≥60%（§10 必须）", dev_rate is not None and dev_rate >= 0.60,
         rate_text(summary["status_correct"])),
        ("status_correct ≥90%（§3）", dev_rate is not None and dev_rate >= 0.90,
         rate_text(summary["status_correct"])),
        ("schema_pass 100%（§3）", summary["schema_pass"]["rate"] == 1.0,
         rate_text(summary["schema_pass"])),
        ("route_valid ≥95%（§3）", summary["route_valid"]["rate"] is not None
         and summary["route_valid"]["rate"] >= 0.95, rate_text(summary["route_valid"])),
        ("stop_cap_ok 100%（§3）", summary["stop_cap_ok"]["rate"] is not None
         and summary["stop_cap_ok"]["rate"] >= 1.0, rate_text(summary["stop_cap_ok"])),
        ("证据覆盖 ≥95%（§10 必须）", evidence_rate is not None and evidence_rate >= 0.95,
         rate_text(overall_evidence)),
        ("partial 率 ≤30%（§10 必须）", partial_rate is not None and partial_rate <= 0.30,
         rate_text(summary["partial_rate"])),
        ("P50 ≤45s（§10 必须）", p50 is not None and p50 <= 45, seconds(p50)),
        ("P95 ≤150s（§10 必须）", p95 is not None and p95 <= 150, seconds(p95)),
        ("零超时/零执行错误", summary["n_timeout_cases"] == 0 and summary["n_error_cases"] == 0,
         f"超时 {summary['n_timeout_cases']} / 错误 {summary['n_error_cases']}"),
    ]
    for name, passed, value in checks:
        add(f"- {'达标' if passed else '未达标'}：{name} → {value}")
    add("")
    add("- **不能据此宣布整体达标**：held-out 未运行（成功率未知），人工评分未做，编造事实/未知标注等指标未采集。")
    add("- 下一轮优先修失败清单里的主类（按 §5 主类计数从高到低）；T4.3 的 B0 baseline 应复用本文件的"
        "`cases[]`（status/route/evidence/latency）与同一套 F 分类，保证同口径对比。")
    add("")
    add("## 8. 限制")
    add("")
    add("- **held-out 10 条未运行：held-out 成功率为未知，不是 0。** 本轮按任务要求只跑 dev，"
        "未打开、未运行 held-out 明细。")
    add("- 单次运行（temperature=0）；未做稳定性子集重跑（§8 建议的 10 条 × 2 次），因此不报告波动。")
    add("- `evidence_coverage` 只覆盖 NEXT 段；点位级证据（doc → 标题/URL/摘句）属 T1.6，尚未实现。")
    add("- `route_valid` 对单点园区（0 段）会因“至少两个节点才能校验”计 false，这是现状，未隐藏。")
    add("- `must_include` / `must_not` 未自动评分，表中 F 分类只依据结构化字段，可能低估语义类失败。")
    add("- `stop_cap_ok` 使用 golden set 的 `max_stops`；`CL-FAM-02` 仍为 8，与 Q4「0–6 岁 ≤6」冲突"
        "（`REVIEW_T4.1.md` §4.2），本报告按 8 判定，未静默改。")
    add("- 延迟是 runner 实测墙钟（含重试与多轮），受本机负载影响，不能直接外推到其他机器。")
    timeout_s = meta.get("timeout_s") or 0
    near_timeout = [
        (case["id"], case["latency_s"]) for case in attempted
        if case.get("latency_s") is not None and timeout_s and case["latency_s"] >= 0.9 * timeout_s
    ]
    if near_timeout:
        pairs = "、".join(f"`{cid}` {latency:.2f}s" for cid, latency in near_timeout)
        add(f"- **接近超时**：{pairs} 已达到单条超时阈值的 90% 以上；本次均在第 1 次尝试返回、"
            "未触发重试，但稳定性风险高（T2.7 性能）。")
    add("- 会话轨迹含用户原文，`eval/results/sessions/` 已被 `.gitignore` 忽略；仓库内只保留结构化结果。")
    add("")
    add("## 9. 复算命令")
    add("")
    add("```powershell")
    add("$env:PYTHONIOENCODING='utf-8'; $py='.\\.venv\\Scripts\\python.exe'")
    add(f"& $py analysis\\p07_agent\\eval\\report.py analysis\\p07_agent\\eval\\results\\{results_path.name} "
        "--out analysis\\p07_agent\\eval\\report.md")
    add(f"& $py -c \"import json;d=json.load(open(r'analysis/p07_agent/eval/results/{results_path.name}',encoding='utf-8'));"
        "print(d['meta']);print(d['summary']);print(len(d['cases']));"
        "print(sorted({c['status'] for c in d['cases']}))\"")
    add("```")
    add("")
    add("`report.py` 会对账 `summary` 与 `cases` 复算值：不一致时退出码 3、不写报告。")
    add("")
    add("## 10. 附录：逐条结果（按 golden set 顺序）")
    add("")
    add("| id | status | expected | correct | 节点/上限 | NEXT 段（有来源） | latency | calls | F 标签 |")
    add("|---|---|---|---|---|---:|---:|---:|---|")
    for case in cases:
        route = case.get("route") or {}
        evidence = case.get("evidence") or {}
        max_stops = (case.get("expected") or {}).get("max_stops")
        node_count = route.get("node_count")
        nodes_text = f"{node_count if node_count is not None else '—'}/{max_stops if max_stops is not None else '—'}"
        tags = "、".join(tag for tag, _ in dedupe(classify_case(case))) or "—"
        correct = case.get("status_correct")
        correct_text = "—" if correct is None else ("✓" if correct else "✗")
        add(f"| `{case['id']}` | {status_text(case)} | {case['expected'].get('status')} | {correct_text} "
            f"| {nodes_text} | {evidence.get('segments_with_source', '—')}/{evidence.get('segments_total', '—')} "
            f"| {seconds(case.get('latency_s'))} | {case.get('model_calls')} | {tags} |")
    add("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="从 P7 results JSON 生成 report.md（确定性）")
    parser.add_argument("results", help="results/*.json 路径")
    parser.add_argument("--out", default=str(EVAL_DIR / "report.md"),
                        help="输出 Markdown 路径（默认 eval/report.md）")
    parser.add_argument("--allow-non-dev", action="store_true",
                        help="允许非 dev split（仅 G4/G5 打开 held-out 时使用）")
    args = parser.parse_args(argv)

    results_path = Path(args.results)
    data = load_results(results_path)
    meta = data.get("meta") or {}
    if meta.get("run_mode") != "real":
        raise SystemExit(f"拒绝：run_mode={meta.get('run_mode')!r}，报告只接受真实运行结果")
    bad_splits = sorted({case.get("split") for case in data["cases"]
                         if case.get("split") != "dev"})
    if bad_splits and not args.allow_non_dev:
        raise SystemExit(
            f"拒绝：结果含非 dev 条目 {bad_splits}；T4.2 只生成 dev 报告，"
            "如确需 held-out 报告请加 --allow-non-dev"
        )

    report = build_report(data, results_path)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8", newline="\n")
    print(f"报告已写入：{out_path}")
    print(f"结果：{results_path}，n={len(data['cases'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
