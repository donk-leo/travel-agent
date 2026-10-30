# -*- coding: utf-8 -*-
"""生成 P4 报告插图（Pillow，无额外依赖）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from lib.paths import analysis_dir  # noqa: E402

ROOT = analysis_dir("p04_coref")
OUT = ROOT / "report" / "figures"
STATS = json.loads((ROOT / "outputs" / "coref_stats.json").read_text(encoding="utf-8"))
EVAL = json.loads((ROOT / "outputs" / "eval_stats.json").read_text(encoding="utf-8"))

BLUE = (31, 78, 121)
MID = (68, 114, 158)
LIGHT = (219, 229, 241)
ORANGE = (237, 125, 49)
GREEN = (112, 173, 71)
GRAY = (89, 89, 89)
LGRAY = (242, 242, 242)
WHITE = (255, 255, 255)


def font(size: int, bold: bool = False):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)


def text(d, xy, s, size=22, fill=GRAY, bold=False, anchor=None):
    d.text(xy, s, font=font(size, bold), fill=fill, anchor=anchor)


def arrow(d, x1, y1, x2, y2, color=BLUE, width=4):
    d.line((x1, y1, x2, y2), fill=color, width=width)
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    L = 14
    for a in (ang + 2.6, ang - 2.6):
        d.line((x2, y2, x2 + L * math.cos(a), y2 + L * math.sin(a)), fill=color, width=width)


def fig_pipeline():
    W, H = 1400, 690
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    boxes = [
        ("① 代词检测", "15 个代词 / 140 条候选", "正则 + 最长优先，保留绝对位置"),
        ("② 候选筛选", "同句 / 前句 + 类型白名单", "POI、时间、交通分别允许的代词类"),
        ("③ 最近实体规则", "距离 ≤ 100 字，阈值 0.60", "P2 实体 + P3 路线 POI 补充"),
        ("④ 结果分流", "28 条消解 / 112 条留空", "留空写 needs_review + reason"),
        ("⑤ 人工评估", "20 条标注 / 16 条有先行词", "准确率、覆盖率、精确率/召回率"),
    ]
    bw, bh = 400, 180
    row1 = [40, 500, 960]
    row2 = [270, 830]
    y1, y2 = 120, 420
    for i in range(3):
        x = row1[i]
        title, l1, l2 = boxes[i]
        d.rounded_rectangle((x, y1, x + bw, y1 + bh), 16, fill=LIGHT, outline=BLUE, width=3)
        text(d, (x + bw // 2, y1 + 34), title, 30, BLUE, True, "ma")
        text(d, (x + bw // 2, y1 + 92), l1, 22, GRAY, False, "ma")
        text(d, (x + bw // 2, y1 + 136), l2, 18, (110, 110, 110), False, "ma")
    for i in range(3, 5):
        x = row2[i - 3]
        title, l1, l2 = boxes[i]
        d.rounded_rectangle((x, y2, x + bw, y2 + bh), 16, fill=LIGHT, outline=BLUE, width=3)
        text(d, (x + bw // 2, y2 + 34), title, 30, BLUE, True, "ma")
        text(d, (x + bw // 2, y2 + 92), l1, 22, GRAY, False, "ma")
        text(d, (x + bw // 2, y2 + 136), l2, 18, (110, 110, 110), False, "ma")
    arrow(d, row1[0] + bw + 6, y1 + bh // 2, row1[1] - 8, y1 + bh // 2)
    arrow(d, row1[1] + bw + 6, y1 + bh // 2, row1[2] - 8, y1 + bh // 2)
    # ③ 底部折回 ④（第二行左侧）
    x3 = row1[2] + bw // 2
    x4 = row2[0] + bw // 2
    d.line((x3, y1 + bh, x3, y1 + bh + 40), fill=BLUE, width=4)
    d.line((x3, y1 + bh + 40, x4, y1 + bh + 40), fill=BLUE, width=4)
    arrow(d, x4, y1 + bh + 40, x4, y2 - 4)
    arrow(d, row2[0] + bw + 6, y2 + bh // 2, row2[1] - 8, y2 + bh // 2)
    text(d, (W // 2, 55), "代词检测 → 候选筛选 → 最近实体 → 分流 → 人工评估", 30, BLUE, True, "ma")
    img.save(OUT / "fig1_pipeline.png")

    # 图2：代词分布（堆叠）
    items = sorted(STATS["by_pronoun"].items(), key=lambda kv: -kv[1]["total"])
    W, H = 1500, 900
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    left, right, top, bottom = 250, 1330, 80, 820
    maxv = max(v["total"] for _, v in items)
    row_h = (bottom - top) / len(items)
    bar_h = row_h * 0.52
    for i, (p, v) in enumerate(items):
        cy = top + row_h * i + row_h / 2
        text(d, (left - 20, cy), p, 21, GRAY, False, "rm")
        total = v["total"]
        res = v["resolved"]
        w_total = (right - left) * total / maxv
        w_res = (right - left) * res / maxv
        d.rectangle((left, cy - bar_h / 2, left + w_total, cy + bar_h / 2), fill=LIGHT)
        if res:
            d.rectangle((left, cy - bar_h / 2, left + w_res, cy + bar_h / 2), fill=BLUE)
        text(d, (left + w_total + 10, cy), f"{total}", 18, GRAY, False, "lm")
        if res:
            text(d, (left + w_res + 8, cy + 2), f"{res}", 16, WHITE, True, "lm")
    # 图例
    lx, ly = 1080, 30
    d.rectangle((lx, ly, lx + 22, ly + 22), fill=LIGHT)
    text(d, (lx + 30, ly + 2), "候选", 19, GRAY)
    d.rectangle((lx + 130, ly, lx + 152, ly + 22), fill=BLUE)
    text(d, (lx + 160, ly + 2), "已消解", 19, GRAY)
    text(d, (left, 30), "各代词候选数与消解数", 26, BLUE, True)
    img.save(OUT / "fig2_pronoun_distribution.png")

    # 图3：三景区消解率（横向条形，避免小数值标签重叠）
    areas = [("长隆", "changlong"), ("白云山", "baiyunshan"), ("武功山", "wugongshan")]
    W, H = 1300, 520
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    left, right, top, bottom = 230, 1080, 100, 430
    maxv = max(STATS["by_area"][k]["total"] for _, k in areas)
    row_h = (bottom - top) / len(areas)
    bar_h = row_h * 0.48
    for i, (label, key) in enumerate(areas):
        v = STATS["by_area"][key]
        cy = top + row_h * i + row_h / 2
        w_total = (right - left) * v["total"] / maxv
        w_res = (right - left) * v["resolved"] / maxv
        text(d, (left - 20, cy), label, 24, GRAY, False, "rm")
        d.rectangle((left, cy - bar_h / 2, left + w_total, cy + bar_h / 2), fill=LIGHT)
        if v["resolved"]:
            d.rectangle((left, cy - bar_h / 2, left + w_res, cy + bar_h / 2), fill=BLUE)
        text(d, (left + w_total + 14, cy), f"{v['resolved']}/{v['total']}", 21, GRAY, False, "lm")
        text(d, (left + w_total + 150, cy), f"{v['rate']:.1%}", 21, ORANGE, True, "lm")
    lx, ly = 230, 30
    d.rectangle((lx, ly, lx + 22, ly + 22), fill=LIGHT)
    text(d, (lx + 30, ly + 1), "候选数", 19, GRAY)
    d.rectangle((lx + 150, ly, lx + 172, ly + 22), fill=BLUE)
    text(d, (lx + 180, ly + 1), "已消解", 19, GRAY)
    text(d, (lx + 320, ly + 1), "右侧：已消解/候选、消解率", 19, GRAY)
    img.save(OUT / "fig3_area_resolution.png")

    # 图4：评估指标
    metrics = [("准确率", EVAL["accuracy"]), ("精确率", EVAL["precision"]),
               ("召回率", EVAL["recall"]), ("标注覆盖率", EVAL["coverage_on_annotations"])]
    W, H = 1200, 700
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    left, right, top, bottom = 110, 1120, 90, 590
    bw, gap = 150, 120
    for i, (label, val) in enumerate(metrics):
        cx = left + 90 + i * (bw + gap)
        h = (bottom - top) * val
        color = BLUE if i < 3 else GREEN
        d.rectangle((cx - bw / 2, bottom - h, cx + bw / 2, bottom), fill=color)
        text(d, (cx, bottom - h - 34), f"{val:.0%}", 24, color, True, "ma")
        text(d, (cx, bottom + 20), label, 21, GRAY, False, "ma")
    text(d, (90, 30), "20 条人工标注上的评估指标", 26, BLUE, True)
    img.save(OUT / "fig4_metrics.png")

    print("figures ->", OUT)


if __name__ == "__main__":
    fig_pipeline()
