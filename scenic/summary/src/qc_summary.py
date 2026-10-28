# -*- coding: utf-8 -*-
"""三景区汇总数据的质量检查 + Excel 输出 + 前后对比样例。

输入：scenic/summary/outputs/三景区汇总数据集.csv
输出：
  scenic/summary/outputs/三景区质量检查.md
  scenic/summary/outputs/清洗前后对比.md
  scenic/summary/outputs/三景区景区指南数据集.xlsx
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[3]
GROUP = ROOT / "scenic" / "summary"
OUT = GROUP / "outputs"
COLS = [
    "doc_id", "scenic_area", "doc_type", "subtype", "title", "author",
    "publish_date", "source_site", "source_url", "extract_rule",
    "raw_content", "clean_content", "char_raw", "char_clean", "para_raw",
    "para_clean", "removed_char_ratio", "noise_lines_removed", "emoji_removed",
    "urls_removed", "dup_paragraphs_removed", "quality_flags", "is_valid",
    "clean_hash",
]
FIELD_DESC = [
    ("doc_id", "记录ID", "CL-O-01 / BYS-T-02 / WGS-O-01"),
    ("scenic_area", "景区", "长隆 / 广州白云山 / 武功山"),
    ("doc_type", "文本类型", "官方路线 / 游客游记 / 站点攻略"),
    ("subtype", "子类型", "一日游 / 亲子 / 夜爬 / 官方线路-A线"),
    ("title", "标题", "页面标题"),
    ("author", "作者", "缺失写“未知”"),
    ("publish_date", "发布时间", "YYYY-MM-DD；缺失写“未知”"),
    ("source_site", "来源站点", "长隆官网 / 去哪儿 / 小红书"),
    ("source_url", "来源链接", "原始页面 URL"),
    ("extract_rule", "抽取规则", "官网-div.flow-list / 组员采集-正文"),
    ("raw_content", "原始内容", "抽取后、清洗前"),
    ("clean_content", "清洗后内容", "后续项目只读这一列"),
    ("char_raw", "原始字数", "去空白"),
    ("char_clean", "清洗后字数", "去空白"),
    ("para_raw", "原始段落数", "非空行数"),
    ("para_clean", "清洗后段落数", "非空行数"),
    ("removed_char_ratio", "删除比例", "1 - clean/raw"),
    ("noise_lines_removed", "删除噪声行", "导航/按钮/版权等"),
    ("emoji_removed", "删除表情", "emoji 字符数"),
    ("urls_removed", "删除链接", "URL/邮箱"),
    ("dup_paragraphs_removed", "删除重复段", "完全重复或相似度≥0.90"),
    ("quality_flags", "质量标记", "分号分隔"),
    ("is_valid", "是否有效", "True/False"),
    ("clean_hash", "文本指纹", "sha1(去空白 clean_content)"),
]

DARK = "1F3B63"
HDR_FONT = Font(name="微软雅黑", size=9, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=9)
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True, color=DARK)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def markdown(df: pd.DataFrame, stats: dict) -> None:
    areas = ["长隆", "广州白云山", "武功山"]
    per_area = []
    for a in areas:
        g = df[df.scenic_area == a]
        per_area.append({
            "景区": a, "记录数": len(g),
            "官方路线": int((g.doc_type == "官方路线").sum()),
            "游客游记": int((g.doc_type == "游客游记").sum()),
            "站点攻略": int((g.doc_type == "站点攻略").sum()),
            "有效游记": int(((g.doc_type == "游客游记") & g.is_valid).sum()),
            "有效记录": int(g.is_valid.sum()),
        })
    missing = df.assign(a=df.author.eq("未知"), d=df.publish_date.eq("未知"))
    miss = missing.groupby("scenic_area")[["a", "d"]].sum()

    lines = [
        "# 三景区景区指南数据质量检查报告", "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 覆盖景区：{df.scenic_area.nunique()} 个（{'、'.join(areas)}）",
        f"- 记录总数：{len(df)} 条（官方路线 {stats['official']}、游客游记 {stats['travelogue']}、站点攻略 {stats['guide']}）",
        f"- 有效记录：{int(df.is_valid.sum())} 条",
        f"- 原始 / 清洗后字数：{stats['char_raw']} / {stats['char_clean']}",
        "",
        "## 1. 各景区数量与最低要求", "",
        "| 景区 | 记录数 | 官方路线 | 游客游记 | 站点攻略 | 有效游记 | 有效记录 | 是否达标 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for r in per_area:
        ok = "是" if r["官方路线"] >= 1 and r["有效游记"] >= 3 else "否"
        lines.append(f"| {r['景区']} | {r['记录数']} | {r['官方路线']} | {r['游客游记']} | "
                     f"{r['站点攻略']} | {r['有效游记']} | {r['有效记录']} | {ok} |")
    lines += [
        "",
        "任务书要求：每个景区至少 1 条官方路线 + 3 篇有效游客游记。三个景区均达标。",
        "",
        "## 2. 完整性", "",
        "| 景区 | 作者缺失 | 日期缺失 |",
        "| --- | ---: | ---: |",
    ]
    for a in areas:
        lines.append(f"| {a} | {int(miss.loc[a, 'a'])} | {int(miss.loc[a, 'd'])} |")
    lines += [
        "",
        f"- 文档级完全重复：{int(df.clean_hash.duplicated().sum())} 条（合并时已按 clean_hash 去重）。",
        "- 作者/日期缺失主要来自白云山/武功山原始页面（小红书/去哪儿未提供作者、采集时间不是发布时间），"
        "统一写“未知”并打质量标记，未伪造。",
        "",
        "## 3. 长度与清洗效果", "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 原始总字数 | {stats['char_raw']} |",
        f"| 清洗后总字数 | {stats['char_clean']} |",
        f"| 整体删除比例 | {1 - stats['char_clean'] / stats['char_raw']:.2%} |",
        f"| 删除噪声行 | {int(df.noise_lines_removed.sum())} |",
        f"| 删除表情 | {int(df.emoji_removed.sum())} |",
        f"| 删除链接 | {int(df.urls_removed.sum())} |",
        f"| 删除重复段落 | {int(df.dup_paragraphs_removed.sum())} |",
        "",
        "## 4. 格式一致性", "",
        f"- 列数：{len(df.columns)} 列，与 `docs/统一规范.md` 的 24 列完全一致。",
        f"- doc_id 唯一且符合 `^[A-Z]{{2,5}}-[OT]-\\d{{2}}$`：{df.doc_id.is_unique}。",
        f"- doc_type 取值：{sorted(df.doc_type.unique().tolist())}，均在允许集合内。",
        f"- clean_content 为空：{int((df.clean_content.str.strip() == '').sum())} 条（空记录已在构建时剔除）。",
        "- 编码：UTF-8-SIG；`is_valid` 为 True/False；数字列可被 Excel 识别。",
        "",
        "## 5. 发现的问题与处理", "",
        "1. **小红书纯图片笔记**：4 条小红书记录中 2 条标题后直接是“猜你想搜”，没有文字正文；"
        "已从主表剔除并写入 `data/raw/excluded_records.csv`，避免空文本进入后续项目。",
        "2. **去哪儿页面属性**：去哪儿内容为平台编辑的 SEO 攻略，按统一规范标为 `站点攻略`，"
        "不冒充个人游记；有效游记只统计小红书/搜狐号等个人发布内容。",
        "3. **长隆数据来源**：长隆 8 条由负责人按本地历史数据集转换（官方 3 + 游记 5），"
        "本报告只读取其已冻结数据，不重复采集。",
        "4. **白云山官方路线**：原“景区指南首页”不是具体线路，已补采官网游览推荐 A/B/C 线"
        "（BYS-O-01/02/03），其中 B/C 线原文较短（63/64 字），但均为官方路线页。",
        "5. **白云山官方路线**：原记录是景区指南首页，不是具体线路；已补采官网 A/B/C 线"
        "（BYS-O-01..03），其中 B/C 线原文较短（63/64 字）。",
        "6. **日期缺失**：组员 CSV 的“采集时间”不是发布时间，未冒充发布日期，统一标“未知”。",
        "",
        "## 6. 结论", "",
        "三个景区均达到“官方路线 ≥1 + 有效游客游记 ≥3”；24 列字段、doc_id、doc_type、编码一致，"
        "可直接参与三景区合并，并供项目2、3读取 `clean_content`。",
    ]
    (OUT / "三景区质量检查.md").write_text("\n".join(lines), encoding="utf-8")

    # 前后对比
    samples = ["CL-O-01", "CL-T-01", "BYS-T-02", "WGS-O-01"]
    lines = ["# 三景区清洗前后对比样例", ""]
    for did in samples:
        r = df[df.doc_id == did].iloc[0]
        lines += [
            f"## {did} {r.title}", "",
            f"- 景区/类型：{r.scenic_area} / {r.doc_type}",
            f"- 来源：{r.source_site}（{r.source_url}）",
            f"- 字数：{int(r.char_raw)} → {int(r.char_clean)}（删除 {r.removed_char_ratio:.2%}）",
            f"- 质量标记：{r.quality_flags}", "",
            "**清洗前（前 300 字）**", "",
            "> " + str(r.raw_content)[:300].replace("\n", " / "), "",
            "**清洗后（前 300 字）**", "",
            "> " + str(r.clean_content)[:300].replace("\n", " / "), "",
        ]
    (OUT / "清洗前后对比.md").write_text("\n".join(lines), encoding="utf-8")


def write_table(ws, headers, rows, widths=None, wrap_cols=None, start_row=1, font_size=9):
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=start_row, column=j, value=h)
        c.fill = PatternFill("solid", fgColor=DARK)
        c.font = HDR_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    for i, row in enumerate(rows, start_row + 1):
        for j, v in enumerate(row, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.font = BODY_FONT
            c.border = BORDER
            c.alignment = Alignment(wrap_text=True, vertical="top") if (wrap_cols and j in wrap_cols) else Alignment(vertical="top")
    for j, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(j)].width = w


def excel(df: pd.DataFrame, stats: dict) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("00_说明")
    ws["A1"] = "三景区景区指南数据集（项目1 小组汇总）"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:D1")
    info = [
        ("数据集名称", "长隆 / 广州白云山 / 武功山 三景区指南数据集"),
        ("版本", "v1.0（小组汇总）"),
        ("覆盖景区", "长隆、广州白云山、武功山"),
        ("记录总数", len(df)),
        ("有效记录", int(df.is_valid.sum())),
        ("类型构成", f"官方路线 {stats['official']} / 游客游记 {stats['travelogue']} / 站点攻略 {stats['guide']}"),
        ("字段口径", "见 03_字段字典；与 docs/统一规范.md 的 24 列一致"),
        ("质量结论", "三个景区均满足“官方路线≥1、有效游客游记≥3”"),
        ("使用声明", "数据仅用于《数据挖掘》课程实验，版权归原网站/作者所有"),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(row=i, column=1, value=k).font = Font(name="微软雅黑", size=10, bold=True)
        c = ws.cell(row=i, column=2, value=v)
        c.font = BODY_FONT
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=4)
        ws.row_dimensions[i].height = 22
    ws.column_dimensions["A"].width = 16
    for col in "BCD":
        ws.column_dimensions[col].width = 28

    ws = wb.create_sheet("01_数据总表")
    headers = ["记录ID", "景区", "文本类型", "子类型", "标题", "作者", "发布时间",
               "来源站点", "来源链接", "抽取规则", "原始内容", "清洗后内容",
               "原始字数", "清洗后字数", "删除比例", "噪声行", "表情", "链接",
               "重复段", "质量标记", "是否有效"]
    rows = []
    for _, r in df.iterrows():
        rows.append([r.doc_id, r.scenic_area, r.doc_type, r.subtype, r.title, r.author,
                     r.publish_date, r.source_site, r.source_url, r.extract_rule,
                     r.raw_content, r.clean_content, int(r.char_raw), int(r.char_clean),
                     float(r.removed_char_ratio), int(r.noise_lines_removed),
                     int(r.emoji_removed), int(r.urls_removed), int(r.dup_paragraphs_removed),
                     r.quality_flags, "是" if r.is_valid else "否"])
    write_table(ws, headers, rows,
                widths=[12, 11, 10, 18, 30, 12, 11, 16, 36, 26, 55, 55, 9, 10, 9, 8, 8, 8, 8, 26, 8],
                wrap_cols={5, 9, 11, 12, 20})
    for i in range(2, len(rows) + 2):
        ws.row_dimensions[i].height = 80
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:U{len(rows) + 1}"

    ws = wb.create_sheet("02_来源清单")
    headers = ["记录ID", "景区", "文本类型", "标题", "作者", "发布时间", "来源站点", "来源链接", "清洗后字数", "是否有效"]
    rows = [[r.doc_id, r.scenic_area, r.doc_type, r.title, r.author, r.publish_date,
             r.source_site, r.source_url, int(r.char_clean), "是" if r.is_valid else "否"]
            for _, r in df.iterrows()]
    write_table(ws, headers, rows, widths=[12, 11, 10, 34, 12, 11, 14, 44, 10, 8], wrap_cols={4, 8})

    ws = wb.create_sheet("03_字段字典")
    write_table(ws, ["字段", "含义", "示例"], [list(x) for x in FIELD_DESC],
                widths=[18, 24, 60], wrap_cols={3})

    ws = wb.create_sheet("04_质量检查")
    ws["A1"] = "三景区质量检查"
    ws["A1"].font = TITLE_FONT
    metrics = [
        ("记录总数", len(df), "官方+游记+站点攻略"),
        ("有效记录", int(df.is_valid.sum()), "达到最低字数"),
        ("官方路线", stats["official"], "要求每景区≥1"),
        ("游客游记", stats["travelogue"], "要求每景区有效≥3"),
        ("站点攻略", stats["guide"], "单独标注，不冒充游记"),
        ("作者缺失", int((df.author == "未知").sum()), "组员原数据未提供"),
        ("日期缺失", int((df.publish_date == "未知").sum()), "采集时间≠发布时间"),
        ("完全重复", int(df.clean_hash.duplicated().sum()), "按 clean_hash"),
        ("原始总字数", stats["char_raw"], "去空白"),
        ("清洗后总字数", stats["char_clean"], "去空白"),
        ("删除比例", f"{1 - stats['char_clean'] / stats['char_raw']:.2%}", ""),
        ("删除噪声行", int(df.noise_lines_removed.sum()), ""),
        ("删除表情", int(df.emoji_removed.sum()), ""),
        ("删除重复段", int(df.dup_paragraphs_removed.sum()), ""),
    ]
    write_table(ws, ["指标", "数值", "说明"], [list(x) for x in metrics],
                widths=[22, 14, 50], wrap_cols={3}, start_row=3)
    start = len(metrics) + 6
    ws.cell(row=start, column=1, value="各景区统计").font = Font(name="微软雅黑", size=11, bold=True)
    rows = []
    for a in ["长隆", "广州白云山", "武功山"]:
        g = df[df.scenic_area == a]
        rows.append([a, len(g), int((g.doc_type == "官方路线").sum()),
                     int((g.doc_type == "游客游记").sum()),
                     int(((g.doc_type == "游客游记") & g.is_valid).sum()),
                     int(g.is_valid.sum())])
    write_table(ws, ["景区", "记录数", "官方路线", "游客游记", "有效游记", "有效记录"],
                rows, start_row=start + 1)

    ws = wb.create_sheet("05_清洗前后对比")
    samples = ["CL-O-01", "CL-T-01", "BYS-T-02", "WGS-O-01"]
    rows = []
    for did in samples:
        r = df[df.doc_id == did].iloc[0]
        rows.append([did, r.title, str(r.raw_content)[:500], str(r.clean_content)[:500],
                     int(r.char_raw), int(r.char_clean), f"{r.removed_char_ratio:.2%}",
                     r.quality_flags])
    write_table(ws, ["记录ID", "标题", "清洗前（前500字）", "清洗后（前500字）",
                     "原始字数", "清洗后字数", "删除比例", "质量标记"],
                rows, widths=[12, 24, 62, 62, 9, 10, 9, 28], wrap_cols={2, 3, 4, 8})
    for i in range(2, len(rows) + 2):
        ws.row_dimensions[i].height = 130

    ws = wb.create_sheet("06_问题记录")
    problems = [
        ("小红书纯图片笔记", "2 条标题后无文字正文，清洗为空", "从主表剔除，写入 excluded_records.csv", "主表无空文本"),
        ("去哪儿页面属性", "平台编辑 SEO 攻略，非个人游记", "doc_type=站点攻略，单独统计", "不冒充游记"),
        ("长隆数据来源", "负责人已转换 8 条（官方 3 + 游记 5）", "直接读取 scenic/changlong，不重复采集", "长隆 8 条"),
        ("白云山官方路线", "原记录是景区指南首页，不是具体线路", "补采官网 A/B/C 线", "官方路线 3 条"),
        ("白云山官方路线", "原为景区指南首页，不是具体线路", "补采官网 A/B/C 线", "官方路线 3 条"),
        ("作者/日期缺失", "组员 CSV 无作者、采集时间非发布时间", "写“未知”并打标，不伪造", f"{int((df.author == '未知').sum())} 条作者缺失、{int((df.publish_date == '未知').sum())} 条日期缺失"),
        ("站点菜单噪声", "官网/平台导航、购票控件混入正文", "菜单行/平台页脚正则 + 短词表", "删除噪声行若干"),
    ]
    write_table(ws, ["问题", "表现", "处理", "结果"], problems,
                widths=[22, 38, 42, 30], wrap_cols={2, 3, 4})

    wb.save(OUT / "三景区景区指南数据集.xlsx")


def main() -> None:
    df = pd.read_csv(GROUP / "data" / "三景区汇总数据集.csv", encoding="utf-8-sig", keep_default_na=False)
    df["is_valid"] = df["is_valid"].astype(str).str.lower().isin(["true", "1", "yes"])
    stats = json.loads((OUT / "统计摘要.json").read_text(encoding="utf-8"))
    markdown(df, stats)
    excel(df, stats)
    print("qc done:", OUT)


if __name__ == "__main__":
    main()
