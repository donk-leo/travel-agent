# -*- coding: utf-8 -*-
"""一条命令重建 P6 全链路：建图 → 出图 → QA → 自检。

用法（仓库根目录）：
    python analysis/p06_graph/src/run_all.py
    python analysis/p06_graph/src/run_all.py --areas changlong   # 只跑单景区
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "analysis" / "p06_graph"
OUTPUTS = PROJECT / "outputs"
CHECK = ROOT / "checks" / "check_graph.py"


def run(cmd: list[str]) -> None:
    print("\n$ " + " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"命令失败（exit {result.returncode}）：{cmd}")


def main() -> int:
    parser = argparse.ArgumentParser(description="P6 全链路重建")
    parser.add_argument("--areas", nargs="*", default=None)
    args = parser.parse_args()

    build = [sys.executable, str(PROJECT / "src" / "build_graph.py")]
    if args.areas:
        build += ["--areas", *args.areas]
    run(build)
    run([sys.executable, str(CHECK), str(OUTPUTS)])

    stats = json.loads((OUTPUTS / "graph_stats.json").read_text(encoding="utf-8"))
    print("\n=== 交付摘要 ===")
    print(f"节点 {stats['counts']['nodes']} / 边 {stats['counts']['edges']}")
    print("节点类型 " + json.dumps(stats["counts"]["by_type"], ensure_ascii=False))
    print("边类型   " + json.dumps(stats["counts"]["by_rel"], ensure_ascii=False))
    print("输出目录 " + str(OUTPUTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
