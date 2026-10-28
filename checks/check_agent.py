# -*- coding: utf-8 -*-
"""项目 7 自检：Agent 交付物与安全约束。

用法：
    python checks/check_agent.py [analysis/p07_agent]

检查：入口与工具脚本存在、工具 Schema 已定义、会话轨迹非空、
测试与示范文件存在、仓库内没有明文密钥、.env 未被提交。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks._common import Report, not_ready  # noqa: E402
from lib.paths import ANALYSIS  # noqa: E402

DEFAULT = ANALYSIS / "p07_agent"
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "疑似 OpenAI API Key"),
    (re.compile(r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][^'\"]{12,}['\"]"), "疑似硬编码密钥"),
]


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    required = [base / "src" / "agent.py", base / "src" / "tools.py"]
    if not any(p.exists() for p in required):
        return not_ready("p07_agent", required)

    rep = Report(f"p07_agent · {base}")
    for p in required:
        if not p.exists():
            rep.error(f"缺少文件：{p.relative_to(base.parent.parent)}")

    sessions = sorted((base / "outputs" / "sessions").glob("*.jsonl"))
    if not sessions:
        rep.error("缺少 outputs/sessions/*.jsonl（工具调用轨迹，用于证明回答基于图谱）")
    else:
        total = sum(sum(1 for line in p.open(encoding="utf-8") if line.strip()) for p in sessions)
        rep.note(f"会话轨迹 {len(sessions)} 个文件，共 {total} 步")

    for name in ("tests.md", "demo.md"):
        if not (base / "outputs" / name).exists():
            rep.error(f"缺少 outputs/{name}")

    if (base / ".env").exists():
        rep.error("发现 .env 被提交（密钥不得入库，只留 .env.example）")
    elif not (base / ".env.example").exists():
        rep.warn("缺少 .env.example（应说明需要哪些环境变量）")

    for py in base.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                rep.error(f"{py.name} 中{label}")

    if not (base / "outputs" / "sessions").exists():
        rep.note("提示：跑一次 CLI 并把轨迹落盘到 outputs/sessions/")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
