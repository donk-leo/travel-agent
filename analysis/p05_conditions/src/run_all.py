# -*- coding: utf-8 -*-
"""项目5 一键运行：抽取 → 评估 → 映射表 → 图 → 报告 → 自检。

用法（仓库根目录）：
    python analysis/p05_conditions/src/run_all.py

若本机 python 没装 openpyxl/Pillow/python-docx，请改用课程环境里的 python.exe。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
STEPS = [
    ("抽取条件-建议", HERE / "extract_conditions.py"),
    ("人工抽查评估", HERE / "eval_conditions.py"),
    ("生成映射表", HERE / "build_mapping.py"),
    ("生成统计图", HERE / "make_figures.py"),
    ("生成报告", HERE / "build_report.py"),
]


def main() -> int:
    for name, script in STEPS:
        print(f"\n=== {name}：{script.name} ===")
        proc = subprocess.run([sys.executable, str(script)], cwd=REPO)
        if proc.returncode:
            print(f"步骤失败：{script.name}，退出码 {proc.returncode}")
            return proc.returncode
    print("\n=== 自检：checks/check_conditions.py ===")
    proc = subprocess.run([sys.executable, str(REPO / "checks" / "check_conditions.py")], cwd=REPO)
    if proc.returncode:
        print(f"自检失败，退出码 {proc.returncode}")
        return proc.returncode
    print("\n全部完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())