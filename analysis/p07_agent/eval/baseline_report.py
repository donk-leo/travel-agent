#!/usr/bin/env python
"""从 B0 baseline JSON + T4.2 dev 结果 + 人工判据 JSON 生成「Baseline 对比」节（T4.3）。

数据来源（三份，全部只读）：
- ``results/baseline-dev-<ts>.json``：B0 机器记录（``baseline.py`` 生成，未手改）；
- ``results/baseline-dev-manual-labels.json``：B0 逐条人工判据（成功/编造，**人工**）；
- ``results/dev-real-20261115T195954.json``：图谱 Agent（T4.2 重跑，T2.2/T2.3 后）结果，**原样引用**
  ``summary``，不重算成别的口径。

本脚本做三件事：
1. 校验三份文件的 id 集合完全一致、且都是 dev（绝不混入 held-out）；
2. 用 B0 的 ``cases`` 复算延迟 P50/P95 并与 ``summary`` 对账（不一致退出码 3），
   用人工判据复算成功率/编造次数，扫描 ``response_text`` 复算“有无来源标识”；
3. 生成 Markdown 节，``--append-to`` 时按 ``<!-- T4.3 BASELINE BEGIN/END -->``
   标记幂等替换 ``report.md`` 的该节（不影响 ``report.py`` 生成的 §0–§10）。

用法（仓库根）：
    .\\.venv\\Scripts\\python.exe analysis\\p07_agent\\eval\\baseline_report.py ^
        analysis\\p07_agent\\eval\\results\\baseline-dev-<ts>.json
    .\\.venv\\Scripts\\python.exe analysis\\p07_agent\\eval\\baseline_report.py ^
        analysis\\p07_agent\\eval\\results\\baseline-dev-<ts>.json --append-to analysis\\p07_agent\\eval\\report.md
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_AGENT_RESULTS = EVAL_DIR / "results" / "dev-real-20261115T195954.json"
DEFAULT_LABELS = EVAL_DIR / "results" / "baseline-dev-manual-labels.json"

BEGIN_MARKER = "<!-- T4.3 BASELINE BEGIN -->"
END_MARKER = "<!-- T4.3 BASELINE END -->"

# 严格来源标识：doc_id（如 CL-O-01）或 URL；普通“参考/来源”字样不算可核对来源。
DOC_ID_RE = re.compile(r"\b[A-Z]{2,4}-[OT]-\d{2}\b")
URL_RE = re.compile(r"https?://\S+")

# 与 run_eval / baseline 相同的 nearest-rank 口径。
def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(percent / 100.0 * len(ordered)), 1)
    return round(ordered[rank - 1], 3)


def load_json(path):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 解析失败：{path}（{exc}）")
    if not isinstance(data, dict):
        raise SystemExit(f"JSON 顶层不是对象：{path}")
    return data


def fmt_rate(numerator, denominator, digits=2):
    if not denominator:
        return f"{numerator}/{denominator}（N/A，分母为 0）"
    return f"{numerator}/{denominator}（{numerator / denominator * 100:.{digits}f}%）"


def fmt_sec(value):
    return "N/A" if value is None else f"{value:.2f}s"


def md_cell(value):
    return str(value).replace("|", "\\|")


def has_citation(text):
    return bool(DOC_ID_RE.search(text or "") or URL_RE.search(text or ""))


def validate(baseline, agent, labels):
    base_cases = baseline.get("cases")
    agent_cases = agent.get("cases")
    label_cases = labels.get("cases")
    for name, value in (("baseline", base_cases), ("agent", agent_cases), ("labels", label_cases)):
        if not isinstance(value, list):
            raise SystemExit(f"{name} 的 cases 不是数组")

    base_ids = [case.get("id") for case in base_cases]
    agent_ids = [case.get("id") for case in agent_cases]
    label_ids = [case.get("id") for case in label_cases]
    if len(set(base_ids)) != len(base_ids):
        raise SystemExit("baseline 的 id 有重复")
    if set(base_ids) != set(agent_ids):
        raise SystemExit(
            f"baseline 与 T4.2 的 id 集合不一致："
            f"仅 baseline {sorted(set(base_ids) - set(agent_ids))}；"
            f"仅 T4.2 {sorted(set(agent_ids) - set(base_ids))}"
        )
    if set(base_ids) != set(label_ids):
        raise SystemExit(
            f"人工判据与 baseline 的 id 集合不一致："
            f"缺 {sorted(set(base_ids) - set(label_ids))}；"
            f"多 {sorted(set(label_ids) - set(base_ids))}"
        )
    for source, cases in (("baseline", base_cases), ("agent", agent_cases), ("labels", label_cases)):
        bad = [case.get("id") for case in cases if case.get("split") != "dev"]
        if bad:
            raise SystemExit(f"{source} 含非 dev 条目：{bad}")


def recompute_b0(baseline, labels):
    """从 baseline.cases 与人工判据复算 B0 指标；对账 summary 的机器事实。"""
    cases = baseline["cases"]
    summary = baseline.get("summary") or {}
    latencies = [case["latency_s"] for case in cases
                 if isinstance(case.get("latency_s"), (int, float))]
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    latency_summary = summary.get("latency_s") or {}
    if p50 != latency_summary.get("p50") or p95 != latency_summary.get("p95"):
        raise SystemExit(
            "B0 延迟复算与 summary 不一致："
            f"复算 p50={p50} p95={p95}，summary={latency_summary}"
        )
    if summary.get("n_cases") != len(cases):
        raise SystemExit(
            f"B0 summary.n_cases={summary.get('n_cases')} 与 cases={len(cases)} 不一致"
        )

    label_by_id = {case["id"]: case for case in labels["cases"]}
    success = 0
    fabrications = 0
    fabrication_cases = 0
    fabrication_rows = []
    evidence_cases = 0
    empty_cases = 0
    for case in cases:
        case_id = case["id"]
        label = label_by_id[case_id]
        if not isinstance(label.get("success"), bool):
            raise SystemExit(f"{case_id}: 人工判据 success 必须是布尔值")
        if not isinstance(label.get("fabrication_count"), int) or label["fabrication_count"] < 0:
            raise SystemExit(f"{case_id}: 人工判据 fabrication_count 必须是非负整数")
        quotes = label.get("fabricated_quotes") or []
        if len(quotes) != label["fabrication_count"]:
            raise SystemExit(
                f"{case_id}: fabricated_quotes 条数 {len(quotes)} "
                f"!= fabrication_count {label['fabrication_count']}"
            )
        text = case.get("response_text") or ""
        for quote in quotes:
            if not isinstance(quote, str) or not quote.strip() or quote not in text:
                raise SystemExit(
                    f"{case_id}: 编造原句必须是 response_text 的逐字子串：{quote!r}"
                )
        if not text.strip():
            empty_cases += 1
        if has_citation(text):
            evidence_cases += 1
        if label["success"]:
            if label["fabrication_count"]:
                raise SystemExit(f"{case_id}: 有编造却判成功，与判据矛盾")
            if not text.strip():
                raise SystemExit(f"{case_id}: 无响应却判成功")
            success += 1
        if label["fabrication_count"]:
            fabrication_cases += 1
            fabrications += label["fabrication_count"]
            fabrication_rows.append({
                "id": case_id,
                "count": label["fabrication_count"],
                "quotes": quotes,
                "notes": label.get("notes") or "",
            })
    return {
        "n": len(cases),
        "success": success,
        "fabrications": fabrications,
        "fabrication_cases": fabrication_cases,
        "fabrication_rows": fabrication_rows,
        "evidence_cases": evidence_cases,
        "empty_cases": empty_cases,
        "p50": p50,
        "p95": p95,
        "timeout": summary.get("n_timeout_cases"),
        "errors": summary.get("n_error_cases"),
        "chars": summary.get("response_chars") or {},
    }


def build_section(baseline_path, agent_path, labels_path, baseline, agent, labels):
    meta_b0 = baseline.get("meta") or {}
    meta_agent = agent.get("meta") or {}
    summary_agent = agent.get("summary") or {}
    b0 = recompute_b0(baseline, labels)
    label_meta = labels.get("meta") or {}

    agent_success = summary_agent.get("status_correct") or {}
    agent_evidence = summary_agent.get("evidence_coverage") or {}
    agent_partial = summary_agent.get("partial_rate") or {}
    agent_latency = summary_agent.get("latency_s") or {}

    lines = []
    add = lines.append
    add("## 11. Baseline 对比（T4.3：B0 同模型无图谱）")
    add("")
    add("> 本节由 `analysis/p07_agent/eval/baseline_report.py` 从三份文件确定性生成并追加；"
        "不修改 §0–§10（由 `report.py` 生成）。")
    add(f"> B0 机器记录：`results/{baseline_path.name}`（runner 生成，未手改）；"
        f"B0 人工判据：`results/{labels_path.name}`（**人工**逐条）；"
        f"图谱 Agent（T4.2）：`results/{agent_path.name}`（原样引用 `summary`，不重算口径）。")
    add("> §2 末尾「基线 B0 — 未运行（T4.3）」是 T4.2 生成时的状态；T4.3 已运行 B0，"
        "对比以本节为准，§0–§10 正文未改。")
    add("")
    add("### 11.1 对比条件（公平性）")
    add("")
    add("| 项 | 图谱 Agent（T4.2） | 通用 LLM B0 |")
    add("|---|---|---|")
    add(f"| 模型 | `{meta_agent.get('model')}` | `{meta_b0.get('model')}` |")
    add("| temperature | 0（src 固定） | 0（请求 options 固定） |")
    add(f"| 运行时 HEAD / 工作区 | `{meta_agent.get('commit')}` / "
        f"dirty={meta_agent.get('git_dirty')} | `{meta_b0.get('commit')}` / "
        f"dirty={meta_b0.get('git_dirty')}（运行时 `baseline.py` 还未提交） |")
    add(f"| 查询集合 | dev 20 条（golden set） | dev 20 条，`query` 逐字提交 |")
    add("| 图谱 / 工具 / 证据 | 有（P6 图谱写进 prompt，路线逐段带 `source_doc_ids`） "
        "| 无（只有 system prompt + query） |")
    add("| 输出形态 | 结构化路线 + 四状态契约 | 自由文本（无状态） |")
    add(f"| 单条超时 / 重试 | {meta_agent.get('timeout_s')}s / "
        f"{meta_agent.get('max_attempts')} 次 | {meta_b0.get('timeout_s')}s / "
        f"{meta_b0.get('max_attempts')} 次 |")
    add("| 多轮 query | 按 `turns` 逐轮累积提交 | 未展开：`EDGE-FOLLOW-01` 按 `query` 字面单轮提交 |")
    add(f"| system prompt | 见 `src/`（意图/工具/路线多个 prompt） "
        f"| `{md_cell(meta_b0.get('system_prompt'))}` |")
    add("")
    add("条件说明：B0 只调用一次模型，图谱 Agent 内部按意图/工具/路线多次调用；"
        "因此延迟是「端到端系统 vs 单次调用」，不是同等工作量的对比。")
    add("")
    add("### 11.2 对比表")
    add("")
    add("| 指标 | 图谱 Agent（T4.2） | 通用 LLM B0 |")
    add("|---|---|---|")
    add(f"| 样本 / 有响应 | {summary_agent.get('n_cases')} / "
        f"{summary_agent.get('n_executed_cases')} "
        f"| {b0['n']} / {b0['n'] - b0['empty_cases']} |")
    add(f"| 成功率 | {fmt_rate(agent_success.get('numerator'), agent_success.get('denominator'))} "
        f"| {fmt_rate(b0['success'], b0['n'])} |")
    add(f"| 证据正确率（有来源比例） | {fmt_rate(agent_evidence.get('numerator'), agent_evidence.get('denominator'))}"
        f"（NEXT 段级） | {fmt_rate(b0['evidence_cases'], b0['n'])}（条级，无 doc_id/URL 引用） |")
    add(f"| 编造次数 | 未测（T4.2 runner 不采集，`report.md` §2 `fabrication_count`=未测） "
        f"| {b0['fabrications']} 次（涉及 {b0['fabrication_cases']} 条，人工判据） |")
    add(f"| partial 率 | {fmt_rate(agent_partial.get('numerator'), agent_partial.get('denominator'))} "
        "| 不适用（无状态契约） |")
    add(f"| P50 | {fmt_sec(agent_latency.get('p50'))} | {fmt_sec(b0['p50'])} |")
    add(f"| P95 | {fmt_sec(agent_latency.get('p95'))} | {fmt_sec(b0['p95'])} |")
    add(f"| 超时 / 执行错误 | {summary_agent.get('n_timeout_cases')} / "
        f"{summary_agent.get('n_error_cases')} "
        f"| {b0['timeout']} / {b0['errors']} |")
    add("")
    add("**两列的成功率定义不同，不能直接相减当作“图谱增量”**：图谱 Agent 的 95% 是"
        "「`status` 落在 `expected.status` 内」的状态判定；B0 的 30% 是「输出有 ≥3 地点顺序行程且"
        "无四类编造」的内容判定。前者不评估文本是否编造，后者不区分 verified/partial。")
    agent_route = summary_agent.get("route_valid") or {}
    agent_stop = summary_agent.get("stop_cap_ok") or {}
    add(f"补充（T4.2 原样引用）：`route_valid` = "
        f"{fmt_rate(agent_route.get('numerator'), agent_route.get('denominator'))}，"
        f"`stop_cap_ok` = {fmt_rate(agent_stop.get('numerator'), agent_stop.get('denominator'))}；"
        "B0 无对应结构指标，不能比较。")
    add("")
    add("### 11.3 指标定义与数据来源")
    add("")
    add("| 指标 | 定义 | 图谱 Agent（T4.2）数据来源 | B0 数据来源 |")
    add("|---|---|---|---|")
    add("| 成功率 | 图谱 Agent：`status ∈ expected.status` 的条数 / 已执行条数；"
        "B0：输出含可执行顺序行程（≥3 个地点且有顺序）**且无编造**的条数 / 20 | "
        f"`results/{agent_path.name}` 的 `summary.status_correct`（`run_eval.py::compute_summary`） "
        "| 人工判据 `success=true` 的计数（`baseline_report.py` 复算） |")
    add("| 证据正确率（有来源比例） | 图谱 Agent：有来源文档的 NEXT 段 / 全部 NEXT 段（`source_doc_ids` 非空）；"
        "B0：响应中出现可核对来源标识（doc_id 或 URL）的条数 / 20 | "
        f"`results/{agent_path.name}` 的 `summary.evidence_coverage` "
        "| `baseline_report.py` 扫描 `response_text`（正则：doc_id / URL），结果见 11.2 |")
    add("| 编造次数 | 具体距离（X 米/公里）、步行耗时、票价、开放时间且无来源 → 每句计 1 次（人工） | "
        f"`report.md` §2 明确标注为「未测」（runner 不采集自然语言事实） "
        f"| 人工判据 `fabrication_count` 之和（`results/{labels_path.name}`） |")
    add("| partial 率 | `status=partial` 条数 / 已执行条数 | "
        f"`results/{agent_path.name}` 的 `summary.partial_rate` "
        "| 不适用：B0 无 verified/partial/clarify/error 状态契约，不填 0 冒充 |")
    add("| P50 / P95 | 端到端墙钟耗时（nearest-rank） | "
        f"`results/{agent_path.name}` 的 `summary.latency_s` "
        "| `baseline_report.py` 从 B0 `cases[].latency_s` 复算，并与 `summary.latency_s` 对账 |")
    add("")
    add("### 11.4 B0 人工判据（人工判断，非脚本判定）")
    add("")
    add(f"- 判据来源：`results/{labels_path.name}`；"
        f"判据说明：{md_cell(label_meta.get('annotation') or '人工逐条')}；"
        f"标注人：{md_cell(label_meta.get('annotator') or 'QA（T4.3）')}；"
        f"日期：{md_cell(label_meta.get('date') or '未记录')}。")
    add("- **编造**：出现具体距离（X 米/公里）、步行耗时、票价、开放时间且无来源 → 每条原句计 1 次编造；")
    add("- **成功**：输出含可执行的顺序行程（至少 3 个地点 + 顺序）且无编造 → 成功；否则失败；")
    add("- 同一判据不对 B0 提供图谱/工具/景区数据，也不因“格式不如结构化输出”扣分，只看内容事实与可执行性。")
    add("")
    add(f"### 11.5 B0 编造清单（人工判据：{b0['fabrications']} 次 / "
        f"{b0['fabrication_cases']} 条）")
    add("")
    if b0["fabrication_rows"]:
        for index, row in enumerate(b0["fabrication_rows"], 1):
            add(f"{index}. `{row['id']}`（{row['count']} 次）")
            for quote in row["quotes"]:
                add(f"   - 「{md_cell(quote)}」")
            if row["notes"]:
                add(f"   - 判据说明：{md_cell(row['notes'])}")
    else:
        add("本次未发现符合判据的编造原句。")
    add("")
    add("### 11.6 复算命令")
    add("")
    add("```powershell")
    add("$env:PYTHONIOENCODING='utf-8'; $py='.\\.venv\\Scripts\\python.exe'")
    add(f"& $py analysis\\p07_agent\\eval\\baseline_report.py "
        f"analysis\\p07_agent\\eval\\results\\{baseline_path.name}")
    add(f"& $py analysis\\p07_agent\\eval\\baseline_report.py "
        f"analysis\\p07_agent\\eval\\results\\{baseline_path.name} "
        "--append-to analysis\\p07_agent\\eval\\report.md")
    add("```")
    add("")
    add("注意：`report.py` 重跑会覆盖 `report.md` 并删除本节；重跑 `report.py` 后需再执行上面的"
        "`--append-to` 命令恢复本节（按本节首尾的基线标记幂等替换，不会重复追加）。")
    add("")
    add("### 11.7 局限")
    add("")
    add("- B0 是**单次调用、自由文本**；图谱 Agent 是多次模型调用 + 图谱检索 + 结构校验，"
        "延迟与成功率都不是同等工作量的对比。")
    add("- B0 的成功/编造是**人工**按 §11.4 判据逐条判定的，不是脚本自动评分；"
        "人工判据文件与原始响应（`response_text`）都在仓库内，可复核。")
    add("- **成功率口径不同**（见 §11.2 表后说明）：图谱 Agent 是状态判定，B0 是内容判定；"
        "两者的差值不能整体归因于图谱/工具的价值。")
    add("- 图谱 Agent 的编造次数**未测**：T4.2 runner 只记录结构化路线与 `source_doc_ids`，"
        "不采集自然语言事实，因此不能把 0 当作“无编造”。")
    add("- 证据正确率的两种单位不同（NEXT 段 vs 条），但 B0 的任何响应都不含 doc_id/URL 引用，"
        "两种单位下均为 0；图谱侧的 100% 是「段有来源」，不是「来源内容正确」的语义校验。")
    add("- `EDGE-FOLLOW-01` 在 B0 中按 `query` 字面单轮提交（含 `→` 记号），与 Agent 的多轮提交不同口径。")
    add(f"- B0 输出受 `num_predict={meta_b0.get('num_predict')}` 限制，可能在中途被截断；"
        f"本次响应长度 min/p50/max = {b0['chars'].get('min')}/{b0['chars'].get('p50')}/"
        f"{b0['chars'].get('max')} 字符。")
    add("- **编造判据只覆盖四类**（距离/步行耗时/票价/开放时间）：景点名、餐厅名、演出名、"
        "日落/日出时刻、海拔等若为编造，本表不计；因此 B0 的成功率是**该窄判据下的上限**。")
    add("- **敏感项**：`CL-FAM-01` 的「时间：上午9:00 - 下午5:00」按“建议时段”未计为开放时间；"
        "若判为开放时间，则编造 23 次、成功 5/20（25.00%）。")
    add("- 未做 03_EVAL_SPEC §4 的 6 维人工评分（结构/证据/可行/偏好/清晰/诚实），"
        "B0 与图谱 Agent 的“可行性/偏好满足”没有同 rubric 分数，只给任务成功与编造判据。")
    add("- held-out 10 条**未运行**（本任务只允许 dev）；B0 的 held-out 表现未知，不是 0。")
    add("")
    add(END_MARKER)
    return "\n".join(lines)


def append_section(report_path, section):
    report_path = Path(report_path)
    text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    block = f"{BEGIN_MARKER}\n{section}\n"
    if BEGIN_MARKER in text and END_MARKER in text:
        start = text.index(BEGIN_MARKER)
        end = text.index(END_MARKER) + len(END_MARKER)
        new_text = text[:start] + block.rstrip("\n") + text[end:]
    else:
        base = text.rstrip("\n")
        new_text = f"{base}\n\n{block}" if base else block
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(new_text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
    return report_path


def build_parser():
    parser = argparse.ArgumentParser(description="生成 P7 Baseline 对比节（T4.3）")
    parser.add_argument("baseline", help="B0 结果 JSON（results/baseline-dev-*.json）")
    parser.add_argument("--agent-results", default=str(DEFAULT_AGENT_RESULTS),
                        help=f"T4.2 dev 结果 JSON（默认 {DEFAULT_AGENT_RESULTS.name}）")
    parser.add_argument("--labels", default=str(DEFAULT_LABELS),
                        help="B0 人工判据 JSON")
    parser.add_argument("--out", default=None,
                        help="把本节 Markdown 写到该路径（默认打印到 stdout）")
    parser.add_argument("--append-to", default=None,
                        help="把本节幂等追加/替换到该 Markdown（如 eval/report.md）")
    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001 - 控制台编码差异不影响输出
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    agent_path = Path(args.agent_results)
    labels_path = Path(args.labels)
    baseline = load_json(baseline_path)
    agent = load_json(agent_path)
    labels = load_json(labels_path)

    validate(baseline, agent, labels)
    section = build_section(baseline_path, agent_path, labels_path, baseline, agent, labels)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(section + "\n", encoding="utf-8", newline="\n")
        print(f"对比节已写入：{out_path}")
    if args.append_to:
        report_path = append_section(args.append_to, section)
        print(f"对比节已追加/替换：{report_path}")
    if not args.out and not args.append_to:
        print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
