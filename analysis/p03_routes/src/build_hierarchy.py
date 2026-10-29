# -*- coding: utf-8 -*-
"""项目 3 第二段：构建上午/中午/下午层级、官方 vs 游客对比、结构图。

输入：outputs/routes.jsonl（第一段产出）+ 三景区 *_guides.csv 的 doc_type 元信息
输出：
  outputs/hierarchy.json
  outputs/compare_official_vs_user.csv
  outputs/figures/route_structure.png

口径（冻结项之一，写进报告）：
  * 时间层级只由 time_source=explicit 的步骤决定，absent 的步骤进"未知"，不做推断；
  * 上午 06:00–11:59；中午 12:00–13:59；下午 14:00–17:59；晚上 18:00–05:59；
  * "上午/早上/中午/下午/傍晚/晚上"等词按 AM/NOON/PM 记录 time_norm，同时落 time_period。
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.io_utils import read_csv_sig  # noqa: E402
from lib.paths import SCENIC_AREAS, scenic_csv  # noqa: E402

PROJECT = ROOT / "analysis" / "p03_routes"
OUTPUTS = PROJECT / "outputs"
FIGURES = OUTPUTS / "figures"
PERIODS = ("上午", "中午", "下午", "晚上", "未知")
PERIOD_RULE = {
    "上午": "06:00 ≤ 时间 < 12:00，或原文写上午/早上/清晨",
    "中午": "12:00 ≤ 时间 < 14:00，或原文写中午",
    "下午": "14:00 ≤ 时间 < 18:00，或原文写下午",
    "晚上": "18:00 ≤ 时间 或 < 06:00，或原文写傍晚/晚上",
    "未知": "time_source=absent，原文没有任何时间表达（不做推断）",
}
TIME_NORM_RULE = {
    "HH:MM": "原文显式时刻；时间段取起点（time_raw 保留完整区间）",
    "AM": "原文显式写上午/早上/清晨/凌晨",
    "NOON": "原文显式写中午/正午",
    "PM": "原文显式写下午/傍晚/晚上",
    "": "time_source=absent 时不填",
}


def load_routes() -> list[dict]:
    path = OUTPUTS / "routes.jsonl"
    with path.open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return sorted(rows, key=lambda r: (r["route_id"], r["step_no"]))


def load_doc_meta() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for area in SCENIC_AREAS:
        for row in read_csv_sig(scenic_csv(area))[0]:
            meta[(row.get("doc_id") or "").strip()] = {
                "scenic_area": (row.get("scenic_area") or "").strip(),
                "doc_type": (row.get("doc_type") or "").strip(),
                "subtype": (row.get("subtype") or "").strip(),
                "title": (row.get("title") or "").strip(),
            }
    return meta


def kendall_tau(pairs: list[tuple[int, int]]) -> float | None:
    """pairs 为 (官方序, 游客序)；返回一致对占比映射到 [-1,1]，样本不足返回 None。"""
    if len(pairs) < 2:
        return None
    conc = disc = 0
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            s = (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1])
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
    total = conc + disc
    if total == 0:
        return None
    return (conc - disc) / total


def sequence_of(routes_steps: list[dict]) -> list[str]:
    seen, order = set(), []
    for step in routes_steps:
        poi = step.get("poi")
        if poi and poi not in seen:
            seen.add(poi)
            order.append(poi)
    return order


def main() -> int:
    rows = load_routes()
    doc_meta = load_doc_meta()

    by_route: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_route[r["route_id"]].append(r)
    for steps in by_route.values():
        steps.sort(key=lambda s: s["step_no"])

    route_info = []
    for route_id, steps in by_route.items():
        doc_id = steps[0]["doc_id"]
        info = doc_meta.get(doc_id, {})
        periods = Counter(s.get("time_period", "未知") for s in steps)
        timed = [s for s in steps if s.get("time_source") == "explicit"]
        route_info.append({
            "route_id": route_id,
            "doc_id": doc_id,
            "scenic_area": info.get("scenic_area", ""),
            "doc_type": info.get("doc_type", ""),
            "subtype": info.get("subtype", ""),
            "title": info.get("title", ""),
            "format": steps[0].get("format", ""),
            "n_steps": len(steps),
            "n_timed": len(timed),
            "periods": {p: periods.get(p, 0) for p in PERIODS},
            "steps": [{"step_no": s["step_no"], "poi": s.get("poi", ""),
                       "activity": s.get("activity", ""),
                       "time_raw": s.get("time_raw", ""),
                       "time_norm": s.get("time_norm", ""),
                       "time_source": s["time_source"],
                       "time_period": s.get("time_period", "未知")} for s in steps],
        })
    route_info.sort(key=lambda r: (r["scenic_area"], r["doc_id"], r["route_id"]))

    def agg(items) -> dict:
        steps = [s for r in items for s in r["steps"]]
        return {
            "routes": len(items),
            "steps": len(steps),
            "timed_steps": sum(1 for s in steps if s["time_source"] == "explicit"),
            "periods": dict(Counter(s["time_period"] for s in steps)),
        }

    by_area = {a: agg([r for r in route_info if r["scenic_area"] == a])
               for a in ("长隆", "广州白云山", "武功山")}
    by_type = {t: agg([r for r in route_info if r["doc_type"] == t])
               for t in ("官方路线", "游客游记", "站点攻略")}
    total_steps = [s for r in route_info for s in r["steps"]]

    hierarchy = {
        "source": "analysis/p03_routes/outputs/routes.jsonl",
        "period_rule": PERIOD_RULE,
        "time_norm_rule": TIME_NORM_RULE,
        "frozen": ["同 route_id 内 step_no 从 1 连续递增", "本 period_rule 一旦交付即冻结"],
        "totals": {
            "routes": len(route_info),
            "steps": len(total_steps),
            "timed_steps": sum(1 for s in total_steps if s["time_source"] == "explicit"),
            "by_time_source": dict(Counter(s["time_source"] for s in total_steps)),
            "by_period": dict(Counter(s["time_period"] for s in total_steps)),
            "by_format": dict(Counter(r["format"] for r in route_info)),
        },
        "by_area": by_area,
        "by_doc_type": by_type,
        "routes": route_info,
    }
    (OUTPUTS / "hierarchy.json").write_text(
        json.dumps(hierarchy, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    # ---------------- 官方 vs 游客（附加题） ----------------
    def group(area: str, official: bool) -> list[dict]:
        return [r for r in route_info
                if r["scenic_area"] == area
                and (r["doc_type"] == "官方路线") == official]

    compare_rows = []
    for area in ("长隆", "广州白云山", "武功山", "合计"):
        off = [r for r in route_info if r["doc_type"] == "官方路线" and
               (area == "合计" or r["scenic_area"] == area)]
        usr = [r for r in route_info if r["doc_type"] != "官方路线" and
               (area == "合计" or r["scenic_area"] == area)]
        off_steps = [s for r in off for s in r["steps"]]
        usr_steps = [s for r in usr for s in r["steps"]]
        off_poi = sequence_of(off_steps)
        usr_poi = sequence_of(usr_steps)
        shared = [p for p in off_poi if p in set(usr_poi)]
        pairs = [(off_poi.index(p), usr_poi.index(p)) for p in shared]
        tau = kendall_tau(pairs)
        def dist(steps):
            c = Counter(s["time_period"] for s in steps if s["time_source"] == "explicit")
            n = sum(c.values())
            return {p: round(c.get(p, 0) / n, 3) if n else 0.0 for p in ("上午", "中午", "下午", "晚上")}, n
        off_dist, off_timed = dist(off_steps)
        usr_dist, usr_timed = dist(usr_steps)
        missing = [p for p in off_poi if p not in set(usr_poi)]
        compare_rows.append({
            "scenic_area": area,
            "n_official_routes": len(off),
            "n_user_routes": len(usr),
            "official_poi_n": len(off_poi),
            "user_poi_n": len(usr_poi),
            "shared_poi_n": len(shared),
            "poi_coverage": round(len(shared) / len(off_poi), 3) if off_poi else "",
            "user_poi_overlap": round(len(shared) / len(usr_poi), 3) if usr_poi else "",
            "order_tau": round(tau, 3) if tau is not None else "",
            "official_steps": len(off_steps),
            "user_steps": len(usr_steps),
            "official_steps_per_route": round(len(off_steps) / len(off), 2) if off else "",
            "user_steps_per_route": round(len(usr_steps) / len(usr), 2) if usr else "",
            "official_explicit_time_ratio": round(off_timed / len(off_steps), 3) if off_steps else "",
            "user_explicit_time_ratio": round(usr_timed / len(usr_steps), 3) if usr_steps else "",
            "official_am_noon_pm": "/".join(f"{off_dist[p]:.2f}" for p in ("上午", "中午", "下午")),
            "user_am_noon_pm": "/".join(f"{usr_dist[p]:.2f}" for p in ("上午", "中午", "下午")),
            "official_poi_missing_in_user": ";".join(missing[:10]) + (";…" if len(missing) > 10 else ""),
        })

    FIGURES.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUTS / "compare_official_vs_user.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(compare_rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(compare_rows)

    make_figure(route_info, compare_rows)

    print(f"路线 {len(route_info)} 条 / 步骤 {len(total_steps)} 个；"
          f"有显式时间 {hierarchy['totals']['timed_steps']} 个")
    print("按景区：", {k: (v["routes"], v["steps"]) for k, v in by_area.items()})
    print("按类型：", {k: (v["routes"], v["steps"]) for k, v in by_type.items()})
    for row in compare_rows:
        print(f"  {row['scenic_area']}: 覆盖度={row['poi_coverage']} 顺序tau={row['order_tau']} "
              f"显式时间比={row['official_explicit_time_ratio']}/{row['user_explicit_time_ratio']}")
    return 0


def make_figure(route_info, compare_rows) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        try:
            font_manager.fontManager.addfont(cand)
        except Exception:
            pass
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    areas = ["长隆", "广州白云山", "武功山"]
    colors = {"上午": "#7fb3d5", "中午": "#f5b041", "下午": "#e59866", "晚上": "#5d6d7e", "未知": "#d5d8dc"}

    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    ax = axes[0][0]
    bottom = [0] * len(areas)
    for p in PERIODS:
        vals = [sum(1 for r in route_info if r["scenic_area"] == a for s in r["steps"]
                    if s["time_period"] == p) for a in areas]
        ax.bar(areas, vals, bottom=bottom, label=p, color=colors[p])
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_title("(a) 各景区步骤的时间层级分布")
    ax.set_ylabel("步骤数")
    ax.legend(fontsize=8, ncol=5)

    ax = axes[0][1]
    exp = [sum(1 for r in route_info if r["scenic_area"] == a for s in r["steps"]
               if s["time_source"] == "explicit") for a in areas]
    absn = [sum(1 for r in route_info if r["scenic_area"] == a for s in r["steps"]
                if s["time_source"] == "absent") for a in areas]
    ax.bar(areas, exp, label="explicit（原文有）", color="#5499c7")
    ax.bar(areas, absn, bottom=exp, label="absent（原文没有）", color="#d5d8dc")
    ax.set_title("(b) time_source 分布：多少步骤有真实时间")
    ax.set_ylabel("步骤数")
    ax.legend(fontsize=8)
    ax.set_ylim(0, max(e + a for e, a in zip(exp, absn)) * 1.18)
    for i, (e, a) in enumerate(zip(exp, absn)):
        ax.text(i, e + a + 2, f"{e}/{e+a} = {e/(e+a):.0%}" if e + a else "-", ha="center", fontsize=8)

    ax = axes[1][0]
    off_spr = [r["official_steps_per_route"] for r in compare_rows if r["scenic_area"] != "合计"]
    usr_spr = [r["user_steps_per_route"] for r in compare_rows if r["scenic_area"] != "合计"]
    x = range(len(areas))
    ax.bar([i - 0.2 for i in x], off_spr, width=0.4, label="官方路线", color="#c0392b")
    ax.bar([i + 0.2 for i in x], usr_spr, width=0.4, label="游客游记", color="#2980b9")
    ax.set_xticks(list(x))
    ax.set_xticklabels(areas)
    ax.set_title("(c) 每条路线平均步骤数：官方 vs 游客")
    ax.set_ylabel("步骤数 / 路线")
    ax.legend(fontsize=8)

    ax = axes[1][1]
    off_t = [float(r["official_explicit_time_ratio"] or 0) for r in compare_rows if r["scenic_area"] != "合计"]
    usr_t = [float(r["user_explicit_time_ratio"] or 0) for r in compare_rows if r["scenic_area"] != "合计"]
    ax.bar([i - 0.2 for i in x], off_t, width=0.4, label="官方路线", color="#c0392b")
    ax.bar([i + 0.2 for i in x], usr_t, width=0.4, label="游客游记", color="#2980b9")
    ax.set_xticks(list(x))
    ax.set_xticklabels(areas)
    ax.set_title("(d) 显式时间步骤占比：官方 vs 游客")
    ax.set_ylabel("占比")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)

    fig.tight_layout()
    out = FIGURES / "route_structure.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"写入 {out}")


if __name__ == "__main__":
    sys.exit(main())
