# -*- coding: utf-8 -*-
"""项目 3 自检：路线结构输出是否符合契约。

用法：
    python checks/check_routes.py [analysis/p03_routes/outputs/routes.jsonl]

检查：必填字段、time_source 枚举、step_no 在同一 route_id 内连续唯一、
time_source=absent 时不得填 time_norm、时间层级枚举、统计输出。
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks._common import Report, check_fields, load_jsonl, not_ready  # noqa: E402
from lib.paths import ANALYSIS  # noqa: E402

DEFAULT = ANALYSIS / "p03_routes" / "outputs" / "routes.jsonl"
REQUIRED = ["doc_id", "route_id", "step_no", "time_source"]
ENUMS = {
    "time_source": {"explicit", "inferred", "absent"},
    "time_period": {"上午", "中午", "下午", "晚上", "未知"},
}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        return not_ready("p03_routes", [path])

    rows = load_jsonl(path)
    rep = Report(f"p03_routes · {path.name} · {len(rows)} 个步骤")
    check_fields(rep, rows, REQUIRED, ENUMS, label="步骤")

    routes: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        routes[row.get("route_id")].append(row)

    absent_with_time = 0
    for route_id, steps in routes.items():
        seq = sorted(int(s.get("step_no", 0)) for s in steps)
        if seq != list(range(1, len(seq) + 1)):
            rep.error(f"{route_id} 的 step_no 不连续：{seq[:10]}…")
        for s in steps:
            if s.get("time_source") == "absent" and str(s.get("time_norm", "")).strip():
                absent_with_time += 1
    if absent_with_time:
        rep.error(f"{absent_with_time} 个步骤 time_source=absent 却填了 time_norm（把推断写成事实）")

    periods = Counter(s.get("time_period") for s in rows)
    rep.note(f"路线数 {len(routes)}；步骤数 {len(rows)}；时间层级 {dict(periods)}")
    rep.note(f"time_source 分布 {dict(Counter(s.get('time_source') for s in rows))}")
    if len(routes) < 2:
        rep.warn("路线数 < 2，任务书要求至少解析 1–2 种格式/路线")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
