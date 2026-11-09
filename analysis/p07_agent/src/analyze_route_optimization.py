"""离线复算路线整理效果。

读取 ``outputs/evaluation_results.json`` 中 2026-11-03 的真实模型路线，把其中的
``route_nodes`` 交给 ``tools.optimize_route`` 重新整理，输出可直接粘进测试记录的
Markdown 对照表。只做确定性计算，不调用模型、不修改原始结果文件。

用法（仓库根目录）：

    python analysis/p07_agent/src/analyze_route_optimization.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools import get_route_candidates, optimize_route  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "analysis" / "p07_agent" / "outputs" / "evaluation_results.json"


def main():
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    rows = []
    for case in data["cases"]:
        nodes = case.get("route_nodes") or []
        if len(nodes) < 2:
            continue
        area = case["intent"]["scenic_area"]
        optimized = optimize_route(nodes, get_route_candidates(area))
        before = optimized["original_metrics"]
        after = optimized["metrics"]
        rows.append({
            "case_id": case["case_id"],
            "label": case["label"],
            "area": area,
            "before": f'{before["steps"]} 步 / 重复 {before["repeats"]}',
            "after": f'{after["steps"]} 步 / 重复 {after["repeats"]}',
            "method": optimized["method"],
            "changed": "是" if optimized["optimized"] else "否",
        })

    print("| 案例 | 景区 | 模型原始路线 | 整理后 | 是否变化 | 算法 |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        print(f'| {row["label"]}（`{row["case_id"]}`） | {row["area"]} | '
              f'{row["before"]} | {row["after"]} | {row["changed"]} | {row["method"]} |')
    print()
    print("说明：步数指图谱 NEXT 连接的段数，不是实际步行距离；"
          "“重复”指同一地点在路线中再次出现。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
