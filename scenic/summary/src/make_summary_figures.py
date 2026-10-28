# -*- coding: utf-8 -*-
"""生成小组汇总报告的插图（PIL，不依赖 matplotlib）。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
GROUP = ROOT / "scenic" / "summary"
OUT = GROUP / "report" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"
BLUE = (31, 78, 121)
LIGHT = (222, 235, 247)
ORANGE = (237, 125, 49)
GREEN = (84, 130, 53)
GRAY = (90, 90, 90)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def center(draw, box, text, fnt, fill=GRAY):
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    hs = [draw.textbbox((0, 0), ln, font=fnt)[3] for ln in lines]
    total = sum(hs) + (len(lines) - 1) * 6
    y = y0 + (y1 - y0 - total) / 2
    for ln, h in zip(lines, hs):
        w = draw.textbbox((0, 0), ln, font=fnt)[2]
        draw.text((x0 + (x1 - x0 - w) / 2, y), ln, font=fnt, fill=fill)
        y += h + 6


def arrow(draw, x0, y0, x1, y1):
    import math
    draw.line((x0, y0, x1, y1), fill=BLUE, width=3)
    ang = math.atan2(y1 - y0, x1 - x0)
    for d in (2.6, -2.6):
        draw.line((x1, y1, x1 + 12 * math.cos(ang + d), y1 + 12 * math.sin(ang + d)),
                  fill=BLUE, width=3)


def flow():
    W, H = 1600, 560
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    boxes = [
        ("① 原始材料", "组员 CSV（3 景区）\n+ 官网补采 HTML"),
        ("② 字段映射", "统一 24 列\ndoc_id / doc_type"),
        ("③ 正文清洗", "R1–R8 + 平台噪声\n去重 / 规范化"),
        ("④ 三景区标准表", "changlong / baiyunshan\n/ wugongshan"),
        ("⑤ 合并与质检", "38 → 37 条\n去空 / 去重 / 统计"),
        ("⑥ 交付", "CSV / Excel\n质量报告 / 实验报告"),
    ]
    bw, bh = 430, 145
    xs = [45, 585, 1125]
    rows = [(60, 60 + bh), (350, 350 + bh)]
    for r, (y0, y1) in enumerate(rows):
        for c in range(3):
            i = r * 3 + c
            x0 = xs[c]
            d.rounded_rectangle((x0, y0, x0 + bw, y1), radius=14,
                                fill=LIGHT, outline=BLUE, width=2)
            center(d, (x0 + 10, y0 + 10, x0 + bw - 10, y0 + 55), boxes[i][0],
                   font(30, True), BLUE)
            center(d, (x0 + 10, y0 + 58, x0 + bw - 10, y1 - 8), boxes[i][1],
                   font(21), GRAY)
            if c < 2:
                arrow(d, x0 + bw + 4, (y0 + y1) // 2, xs[c + 1] - 6, (y0 + y1) // 2)
        if r == 0:
            x_end = xs[2] + bw // 2
            x_start = xs[0] + bw // 2
            d.line((x_end, y1, x_end, 285), fill=BLUE, width=3)
            d.line((x_end, 285, x_start, 285), fill=BLUE, width=3)
            arrow(d, x_start, 285, x_start, 345)
    img.save(OUT / "group_flow.png")


def stacked():
    df = pd.read_csv(GROUP / "data" / "三景区汇总数据集.csv",
                     encoding="utf-8-sig", keep_default_na=False)
    order = ["长隆", "广州白云山", "武功山"]
    types = ["官方路线", "游客游记", "站点攻略"]
    colors = [BLUE, ORANGE, GREEN]
    counts = {a: {t: int(((df.scenic_area == a) & (df.doc_type == t)).sum()) for t in types}
              for a in order}
    W, H = 1500, 720
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    left, top, width, height = 260, 70, 1000, 520
    maxv = max(sum(c.values()) for c in counts.values()) + 2
    step = width / len(order)
    for i, a in enumerate(order):
        x = left + i * step + step * 0.2
        barw = step * 0.45
        y = top + height
        for t, col in zip(types, colors):
            v = counts[a][t]
            h = height * v / maxv
            d.rectangle((x, y - h, x + barw, y), fill=col)
            if v:
                d.text((x + barw + 10, y - h + 6), str(v), font=font(22, True), fill=col)
            y -= h
        d.text((left + i * step + step * 0.15, top + height + 18), a,
               font=font(24, True), fill=GRAY)
    # legend
    lx, ly = 1150, 50
    for t, col in zip(types, colors):
        d.rectangle((lx, ly, lx + 28, ly + 20), fill=col)
        d.text((lx + 38, ly - 4), t, font=font(22), fill=GRAY)
        ly += 38
    d.line((left, top + height, left + width, top + height), fill=GRAY, width=2)
    img.save(OUT / "group_area_type.png")


def chars():
    df = pd.read_csv(GROUP / "data" / "三景区汇总数据集.csv",
                     encoding="utf-8-sig", keep_default_na=False)
    g = df.groupby("scenic_area")[["char_raw", "char_clean"]].sum()
    order = ["长隆", "广州白云山", "武功山"]
    W, H = 1400, 660
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    left, top, width, height = 240, 70, 1000, 480
    maxv = int(g[["char_raw", "char_clean"]].values.max()) + 2000
    step = width / len(order)
    for i, a in enumerate(order):
        x = left + i * step + step * 0.15
        for j, (colname, col) in enumerate([("char_raw", (189, 215, 238)),
                                            ("char_clean", BLUE)]):
            v = int(g.loc[a, colname])
            h = height * v / maxv
            bx = x + j * step * 0.22
            d.rectangle((bx, top + height - h, bx + step * 0.18, top + height - h + 0), fill=col)
            # 用竖条从底向上画
            d.rectangle((bx, top + height - h, bx + step * 0.18, top + height), fill=col)
            d.text((bx - 4, top + height - h - 30), str(v), font=font(18), fill=GRAY)
        d.text((left + i * step + step * 0.18, top + height + 16), a,
               font=font(24, True), fill=GRAY)
    d.rectangle((1080, 70, 1108, 92), fill=(189, 215, 238))
    d.text((1118, 66), "原始", font=font(20), fill=GRAY)
    d.rectangle((1190, 70, 1218, 92), fill=BLUE)
    d.text((1228, 66), "清洗后", font=font(20), fill=GRAY)
    d.line((left, top + height, left + width, top + height), fill=GRAY, width=2)
    img.save(OUT / "group_chars.png")


if __name__ == "__main__":
    flow()
    stacked()
    chars()
    print("figures ->", OUT)
