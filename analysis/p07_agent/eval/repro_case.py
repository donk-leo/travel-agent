"""T4.5 单案例复现工具：按 ``--id`` 只跑 golden set 里的一条，打印该条的 runner 记录。

设计约束（与 ``03_EVAL_SPEC.md`` §7 / README §8 一致）：

- **只读** golden set，不写 ``results/``、不新增评测轮、不改任何评分口径；
- 单条执行**完全复用** ``run_eval.run_case``（同一超时 180s、同一重试 1 次、
  同一字段提取），因此复现结果与全量评测里的该条同口径；
- ``--dry-run`` 只按 id 选条并输出空骨架，**不 import agent、不调用模型**，
  用于验证 id 是否存在、golden 字段是否可读；
- 输出只写 stdout（可选 ``--out`` 落到调用方指定路径），不默认污染结果目录。

用法（仓库根目录）::

    $env:PYTHONIOENCODING='utf-8'
    .\\.venv\\Scripts\\python.exe analysis\\p07_agent\\eval\\repro_case.py --id CL-SUB-03 --dry-run
    .\\.venv\\Scripts\\python.exe analysis\\p07_agent\\eval\\repro_case.py --id CL-SUB-03
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import run_eval  # noqa: E402 - 同目录模块，必须先补 sys.path


def find_case(case_id, golden_path=None):
    """从 golden set 里按 id 选出一条；返回 (case, problems)。

    找不到时返回 ``(None, ["golden set 里没有 id=..."])``，绝不新建/改写条目。
    """
    path = run_eval.GOLDEN_PATH if golden_path is None else golden_path
    cases, problems = run_eval.load_golden_set(path)
    if problems:
        return None, list(problems)
    matches = [case for case in cases if case.get("id") == case_id]
    if not matches:
        known = "、".join(str(case.get("id")) for case in cases)
        return None, [f"golden set 里没有 id={case_id!r}；可选 id：{known}"]
    return matches[0], []


def build_parser():
    parser = argparse.ArgumentParser(
        description="T4.5 单案例复现：按 id 选 1 条 golden 查询并复用 run_eval.run_case 执行。",
    )
    parser.add_argument("--id", required=True, help="golden set 的查询 id，例如 CL-SUB-03")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只选条并输出空骨架，不 import agent、不调用模型",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="可选：把该条记录写到指定 JSON 路径（默认只打印到 stdout）",
    )
    return parser


def _emit(payload, out_path=None):
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if out_path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"已写入：{path}")
    else:
        sys.stdout.write(text)


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001 - 控制台编码差异不影响复现
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    case, problems = find_case(args.id)
    if problems:
        print(f"无法复现 {args.id}：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(
            f"[dry-run] id={case['id']} split={case['split']}；"
            "未 import agent、未调用模型，仅输出空骨架。",
            file=sys.stderr,
        )
        _emit(run_eval.dry_run_record(case), args.out)
        return 0

    # 真实复现：单条、与 run_eval 同口径（超时/重试/字段提取均由 run_case 决定）。
    try:
        run_agent, model, url = run_eval.load_agent()
    except Exception as exc:  # noqa: BLE001 - 环境缺失时如实报错，不伪造结果
        print(
            f"无法加载 agent（{type(exc).__name__}: {exc}）；"
            "可先用 --dry-run 验证选条逻辑。",
            file=sys.stderr,
        )
        return 3

    print(f"复现 id={case['id']}；模型={model}；地址={url}", file=sys.stderr)
    record = run_eval.run_case(case, run_agent)
    _emit(record, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
