#!/usr/bin/env python3
"""生成项目 2 的实体词频图与词典优化前后对比图。

输入：
    outputs/entities.jsonl

输出：
    outputs/entity_frequency_poi.png
    outputs/entity_frequency_transport.png
    outputs/entity_frequency_time.png
    outputs/entity_count_before_after.png
    outputs/entity_frequency_summary.json

依赖：Pillow（本机已有，无需 Excel 或 Matplotlib）
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[3]
OUTPUTS = ROOT / "analysis" / "p02_entities" / "outputs"
ENTITIES_PATH = OUTPUTS / "entities.jsonl"

# 该数据来自本次词典优化前、已通过 check_entities.py 的第一次运行结果。
BEFORE_COUNTS = {"TIME": 248, "POI": 532, "TRANSPORT": 185}
TYPE_LABELS = {"POI": "景点 POI", "TRANSPORT": "交通方式", "TIME": "时间节点"}
TYPE_COLORS = {"POI": "#2F7D57", "TRANSPORT": "#2D6AA0", "TIME": "#B57924"}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """优先使用 macOS 自带中文字体；找不到时让 Pillow 报出可读错误。"""
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    )
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size, index=1 if bold else 0)
    raise RuntimeError("未找到可用中文字体；请安装中文 TrueType/OpenType 字体后重试。")


def load_entities() -> list[dict]:
    return [
        json.loads(line)
        for line in ENTITIES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def draw_frequency_chart(entity_type: str, frequencies: Counter[str], destination: Path) -> None:
    """绘制某一类型前 12 个实体的横向词频柱状图。"""
    items = frequencies.most_common(12)
    width, height = 1500, 260 + max(len(items), 1) * 78
    margin_left, margin_right, top, bottom = 310, 150, 160, 100
    chart_width = width - margin_left - margin_right
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title_font, label_font, value_font, note_font = font(40, True), font(30), font(28, True), font(24)

    title = f"{TYPE_LABELS[entity_type]}实体词频（优化后 Top {len(items)}）"
    draw.text((70, 45), title, fill="#1F2933", font=title_font)
    draw.text((70, 105), "统计单位：实体出现次数；同一实体在不同文本中重复出现会累计。", fill="#59636E", font=note_font)

    max_count = max(frequencies.values(), default=1)
    for index, (term, count) in enumerate(items):
        y = top + index * 78
        label_box = draw.textbbox((0, 0), term, font=label_font)
        draw.text((margin_left - 28 - (label_box[2] - label_box[0]), y + 8), term, fill="#1F2933", font=label_font)
        bar_width = max(2, int(chart_width * count / max_count))
        draw.rounded_rectangle((margin_left, y + 8, margin_left + bar_width, y + 47), radius=8, fill=TYPE_COLORS[entity_type])
        draw.text((margin_left + bar_width + 18, y + 8), str(count), fill="#1F2933", font=value_font)

    draw.line((margin_left, height - bottom + 8, width - margin_right, height - bottom + 8), fill="#B8C0C8", width=2)
    draw.text((margin_left, height - bottom + 30), "词频", fill="#59636E", font=note_font)
    image.save(destination)


def draw_before_after(after_counts: Counter[str], destination: Path) -> None:
    """绘制词典优化前后的三类实体总数对比。"""
    types = ("POI", "TRANSPORT", "TIME")
    width, height = 1500, 740
    margin_left, margin_right, top, bottom = 150, 120, 160, 140
    baseline_y = height - bottom
    chart_height = baseline_y - top
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title_font, label_font, value_font, note_font = font(40, True), font(29), font(27, True), font(24)

    draw.text((70, 45), "自定义词典优化前后：实体数量对比", fill="#1F2933", font=title_font)
    draw.text((70, 105), "本次补充 5 个武功山 POI 与 2 条地铁线路；优化前后均处理同一批 29 篇文本。", fill="#59636E", font=note_font)
    draw.line((margin_left, baseline_y, width - margin_right, baseline_y), fill="#9099A1", width=2)

    max_count = max(max(BEFORE_COUNTS.values()), max(after_counts.values()))
    group_width = 350
    start_x = 230
    for index, entity_type in enumerate(types):
        group_x = start_x + index * group_width
        before, after = BEFORE_COUNTS[entity_type], after_counts[entity_type]
        before_height = int(chart_height * before / max_count)
        after_height = int(chart_height * after / max_count)
        draw.rectangle((group_x, baseline_y - before_height, group_x + 82, baseline_y), fill="#A8B2BA")
        draw.rectangle((group_x + 110, baseline_y - after_height, group_x + 192, baseline_y), fill=TYPE_COLORS[entity_type])
        draw.text((group_x + 10, baseline_y - before_height - 45), str(before), fill="#1F2933", font=value_font)
        draw.text((group_x + 120, baseline_y - after_height - 45), str(after), fill="#1F2933", font=value_font)
        group_label = TYPE_LABELS[entity_type]
        label_box = draw.textbbox((0, 0), group_label, font=label_font)
        draw.text((group_x + 96 - (label_box[2] - label_box[0]) / 2, baseline_y + 25), group_label, fill="#1F2933", font=label_font)
        delta = after - before
        draw.text((group_x, baseline_y + 70), f"变化：{delta:+d}", fill="#59636E", font=note_font)

    legend_y = height - 55
    draw.rectangle((width - 450, legend_y, width - 424, legend_y + 26), fill="#A8B2BA")
    draw.text((width - 415, legend_y - 3), "优化前", fill="#59636E", font=note_font)
    draw.rectangle((width - 270, legend_y, width - 244, legend_y + 26), fill="#2F7D57")
    draw.text((width - 235, legend_y - 3), "优化后", fill="#59636E", font=note_font)
    image.save(destination)


def main() -> None:
    entities = load_entities()
    by_type = {entity_type: Counter() for entity_type in TYPE_LABELS}
    for entity in entities:
        by_type[entity["entity_type"]][entity["normalized_name"]] += 1

    for entity_type, frequencies in by_type.items():
        draw_frequency_chart(entity_type, frequencies, OUTPUTS / f"entity_frequency_{entity_type.lower()}.png")

    after_counts = Counter(entity["entity_type"] for entity in entities)
    draw_before_after(after_counts, OUTPUTS / "entity_count_before_after.png")
    summary = {
        "documents_processed": 29,
        "before_lexicon_optimization": BEFORE_COUNTS,
        "after_lexicon_optimization": dict(after_counts),
        "delta": {entity_type: after_counts[entity_type] - BEFORE_COUNTS[entity_type] for entity_type in BEFORE_COUNTS},
        "top_entities_by_type": {
            entity_type: [{"entity": term, "frequency": count} for term, count in frequencies.most_common(12)]
            for entity_type, frequencies in by_type.items()
        },
    }
    (OUTPUTS / "entity_frequency_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[完成] 已生成 4 张 PNG 图表与 entity_frequency_summary.json")


if __name__ == "__main__":
    main()
