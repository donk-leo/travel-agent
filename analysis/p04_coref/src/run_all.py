# -*- coding: utf-8 -*-
"""项目4 一键复现：检测 → 消解 → 标注 → 评估 → 插图 → 报告 → 自检。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "analysis" / "p04_coref" / "src"
STEPS = [
    "detect_pronouns.py",
    "resolve_coref.py",
    "build_annotations.py",
    "eval_coref.py",
    "make_figures.py",
    "build_report.py",
]


def main() -> int:
    for name in STEPS:
        print(f"\n=== {name} ===")
        r = subprocess.run([sys.executable, str(SRC / name)], cwd=ROOT)
        if r.returncode:
            return r.returncode
    print("\n=== checks/check_coref.py ===")
    return subprocess.run([sys.executable, str(ROOT / "checks" / "check_coref.py")], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
