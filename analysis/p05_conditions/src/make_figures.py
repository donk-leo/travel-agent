# -*- coding: utf-8 -*-
"""P5 统计图：条件类型、景区分布、景区×类型、人工抽查。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from lib.paths import analysis_dir  # noqa: E402

ROOT = analysis_dir("p05_conditions")
OUT = ROOT / "outputs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

STATS = json.loads((ROOT / "outputs" / "condition_stats.json").read_text(encoding="utf-8"))
EVAL = json.loads((ROOT / "outputs" / "eval_stats.json").read_text(encoding="utf-8"))

BLUE = (31, 59, 99)
MID = (68, 114, 158)
LIGHT = (219, 229, 241)
ORANGE = (237, 125, 49)
GREEN = (112, 173, 71)
RED = (192, 80, 77)
GRAY = (89, 89, 89)
LGRAY = (242, 242, 242)
WHITE = (255, 255, 255)
TYPE_COLORS = {
    "天气": (91, 155, 213),
    "人群": (237, 125, 49),
    "时间": (112, 173, 71),
    "体力": (255, 192, 0),
    "预算": (165, 105, 189),
    "交通": (68, 114, 158),
    "其他": (150, 150, 150),
}


def font(size: int, bold: bool = False):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)


def text(d, xy, s, size=20, fill=GRAY, bold=False, anchor=None):
    d.text(xy, s, font=font(size, bold), fill=fill, anchor=anchor)


def panel(d, box, title):
    x1, y1, x2, y2 = box
    d.rounded_rectangle((x1, y1, x2, y2), 14, fill=WHITE, outline=(210, 218, 230), width=2)
    text(d, (x1 + 24, y1 + 16), title, 24, BLUE, True)


def hbars(d, box, items, maxv, color_fn, label_size=18, value_size=18):
    x1, y1, x2, y2 = box
    left = x1 + 120
    right = x2 - 70
    top = y1 + 70
    bottom = y2 - 20
    n = max(len(items), 1)
    row_h = (bottom - top) / n
    bar_h = min(row_h * 0.56, 34)
    for i, (label, value) in enumerate(items):
        cy = top + row_h * i + row_h / 2
        text(d, (left - 16, cy), str(label), label_size, GRAY, False, "rm")
        w = (right - left) * value / maxv if maxv else 0
        d.rounded_rectangle((left, cy - bar_h / 2, left + w, cy + bar_h / 2), 6, fill=color_fn(label))
        text(d, (left + w + 10, cy), str(value), value_size, GRAY, False, "lm")


def main() -> int:
    W, H = 1500, 1100
    img = Image.new("RGB", (W, H), (248, 250, 253))
    d = ImageDraw.Draw(img)
    text(d, (W // 2, 26), "项目5 条件-建议抽取统计", 30, BLUE, True, "ma")

    # 1 条件类型
    box = (40, 80, 740, 520)
    panel(d, box, "① 条件类型分布")
    items = sorted(STATS["by_type"].items(), key=lambda kv: -kv[1])
    hbars(d, (box[0] + 10, box[1] + 20, box[2] - 10, box[3] - 10), items, max(v for _, v in items),
          lambda k: TYPE_COLORS.get(k, MID))

    # 2 景区分布
    box = (760, 80, 1460, 520)
    panel(d, box, "② 景区分布")
    items = sorted(STATS["by_area"].items(), key=lambda kv: -kv[1])
    area_color = {"长隆": BLUE, "广州白云山": GREEN, "武功山": ORANGE}
    hbars(d, (box[0] + 10, box[1] + 20, box[2] - 10, box[3] - 10), items, max(v for _, v in items),
          lambda k: area_color.get(k, MID))

    # 3 景区×类型堆叠
    box = (40, 560, 740, 1050)
    panel(d, box, "③ 景区×条件类型")
    areas = ["长隆", "广州白云山", "武功山"]
    types = [t for t in ("天气", "人群", "时间", "体力", "预算", "交通", "其他")
             if STATS["by_area_type"].get(areas[0], {}).get(t, 0)
             or STATS["by_area_type"].get(areas[1], {}).get(t, 0)
             or STATS["by_area_type"].get(areas[2], {}).get(t, 0)]
    left, right, top, bottom = box[0] + 90, box[2] - 40, box[1] + 80, box[3] - 80
    maxv = max(sum(STATS["by_area_type"].get(a, {}).get(t, 0) for t in types) for a in areas)
    bar_w = (right - left) / len(areas) * 0.42
    gap = (right - left) / len(areas)
    for i, area in enumerate(areas):
        cx = left + gap * i + gap / 2
        y = bottom
        for t in types:
            v = STATS["by_area_type"].get(area, {}).get(t, 0)
            if not v:
                continue
            h = (bottom - top) * v / maxv if maxv else 0
            d.rectangle((cx - bar_w / 2, y - h, cx + bar_w / 2, y), fill=TYPE_COLORS.get(t, MID))
            y -= h
        text(d, (cx, bottom + 12), area, 18, GRAY, False, "ma")
        text(d, (cx, y - 10), str(sum(STATS["by_area_type"].get(area, {}).values())), 18, BLUE, True, "ma")
    # legend
    lx, ly = box[0] + 24, box[3] - 38
    for t in types:
        d.rectangle((lx, ly, lx + 16, ly + 16), fill=TYPE_COLORS.get(t, MID))
        text(d, (lx + 22, ly - 2), t, 15, GRAY)
        lx += 74

    # 4 抽查结果
    box = (760, 560, 1460, 1050)
    panel(d, box, "④ 20 条人工抽查")
    labels = [("正确", EVAL["correct"], GREEN), ("部分正确", EVAL["partial"], ORANGE), ("错误", EVAL["wrong"], RED)]
    maxv = max(v for _, v, _ in labels) or 1
    left, right, top, bottom = box[0] + 120, box[2] - 70, box[1] + 80, box[1] + 290
    row_h = (bottom - top) / 3
    for i, (label, value, color) in enumerate(labels):
        cy = top + row_h * i + row_h / 2
        text(d, (left - 18, cy), label, 20, GRAY, False, "rm")
        w = (right - left) * value / maxv
        d.rounded_rectangle((left, cy - 20, left + w, cy + 20), 6, fill=color)
        text(d, (left + w + 12, cy), str(value), 20, GRAY, False, "lm")
    # 指标卡
    strict = EVAL["strict_accuracy"] * 100
    lenient = EVAL["lenient_accuracy"] * 100
    cards = [
        ("严格准确率", f"{strict:.0f}%", BLUE),
        ("宽松可用率", f"{lenient:.0f}%", GREEN),
        ("文档覆盖率", f"{STATS['coverage'] * 100:.0f}%", ORANGE),
    ]
    cw = (box[2] - box[0] - 80) / 3
    for i, (k, v, color) in enumerate(cards):
        x = box[0] + 30 + i * (cw + 10)
        y = box[1] + 340
        d.rounded_rectangle((x, y, x + cw, y + 110), 10, fill=LGRAY, outline=(220, 226, 236))
        text(d, (x + cw / 2, y + 24), k, 17, GRAY, False, "ma")
        text(d, (x + cw / 2, y + 62), v, 30, color, True, "ma")
    text(d, (box[0] + 30, box[3] - 66), f"共 {STATS['total']} 条，去重后 {STATS['unique']} 条；"
         f"{STATS['docs_with_conditions']}/{STATS['docs_valid']} 篇文档有结果", 17, (110, 110, 110))
    text(d, (box[0] + 30, box[3] - 38), "抽查为三景区分层抽样，判定口径见报告 5.2 节", 16, (140, 140, 140))

    path = OUT / "condition_stats.png"
    img.save(path)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())