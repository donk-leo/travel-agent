# -*- coding: utf-8 -*-
"""用 PIL 生成报告插图（流程图、字数对比、来源分布），无需 matplotlib。

输出：report/figures/*.png
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FIG_DIR = ROOT / "report" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"

BLUE = (31, 78, 121)
LIGHT_BLUE = (222, 235, 247)
ORANGE = (237, 125, 49)
GRAY = (90, 90, 90)
BG = (255, 255, 255)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def center_text(draw, box, text, fnt, fill=GRAY):
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    heights = [draw.textbbox((0, 0), ln, font=fnt)[3] for ln in lines]
    total = sum(heights) + (len(lines) - 1) * 6
    y = y0 + (y1 - y0 - total) / 2
    for ln, h in zip(lines, heights):
        w = draw.textbbox((0, 0), ln, font=fnt)[2]
        draw.text((x0 + (x1 - x0 - w) / 2, y), ln, font=fnt, fill=fill)
        y += h + 6


def arrow(draw, x0, y0, x1, y1, color=BLUE, width=4):
    draw.line((x0, y0, x1, y1), fill=color, width=width)
    # 箭头
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    size = 14
    for delta in (2.6, -2.6):
        draw.line(
            (x1, y1, x1 + size * math.cos(ang + delta), y1 + size * math.sin(ang + delta)),
            fill=color, width=width,
        )


def flow_figure():
    W, H = 1800, 520
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    boxes = [
        ("① 原始页面采集\n14 个 URL / 14 份 HTML", "保存快照与 SHA256"),
        ("② 正文抽取\n站点规则 + 文本密度兜底", "剔除导航/脚本/评论"),
        ("③ 行级清洗\n噪声行、URL、emoji、乱码", "R1–R4"),
        ("④ 规范化\n空白、标点、字符宽度", "R5–R6"),
        ("⑤ 段落去重\n完全重复 + 相似度≥0.90", "R7"),
        ("⑥ 质量检查\n数量/缺失/重复/长度", "有效 13 / 14"),
        ("⑦ 结构化输出\nCSV · JSONL · Excel", "UTF-8-SIG / 多工作表"),
        ("⑧ 下游衔接\n项目2 实体识别 · 项目3 路线", "clean_content"),
    ]
    bw, bh = 380, 150
    xs = [70, 500, 930, 1360]
    rows = [(70, 220), (320, 470)]
    for row, (y0, y1) in enumerate(rows):
        for col in range(4):
            i = row * 4 + col
            x0 = xs[col]
            d.rounded_rectangle((x0, y0, x0 + bw, y1), radius=14, fill=LIGHT_BLUE, outline=BLUE, width=2)
            center_text(d, (x0 + 10, y0 + 10, x0 + bw - 10, y1 - 34), boxes[i][0], font(24, True), BLUE)
            center_text(d, (x0 + 10, y1 - 36, x0 + bw - 10, y1 - 8), boxes[i][1], font(20), GRAY)
            if col < 3:
                arrow(d, x0 + bw + 4, (y0 + y1) // 2, xs[col + 1] - 6, (y0 + y1) // 2)
        if row == 0:
            # 第一行末尾向下、再向左折回第二行开头，形成“蛇形”阅读顺序
            x_end = xs[3] + bw // 2
            x_start = xs[0] + bw // 2
            d.line((x_end, 220, x_end, 270), fill=BLUE, width=4)
            d.line((x_end, 270, x_start, 270), fill=BLUE, width=4)
            arrow(d, x_start, 270, x_start, 318)
        else:
            for col in range(3):
                arrow(d, xs[col] + bw + 4, 395, xs[col + 1] - 6, 395)
    img.save(FIG_DIR / "fig1_flow.png")
    return FIG_DIR / "fig1_flow.png"


def bar_figure(df: pd.DataFrame):
    df = df.sort_values("char_raw", ascending=True)
    W, H = 1700, 900
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    left, right, top, bottom = 440, 1520, 55, 820
    max_v = 3800
    n = len(df)
    step = (bottom - top) / n
    bar_h = step * 0.32
    for i in range(0, max_v + 1, 500):
        x = left + (right - left) * i / max_v
        d.line((x, top, x, bottom), fill=(225, 225, 225), width=1)
        d.text((x - 18, bottom + 12), str(i), font=font(20), fill=GRAY)

    for i, (_, r) in enumerate(df.iterrows()):
        cy = top + step * i + step / 2
        title = r.title if len(r.title) <= 15 else r.title[:15] + "…"
        label = f"{r.doc_id} {title}"
        d.text((28, cy - 22), label, font=font(19), fill=GRAY)
        w1 = (right - left) * r.char_raw / max_v
        w2 = (right - left) * r.char_clean / max_v
        d.rounded_rectangle((left, cy - bar_h - 2, left + w1, cy - 2), radius=4, fill=(189, 215, 238))
        d.rounded_rectangle((left, cy + 2, left + w2, cy + bar_h + 2), radius=4, fill=BLUE)
        d.text((left + w1 + 8, cy - bar_h - 4), str(int(r.char_raw)), font=font(18), fill=GRAY)
        d.text((left + w2 + 8, cy + 2), str(int(r.char_clean)), font=font(18), fill=BLUE)

    d.rectangle((1140, 12, 1165, 32), fill=(189, 215, 238))
    d.text((1173, 8), "原始字数", font=font(22), fill=GRAY)
    d.rectangle((1310, 12, 1335, 32), fill=BLUE)
    d.text((1343, 8), "清洗后", font=font(22), fill=GRAY)
    img.save(FIG_DIR / "fig2_lengths.png")
    return FIG_DIR / "fig2_lengths.png"


def source_figure(df: pd.DataFrame, stats: dict):
    W, H = 1700, 640
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    sites = stats["sites"]
    max_c = max(c for _, c in sites)
    left, top, bar_h = 380, 70, 52
    for i, (site, cnt) in enumerate(sites):
        y = top + i * 80
        d.text((70, y + 8), site, font=font(24), fill=GRAY)
        w = 620 * cnt / max_c
        d.rounded_rectangle((left, y, left + w, y + bar_h), radius=6, fill=BLUE)
        d.text((left + w + 12, y + 8), f"{cnt} 条", font=font(24, True), fill=BLUE)

    # 右侧饼图：类型占比
    cx, cy, r = 1330, 380, 190
    types = stats["types"]
    total = sum(c for _, c in types)
    start = -90
    colors = [BLUE, ORANGE]
    for (name, cnt), color in zip(types, colors):
        extent = 360 * cnt / total
        d.pieslice((cx - r, cy - r, cx + r, cy + r), start=start, end=start + extent,
                   fill=color, outline=BG, width=3)
        mid = start + extent / 2
        import math
        lx = cx + (r + 30) * math.cos(math.radians(mid))
        ly = cy + (r + 30) * math.sin(math.radians(mid))
        d.text((lx - 40, ly - 14), f"{name}\n{cnt} 条", font=font(22, True), fill=color,
               align="center")
        start += extent
    d.ellipse((cx - 70, cy - 70, cx + 70, cy + 70), fill=BG)
    d.text((cx - 48, cy - 18), f"共 {total} 条", font=font(24, True), fill=GRAY)

    img.save(FIG_DIR / "fig3_sources.png")
    return FIG_DIR / "fig3_sources.png"


def main():
    df = pd.read_csv(ROOT / "data" / "processed" / "wugongshan_guides.csv",
                     encoding="utf-8-sig", keep_default_na=False)
    stats = json.loads((ROOT / "outputs" / "统计摘要.json").read_text(encoding="utf-8"))
    flow_figure()
    bar_figure(df)
    source_figure(df, stats)
    print("figures ->", FIG_DIR)


if __name__ == "__main__":
    main()
