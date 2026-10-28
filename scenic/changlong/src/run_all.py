# -*- coding: utf-8 -*-
"""长隆 项目1 一键流水线：采集(可选) → 清洗 → 质检 → 标准化导出 → 自检。

用法（仓库根或本目录均可）：
    python scenic/changlong/src/run_all.py            # 复用已提交的 raw_docs.jsonl
    python scenic/changlong/src/run_all.py --refresh  # 重新采集 8 个页面（约 10 秒 + 请求间隔）

产物：
    data/interim/raw_docs.jsonl        采集结果（--refresh 时生成）
    data/interim/legacy_20col.csv      清洗后的 20 列中间表
    data/processed/changlong_guides.csv  交付物（24 列，UTF-8-SIG）
    outputs/                           质量报告、清洗前后样例、图表
    report/                            实验报告章节 docx（单独跑 build_report.py）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]        # scenic/changlong
ROOT = BASE.parents[1]                            # 仓库根
SRC = BASE / "src"
PY = sys.executable


def run(script: Path, *args: str) -> None:
    print(f"\n▶ {script.name} {' '.join(args)}".rstrip())
    result = subprocess.run([PY, str(script), *args], cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit(f"✗ {script.name} 失败（exit {result.returncode}）")


def main() -> int:
    refresh = "--refresh" in sys.argv
    raw_docs = BASE / "data" / "interim" / "raw_docs.jsonl"

    if refresh:
        run(SRC / "collect_pages.py")
    elif not raw_docs.exists():
        print(f"✗ 缺少 {raw_docs}，请先运行：python scenic/changlong/src/run_all.py --refresh")
        return 1
    else:
        print(f"· 复用已采集的 {raw_docs.relative_to(ROOT)}")

    run(SRC / "clean_dataset.py")
    run(SRC / "qc_dataset.py")
    run(SRC / "export_standard.py")
    run(ROOT / "checks" / "check_scenic.py", str(BASE / "data" / "processed" / "changlong_guides.csv"))

    print("\n✓ 长隆流水线完成：")
    print(f"  数据集 {BASE / 'data' / 'processed' / 'changlong_guides.csv'}")
    print(f"  质量报告 {BASE / 'outputs' / '质量检查报告.md'}")
    print("  报告章节：python scenic/changlong/src/build_report.py（可选）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
