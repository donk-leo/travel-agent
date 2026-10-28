# -*- coding: utf-8 -*-
"""结构化输出与质量检查：生成 CSV / JSONL / Excel 数据集及质量报告。

输出：
    data/processed/wugongshan_guides.jsonl
    data/processed/武功山景区指南数据集.xlsx
    outputs/质量检查报告.md
    outputs/清洗前后对比.md
    outputs/统计摘要.json

用法：
    python src/build_dataset.py
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.data_source import AxDataSource, StrRef
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from common import (
    DATASET_CSV, DATASET_JSONL, DATASET_XLSX, MANIFEST_CSV, MIN_OFFICIAL,
    MIN_TRAVELOGUE, OUTPUT_DIR, PROCESSED_DIR, SCENIC_AREA, setup_logging,
)

log = logging.getLogger("build")

FIELD_DICT = [
    ("doc_id", "记录ID", "文本", "唯一标识；O=官方路线，T=游客游记", "WGS-O-01"),
    ("scenic_area", "景区", "文本", "所属景区名称", "武功山"),
    ("doc_type", "文本类型", "文本", "官方路线 / 游客游记", "官方路线"),
    ("subtype", "子类型", "文本", "路线主题或游记类型", "徒步一日游"),
    ("title", "标题", "文本", "页面标题或人工核定标题", "户外体验一日游"),
    ("author", "作者", "文本", "官方账号或游记作者；缺失记为“未知”", "武功山景区管理员"),
    ("publish_date", "发布时间", "日期", "页面发布时间，统一为 YYYY-MM-DD", "2017-06-25"),
    ("source_site", "来源站点", "文本", "网站/平台名称", "萍乡武功山景区官网"),
    ("source_url", "来源链接", "URL", "原始页面地址，便于复核", "http://...id=104"),
    ("extract_rule", "抽取规则", "文本", "正文定位所用规则", "官网-富文本div.raid-main"),
    ("raw_content", "原始内容", "长文本", "正文抽取后、清洗前的文本", "简要行程\n路线：石鼓寺--..."),
    ("clean_content", "清洗后内容", "长文本", "去噪、规范化、去重后的文本", "简要行程\n路线：石鼓寺--..."),
    ("char_raw", "原始字数", "整数", "去除空白后的字符数", "215"),
    ("char_clean", "清洗后字数", "整数", "去除空白后的字符数", "215"),
    ("para_raw", "原始段落数", "整数", "按换行切分的非空段落数", "4"),
    ("para_clean", "清洗后段落数", "整数", "按换行切分的非空段落数", "4"),
    ("removed_char_ratio", "删除字符比例", "小数", "1 - 清洗后字数/原始字数", "0.0123"),
    ("noise_lines_removed", "删除噪声行", "整数", "导航、按钮、版权等整行删除数", "3"),
    ("emoji_removed", "删除表情符号", "整数", "emoji/特殊符号删除字符数", "12"),
    ("urls_removed", "删除链接", "整数", "URL/邮箱删除数", "2"),
    ("dup_paragraphs_removed", "删除重复段落", "整数", "完全重复或相似度≥0.90 的段落数", "1"),
    ("quality_flags", "质量标记", "文本", "分号分隔的质量问题/处理记录", "站点噪声已清理；作者缺失"),
    ("is_valid", "是否有效", "布尔", "达到最低字数与信息量要求", "TRUE"),
    ("clean_hash", "文本指纹", "文本", "清洗后文本 SHA1，用于查重", "a1b2..."),
]


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(DATASET_CSV, encoding="utf-8-sig", keep_default_na=False)
    manifest = pd.read_csv(MANIFEST_CSV, encoding="utf-8-sig", keep_default_na=False)
    return df, manifest


def add_checks(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """计算质量指标与逐篇标记。"""
    df = df.copy()
    df["author"] = df["author"].replace("", "未知")
    df["is_valid"] = df["is_valid"].astype(str).str.lower().isin(["true", "1", "yes"])
    # 原始文本中的替换符（编码损伤）统计
    df["bad_chars_raw"] = df["raw_content"].str.count("\ufffd")
    df["has_route_sep"] = df["clean_content"].str.contains(r"--|—|→", regex=True)

    # 文档级近似重复（不同 doc_id、清洗文本相似度≥0.85）
    near_dups: list[tuple[str, str, float]] = []
    texts = df["clean_content"].tolist()
    ids = df["doc_id"].tolist()
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if abs(len(a) - len(b)) / max(len(a), len(b), 1) > 0.4:
                continue
            ratio = SequenceMatcher(None, a[:600], b[:600]).ratio()
            if ratio >= 0.85:
                near_dups.append((ids[i], ids[j], round(ratio, 3)))

    exact_dups = df[df.duplicated("clean_hash", keep=False)]["doc_id"].tolist()
    if exact_dups:
        df.loc[df["doc_id"].isin(exact_dups), "quality_flags"] += "；文档级重复"
    for a, b, ratio in near_dups:
        df.loc[df["doc_id"] == a, "quality_flags"] += f"；与{b}高度相似({ratio})"
        df.loc[df["doc_id"] == b, "quality_flags"] += f"；与{a}高度相似({ratio})"

    stats = {
        "records": len(df),
        "valid": int(df["is_valid"].sum()),
        "official": int((df["doc_type"] == "官方路线").sum()),
        "travelogue": int((df["doc_type"] == "游客游记").sum()),
        "valid_official": int(((df["doc_type"] == "官方路线") & df["is_valid"]).sum()),
        "valid_travelogue": int(((df["doc_type"] == "游客游记") & df["is_valid"]).sum()),
        "sites": Counter(df["source_site"]).most_common(),
        "types": Counter(df["doc_type"]).most_common(),
        "missing_author": int((df["author"] == "未知").sum()),
        "missing_date": int((df["publish_date"] == "").sum()),
        "exact_dups": exact_dups,
        "near_dups": near_dups,
        "bad_char_docs": int((df["bad_chars_raw"] > 0).sum()),
        "bad_chars": int(df["bad_chars_raw"].sum()),
        "route_sep_docs": int(df["has_route_sep"].sum()),
        "char_raw_total": int(df["char_raw"].sum()),
        "char_clean_total": int(df["char_clean"].sum()),
        "char_raw_mean": round(float(df["char_raw"].mean()), 1),
        "char_clean_mean": round(float(df["char_clean"].mean()), 1),
        "char_clean_median": float(df["char_clean"].median()),
        "char_clean_min": int(df["char_clean"].min()),
        "char_clean_max": int(df["char_clean"].max()),
        "removed_ratio": round(1 - df["char_clean"].sum() / df["char_raw"].sum(), 4),
        "noise_lines": int(df["noise_lines_removed"].sum()),
        "emoji": int(df["emoji_removed"].sum()),
        "urls": int(df["urls_removed"].sum()),
        "dup_paras": int(df["dup_paragraphs_removed"].sum()),
        "flags": Counter(
            flag
            for flags in df["quality_flags"].fillna("")
            for flag in str(flags).split("；")
            if flag and flag != "无"
        ).most_common(),
        "check_official": int(((df["doc_type"] == "官方路线") & df["is_valid"]).sum()) >= MIN_OFFICIAL,
        "check_travelogue": int(((df["doc_type"] == "游客游记") & df["is_valid"]).sum()) >= MIN_TRAVELOGUE,
    }
    stats["requirements_pass"] = stats["check_official"] and stats["check_travelogue"]
    return df, stats


# ---------------- Excel ----------------
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=10)
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True, color="1F4E79")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def style_header(ws, ncols: int, row: int = 1) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cell.border = BORDER


def write_table(ws, headers: list[str], rows: list[list], widths: list[int] | None = None,
                wrap_cols: set[int] | None = None, start_row: int = 1) -> None:
    for j, h in enumerate(headers, 1):
        ws.cell(row=start_row, column=j, value=h)
    style_header(ws, len(headers), start_row)
    for i, row in enumerate(rows, start_row + 1):
        for j, val in enumerate(row, 1):
            cell = ws.cell(row=i, column=j, value=val)
            cell.font = BODY_FONT
            cell.border = BORDER
            cell.alignment = WRAP if (wrap_cols and j in wrap_cols) else Alignment(vertical="top")
    for j, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(j)].width = w


def build_excel(df: pd.DataFrame, manifest: pd.DataFrame, stats: dict) -> None:
    wb = Workbook()
    wb.remove(wb.active)

    # 00 说明
    ws = wb.create_sheet("00_说明")
    ws["A1"] = f"{SCENIC_AREA}景区指南数据集（项目1：数据采集与预处理）"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:D1")
    info = [
        ("数据集名称", f"{SCENIC_AREA}景区游览指南文本数据集"),
        ("数据集版本", "v1.0"),
        ("覆盖景区", SCENIC_AREA),
        ("采集日期", "2026-10-28"),
        ("记录总数", stats["records"]),
        ("有效记录", stats["valid"]),
        ("官方路线", f"{stats['official']} 条（有效 {stats['valid_official']} 条）"),
        ("游客游记", f"{stats['travelogue']} 条（有效 {stats['valid_travelogue']} 条）"),
        ("字段口径", "见“03_字段字典”；原始内容与清洗后内容均保留，便于对照复核"),
        ("质量结论", "达到任务书“≥1 条官方路线、≥3 篇有效游记”的要求" if stats["requirements_pass"] else "未达标，请检查"),
        ("使用声明", "数据仅用于《数据挖掘》课程实验，版权归原作者/平台所有；引用请标注来源链接"),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("生成脚本", "src/build_dataset.py（采集 collect.py / 抽取 extract.py / 清洗 clean.py）"),
    ]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(row=i, column=1, value=k).font = Font(name="微软雅黑", size=10, bold=True)
        ws.cell(row=i, column=1).alignment = Alignment(vertical="center", wrap_text=True)
        cell = ws.cell(row=i, column=2, value=v)
        cell.font = BODY_FONT
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=4)
        ws.row_dimensions[i].height = 22
    ws.row_dimensions[1].height = 32
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18

    # 01 数据总表
    ws = wb.create_sheet("01_数据总表")
    headers = [
        "记录ID", "景区", "文本类型", "子类型", "标题", "作者", "发布时间",
        "来源站点", "来源链接", "抽取规则", "原始内容", "清洗后内容",
        "原始字数", "清洗后字数", "删除比例", "噪声行", "表情", "链接",
        "重复段", "质量标记", "是否有效",
    ]
    rows = []
    for _, r in df.iterrows():
        rows.append([
            r.doc_id, r.scenic_area, r.doc_type, r.subtype, r.title, r.author,
            r.publish_date, r.source_site, r.source_url, r.extract_rule,
            r.raw_content, r.clean_content, int(r.char_raw), int(r.char_clean),
            float(r.removed_char_ratio), int(r.noise_lines_removed),
            int(r.emoji_removed), int(r.urls_removed), int(r.dup_paragraphs_removed),
            r.quality_flags, "是" if r.is_valid else "否",
        ])
    write_table(
        ws, headers, rows,
        widths=[12, 8, 10, 16, 30, 14, 11, 18, 38, 22, 60, 60, 9, 10, 9, 8, 8, 8, 8, 24, 8],
        wrap_cols={5, 9, 11, 12, 20},
    )
    for i in range(2, len(rows) + 2):
        url_cell = ws.cell(row=i, column=9)
        if url_cell.value:
            url_cell.hyperlink = url_cell.value
            url_cell.font = Font(name="微软雅黑", size=9, color="0563C1", underline="single")
        ws.row_dimensions[i].height = 90
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:U{len(rows) + 1}"

    # 02 来源清单
    ws = wb.create_sheet("02_来源清单")
    headers = ["记录ID", "文本类型", "标题", "作者", "发布时间", "来源站点", "来源链接",
               "HTTP状态", "原始字节", "抓取时间", "SHA256(前12位)", "状态"]
    rows = []
    meta = df.set_index("doc_id")
    for _, m in manifest.iterrows():
        author = meta.loc[m.doc_id, "author"] if m.doc_id in meta.index else ""
        pub_date = meta.loc[m.doc_id, "publish_date"] if m.doc_id in meta.index else ""
        rows.append([
            m.doc_id, m.doc_type, m.title, author, pub_date, m.source_site,
            m.source_url, m.http_status, int(m.content_bytes), m.fetch_time,
            str(m.sha256)[:12], m.status,
        ])
    write_table(ws, headers, rows, widths=[12, 10, 34, 14, 11, 18, 46, 9, 10, 20, 14, 9],
                wrap_cols={3, 7})
    for i in range(2, len(rows) + 2):
        cell = ws.cell(row=i, column=7)
        if cell.value:
            cell.hyperlink = cell.value
            cell.font = Font(name="微软雅黑", size=9, color="0563C1", underline="single")
    ws.freeze_panes = "A2"

    # 03 字段字典
    ws = wb.create_sheet("03_字段字典")
    write_table(ws, ["字段名", "中文名", "类型", "说明", "示例"],
                [list(x) for x in FIELD_DICT], widths=[18, 14, 8, 52, 34], wrap_cols={4, 5})
    ws.freeze_panes = "A2"

    # 04 质量检查
    ws = wb.create_sheet("04_质量检查")
    ws["A1"] = "数据质量检查指标"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:C1")
    qc = [
        ("记录总数", stats["records"], "官方+游记"),
        ("有效记录数", stats["valid"], "达到最低字数与信息量要求"),
        ("有效官方路线", stats["valid_official"], f"要求 ≥{MIN_OFFICIAL}"),
        ("有效游客游记", stats["valid_travelogue"], f"要求 ≥{MIN_TRAVELOGUE}（任务书写 5 篇，实际可用 7 篇）"),
        ("是否满足任务要求", "是" if stats["requirements_pass"] else "否", "按任务书最低要求判定"),
        ("作者缺失", stats["missing_author"], "已在质量标记中注明"),
        ("日期缺失", stats["missing_date"], "发布时间统一为 YYYY-MM-DD"),
        ("文档级完全重复", len(stats["exact_dups"]), "按清洗后文本 SHA1 判定"),
        ("文档级高度相似", len(stats["near_dups"]), "前 600 字相似度 ≥0.85"),
        ("含编码替换符的记录", stats["bad_char_docs"], f"共 {stats['bad_chars']} 个 U+FFFD，清洗时删除"),
        ("含路线分隔符的记录", stats["route_sep_docs"], "包含 -- / — / →，可支撑项目3路线解析"),
        ("原始总字数", stats["char_raw_total"], "去空白"),
        ("清洗后总字数", stats["char_clean_total"], "去空白"),
        ("平均字数（清洗后）", stats["char_clean_mean"], "含短文本，中位数更稳健"),
        ("中位数字数（清洗后）", stats["char_clean_median"], ""),
        ("最短/最长（清洗后）", f"{stats['char_clean_min']} / {stats['char_clean_max']}", "最短为图片为主游记"),
        ("整体删除字符比例", f"{stats['removed_ratio']:.2%}", "清洗造成的字符减少比例"),
        ("删除噪声行合计", stats["noise_lines"], "导航、按钮、版权、附件信息等"),
        ("删除表情符号合计", stats["emoji"], "emoji 及特殊装饰符"),
        ("删除链接合计", stats["urls"], "URL/邮箱"),
        ("删除重复段落合计", stats["dup_paras"], "完全重复或相似度 ≥0.90"),
    ]
    write_table(ws, ["指标", "数值", "说明"], [list(x) for x in qc],
                widths=[26, 16, 58], wrap_cols={3}, start_row=3)
    start = len(qc) + 6
    ws.cell(row=start, column=1, value="各来源站点记录数").font = Font(name="微软雅黑", size=11, bold=True)
    site_rows = [[site, cnt] for site, cnt in stats["sites"]]
    write_table(ws, ["来源站点", "记录数"], site_rows, start_row=start + 1)
    start2 = start + len(site_rows) + 4
    ws.cell(row=start2, column=1, value="质量标记分布").font = Font(name="微软雅黑", size=11, bold=True)
    write_table(ws, ["质量标记", "次数"], [[k, v] for k, v in stats["flags"]], start_row=start2 + 1)

    # 05 清洗前后对比
    ws = wb.create_sheet("05_清洗前后对比")
    samples = ["WGS-T-01", "WGS-T-02", "WGS-T-03", "WGS-T-07", "WGS-O-01"]
    rows = []
    for did in samples:
        r = df[df.doc_id == did].iloc[0]
        rows.append([
            did, r.title, r.raw_content[:500], r.clean_content[:500],
            int(r.char_raw), int(r.char_clean), f"{r.removed_char_ratio:.2%}",
            r.quality_flags,
        ])
    write_table(ws, ["记录ID", "标题", "清洗前（前500字）", "清洗后（前500字）",
                     "原始字数", "清洗后字数", "删除比例", "主要处理"],
                rows, widths=[12, 26, 70, 70, 9, 10, 9, 28], wrap_cols={2, 3, 4, 8})
    for i in range(2, len(rows) + 2):
        ws.row_dimensions[i].height = 120
    ws.freeze_panes = "C2"

    # 06 统计图表
    ws = wb.create_sheet("06_统计图表")
    ws["A1"] = "来源站点分布"
    ws["A1"].font = Font(name="微软雅黑", size=11, bold=True)
    site_rows = [[site, cnt] for site, cnt in stats["sites"]]
    write_table(ws, ["来源站点", "记录数"], site_rows, start_row=2,
                widths=[22, 12])
    chart = BarChart()
    chart.title = "各来源站点记录数"
    chart.y_axis.title = "记录数"
    data = Reference(ws, min_col=2, min_row=2, max_row=2 + len(site_rows))
    cats = Reference(ws, min_col=1, min_row=3, max_row=2 + len(site_rows))
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    # openpyxl 默认用 numRef 引用文本分类，LibreOffice/部分 Excel 会丢分类标签；
    # 显式改为 strRef，兼容性更好。
    chart.series[0].cat = AxDataSource(
        strRef=StrRef(f=f"'06_统计图表'!$A$3:$A${2 + len(site_rows)}")
    )
    chart.y_axis.scaling.min = 0       # 否则最小值落在 2 附近，2/1 的柱子会被裁掉
    chart.y_axis.majorUnit = 1
    chart.height, chart.width = 8, 14
    ws.add_chart(chart, "E2")

    # 第二个图表整体下移，避免与第一个图表重叠（Excel 图表按锚点浮动）
    start = 2 + len(site_rows) + 13
    ws.cell(row=start, column=1, value="各文档字数（原始 vs 清洗后）").font = Font(name="微软雅黑", size=11, bold=True)
    write_table(ws, ["记录ID", "原始字数", "清洗后字数"],
                [[r.doc_id, int(r.char_raw), int(r.char_clean)] for _, r in df.iterrows()],
                start_row=start + 1, widths=[22, 12, 12])
    n = len(df)
    chart2 = BarChart()
    chart2.type = "col"
    chart2.title = "清洗前后字数对比"
    chart2.y_axis.title = "字数"
    data = Reference(ws, min_col=2, max_col=3, min_row=start + 1, max_row=start + 1 + n)
    cats = Reference(ws, min_col=1, min_row=start + 2, max_row=start + 1 + n)
    chart2.add_data(data, titles_from_data=True)
    chart2.set_categories(cats)
    for s in chart2.series:
        s.cat = AxDataSource(
            strRef=StrRef(f=f"'06_统计图表'!$A${start + 2}:$A${start + 1 + n}")
        )
    chart2.height, chart2.width = 9, 20
    ws.add_chart(chart2, f"E{start}")

    # 07 问题与处理
    ws = wb.create_sheet("07_问题与处理")
    problems = [
        ["部分站点反爬/跳转", "马蜂窝游记跳转登录验证（HTTP 202）", "记录失败原因，改用其他公开来源补足样本", "来源清单保留失败记录，未影响数量要求"],
        ["页面编码混用", "8264 页面声明 GBK，实际混有 UTF-8 片段，脚本区出现 6 个替换符", "多编码候选打分解码 + 替换符兜底；站点规则只取正文", "正文解码正确；脚本区乱码未进入数据集，最终 0 个替换符"],
        ["正文与站点框架混杂", "导航、按钮、版权、推荐流混在正文容器内", "站点规则定位正文 + 行级噪声规则 + 文本密度兜底", "删除噪声行 18 行，正文完整保留"],
        ["图片为主/短文本", "豆瓣图片帖正文仅 33 字", "保留记录并标记“文本过短/图片为主”，不计入有效游记", "有效游记 7 篇，仍满足要求"],
        ["重复段落", "部分攻略在开头/结尾重复口号式段落", "完全重复 + 相似度≥0.90 段落去重", "删除 2 段，未误删正文"],
        ["论坛签名/时间戳", "老帖正文句末粘附论坛签名、上传时间", "句末异常符号比例检测 + 时间戳正则清理", "已清除；规则偏保守，可能漏掉极短签名"],
        ["繁体/多语言页面", "Trip.com 页面为繁体且正文由前端 JSON 渲染", "不纳入数据集，保留拒绝记录", "保证语料以简体中文为主"],
    ]
    write_table(ws, ["问题", "表现", "处理方式", "结果/残留"], problems,
                widths=[20, 40, 46, 40], wrap_cols={2, 3, 4})
    for i in range(2, len(problems) + 2):
        ws.row_dimensions[i].height = 60

    wb.save(DATASET_XLSX)
    log.info("Excel 数据集 -> %s", DATASET_XLSX)


def write_reports(df: pd.DataFrame, stats: dict) -> None:
    # 统计摘要 JSON
    with open(OUTPUT_DIR / "统计摘要.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # 质量检查报告 Markdown
    lines = [
        f"# {SCENIC_AREA}景区指南数据质量检查报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 记录总数：{stats['records']}（官方路线 {stats['official']}，游客游记 {stats['travelogue']}）",
        f"- 有效记录：{stats['valid']}（官方 {stats['valid_official']}，游记 {stats['valid_travelogue']}）",
        f"- 任务要求：官方路线 ≥{MIN_OFFICIAL} 条、有效游记 ≥{MIN_TRAVELOGUE} 篇 —— "
        f"**{'满足' if stats['requirements_pass'] else '不满足'}**",
        "",
        "## 1. 数量与覆盖",
        "",
        "| 来源站点 | 记录数 |",
        "| --- | ---: |",
        *[f"| {s} | {c} |" for s, c in stats["sites"]],
        "",
        "## 2. 完整性",
        "",
        "| 检查项 | 结果 | 说明 |",
        "| --- | ---: | --- |",
        f"| 作者缺失 | {stats['missing_author']} | 已在质量标记中注明 |",
        f"| 日期缺失 | {stats['missing_date']} | 统一为 YYYY-MM-DD |",
        f"| 文档级完全重复 | {len(stats['exact_dups'])} | 清洗后文本 SHA1 |",
        f"| 文档级高度相似 | {len(stats['near_dups'])} | 前 600 字相似度 ≥0.85 |",
        f"| 编码替换符 | {stats['bad_chars']} 个 / {stats['bad_char_docs']} 篇 | 清洗时删除 |",
        "",
        "## 3. 长度分布（清洗后，去空白）",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 总字数 | {stats['char_clean_total']} |",
        f"| 平均 | {stats['char_clean_mean']} |",
        f"| 中位数 | {stats['char_clean_median']} |",
        f"| 最短 | {stats['char_clean_min']} |",
        f"| 最长 | {stats['char_clean_max']} |",
        "",
        "## 4. 清洗效果",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 原始总字数 | {stats['char_raw_total']} |",
        f"| 清洗后总字数 | {stats['char_clean_total']} |",
        f"| 整体删除比例 | {stats['removed_ratio']:.2%} |",
        f"| 删除噪声行 | {stats['noise_lines']} |",
        f"| 删除表情符号 | {stats['emoji']} |",
        f"| 删除链接 | {stats['urls']} |",
        f"| 删除重复段落 | {stats['dup_paras']} |",
        "",
        "## 5. 逐篇记录",
        "",
        "| 记录ID | 类型 | 标题 | 原始字数 | 清洗后字数 | 有效 | 质量标记 |",
        "| --- | --- | --- | ---: | ---: | :---: | --- |",
    ]
    for _, r in df.iterrows():
        title = str(r.title[:24]).replace("|", "\\|")
        flags = str(r.quality_flags).replace("|", "\\|")
        lines.append(
            f"| {r.doc_id} | {r.doc_type} | {title} | {int(r.char_raw)} | "
            f"{int(r.char_clean)} | {'是' if r.is_valid else '否'} | {flags} |"
        )
    lines += [
        "",
        "## 6. 发现的问题",
        "",
        "1. **短文本/图片为主**：豆瓣帖 "
        f"{', '.join(df[df['quality_flags'].str.contains('图片为主')]['doc_id'])} 正文仅一句图注，"
        "已保留但不计入有效游记，避免后续实体识别被空文本干扰。",
        f"2. **作者缺失**：{stats['missing_author']} 篇简书游记页面未提供作者字段，统一记“未知”并打标。",
        "3. **页面编码混用**：8264 页面声明 GBK，但脚本区混有 UTF-8 片段，整页解码后出现 6 个替换符；"
        "由于站点规则只截取首帖正文，替换符未进入数据集（最终 0 个）。",
        "4. **站点框架残留**：图片说明（如“线路图”“小程序预约”）属于短图注，规则未强行删除，"
        "以免误删“行前准备”等有效小标题；对项目2的实体识别影响很小。",
        "",
    ]
    (OUTPUT_DIR / "质量检查报告.md").write_text("\n".join(lines), encoding="utf-8")

    # 清洗前后对比 Markdown
    samples = ["WGS-T-01", "WGS-T-02", "WGS-T-03", "WGS-T-07"]
    lines = ["# 清洗前后对比样例", ""]
    for did in samples:
        r = df[df.doc_id == did].iloc[0]
        lines += [
            f"## {did} {r.title}",
            "",
            f"- 来源：{r.source_site}（{r.source_url}）",
            f"- 字数：{int(r.char_raw)} → {int(r.char_clean)}（删除 {r.removed_char_ratio:.2%}）",
            f"- 质量标记：{r.quality_flags}",
            "",
            "**清洗前（前 300 字）**",
            "",
            "> " + r.raw_content[:300].replace("\n", " / "),
            "",
            "**清洗后（前 300 字）**",
            "",
            "> " + r.clean_content[:300].replace("\n", " / "),
            "",
        ]
    (OUTPUT_DIR / "清洗前后对比.md").write_text("\n".join(lines), encoding="utf-8")
    log.info("质量报告/对比样例 -> %s", OUTPUT_DIR)


def main() -> None:
    setup_logging()
    df, manifest = load()
    df, stats = add_checks(df)
    # 转 JSONL
    with open(DATASET_JSONL, "w", encoding="utf-8") as f:
        for _, r in df.iterrows():
            rec = {k: (int(v) if k.startswith("char_") or k.startswith("para_") or
                       k in ("noise_lines_removed", "emoji_removed", "urls_removed",
                             "dup_paragraphs_removed", "bad_chars_raw") else v)
                   for k, v in r.items()}
            rec["is_valid"] = bool(rec["is_valid"])
            rec["has_route_sep"] = bool(rec["has_route_sep"])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    build_excel(df, manifest, stats)
    write_reports(df, stats)
    log.info(
        "完成：%d 条（有效 %d），来源 %d 个；要求达标=%s",
        stats["records"], stats["valid"], len(stats["sites"]), stats["requirements_pass"],
    )


if __name__ == "__main__":
    main()
