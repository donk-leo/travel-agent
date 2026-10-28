# -*- coding: utf-8 -*-
"""生成《项目1：三景区景区指南数据采集与预处理（小组汇总）》实验报告。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[3]
GROUP = ROOT / "scenic" / "summary"
OUT = GROUP / "report" / "项目1_三景区景区指南数据采集与预处理_实验报告.docx"
FIG = GROUP / "report" / "figures"
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
         after=4, line=1.4):
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


def quote(doc, text, size=9):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.line_spacing = 1.3
    p.paragraph_format.space_after = Pt(4)
    shade(p._p, "F7F9FC")
    r = p.add_run(text)
    set_font(r, "楷体", size, False, INK)
    return p


def table(doc, headers, rows, widths, size=8.6, center_cols=(), keep=True):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
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
            p.paragraph_format.line_spacing = 1.1
            if j in center_cols:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(str(v))
            set_font(r, BODY, size, False, INK)
    if keep:
        for row in t.rows[:-1]:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True
    return t


def picture(doc, path, width=16.0):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
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
    r = hp.add_run("2026《数据挖掘》探索性实验 · 项目1 · 三景区汇总")
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
    r = p.add_run("实验项目1：景区指南数据采集与预处理"); set_font(r, HEAD, 18, True, RGBColor(0x2E, 0x5C, 0x8A))
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("—— 长隆 · 广州白云山 · 武功山（小组汇总）"); set_font(r, BODY, 15, False, INK)
    for _ in range(3):
        para(doc, "", indent=False)
    info = [("课程名称", "数据挖掘"), ("实验项目", "项目1 景区指南数据采集与预处理"),
            ("覆盖景区", "长隆 / 广州白云山 / 武功山"),
            ("小组成员", "________（组长）　________　________"),
            ("学号／班级", "________　________"), ("提交日期", "2026 年 11 月")]
    t = doc.add_table(rows=0, cols=2); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for k, v in info:
        cells = t.add_row().cells
        cells[0].width, cells[1].width = Cm(4.2), Cm(9.0)
        p0 = cells[0].paragraphs[0]; p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p0.add_run(k + "："); set_font(r, HEAD, 10.5, True, GRAY)
        r = cells[1].paragraphs[0].add_run(v); set_font(r, BODY, 10.5, False, INK)
    para(doc, "", indent=False)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("本报告整合三位成员采集的长隆、白云山、武功山数据；各景区分册见对应目录。")
    set_font(r, "楷体", 9, False, GRAY)
    doc.add_page_break()


def main():
    df = pd.read_csv(GROUP / "data" / "三景区汇总数据集.csv", encoding="utf-8-sig", keep_default_na=False)
    df["is_valid"] = df["is_valid"].astype(str).str.lower().isin(["true", "1", "yes"])
    stats = json.loads((GROUP / "outputs" / "统计摘要.json").read_text(encoding="utf-8"))
    areas = ["长隆", "广州白云山", "武功山"]
    doc = Document(); setup(doc)
    doc.core_properties.title = "项目1 三景区景区指南数据采集与预处理（小组汇总）"
    cover(doc)

    heading(doc, "摘　要", 1)
    para(doc, (
        f"本报告整合长隆、广州白云山、武功山三个景区的官方推荐路线与游客游记，共 {len(df)} 条记录："
        f"官方路线 {stats['official']} 条、游客游记 {stats['travelogue']} 篇、站点攻略 {stats['guide']} 条，"
        f"有效 {int(df.is_valid.sum())} 条。三个景区均满足“官方路线≥1、有效游客游记≥3”。"
        f"原始 {stats['char_raw']} 字，清洗后 {stats['char_clean']} 字，整体删除率 "
        f"{1 - stats['char_clean'] / stats['char_raw']:.2%}；统一为 24 列字段，输出 CSV / Excel / JSONL，"
        "并给出各景区数量、缺失、重复与格式一致性检查。"
    ))
    p = doc.add_paragraph()
    r = p.add_run("关键词："); set_font(r, HEAD, 10.5, True)
    r = p.add_run("三景区；数据采集；文本清洗；数据质量；可复现"); set_font(r, BODY, 10.5)
    doc.add_page_break()

    heading(doc, "一、任务理解与数据来源", 1)
    heading(doc, "1.1 项目要求", 2)
    para(doc, (
        "项目1要求准备 3 个景区的官方推荐路线与游客游记，完成去 HTML/元数据/特殊字符、统一空白等清洗，"
        "输出含来源、景区、文本类型、原始内容等字段的结构化文件，并检查数量、缺失、重复与格式一致性。"
        "评分侧重数据准备（20 分）、清洗实现（40 分）、结构化输出与质量验证（25 分）、报告与可复现性（15 分）。"
    ))
    heading(doc, "1.2 三景区数据来源", 2)
    caption(doc, "表1-1  三景区数据来源与数量", before=True)
    rows = []
    for a in areas:
        g = df[df.scenic_area == a]
        rows.append([a, len(g), int((g.doc_type == "官方路线").sum()),
                     int((g.doc_type == "游客游记").sum()),
                     int((g.doc_type == "站点攻略").sum()),
                     "、".join(sorted(g.source_site.unique()))])
    table(doc, ["景区", "记录数", "官方路线", "游客游记", "站点攻略", "来源站点"],
          rows, [2.2, 1.4, 1.4, 1.4, 1.4, 7.2], center_cols={1, 2, 3, 4})
    para(doc, (
        "长隆 8 条由长隆负责人按本地历史数据集转换入库（官方 3 + 游记 5）；武功山 14 条为本人已完成的数据集；"
        "白云山 7 条由本人代整理（官方 3 + 游记 3 + 站点攻略 1），待白云山负责人复核。"
        "白云山原“官方路线”是景区指南首页，不是具体线路，因此补采了官网“游览推荐”A/B/C 线；"
        "补采页面的 URL 与 SHA256 记录在 `scenic/baiyunshan/data/raw/sources.csv`。"
    ))

    heading(doc, "二、采集与整合方案", 1)
    heading(doc, "2.1 原始材料盘点", 2)
    para(doc, (
        "整理前组员的平台 CSV 共 23 条，字段只有 6 列（景区/类型/标题/来源链接/采集时间/正文）。"
        "长隆已由负责人按本地历史数据集转换为 8 条标准数据；白云山的“官方路线”是景区指南首页，"
        "不是具体线路，去哪儿页面属于平台 SEO 攻略，不是个人游记。按 `docs/01_统一规范.md` 的口径，"
        "白云山改用官网 A/B/C 线，去哪儿记录改标为 `站点攻略`，无正文的小红书笔记剔除。"
    ))
    heading(doc, "2.2 补采官方路线", 2)
    caption(doc, "表2-1  补采的白云山官方路线页面", before=True)
    table(doc, ["记录ID", "景区", "标题", "来源", "发布日期"],
          [["BYS-O-01", "广州白云山", "白云山游览线路（A线）", "白云山官网", "2020-06-29"],
           ["BYS-O-02", "广州白云山", "白云山游览路线（B线）", "白云山官网", "2020-08-18"],
           ["BYS-O-03", "广州白云山", "白云山游览路线（C线）", "白云山官网", "2020-08-18"]],
          [2.0, 2.4, 6.2, 3.0, 2.0], center_cols={0, 1, 4})
    heading(doc, "2.3 统一字段与编号", 2)
    para(doc, (
        "三景区统一为 `docs/统一规范.md` 的 24 列：前 9 列（doc_id、scenic_area、doc_type、title、"
        "source_site、source_url、raw_content、clean_content、is_valid）为合并必需字段。"
        "doc_id 使用“景区码-O/T-两位序号”，doc_type 只允许“官方路线 / 游客游记 / 站点攻略”三种；"
        "去哪儿内容统一标为 `站点攻略`，不冒充个人游记。"
    ))
    picture(doc, FIG / "group_flow.png", 15.6)
    caption(doc, "图1  三景区数据整合流程")

    heading(doc, "三、数据清洗实现", 1)
    heading(doc, "3.1 平台噪声与小红书正文截取", 2)
    para(doc, (
        "组员的小红书 CSV 把整页文本（顶部导航、推荐流、笔记头、评论）都放进了“正文”。"
        "直接清洗会把推荐流的标题当成游记，因此先以笔记标题最后一次出现为锚点，截到“猜你想搜/评论/编辑于”"
        "等结束标记；标题后没有正文的记录（纯图片/视频笔记）直接判为空并从主表剔除。"
    ))
    code(doc, """t = re.sub(r"\\s*-\\s*小红书\\s*$", "", title).strip()
idxs = [i for i, ln in enumerate(lines) if ln == t or (len(t) > 8 and t in ln)]
start = idxs[-1] + 1          # 最后一次出现 = 笔记头
for j in range(start, len(lines)):
    if lines[j] in XHS_STOP or lines[j].startswith("猜你想搜"):
        end = j; break
body = [ln for ln in lines[start:end] if ln and not ln.startswith("#")]""")
    heading(doc, "3.2 清洗规则（R1–R8）", 2)
    caption(doc, "表3-1  三景区统一清洗规则", before=True)
    table(doc, ["编号", "问题", "处理方法", "示例/效果"],
          [["R1", "HTML 残留", "删除标签与实体，块级元素转换行", "官网正文保留分段"],
           ["R2", "站点噪声", "行级正则删除导航、按钮、版权、购票控件、日期行", f"删除噪声行 {int(df.noise_lines_removed.sum())} 行"],
           ["R3", "链接/联系方式", "删除 URL、邮箱；以链接为主的行整行删除", f"删除链接 {int(df.urls_removed.sum())} 个"],
           ["R4", "表情/异常符号", "删除 emoji、零宽字符、控制符；键帽数字还原", f"删除表情 {int(df.emoji_removed.sum())} 个"],
           ["R5", "空白/换行", "统一换行、压缩空格、去连续空行", "段落数稳定"],
           ["R6", "标点/字符宽度", "全角字母数字转半角、合并重复标点、去汉字间空格", "统一全半角"],
           ["R7", "重复段落", "完全重复 + 相似度≥0.90 去重", f"删除重复段 {int(df.dup_paragraphs_removed.sum())} 段"],
           ["R8", "编码/空值", "删除 U+FFFD；作者/日期缺失写“未知”", f"{stats['missing_author']}/{stats['missing_date']} 条缺失已标注"]],
          [1.0, 2.6, 6.8, 5.2], center_cols={0}, size=8.2)
    heading(doc, "3.3 关键代码", 2)
    code(doc, """def clean_text(raw, doc_type):
    text, stats = strip_noise_lines(raw)      # 菜单/平台页脚/URL/emoji
    text = normalize_punctuation(text)        # 空白、标点、全半角
    text, dup = dedupe_paragraphs(text)       # 完全重复 + 相似度≥0.90
    return {..., "clean_hash": sha1(去空白 text)}""")
    para(doc, (
        "平台噪声规则包括：官网菜单行（“首页 / 走进云山 / 景区动态…”）、购票控件行"
        "（“立即购票/选择地区/游玩日期”）、去哪儿“· 广州· 行程攻略· 发布时间”、"
        "小红书页脚（“首页/直播/发布/通知/消息/我”、备案号、行吟信息科技等）。"
    ), size=10)

    heading(doc, "四、结构化输出", 1)
    heading(doc, "4.1 字段与文件", 2)
    para(doc, (
        "24 列字段与组内规范完全一致，既保留 `raw_content` 供复核，也提供 `clean_content` 供项目2、3"
        "直接读取；`clean_hash` 用于跨景区去重，`is_valid`/`quality_flags` 保留质量信息。"
    ))
    caption(doc, "表4-1  主要输出文件", before=True)
    table(doc, ["文件", "内容", "用途"],
          [["scenic/changlong/data/processed/changlong_guides.csv", "长隆 8 条（24 列）", "景区交付/复查"],
           ["scenic/baiyunshan/data/processed/baiyunshan_guides.csv", "白云山 7 条（24 列）", "景区交付/复查"],
           ["scenic/wugongshan/data/processed/wugongshan_guides.csv", "武功山 14 条（24 列）", "景区交付/复查"],
           ["scenic/summary/data/三景区汇总数据集.csv", "29 条合并数据", "总报告/后续项目"],
           ["scenic/summary/outputs/三景区景区指南数据集.xlsx", "7 个工作表", "提交/答辩"],
           ["scenic/summary/outputs/三景区质量检查.md", "数量/缺失/重复/格式", "质量验证"]],
          [7.0, 4.8, 3.8], size=8.2)
    heading(doc, "4.2 数据样例", 2)
    para(doc, "官方路线（CL-O-01，清洗后节选）：", indent=False, size=10, bold=True)
    cl = df[df.doc_id == "CL-O-01"].iloc[0].clean_content
    quote(doc, cl[:260] + "……")
    para(doc, "游客游记（BYS-T-02，清洗后节选）：", indent=False, size=10, bold=True)
    bys = df[df.doc_id == "BYS-T-02"].iloc[0].clean_content
    quote(doc, bys[:220] + "……")

    heading(doc, "五、数据质量验证", 1)
    heading(doc, "5.1 数量与最低要求", 2)
    caption(doc, "表5-1  各景区数量与最低要求", before=True)
    rows = []
    for a in areas:
        g = df[df.scenic_area == a]
        valid_t = int(((g.doc_type == "游客游记") & g.is_valid).sum())
        rows.append([a, len(g), int((g.doc_type == "官方路线").sum()),
                     int((g.doc_type == "游客游记").sum()), valid_t,
                     "是" if int((g.doc_type == "官方路线").sum()) >= 1 and valid_t >= 3 else "否"])
    table(doc, ["景区", "记录数", "官方路线", "游客游记", "有效游记", "是否达标"],
          rows, [3.2, 2.4, 2.6, 2.6, 2.6, 2.6], center_cols={1, 2, 3, 4, 5})
    picture(doc, FIG / "group_area_type.png", 14.4)
    caption(doc, "图2  三景区记录构成")
    heading(doc, "5.2 长度与清洗效果", 2)
    para(doc, (
        f"三景区原始 {stats['char_raw']} 字，清洗后 {stats['char_clean']} 字，整体删除率 "
        f"{1 - stats['char_clean'] / stats['char_raw']:.2%}；删除噪声行 {int(df.noise_lines_removed.sum())} 行、"
        f"表情 {int(df.emoji_removed.sum())} 个、重复段落 {int(df.dup_paragraphs_removed.sum())} 段。"
        "删除比例不高，说明正文抽取已去掉大部分框架，清洗主要起精修作用。"
    ))
    picture(doc, FIG / "group_chars.png", 14.4)
    caption(doc, "图3  各景区清洗前后字数")
    heading(doc, "5.3 完整性、重复与格式", 2)
    caption(doc, "表5-2  完整性检查", before=True)
    rows = []
    for a in areas:
        g = df[df.scenic_area == a]
        rows.append([a, int((g.author == "未知").sum()), int((g.publish_date == "未知").sum()),
                     int(g.clean_hash.duplicated().sum()), len(g.columns)])
    table(doc, ["景区", "作者缺失", "日期缺失", "重复记录", "字段数"],
          rows, [3.4, 3.2, 3.2, 3.2, 3.0], center_cols={1, 2, 3, 4})
    para(doc, (
        f"全表 {len(df)} 条：doc_id 唯一且符合 `^[A-Z]{{2,5}}-[OT]-\\d{{2}}$`，doc_type 仅取三种允许值，"
        "`clean_content` 无空值，`clean_hash` 无重复，24 列与统一规范一致，编码 UTF-8-SIG。"
        f"作者缺失 {stats['missing_author']} 条、日期缺失 {stats['missing_date']} 条，主要来自白云山/武功山原始页面，"
        "统一写“未知”并打质量标记，没有伪造。"
    ), size=10)
    heading(doc, "5.4 发现的问题与处理", 2)
    caption(doc, "表5-3  主要问题与处理", before=True)
    table(doc, ["问题", "表现", "处理", "结果"],
          [["小红书纯图片", "标题后无文字正文", "按标题锚点截取；空记录剔除", "剔除 2 条纯图片/视频记录"],
           ["去哪儿属性", "平台 SEO 攻略", "标为站点攻略，不计入游客游记", "不冒充个人游记"],
           ["白云山官方路线", "原为景区指南首页", "补采官网 A/B/C 线", "官方路线 3 条"],
           ["长隆官方路线", "负责人已提供 3 条官网行程", "转换入库，不重复补采", "官方路线 3 条"],
           ["日期缺失", "采集时间≠发布时间", "写“未知”，不伪造", f"{stats['missing_date']} 条已标注"]],
          [2.8, 4.6, 4.8, 3.2], size=8.2)
    heading(doc, "5.5 与评分细则的对应", 2)
    caption(doc, "表5-4  评分细则对应关系", before=True)
    table(doc, ["考核项", "分值", "对应证据", "完成情况"],
          [["数据准备与来源规范", "20", f"3 景区/{len(df)} 条；来源表 1-1；官方补采表 2-1；24 列字段", "达成"],
           ["数据清洗与预处理实现", "40", "R1–R8 + 平台规则；小红书正文截取；空值/重复处理；代码", "达成"],
           ["结构化输出与质量验证", "25", "CSV/Excel；表 5-1/5-2；质量报告与前后对比", "达成"],
           ["报告与可复现性", "15", "依赖/命令/路径；代码片段；问题表 5-3", "达成"]],
          [4.8, 1.4, 7.4, 2.0], center_cols={1, 3})

    heading(doc, "六、可复现性说明", 1)
    heading(doc, "6.1 环境与命令", 2)
    bullet(doc, "Python 3.11+（实测 3.12）；pandas、openpyxl、lxml、python-docx。")
    bullet(doc, "合并/质检/报告生成脚本在 `scenic/summary/src/`；三个景区的数据由各自目录维护，本报告只读 `clean_content`。")
    code(doc, """cd scenic/summary
python src/build_summary.py           # 三景区合并 + 统计
python src/qc_summary.py              # 质量检查 + Excel
python src/make_summary_figures.py    # 插图
python src/build_summary_report.py    # 本报告
python ../../checks/check_scenic.py data/三景区汇总数据集.csv""")
    heading(doc, "6.2 输入输出", 2)
    caption(doc, "表6-1  主要输入输出", before=True)
    table(doc, ["环节", "输入", "输出"],
          [["补采", "白云山官网 A/B/C 线 URL", "scenic/baiyunshan/data/raw/sources.csv"],
           ["构建", "scenic/changlong、baiyunshan、wugongshan 的 24 列 CSV", "scenic/summary/data/三景区汇总数据集.csv"],
           ["质检", "三景区汇总数据集.csv", "三景区质量检查.md、Excel、统计摘要.json"],
           ["报告", "CSV/统计/插图", "项目1_三景区…docx/pdf"]],
          [2.2, 6.8, 6.6], size=8.2)
    heading(doc, "6.3 局限", 2)
    bullet(doc, "小红书采集依赖登录态，部分纯图片笔记无正文，已剔除；复现时需重新登录。")
    bullet(doc, "去哪儿页面是平台编辑攻略，按统一规范标为站点攻略，不伪造个人游记。")
    bullet(doc, "作者/发布日期缺失较多，是原始页面限制；报告如实标注，不做推断。")
    bullet(doc, "长隆/白云山官方页面可能改版，补采脚本按当前结构定位；改版后需调整 XPath。")

    heading(doc, "七、小结", 1)
    para(doc, (
        f"本报告把三个景区的已冻结数据整合为 {len(df)} 条、24 列的统一数据集："
        f"长隆 8 条、白云山 7 条、武功山 14 条，官方路线 {stats['official']} 条、"
        f"游客游记 {stats['travelogue']} 篇（有效 {int(((df.doc_type == '游客游记') & df.is_valid).sum())} 篇）、"
        f"站点攻略 {stats['guide']} 条；三个景区均达到“官方路线≥1、有效游客游记≥3”。"
        "相比简单拼接，本方案保留原始内容与清洗统计，对空文本、平台噪声、小红书整页文本、"
        "官方路线缺失等问题都有明确处理记录，可直接支撑项目2、3。"
    ))
    doc.add_page_break()
    heading(doc, "附录A  数据来源", 1)
    para(doc, f"完整 {len(df)} 条 URL 见 `三景区汇总数据集.csv` 的 `source_url` 列；下表列出补采的白云山官方路线。", size=9.5)
    table(doc, ["记录ID", "来源链接"],
          [["BYS-O-01", "https://www.baiyunshan.com.cn/bys/lytj/202006/64091ad56c74407f8475ae9ff2de3f81.shtml"],
           ["BYS-O-02", "https://www.baiyunshan.com.cn/bys/lytj/202008/a1dc4c2358d140059126c530847e1c0b.shtml"],
           ["BYS-O-03", "https://www.baiyunshan.com.cn/bys/lytj/202008/e988337476ac4eef9b978956f0845c9a.shtml"]],
          [2.2, 13.2], size=7.6, center_cols={0})
    para(doc, (
        "组员原始采集脚本与结果在 `archive/legacy_collect_2026-10-28/`；武功山分册见 "
        "`scenic/wugongshan/report/`，长隆分册见 `scenic/changlong/README.md`。"
    ), size=9.5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print("saved:", OUT)


if __name__ == "__main__":
    main()
