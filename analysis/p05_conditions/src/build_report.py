# -*- coding: utf-8 -*-
"""生成《项目5：景区游览指南中的条件-建议抽取》实验报告（DOCX）。"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from lib.paths import analysis_dir  # noqa: E402

ROOT = analysis_dir("p05_conditions")
OUT_DIR = ROOT / "report"
FIG = ROOT / "outputs" / "figures"
OUT = OUT_DIR / "项目5_条件建议抽取_实验报告.docx"

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
    r = hp.add_run("2026《数据挖掘》探索性实验 · 项目5 · 条件-建议抽取")
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
    r = p.add_run("实验项目5：条件-建议抽取"); set_font(r, HEAD, 18, True, RGBColor(0x2E, 0x5C, 0x8A))
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("—— 从“如果/若/建议/可以”到可执行游览提示"); set_font(r, BODY, 15, False, INK)

    for _ in range(3):
        para(doc, "", indent=False)
    info = [("课程名称", "数据挖掘"),
            ("实验项目", "项目5 条件-建议抽取"),
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
    r = p.add_run("本报告为项目5分册；输入为项目1 三景区数据（tag v0.1-p01），项目2/3/4 产出只读。")
    set_font(r, "楷体", 9, False, GRAY)
    doc.add_page_break()


def main():
    rows = [json.loads(x) for x in (ROOT / "outputs" / "conditions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    stats = json.loads((ROOT / "outputs" / "condition_stats.json").read_text(encoding="utf-8"))
    ev = json.loads((ROOT / "outputs" / "eval_stats.json").read_text(encoding="utf-8"))
    with (ROOT / "outputs" / "manual_review.csv").open(encoding="utf-8-sig", newline="") as f:
        review = list(csv.DictReader(f))
    by_id = {r["cond_id"]: r for r in rows}

    doc = Document(); setup(doc)
    doc.core_properties.title = "项目5 条件-建议抽取"
    doc.core_properties.author = "数据挖掘课程小组"
    cover(doc)

    heading(doc, "摘　要", 1)
    para(doc, (
        f"本报告完成《数据挖掘》探索性实验项目5：从三景区 29 条游记/官方路线中抽取“条件→建议”对。"
        f"输入为项目1 冻结的 clean_content（28 条有效），输出 {stats['total']} 条条件-建议、去重后 {stats['unique']} 条，"
        f"覆盖 {stats['docs_with_conditions']} 篇文档（文档覆盖率 {stats['coverage']:.1%}）。"
        f"方法上先用显式触发词（如果/假如/要是/倘若/一旦/若/如）锁定条件，再用“游客状态/场景”窄表识别隐式条件，"
        f"要求同句出现建议标记，并用最近条件、建议边界扩展、同句多建议拆分和三类去重控制质量。"
        f"人工分层抽查 20 条：严格正确 {ev['correct']} 条（{ev['strict_accuracy']:.0%}）、部分正确 {ev['partial']} 条、"
        f"错误 {ev['wrong']} 条；宽松可用率 {ev['lenient_accuracy']:.0%}。"
        "结果表明规则基线在“条件明确、建议动作明确”的句子上稳定，主要误差来自隐式条件角色混淆与长句建议边界。"
    ))
    p = doc.add_paragraph()
    r = p.add_run("关键词："); set_font(r, HEAD, 10.5, True)
    r = p.add_run("条件-建议抽取；规则方法；隐式条件；去重；人工抽查"); set_font(r, BODY, 10.5)
    doc.add_page_break()

    heading(doc, "目　录", 1)
    for item in ["一、任务理解与数据", "二、抽取方法", "三、抽取结果", "四、去重与稀疏性",
                 "五、人工抽查与错误分析", "六、可复现性与局限", "七、小结",
                 "附录A  代表性记录", "附录B  运行与字段说明"]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(7)
        p.paragraph_format.left_indent = Cm(0.6)
        r = p.add_run(item); set_font(r, BODY, 11, False, INK)
    para(doc, "说明：本报告为项目5单项目分册；所有统计量由 outputs/ 下脚本输出，未手工改写。", indent=False, size=9, color=GRAY)
    doc.add_page_break()

    # 1
    heading(doc, "一、任务理解与数据", 1)
    heading(doc, "1.1 项目要求", 2)
    para(doc, (
        "项目5要求从游记与官方路线中抽取“在什么条件下、建议游客做什么”的程序性知识。"
        "任务书给出的触发词包括“如果/假如/若/建议/可以”等，要求条件与建议都是原文片段、边界正确；"
        "同一句有多个建议时要拆分并共享原句；去重要保留去重前后统计。"
    ))
    para(doc, (
        "这句话看起来简单，真正困难的是“条件”并不总由“如果”引导。游记里大量写法是"
        "“带娃贴士：婴儿车可租”“节假日建议错峰”“看日出一定要带厚衣服”，条件隐含在人群、天气、时间、"
        "体力、预算或交通场景里。因此本项目把抽取拆成两条路径：显式条件走触发词，隐式条件走窄表 + 建议标记，"
        "两条路径共用同一套建议边界和去重规则。"
    ))
    heading(doc, "1.2 输入与规模", 2)
    caption(doc, "表1-1  三景区输入与本次抽取覆盖", before=True)
    table(doc, ["景区", "文档数", "有效文档", "有条件的文档", "条件-建议条数"], [
        ["长隆", "8", "8", "6", "12"],
        ["白云山", "7", "7", "2", "8"],
        ["武功山", "14", "13", "5", "16"],
        ["合计", "29", "28", "13", "36"],
    ], [3.2, 3.0, 3.0, 3.8, 4.0], center_cols=(1, 2, 3, 4))
    para(doc, (
        "需要说明的是，“有条件的文档”只有 13 篇，并不代表另外 15 篇没有建议，而是它们的建议不以"
        "“条件 + 建议”的句法出现，例如纯路线描述、票价列表、景点介绍。项目5 只抽可还原为条件-建议对的知识，"
        "不把“建议游玩 3 小时”这类无条件的提示硬凑成条件句。"
    ), size=9.5, color=GRAY)

    # 2
    heading(doc, "二、抽取方法", 1)
    heading(doc, "2.1 句子切分与位置口径", 2)
    para(doc, (
        "以句号、问号、叹号和换行为边界切句，保留每条句子在 clean_content 中的绝对起止位置。"
        "后续所有 char_start / char_end 都是绝对位置（0 起、结束不含），这样条件、建议、原句三者可以"
        "在同一条记录里互相校验：检查脚本会验证 condition_text 和 suggestion_text 是否为 source_sentence 的子串。"
    ))
    heading(doc, "2.2 显式条件", 2)
    para(doc, (
        "显式触发词为“如果、假如、要是、倘若、一旦、若、如”。其中“如”做了两条限制：前面不能是“比”，"
        "且后面必须跟体力、天气、下雨、带、遇、时间、价格、想、不、果等条件线索，避免把“比如”“如此”当成条件。"
        "条件从触发词开始，到第一个逗号或“就/则/那/便/建议/可以”等连接词结束；建议从连接词之后开始。"
    ))
    caption(doc, "表2-1  显式条件示例", before=True)
    table(doc, ["cond_id", "条件", "建议"], [
        ["CND-0013", "如果体力不佳", "乘坐第一级索道返回，如体力充足也可选择徒步下山"],
        ["CND-0018", "学生", "提前一天预约可免门票（一定要提前预约）"],
        ["CND-0020", "如果拼车的价格超过30", "没有必要坐了，价格在30左右就是合理的"],
    ], [2.6, 6.0, 7.4])
    heading(doc, "2.3 隐式条件", 2)
    para(doc, (
        "隐式条件只收“游客状态/场景”，不把索道、徒步、排队这类主题词单独当条件。当前窄表覆盖："
        "天气（下雨/雨天/高温/低温/夏天/冬天等）、人群（带老人/带娃/亲子/学生/情侣/胆子小/怕累等）、"
        "时间（节假日/旺季/五一/看日出/拍日落/错峰等）、体力（体力不佳/膝盖负担/不想爬山等）、"
        "预算（预算有限/不想花钱/价格超过等）、交通（自驾/停车/不想坐索道等）以及其他（排队久/人多/预约不到等）。"
    ))
    para(doc, (
        "隐式条件必须同句出现建议标记，才认为它处在“条件-建议”结构里。标记分两类："
        "一类是建议词（建议/推荐/最好/记得/一定要/可以/可/适合/需要/应/务必/不要/别），"
        "另一类是动作词（带/穿/备好/提前/避开/选择/乘坐/坐/走/按/凭/持）。"
        "如果同句有多个条件，取离建议标记最近的那个，而不是最早出现的那个——这条规则修正了"
        "“打车……适合预算有限者”被误判成交通条件的问题。"
    ))
    heading(doc, "2.4 建议边界与同句多建议", 2)
    para(doc, (
        "建议从建议标记开始；但对“厚衣服一定要带上”“婴儿车可租”这类“宾语 + 标记”的结构，"
        "会把标记前 1–8 字的宾语并入建议，否则会得到“一定要带上”这种没有宾语的残片。"
        "同一句有多个建议时，按分号或“，+建议标记”拆分；拆分后每条建议共享同一个 source_sentence，"
        "但各自有独立的 suggestion 起止位置。"
    ))
    heading(doc, "2.5 过滤与去重", 2)
    para(doc, (
        "过滤规则包括：建议少于 4 字、建议超过 120 字、建议只有“可以/推荐/建议/适合”等空壳、"
        "建议含广告/心理测试/时效活动等明显非游览内容、建议与条件完全重叠。"
        "去重只标记 is_duplicate，不删除记录：同类型下条件+建议完全相同记 exact；"
        "前后缀相同且长度≥8 记 prefix_suffix；相似度≥0.90 记 near。这样既保留原始抽取，又能报告去重前后数量。"
    ))

    # 3
    heading(doc, "三、抽取结果", 1)
    para(doc, (
        f"最终得到 {stats['total']} 条条件-建议，去重后 {stats['unique']} 条（重复 {stats['total'] - stats['unique']} 条："
        f"exact {stats['duplicates'].get('exact', 0)}、prefix_suffix {stats['duplicates'].get('prefix_suffix', 0)}）。"
        f"显式条件 {stats['by_rule'].get('explicit_if', 0)} 条、隐式条件 {stats['by_rule'].get('implicit_condition', 0)} 条。"
    ))
    caption(doc, "图3-1  条件类型、景区分布、景区×类型与人工抽查结果", before=True)
    picture(doc, FIG / "condition_stats.png", 16.2, keep=False)
    caption(doc, "表3-1  条件类型与景区分布", before=True)
    type_order = ["天气", "人群", "时间", "体力", "预算", "交通", "其他"]
    area_order = ["长隆", "广州白云山", "武功山"]
    table_rows = []
    for t in type_order:
        table_rows.append([t] + [str(stats["by_area_type"].get(a, {}).get(t, 0)) for a in area_order] + [str(stats["by_type"].get(t, 0))])
    table_rows.append(["合计"] + [str(stats["by_area"].get(a, 0)) for a in area_order] + [str(stats["total"])])
    table(doc, ["类型", "长隆", "白云山", "武功山", "合计"], table_rows,
          [3.4, 3.2, 3.2, 3.2, 3.0], center_cols=(1, 2, 3, 4))
    para(doc, (
        "时间类最多（13 条），主要是因为“看日出/拍日落/节假日/旺季”在游记里高频，且通常伴随明确建议；"
        "人群类同样 13 条，集中在“带娃/亲子/学生/老人/情侣”。预算类只有 1 条，说明三景区文本里"
        "“条件式省钱建议”本身稀疏，而不是抽取器完全失效。"
    ))
    heading(doc, "3.1 代表性正确样本", 2)
    caption(doc, "表3-2  抽取正确、可直接用于游览提示的样本", before=True)
    table(doc, ["cond_id", "景区", "条件", "建议"], [
        ["CND-0002", "白云山", "节假日", "建议早点排队避开高峰期"],
        ["CND-0006", "白云山", "膝盖负担较大", "建议穿鞋底柔软的运动鞋"],
        ["CND-0007", "白云山", "拍日落", "建议下午4点半左右到达山顶广场或摩星岭"],
        ["CND-0009", "武功山", "如果特别爱干净的朋友", "建议携带自己的睡袋"],
        ["CND-0010", "武功山", "看日出", "厚衣服一定要带上"],
        ["CND-0013", "武功山", "如果体力不佳", "乘坐第一级索道返回"],
        ["CND-0026", "长隆", "小朋友", "别错过，拥有全球唯一大熊猫三胞胎的熊猫村"],
        ["CND-0036", "长隆", "雨天", "备好轻便雨衣更从容"],
    ], [2.4, 2.0, 4.6, 7.0])
    heading(doc, "3.2 仍需改进的样本", 2)
    caption(doc, "表3-3  典型边界/角色问题", before=True)
    table(doc, ["cond_id", "条件", "建议", "问题"], [
        ["CND-0001", "停车", "可停在金贵村长腰岭停车场，收费8元/小时", "“停车”是场景不是游客状态"],
        ["CND-0016", "如果时间差不多", "坐火车也可以的", "“时间”指代不明"],
        ["CND-0025", "小朋友", "都可以进入梦幻童话世界，打卡到人生照片", "建议缺具体项目/地点"],
        ["CND-0035", "儿童", "家长可在「奇幻漂流」旁休息亭同步观景", "条件为儿童，建议对象是家长"],
    ], [2.4, 4.0, 7.2, 3.6])

    # 4
    heading(doc, "四、去重与稀疏性", 1)
    para(doc, (
        f"去重前 {stats['total']} 条，去重后 {stats['unique']} 条。exact 重复 {stats['duplicates'].get('exact', 0)} 条，"
        f"prefix_suffix {stats['duplicates'].get('prefix_suffix', 0)} 条，near 0 条。重复主要来自同一官方路线在"
        "不同页面重复发布，以及游记作者把同一条提示写了两次。"
    ))
    para(doc, (
        f"文档覆盖率 {stats['coverage']:.1%}（{stats['docs_with_conditions']}/{stats['docs_valid']}）。"
        "这个数字不高，但在预期之内：游记以叙事为主，大量句子是“我们几点出发/走了多久/风景如何”，"
        "并不包含条件式建议；官方路线则多为景点介绍和票价表。项目5 的价值不在于把 28 篇都抽满，"
        "而在于把真正可执行的条件-建议对挑出来，并如实报告稀疏性。"
    ))
    para(doc, (
        "另一个值得报告的稀疏性是类型分布：预算类只有 1 条，交通类 4 条。原因是三景区文本中"
        "“如果预算有限……”这类写法很少，更多是直接给价格；这类信息更适合项目6 的推荐/路线任务，"
        "不应在项目5 里强行扩写。"
    ))

    # 5
    heading(doc, "五、人工抽查与错误分析", 1)
    heading(doc, "5.1 抽查设计", 2)
    para(doc, (
        "从 36 条中按景区分层抽取 20 条（白云山 7、武功山 7、长隆 6），覆盖全部 6 个有记录的条件类型。"
        "判定口径：条件与建议都成立且建议可执行，记“正确”；条件或建议有一侧偏弱、另一侧仍可用，记“部分正确”；"
        "条件/建议错配，或建议已失效、不属于游览建议，记“错误”。"
    ))
    caption(doc, "表5-1  20 条人工抽查结果（节选）", before=True)
    sample_ids = ["CND-0001", "CND-0002", "CND-0005", "CND-0007", "CND-0009", "CND-0010",
                  "CND-0016", "CND-0021", "CND-0025", "CND-0027", "CND-0028", "CND-0033", "CND-0035"]
    table_rows = []
    for cid in sample_ids:
        r = by_id[cid]
        rv = next((x for x in review if x["cond_id"] == cid), None)
        table_rows.append([cid, r["condition_type"], r["condition_text"], r["suggestion_text"],
                           rv["label"] if rv else ""])
    table(doc, ["cond_id", "类型", "条件", "建议", "判定"], table_rows,
          [2.4, 1.6, 4.4, 6.4, 2.0], center_cols=(1, 4))
    para(doc, "完整 20 条见 outputs/manual_review.csv；上表为节选，避免表格过长影响排版。", size=9, color=GRAY)
    heading(doc, "5.2 指标", 2)
    caption(doc, "表5-2  人工抽查指标", before=True)
    table(doc, ["指标", "计算", "结果"], [
        ["抽查条数", "分层抽样", f"{ev['reviewed']} 条"],
        ["严格正确", "仅“正确”", f"{ev['correct']}/{ev['reviewed']} = {ev['strict_accuracy']:.0%}"],
        ["部分正确", "条件或建议一侧偏弱", f"{ev['partial']}/{ev['reviewed']} = {ev['partial'] / ev['reviewed']:.0%}"],
        ["错误", "错配/失效/非游览", f"{ev['wrong']}/{ev['reviewed']} = {ev['wrong'] / ev['reviewed']:.0%}"],
        ["宽松可用率", "正确 + 部分正确", f"{ev['correct'] + ev['partial']}/{ev['reviewed']} = {ev['lenient_accuracy']:.0%}"],
        ["全量去重率", "重复/总数", f"{stats['total'] - stats['unique']}/{stats['total']} = {(stats['total'] - stats['unique']) / stats['total']:.0%}"],
    ], [3.8, 7.0, 5.2])
    para(doc, (
        f"严格准确率 {ev['strict_accuracy']:.0%}，宽松可用率 {ev['lenient_accuracy']:.0%}。"
        "两个口径差距来自 5 条“部分正确”：它们的建议本身可用，但条件角色偏弱或建议对象不完全一致。"
        "在课程作业场景下，宽松可用率更能反映“抽出来的东西能不能用”；但严格准确率更诚实，"
        "因此报告同时给出，不把部分正确混进正确。"
    ))
    heading(doc, "5.3 错误类型", 2)
    bullet(doc, "条件角色不一致（2 条）：CND-0035 条件为“儿童”，建议却写给家长；CND-0001 的“停车”是场景，不是游客状态。")
    bullet(doc, "条件指代过泛（1 条）：CND-0016 的“如果时间差不多”没有说明是什么时间，建议“坐火车”本身成立但条件不可直接执行。")
    bullet(doc, "建议缺具体对象（1 条）：CND-0025 只写“进入梦幻童话世界”，没有落到具体项目或地点。")
    bullet(doc, "时效性内容（1 条）：CND-0027 的“十周岁生日”是活动信息，不是稳定可复用的建议。")
    bullet(doc, "非游览建议（1 条）：CND-0028 的心理建设建议成立，但不属于景区游览操作。")

    # 6
    heading(doc, "六、可复现性与局限", 1)
    heading(doc, "6.1 复现", 2)
    para(doc, "所有步骤由脚本完成，不依赖手工改表。运行顺序如下（在仓库根目录）：")
    code(doc, "python analysis/p05_conditions/src/extract_conditions.py\n"
              "python analysis/p05_conditions/src/eval_conditions.py\n"
              "python analysis/p05_conditions/src/build_mapping.py\n"
              "python analysis/p05_conditions/src/make_figures.py\n"
              "python analysis/p05_conditions/src/build_report.py\n"
              "python checks/check_conditions.py")
    para(doc, "若使用本机捆绑运行时，把 python 换成对应的 python.exe 即可；脚本只依赖标准库 + openpyxl/Pillow/python-docx。")
    caption(doc, "表6-1  交付物清单", before=True)
    table(doc, ["文件", "说明"], [
        ["config/triggers.csv", "触发词/建议标记/条件线索表"],
        ["config/manual_review_gold.csv", "20 条人工抽查标注"],
        ["outputs/conditions.jsonl", "36 条条件-建议主表"],
        ["outputs/rejected.jsonl", "被过滤的候选及原因"],
        ["outputs/manual_review.csv", "20 条抽查明细"],
        ["outputs/映射表.xlsx", "条件-建议映射表（3 个工作表）"],
        ["outputs/figures/condition_stats.png", "统计图"],
        ["outputs/eval_conditions.md", "抽查评估报告"],
        ["report/项目5_条件建议抽取_实验报告.docx/.pdf", "本报告"],
    ], [8.4, 7.4], size=8.6)
    heading(doc, "6.2 局限", 2)
    bullet(doc, "规则是用同一批数据调出来的，20 条抽查不是独立测试集；严格准确率会偏乐观。")
    bullet(doc, "只有一名标注者，没有第二人复核，也没有 Cohen's κ；判定口径虽写在报告里，但主观性仍在。")
    bullet(doc, "隐式条件依赖窄表，未覆盖“带宠物/推轮椅/夜爬/摄影”等长尾场景；扩表会带来新的误抽。")
    bullet(doc, "长句建议边界仍是主要误差源；当前用“标记前 1–8 字并入”处理“厚衣服一定要带上”，但对更长的宾语短语不够稳。")
    bullet(doc, "时效性内容（活动、生日、临时票价）没有发布时间过滤；这类建议应在上层应用时按发布时间淘汰。")

    # 7
    heading(doc, "七、小结", 1)
    para(doc, (
        "项目5 交付了一个可解释、可复算的条件-建议抽取基线：29 条文档中抽出 36 条条件-建议（去重后 33 条），"
        "覆盖 13 篇文档；20 条人工抽查严格正确 70%、宽松可用 95%。"
        "它的优势是每个字段都能回溯到原句和绝对位置，适合作为后续推荐/路线任务的结构化输入；"
        "它的短板是隐式条件角色和长句边界，需要更多标注和更细的句法规则，或者引入小型语言模型做候选重排。"
    ))
    para(doc, (
        "如果要把项目5 从“可用基线”推进到“高分成果”，优先做三件事："
        "第一，把人工标注从 20 条扩到 50–100 条，并由第二名成员独立标注 20 条算 κ；"
        "第二，划出 dev/test，规则只在 dev 上调，test 上只评估一次；"
        "第三，对“条件角色”做专门校验（人群/场景/时间/预算），并把时效性内容单独打标签。"
    ))

    # 附录
    doc.add_page_break()
    heading(doc, "附录A  代表性记录", 1)
    para(doc, "以下为 conditions.jsonl 的 3 条原始记录（保留全部字段，便于核对位置口径）。", size=9, color=GRAY)
    for cid in ["CND-0007", "CND-0013", "CND-0026"]:
        r = by_id[cid]
        code(doc, json.dumps(r, ensure_ascii=False, indent=2), size=7.4)

    heading(doc, "附录B  运行与字段说明", 1)
    caption(doc, "表B-1  conditions.jsonl 字段", before=True)
    table(doc, ["字段", "含义"], [
        ["cond_id", "条件ID，CND-0001 起顺序编号"],
        ["doc_id / scenic_area", "来源文档与景区（保留原值）"],
        ["condition_type", "天气/人群/时间/体力/预算/交通/其他"],
        ["condition_text / suggestion_text", "条件、建议原文片段"],
        ["trigger_word", "显式触发词或隐式建议标记"],
        ["source_sentence", "所在原句"],
        ["char_start / char_end", "条件在 clean_content 中的绝对位置，左闭右开"],
        ["is_duplicate / duplicate_reason", "是否重复及 exact/prefix_suffix/near"],
        ["extract_rule / confidence", "explicit_if 或 implicit_condition；规则置信度"],
        ["suggestion_start / suggestion_end", "建议的绝对位置"],
    ], [6.0, 10.0], size=8.4)
    para(doc, "自检命令：python checks/check_conditions.py，应输出“检查通过，可用于交接”。", size=9, color=GRAY)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())