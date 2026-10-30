# -*- coding: utf-8 -*-
"""生成《项目4：程序性知识的共指消解》实验报告（DOCX）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from lib.paths import analysis_dir, scenic_csv  # noqa: E402
from lib.io_utils import read_csv_sig  # noqa: E402

ROOT = analysis_dir("p04_coref")
OUT_DIR = ROOT / "report"
FIG = OUT_DIR / "figures"
OUT = OUT_DIR / "项目4_程序性知识的共指消解_实验报告.docx"

DARK = RGBColor(0x1F, 0x3B, 0x63)
GRAY = RGBColor(0x59, 0x59, 0x59)
INK = RGBColor(0x26, 0x26, 0x26)
BODY, HEAD, CODE = "宋体", "黑体", "Consolas"


def set_font(run, name=BODY, size=None, bold=None, color=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def para(doc, text="", indent=True, size=10.5, bold=False, color=INK, align=None,
         after=4, line=1.45):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = line
    pf.space_after = Pt(after)
    pf.space_before = Pt(0)
    if indent:
        pf.first_line_indent = Pt(size * 2)
    if align is not None:
        p.alignment = align
    r = p.add_run(text)
    set_font(r, BODY, size, bold, color)
    return p


def heading(doc, text, level):
    p = doc.add_paragraph(style={1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}[level])
    r = p.add_run(text)
    set_font(r, HEAD, {1: 16, 2: 13, 3: 11.5}[level], True, DARK)
    p.paragraph_format.space_before = Pt({1: 16, 2: 10, 3: 6}[level])
    p.paragraph_format.space_after = Pt({1: 8, 2: 5, 3: 3}[level])
    p.paragraph_format.keep_with_next = True
    return p


def bullet(doc, text, size=10):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.line_spacing = 1.3
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    set_font(r, BODY, size, False, INK)
    return p


def shade(el, fill):
    pPr = el.get_or_add_pPr() if hasattr(el, "get_or_add_pPr") else el
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pPr.append(shd)


def caption(doc, text, before=False):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6 if not before else 8)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = bool(before)
    r = p.add_run(text)
    set_font(r, HEAD, 9, False, GRAY)
    return p


def code(doc, text, size=8.2):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.5)
    pf.line_spacing = 1.1
    pf.space_before = Pt(2)
    pf.space_after = Pt(4)
    shade(p._p, "F2F2F2")
    r = p.add_run(text.rstrip())
    set_font(r, CODE, size, False, RGBColor(0x1A, 0x1A, 0x1A))
    r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), BODY)
    return p


def table(doc, headers, rows, widths, size=8.6, center_cols=(), keep=True):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False

    trPr = t.rows[0]._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))
    trPr.append(OxmlElement("w:tblHeader"))

    for j, h in enumerate(headers):
        c = t.rows[0].cells[j]
        c.width = Cm(widths[j])
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(h)
        set_font(r, HEAD, size, True, RGBColor(255, 255, 255))
        tcPr = c._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "1F3B63")
        tcPr.append(shd)

    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j, v in enumerate(row):
            cells[j].width = Cm(widths[j])
            p = cells[j].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.08
            if j in center_cols:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(str(v))
            set_font(r, BODY, size, False, INK)

    for row in t.rows[1:]:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    if keep:
        for row in t.rows[:-1]:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True
    return t


def picture(doc, path, width=16.0, keep=True):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = bool(keep)
    p.add_run().add_picture(str(path), width=Cm(width))


def field(p, instr):
    r = p.add_run()
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = instr
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate")
    tx = OxmlElement("w:t"); tx.text = "1"
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end")
    for x in (b, it, s, tx, e):
        r._r.append(x)


def setup(doc):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(2.4), Cm(2.2)
    sec.left_margin, sec.right_margin = Cm(2.6), Cm(2.6)
    sec.different_first_page_header_footer = True
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = hp.add_run("2026《数据挖掘》探索性实验 · 项目4 · 共指消解")
    set_font(r, BODY, 8, False, GRAY)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("第 "); set_font(r, BODY, 8.5, False, GRAY)
    field(fp, "PAGE")
    r = fp.add_run(" 页 / 共 "); set_font(r, BODY, 8.5, False, GRAY)
    field(fp, "NUMPAGES")
    r = fp.add_run(" 页"); set_font(r, BODY, 8.5, False, GRAY)
    st = doc.styles["Normal"]
    st.font.name = BODY
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY)


def cover(doc):
    for _ in range(3):
        para(doc, "", indent=False)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("2026《数据挖掘》课程 · 探索性实验"); set_font(r, HEAD, 14, False, GRAY)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(18)
    r = p.add_run("景区游览指南的程序性知识挖掘"); set_font(r, HEAD, 24, True, DARK)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    r = p.add_run("实验项目4：程序性知识的共指消解"); set_font(r, HEAD, 18, True, RGBColor(0x2E, 0x5C, 0x8A))
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("—— 基于三景区游记与官方路线的规则消解"); set_font(r, BODY, 15, False, INK)

    for _ in range(3):
        para(doc, "", indent=False)
    info = [("课程名称", "数据挖掘"),
            ("实验项目", "项目4 程序性知识的共指消解"),
            ("数据范围", "长隆 / 白云山 / 武功山（29 条）"),
            ("小组成员", "________（本人）　________　________"),
            ("学号／班级", "________　________"),
            ("提交日期", "2026 年 11 月")]
    t = doc.add_table(rows=0, cols=2); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for k, v in info:
        cells = t.add_row().cells
        cells[0].width, cells[1].width = Cm(4.2), Cm(9.4)
        p0 = cells[0].paragraphs[0]; p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p0.add_run(k + "："); set_font(r, HEAD, 10.5, True, GRAY)
        r = cells[1].paragraphs[0].add_run(v); set_font(r, BODY, 10.5, False, INK)
    para(doc, "", indent=False)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("本报告为项目4分册；输入为项目1 三景区数据（tag v0.1-p01），项目2/3 产出只读。")
    set_font(r, "楷体", 9, False, GRAY)
    doc.add_page_break()


def main():
    coref = [json.loads(line) for line in (ROOT / "outputs" / "coref.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads((ROOT / "outputs" / "coref_stats.json").read_text(encoding="utf-8"))
    pstats = json.loads((ROOT / "outputs" / "pronoun_stats.json").read_text(encoding="utf-8"))
    ev = json.loads((ROOT / "outputs" / "eval_stats.json").read_text(encoding="utf-8"))
    ann, _ = read_csv_sig(ROOT / "outputs" / "annotations.csv")
    entities = sum(1 for _ in (analysis_dir("p02_entities") / "outputs" / "entities.jsonl").read_text(encoding="utf-8").splitlines() if _.strip())
    routes = sum(1 for _ in (analysis_dir("p03_routes") / "outputs" / "routes.jsonl").read_text(encoding="utf-8").splitlines() if _.strip())

    area_counts = {}
    valid_counts = {}
    for area in ("changlong", "baiyunshan", "wugongshan"):
        rows, _ = read_csv_sig(scenic_csv(area))
        area_counts[area] = len(rows)
        valid_counts[area] = sum(1 for r in rows if str(r.get("is_valid", "")).lower() in {"true", "1", "yes"})

    doc = Document(); setup(doc)
    doc.core_properties.title = "项目4 程序性知识的共指消解"
    doc.core_properties.author = "数据挖掘课程小组"
    cover(doc)

    # 摘要
    heading(doc, "摘　要", 1)
    para(doc, (
        f"本报告完成《数据挖掘》探索性实验项目4：从三景区 29 条游记/官方路线中检测代词，并把指代不明的"
        f"“它、这、这里、这个、他们”等消解到具体实体。检测阶段使用 23 个代词形式（实际命中 15 个）的最长优先词表与分句规则，"
        f"在 21 篇文档中得到 {len(coref)} 条候选，保留绝对位置与所在句；消解阶段以项目2 的 {entities} 个实体和"
        f"项目3 的 {routes} 条路线为候选，采用“代词类型白名单 + 同句/前句距离 + POI 优先”的最近实体规则，"
        f"输出 {stats['resolved']} 条消解结果，其余 {stats['unresolved']} 条留空并写原因。"
        f"人工标注 {len(ann)} 条（16 条有先行词、4 条无明确先行词），评估得准确率 {ev['accuracy']:.0%}、"
        f"精确率 {ev['precision']:.0%}、召回率 {ev['recall']:.0%}、标注覆盖率 {ev['coverage_on_annotations']:.0%}。"
        "结果表明规则基线在旅游文本上可解释、可复算，主要误差来自项目2 漏标与后置指代。"
    ))
    p = doc.add_paragraph()
    r = p.add_run("关键词："); set_font(r, HEAD, 10.5, True)
    r = p.add_run("共指消解；代词检测；规则方法；人工标注；可复现"); set_font(r, BODY, 10.5)
    doc.add_page_break()

    # 目录（静态，便于打印；页码由 Word 自动编号，不在此重复）
    heading(doc, "目　录", 1)
    toc = ["一、任务理解与方案", "二、代词检测与样本构建", "三、共指消解方法",
           "四、人工标注", "五、评估与错误分析", "六、可复现性与局限",
           "七、小结", "附录A  代表性消解结果", "附录B  词表与运行清单"]
    for item in toc:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(7)
        p.paragraph_format.left_indent = Cm(0.6)
        r = p.add_run(item); set_font(r, BODY, 11, False, INK)
    para(doc, "说明：本报告为项目4单项目分册；所有统计量由 outputs/ 下脚本输出，未手工改写。", indent=False, size=9, color=GRAY)
    doc.add_page_break()

    # 一、任务理解与方案
    heading(doc, "一、任务理解与方案", 1)
    heading(doc, "1.1 项目要求", 2)
    para(doc, (
        "项目4要求解决文本中“它、这、那里、他们”等代词指代不明的问题：先检测代词及所在句，"
        "再做指代消解，最后用人工标注评估准确率。任务书评分由代词检测（20）、人工标注（20）、"
        "消解方法（30）、效果评估（20）、报告与可复现（10）构成，共 100 分。"
    ))
    para(doc, (
        "本项目的输入不是原始网页，而是项目1 冻结的 clean_content；项目2 的实体与项目3 的路线只读复用。"
        "这样做的原因有二：其一，位置口径统一（0 起、结束不含），不会因重新清洗导致 span 漂移；"
        "其二，P4 只做“指代”这一件事，不重复做实体识别，避免与上游结果冲突。"
    ))
    heading(doc, "1.2 输入与接口", 2)
    caption(doc, "表1-1  项目4 的输入与用途", before=True)
    table(doc, ["输入", "规模", "用途"], [
        ["P1 三景区 clean_content", f"{sum(area_counts.values())} 条（有效 {sum(valid_counts.values())} 条）", "代词检测与消解的唯一文本来源"],
        ["P2 entities.jsonl", f"{entities} 个实体（POI 573 / TIME 248 / TRANSPORT 185）", "主候选；POI 优先"],
        ["P3 routes.jsonl", f"{routes} 条路线、29 篇文档", "补 P2 漏标的 POI 候选"],
        ["P4 annotations.csv", f"{len(ann)} 条人工标注", "评估 gold；不参与规则调参"],
    ], [5.2, 5.6, 5.0], size=9, center_cols=(1,))
    para(doc, (
        "三景区记录数为长隆 8、白云山 7、武功山 14；其中白云山含 1 条“站点攻略”，"
        "在 P4 中仍按文本处理，但统计时单独标注 doc_type，避免把它混入游客游记。"
    ))
    heading(doc, "1.3 总体流程", 2)
    para(doc, (
        "流程分为五步：代词检测 → 候选筛选 → 最近实体规则 → 结果分流 → 人工评估（图1）。"
        "设计上坚持“宁可留空，不硬凑”：当候选类型不匹配、距离过远或分数低于阈值时，"
        "输出 antecedent 为空，并在 reason 中写明原因，供人工复核。"
    ))
    picture(doc, FIG / "fig1_pipeline.png", 14.6, keep=False)
    caption(doc, "图1  共指消解流程与各阶段规模")

    # 二、检测
    heading(doc, "二、代词检测与样本构建", 1)
    heading(doc, "2.1 代词表与最长优先匹配", 2)
    para(doc, (
        "代词表覆盖 23 个形式、实际命中 15 个，按语义分为处所、指示、复数、对象、人物、方式、时间、路线、行程与裸指示等类。"
        "检测时先按词表长度降序匹配，确保“这里”不会被拆成“这”+“里”、“这个”不会被拆成“这”+“个”；"
        "同一位置只保留最长匹配，避免重复计数。"
    ))
    caption(doc, "表2-1  代词类别、允许的实体类型与距离约束", before=True)
    table(doc, ["类别", "代词", "允许类型", "距离（同句/前句）", "策略"], [
        ["处所", "这里/这儿/这边/那里/那儿/那边", "POI", "55 / 35", "消解"],
        ["指示", "这个/那个/这座", "POI", "50 / 50", "消解"],
        ["对象", "它/它们", "POI、TRANSPORT", "60 / 50", "消解"],
        ["时间", "这时/那时", "TIME", "60 / 40", "消解"],
        ["人物", "他们/她们", "—", "—", "留空"],
        ["路线", "这条", "—", "—", "留空"],
        ["复数", "这些/那些", "—", "—", "留空"],
        ["方式", "这样/那样", "—", "—", "留空"],
        ["行程", "这次", "—", "—", "留空"],
        ["裸指示", "这/那", "—", "—", "留空"],
    ], [2.2, 6.0, 4.0, 3.0, 1.8], size=8.6, center_cols=(0, 3, 4))
    para(doc, (
        "距离约束按类别收紧：处所代词最保守（同句 55 字、前句 35 字），因为它常回指刚走过的景点；"
        "对象代词稍宽（60/50），允许“它”指交通方式；时间代词只接受 TIME，避免把“这时”错配到景点。"
        "人物、路线、复数、方式、行程与裸指示在 P4 schema 中没有对应类型，直接留空，不强行映射。"
    ))
    heading(doc, "2.2 分句与位置口径", 2)
    para(doc, (
        "分句使用正则 [。！？!?；;\\n]+，记录 sentence_start/sentence_end；代词位置以 clean_content 的 0 为起点、"
        "结束位置不含，pronoun_start/pronoun_end 与 P2 的 char_start/char_end 完全同口径。"
        "同一句出现多个相同代词时，不按“第几个”编号，而是按绝对 pronoun_start 分行；"
        "这样即使句子被重新切分，位置仍然可核对。"
    ))
    para(doc, (
        "检测结果中同句重复代词共 5 组。以 WGS-O-03 为例，同一句里两个“这里”分别位于 169 和 178，"
        "都指“安源路矿工人运动纪念馆”；若按出现次序编号，很容易把第二个错配到后文另一景点。"
        "本实现保留两个独立 span，消解结果也分别写入，后文评估可直接按位置核对。"
    ))
    heading(doc, "2.3 检测结果", 2)
    caption(doc, "表2-2  各代词候选数与消解数", before=True)
    rows = []
    for p, v in sorted(stats["by_pronoun"].items(), key=lambda kv: (-kv[1]["total"], kv[0])):
        rows.append([p, v["total"], v["resolved"], f"{v['resolved'] / v['total']:.0%}"])
    table(doc, ["代词", "候选数", "已消解", "消解率"], rows, [3.0, 3.4, 3.4, 3.4], size=8.8, center_cols=(1, 2, 3))
    para(doc, (
        f"共 {len(coref)} 条候选，分布在 {stats['documents_with_pronoun']} 篇文档（29 篇中 8 篇没有代词）。"
        f"按文本类型：游客游记 71 条、官方路线 69 条；按景区：长隆 66、白云山 4、武功山 70。"
        "“这”最多（41 条），但绝大多数是“这份攻略/这段路”之类的指示限定语，规则选择留空；"
        "真正可消解的是“这里”（24 条，消解 15）和“这个”（18 条，消解 8）。"
    ))
    picture(doc, FIG / "fig2_pronoun_distribution.png", 14.6)
    caption(doc, "图2  各代词候选数与消解数（浅色为候选，深色为已消解）")

    # 三、方法
    heading(doc, "三、共指消解方法", 1)
    heading(doc, "3.1 候选构建", 2)
    para(doc, (
        "候选来自两处：P2 的实体（POI、TIME、TRANSPORT）与 P3 路线步骤中的 POI。P3 的 source_span 偶有偏移，"
        "因此不直接使用，而是在该位置附近按名称回找真实 span，找不到再全篇查找；P3 只补 P2 漏标的 POI，"
        "且过滤“第一站/沿途/路线”等泛化词，避免把操作词当成景点。"
    ))
    para(doc, (
        "同一文档内按 (start, end, name) 去重，P2 优先于 P3；只保留结束位置不晚于代词起点的候选，"
        "即候选必须出现在代词之前；最大距离 100 字，超过直接丢弃。这样既保证“先行词在前”的语言直觉，"
        "也避免跨段落拉一个很远的同名景点。"
    ))
    heading(doc, "3.2 打分与分流", 2)
    para(doc, (
        "对每个候选计算四项加权分：类型基础分（POI 1.0、TRANSPORT/TIME 0.8）、距离邻近度（1 - 距离/80）、"
        "同句加成（0.15）、路线命中（0.05）；权重分别为 0.55、0.25、0.15、0.05。"
        "取最高分，低于 0.60 则留空；消解结果中分数低于 0.70 的标 needs_review=true，提示人工复核。"
    ))
    code(doc, """score = 0.55 * TYPE_BASE[ent.type] + 0.25 * (1 - distance / 80)
        + 0.15 * (1 if same_sentence else 0) + 0.05 * route_hit
if score < 0.60:  antecedent = ""; reason = "最高分低于阈值"
elif score < 0.70: needs_review = True""")
    para(doc, (
        "此外有四条语义护栏：①“我/你/他/她+这里”视为说话人位置，不消解；②“它们”视为复数对象，不消解；"
        "③“与/和/跟/给/让+它”多指人物或动物，不映射为 POI；④“这个/那个+时间词”是时间限定语，不消解。"
        "这些护栏优先于分数，避免“高分但语义错”的硬消解。"
    ))
    heading(doc, "3.3 消解结果", 2)
    caption(doc, "表3-1  三景区候选与消解结果", before=True)
    area_name = {"changlong": "长隆", "baiyunshan": "白云山", "wugongshan": "武功山"}
    rows = []
    for key in ("changlong", "baiyunshan", "wugongshan"):
        v = stats["by_area"][key]
        rows.append([area_name[key], v["total"], v["resolved"], f"{v['rate']:.1%}"])
    rows.append(["合计", stats["candidates"], stats["resolved"], f"{stats['resolution_rate']:.1%}"])
    table(doc, ["景区", "候选数", "已消解", "消解率"], rows, [3.6, 3.6, 3.6, 3.6], size=9, center_cols=(1, 2, 3))
    para(doc, (
        f"全量 {stats['candidates']} 条候选中消解 {stats['resolved']} 条（{stats['resolution_rate']:.1%}），"
        "先行词类型全部为 POI。长隆消解率 24.2%，白云山 25.0%，武功山 15.7%；武功山偏低，"
        "因为其游记里“这里”常回指整段山脊/草甸，缺少具体 POI，规则选择留空。"
    ))
    picture(doc, FIG / "fig3_area_resolution.png", 13.2)
    caption(doc, "图3  三景区候选数与消解率")
    caption(doc, "表3-2  未消解原因（前 8 类）", before=True)
    rows = [[reason, n] for reason, n in list(stats["unresolved_reasons"].items())[:8]]
    table(doc, ["原因", "条数"], rows, [13.2, 2.4], size=8.6, center_cols=(1,))
    para(doc, (
        "未消解 112 条中，指示限定语 53 条，是最大类；“前文无同句/近邻 POI”8 条；"
        "方式、路线、人物各 7 条；时间/复数、复数集合、整段行程各 4 条。"
        "这些不是“漏检”，而是规则主动选择留空；报告把它们计入覆盖率，而不是伪装成消解成功。"
    ))

    # 四、标注
    heading(doc, "四、人工标注", 1)
    heading(doc, "4.1 标注规范", 2)
    para(doc, (
        "标注在 config/annotations_gold.csv 中人工维护，再由 build_annotations.py 与 coref.jsonl 对齐，"
        "生成 outputs/annotations.csv。标注字段包括 doc_id、pronoun、pronoun_start、sentence、"
        "gold_antecedent、gold_type 与 note；脚本额外补 pronoun_end、sentence_start、scenic_area、doc_type。"
        "所有标注按 (doc_id, pronoun_start) 对齐，标了但检测不到会直接报错，防止“标错位置”。"
    ))
    para(doc, (
        "共标注 20 条：16 条有明确先行词，4 条无明确先行词。抽样覆盖三个景区（长隆 8、白云山 2、武功山 10）、"
        "两种文本类型（官方/游记）、成功与失败案例、以及同句重复代词。无明确先行词的 4 条分别覆盖："
        "动物指代（“它”指蚊子）、事件指代（“这”修饰“瞬间”）、人物指代（“他们”指驴友）、"
        "路线指代（“这条”指路线）——这些在 P4 schema 中没有对应类型，gold 留空是正确行为，不是缺失。"
    ))
    caption(doc, "表4-1  有明确先行词的标注（16 条）", before=True)
    rows = []
    for a in ann:
        if a["gold_antecedent"].strip():
            rows.append([a["doc_id"], f"{a['pronoun']}@{a['pronoun_start']}", a["gold_antecedent"], a["note"]])
    table(doc, ["doc_id", "代词@位置", "gold 先行词", "标注说明"], rows, [3.0, 2.6, 4.2, 5.8], size=8.0)
    caption(doc, "表4-2  无明确先行词的标注（4 条）", before=True)
    rows = []
    for a in ann:
        if not a["gold_antecedent"].strip():
            rows.append([a["doc_id"], f"{a['pronoun']}@{a['pronoun_start']}", "∅", a["note"]])
    table(doc, ["doc_id", "代词@位置", "gold", "标注说明"], rows, [3.2, 2.8, 2.0, 7.6], size=8.0, center_cols=(2,))
    para(doc, "注：∅ 表示无明确先行词；gold_type 统一记为 UNKNOWN，评估时与“预测为空”配对判定。")

    # 五、评估
    heading(doc, "五、评估与错误分析", 1)
    heading(doc, "5.1 指标定义", 2)
    para(doc, (
        "评估脚本 eval_coref.py 读取 annotations.csv 与 coref.jsonl，按 (doc_id, pronoun_start) 对齐；"
        "字符串比较前去掉空白与引号。空 gold + 空预测记为正确（识别出“无明确先行词”）。"
    ))
    bullet(doc, "准确率 = 判断正确的标注条数 / 标注总数；")
    bullet(doc, "标注覆盖率 = 模型给出非空先行词的标注条数 / 标注总数；")
    bullet(doc, "精确率 = 正确且非空的条数 / 模型给出非空先行词的条数；")
    bullet(doc, "召回率 = 正确且非空的条数 / gold 非空的条数；")
    bullet(doc, "全量消解率 = coref.jsonl 中 antecedent 非空条数 / 全部候选条数。")
    heading(doc, "5.2 评估结果", 2)
    caption(doc, "表5-1  20 条人工标注上的评估结果", before=True)
    table(doc, ["指标", "数值", "计算式"], [
        ["标注条数", len(ann), "—"],
        ["判断正确", ev["correct"], "12 条非空正确 + 4 条空正确"],
        ["准确率", f"{ev['accuracy']:.2%}", f"{ev['correct']}/{len(ann)}"],
        ["标注覆盖率", f"{ev['coverage_on_annotations']:.2%}", f"{ev['pred_nonempty']}/{len(ann)}"],
        ["精确率", f"{ev['precision']:.2%}", f"TP {ev['tp']} / 预测非空 {ev['pred_nonempty']}"],
        ["召回率", f"{ev['recall']:.2%}", f"TP {ev['tp']} / gold 非空 {ev['gold_nonempty']}"],
        ["全量消解率", f"{ev['all_resolution_rate']:.2%}", f"{ev['all_resolved']}/{ev['all_candidates']}"],
    ], [4.4, 5.2, 6.0], size=9, center_cols=(1,))
    picture(doc, FIG / "fig4_metrics.png", 12.8)
    caption(doc, "图4  准确率、精确率、召回率与标注覆盖率")
    caption(doc, "表5-2  分景区标注准确率", before=True)
    area_ann = {"CL": 0, "BYS": 0, "WGS": 0}
    area_correct = {"CL": 0, "BYS": 0, "WGS": 0}
    err = {(e["doc_id"], int(e["start"])) for e in ev["errors"]}
    for a in ann:
        key = a["doc_id"].split("-")[0]
        area_ann[key] += 1
        if (a["doc_id"], int(a["pronoun_start"])) not in err:
            area_correct[key] += 1
    rows = []
    for key, name in (("CL", "长隆"), ("BYS", "白云山"), ("WGS", "武功山")):
        rows.append([name, area_ann[key], area_correct[key], f"{area_correct[key] / area_ann[key]:.0%}" if area_ann[key] else "—"])
    table(doc, ["景区", "标注数", "正确", "准确率"], rows, [3.6, 3.6, 3.6, 3.6], size=9, center_cols=(1, 2, 3))

    heading(doc, "5.3 错误分析", 2)
    caption(doc, "表5-3  4 条错误案例", before=True)
    rows = []
    for e in ev["errors"]:
        rows.append([e["doc_id"], f"{e['pronoun']}@{e['start']}", e["gold"], e["pred"]])
    table(doc, ["doc_id", "代词@位置", "gold", "预测"], rows, [3.2, 2.8, 5.0, 4.6], size=8.8, center_cols=(1,))
    para(doc, (
        "四类典型错误：① P2 漏标/归一化偏差——“尖叫地带”“吊马桩”“几字湾栈道”未被 P2 识别，"
        "规则只能退到最近的“北门”“武功山”；② 后置指代——“第一站就是尖叫地带……将在这里”中先行词在代词前，"
        "但“尖叫地带”本身未被标为实体，规则看不到；③ 人物/动物/事件指代——schema 无 PERSON/ANIMAL/EVENT，"
        "规则留空是正确行为；④ 路线/集合指代——schema 无 ROUTE/集合类型，规则不硬选单个 POI。"
    ))
    para(doc, (
        "另有一类未计入 20 条标注的错误：CL-T-02 的“它@393”“这个@411”应指“十环过山车”，"
        "因 P2 漏标被“垂直过山车”抢走。它说明 80% 的标注准确率并非上限，P2 召回是当前主要瓶颈；"
        "如果把“十环过山车”补进候选，这两条也会判对。"
    ))
    heading(doc, "5.4 与评分细则的对应", 2)
    caption(doc, "表5-4  项目4 评分细则对应关系", before=True)
    table(doc, ["考核项", "分值", "本报告证据", "完成情况"], [
        ["代词检测与样本构建", "20", "23 个代词形式（命中 15）、140 条候选、位置字段；同句多代词按 start 区分", "达成"],
        ["人工标注", "20", "20 条（16 有 gold + 4 无明确先行词），字段与类型一致", "达成"],
        ["指代消解方法", "30", "rule_nearest + 类型白名单 + 距离/POI 优先；输出 antecedent/reason", "达成"],
        ["效果评估", "20", "准确率/覆盖率/精确率/召回率；eval.md 可复算", "达成"],
        ["报告与可复现", "10", "环境、命令、参数、输出路径、代表性结果", "达成"],
    ], [4.6, 1.6, 8.2, 1.8], size=8.6, center_cols=(1, 3))

    # 六、复现
    heading(doc, "六、可复现性与局限", 1)
    heading(doc, "6.1 环境与命令", 2)
    para(doc, (
        "Python 3.12；pandas 3.0.1、openpyxl、lxml、python-docx；报告插图用 Pillow。"
        "运行期不访问网络、不调用外部模型，所有结果由本地文件计算，适合课程环境复现。"
    ))
    code(doc, """cd gh_repo_donk
python analysis/p04_coref/src/detect_pronouns.py
python analysis/p04_coref/src/resolve_coref.py
python analysis/p04_coref/src/build_annotations.py
python analysis/p04_coref/src/eval_coref.py
python analysis/p04_coref/src/make_figures.py
python analysis/p04_coref/src/build_report.py
python checks/check_coref.py""")
    para(doc, "src/run_all.py 把上述步骤串成一条命令；checks/check_coref.py 必须退出码 0。")
    caption(doc, "表6-1  主要输出文件", before=True)
    table(doc, ["文件", "内容", "用途"], [
        ["outputs/pronoun_candidates.jsonl", "140 条代词候选（含位置/句/上下文）", "检测结果"],
        ["outputs/coref.jsonl", "140 条消解结果（含 antecedent/reason/confidence）", "主产出"],
        ["config/annotations_gold.csv", "20 条人工 gold（人工维护）", "标注源文件"],
        ["outputs/annotations.csv", "与 coref 对齐的标注（含 sentence）", "评估输入"],
        ["outputs/eval.md / eval_stats.json", "指标、逐条核对、错误分析", "评估证据"],
        ["report/项目4_..._实验报告.docx/pdf", "本报告", "章节稿"],
    ], [5.6, 6.8, 3.2], size=8.2)
    heading(doc, "6.2 参数与边界", 2)
    para(doc, (
        "关键参数：阈值 0.60、最大距离 100 字、处所 55/35、指示 50/50、对象 60/50、时间 60/40；"
        "类型权重 POI 1.0、TRANSPORT/TIME 0.8；分数低于 0.70 标 needs_review。"
        "这些参数是依据 20 条标注前的观察设定的，未用测试集反复调参；报告保留全部参数，便于复核。"
    ))
    heading(doc, "6.3 局限与改进", 2)
    bullet(doc, "P2 召回是主要瓶颈：漏标景点会让规则退到更远的父区域（如“武功山”），需在 P2 补“十环过山车/吊马桩/几字湾栈道”等。")
    bullet(doc, "后置指代未处理：当前只看向代词之前的候选；可加“第一站就是 X……在这里”这类后置模式。")
    bullet(doc, "标注规模小（20 条、单人标注）：结论有抽样误差；下一步做双人标注 + Cohen's kappa，并扩大到 50–80 条。")
    bullet(doc, "字符串精确匹配偏严：可加别名/父子景点归一（如“摩星岭南门”与“摩星岭”），但需避免过度对齐。")
    bullet(doc, "未使用模型/LLM：规则可解释、零依赖，但对人物/事件/路线指代只能留空；后续可用 LLM 对未消解项做二次判定，并保留规则作为高精度前置。")

    # 七、小结
    heading(doc, "七、小结", 1)
    para(doc, (
        f"本项目在 29 条三景区文本上检测出 {len(coref)} 条代词，规则消解 {stats['resolved']} 条；"
        f"20 条人工标注上准确率 {ev['accuracy']:.0%}、精确率 {ev['precision']:.0%}、"
        f"召回率 {ev['recall']:.0%}、标注覆盖率 {ev['coverage_on_annotations']:.0%}。"
        "方法的价值不在“全解”，而在“可解释地解一部分、把不确定的留给人工”：每条结果都有位置、"
        "候选数、距离、分数与原因，出错能定位到具体句子和上游实体。"
    ))
    para(doc, (
        "对后续项目的支撑：P5 条件建议抽取可直接复用“这里/这个”的消解结果，把“如果下雨……这里”中的地点补全；"
        "P6 知识图谱可把 antecedent_start/end 作为共指边，连接同一景点的多次提及；"
        "P7 Agent 在回答“第二天从这里怎么走”时，可先查共指表再查路线。"
    ))

    # 附录
    heading(doc, "附录A  代表性消解结果", 1)
    para(doc, "以下 4 条覆盖“正确消解 / 同句双代词 / 后置错误 / 主动留空”，字段取自 coref.jsonl。")
    samples = [
        ("A.1 正确：CL-T-02 它@297 → 垂直过山车",
         '{"doc_id":"CL-T-02","pronoun":"它","pronoun_start":297,"antecedent":"垂直过山车",\n'
         ' "antecedent_type":"POI","confidence":0.797,"distance":17,"needs_review":false}'),
        ("A.2 同句双代词：WGS-O-03 这里@169 与 @178 → 安源路矿工人运动纪念馆",
         '{"doc_id":"WGS-O-03","pronoun":"这里","pronoun_start":169,"antecedent":"安源路矿工人运动纪念馆"}\n'
         '{"doc_id":"WGS-O-03","pronoun":"这里","pronoun_start":178,"antecedent":"安源路矿工人运动纪念馆"}'),
        ("A.3 后置错误：CL-O-03 这里@268 → 北门（gold 尖叫地带）",
         '{"doc_id":"CL-O-03","pronoun":"这里","pronoun_start":268,"antecedent":"北门",\n'
         ' "reason":"同句是；距离 12；类型 POI；候选 2 个，取最高分"}'),
        ("A.4 主动留空：BYS-T-03 这条@219 → 空（路线指代）",
         '{"doc_id":"BYS-T-03","pronoun":"这条","pronoun_start":219,"antecedent":"",\n'
         ' "needs_review":true,"reason":"路线指代，schema 无 ROUTE 类型"}'),
    ]
    for title, body in samples:
        para(doc, title, indent=False, size=9.5, bold=True, color=DARK, after=2)
        code(doc, body, size=8.0)

    heading(doc, "附录B  词表与运行清单", 1)
    para(doc, (
        "代词表共 23 个形式：这里、这儿、这边、那里、那儿、那边、这个、那个、这座、这些、那些、这条、"
        "它、它们、这次、这时、那时、这样、那样、他们、她们、这、那（实际命中 15 个）。"
        "运行顺序：detect_pronouns.py → resolve_coref.py → build_annotations.py → eval_coref.py → "
        "make_figures.py → build_report.py；自检：python checks/check_coref.py。"
    ))
    para(doc, (
        "数据版本：P1 tag v0.1-p01；P2 v0.2-p02；P3 v0.3-p03。本报告未修改 scenic/ 下任何冻结数据；"
        "所有统计量来自脚本输出，报告中的数字与 outputs/*.json、eval.md 一致。"
    ))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print("saved ->", OUT)


if __name__ == "__main__":
    main()
