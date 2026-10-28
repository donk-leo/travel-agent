# -*- coding: utf-8 -*-
"""一键运行：采集（默认走缓存）→ 正文抽取 → 清洗 → 结构化输出与质检。

用法：
    python src/run_all.py              # 有原始 HTML 就直接复用，不重复请求站点
    python src/run_all.py --refresh    # 强制重新采集全部页面
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(script: str, extra: list[str] | None = None) -> None:
    cmd = [sys.executable, str(ROOT / "src" / script), *(extra or [])]
    print(f"\n>>> {' '.join(cmd)}")
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="强制重新抓取页面")
    args = parser.parse_args()

    run("collect.py", ["--force"] if args.refresh else [])
    run("extract.py")
    run("clean.py")
    run("build_dataset.py")
    print("\n全部完成：data/processed/ 与 outputs/ 已更新。")


if __name__ == "__main__":
    main()
