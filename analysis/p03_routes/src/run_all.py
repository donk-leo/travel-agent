#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目 3 一键重跑：路线解析 → 时间层级/对比/图 → 自检。

用法（在仓库根目录执行）：
    python analysis/p03_routes/src/run_all.py

等价于依次执行：
    python analysis/p03_routes/src/parse_routes.py
    python analysis/p03_routes/src/build_hierarchy.py
    python checks/check_routes.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = sys.executable

STEPS = [
    ("路线解析 → outputs/routes.jsonl", ROOT / "analysis" / "p03_routes" / "src" / "parse_routes.py"),
    ("时间层级 / 对比 / 图", ROOT / "analysis" / "p03_routes" / "src" / "build_hierarchy.py"),
    ("自检 checks/check_routes.py", ROOT / "checks" / "check_routes.py"),
]


def main() -> int:
    for title, script in STEPS:
        print(f"\n===== {title}")
        proc = subprocess.run([PY, str(script)], cwd=ROOT)
        if proc.returncode != 0:
            print(f"[失败] {script.name} 退出码 {proc.returncode}", file=sys.stderr)
            return proc.returncode
    print("\n全部完成：routes.jsonl / hierarchy.json / compare_official_vs_user.csv / "
          "figures/route_structure.png 已更新，自检通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
