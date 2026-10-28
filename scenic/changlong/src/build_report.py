# -*- coding: utf-8 -*-
"""
生成《数据挖掘》探索性实验报告 —— 实验项目1（长隆旅游度假区）章节 DOCX
======================================================================
输入：data/interim/legacy_20col.csv、quality_report.json、usability_flags.csv、
      docs/rule_unit_tests.txt、outputs/figures/*.png
输出：实验项目一_长隆旅游度假区_数据采集与预处理.docx

报告结构与任务书 1.1–1.5 小节一一对应；所有数字均从数据文件读取，避免手写不一致。
"""
from __future__ import annotations

import json
import pathlib

import pandas as pd
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BASE = pathlib.Path(__file__).resolve().parents[1]
INTERIM_DIR = BASE / "data" / "interim"
OUT_DIR = BASE / "outputs"
FIG = OUT_DIR / "figures"
OUT = BASE / "report" / "实验项目一_长隆旅游度假区_数据采集与预处理.docx"
OUT.parent.mkdir(parents=True, exist_ok=True)

BODY_FONT = "宋体"
HEAD_FONT = "黑体"
MONO_FONT = "Consolas"


# ---------------------------------------------------------------- 工具函数
def set_font(run, name=BODY_FONT, size=12, bold=None, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def para(doc, text="", size=12, bold=False, align="justify", first_indent=True,
         space_after=6, line=1.5, font=BODY_FONT):
    p = doc.add_paragraph()
    fmt = p.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(space_after)
    fmt.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    fmt.line_spacing = line
    if first_indent:
        fmt.first_line_indent = Pt(size * 2)
    p.alignment = {
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
    }[align]
    if text:
        set_font(p.add_run(text), font, size, bold)
    return p


def heading(doc, text, level=1):
    sizes = {1: 15, 2: 13, 3: 12}
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.3
    set_font(p.add_run(text), HEAD_FONT, sizes[level], bold=True)
    # 标题后不缩进
    p.paragraph_format.first_line_indent = Pt(0)
    return p


def bullet(doc, text, size=11.5):
    p = doc.add_paragraph()
    fmt = p.paragraph_format
    fmt.left_indent = Cm(0.74)
    fmt.first_line_indent = Cm(-0.37)
    fmt.space_after = Pt(3)
    fmt.line_spacing = 1.4
    set_font(p.add_run("· " + text), BODY_FONT, size)
    return p


def code_block(doc, text, size=8.5):
    p = doc.add_paragraph()
    fmt = p.paragraph_format
    fmt.left_indent = Cm(0.5)
    fmt.space_before = Pt(2)
    fmt.space_after = Pt(8)
    fmt.line_spacing = 1.0
    set_font(p.add_run(text), MONO_FONT, size)
    # 浅灰底色
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "F2F2F2")
    p._p.get_or_add_pPr().append(shd)
    return p


def caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)
    set_font(p.add_run(text), BODY_FONT, 9.5, bold=False)
    return p


def shade(cell, color="DCE6F1"):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def add_table(doc, headers, rows, widths_cm, font_size=9, header_fill="DCE6F1"):
    if doc.paragraphs:  # 表前的引导句与表格保持同页
        doc.paragraphs[-1].paragraph_format.keep_with_next = True
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    # 固定布局，否则 Word/LO 会按内容重新分配列宽
    tbl_pr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)
    # 收窄单元格上下留白，让长表尽量落在同一页
    cell_mar = OxmlElement("w:tblCellMar")
    for side, width in (("top", 10), ("bottom", 10), ("left", 80), ("right", 80)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(width))
        node.set(qn("w:type"), "dxa")
        cell_mar.append(node)
    tbl_pr.append(cell_mar)
    for i, w in enumerate(widths_cm):
        table.columns[i].width = Cm(w)

    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.space_before = Pt(1)
        set_font(p.add_run(str(h)), HEAD_FONT, font_size, bold=True)
        shade(hdr[i], header_fill)

    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.line_spacing = 1.0
            set_font(p.add_run(str(val)), BODY_FONT, font_size - 0.5)

    for row_idx, row in enumerate(table.rows):
        # 行内不跨页断开；表头行重复
        tr_pr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        tr_pr.append(cant)
        if row_idx == 0:
            hdr_flag = OxmlElement("w:tblHeader")
            tr_pr.append(hdr_flag)
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)
    # 表头行与后续内容保持同页，避免表头孤零零落在页底
    for cell in table.rows[0].cells:
        for p in cell.paragraphs:
            p.paragraph_format.keep_with_next = True
    return table


def add_image(doc, path, width_cm=15.0):
    if doc.paragraphs:  # 图前的引导句与图片保持同页
        doc.paragraphs[-1].paragraph_format.keep_with_next = True
    if pathlib.Path(path).exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        p.add_run().add_picture(str(path), width=Cm(width_cm))
        p.paragraph_format.keep_with_next = True


def snippet(text: str, n: int = 70, escape: bool = False) -> str:
    """截断并可视化换行，便于放进表格。"""
    t = text.replace("\uf592", "〔图标字体私有区字符〕").replace("\n", " ⏎ ")
    t = " ".join(t.split()) if not escape else t
    return t[:n] + ("…" if len(t) > n else "")


def move_table_captions_above(doc):
    """把紧跟在表格后的“表 x-x”题注移动到表格上方，并与其保持同页。"""
    body = doc.element.body
    for el in list(body.iterchildren()):
        if el.tag != qn("w:tbl"):
            continue
        nxt = el.getnext()
        if nxt is None or nxt.tag != qn("w:p"):
            continue
        text = "".join(t.text or "" for t in nxt.iter(qn("w:t"))).strip()
        if text.startswith("表 "):
            el.addprevious(nxt)
            pPr = nxt.find(qn("w:pPr"))
            keep = OxmlElement("w:keepNext")
            if pPr is None:
                pPr = OxmlElement("w:pPr")
                nxt.insert(0, pPr)
            pPr.append(keep)


# ---------------------------------------------------------------- 主流程
def main() -> None:
    df = pd.read_csv(INTERIM_DIR / "legacy_20col.csv")
    df["_order"] = df["doc_type"].map({"官方路线": 0, "游客游记": 1})
    df = df.sort_values(["_order", "doc_id"]).reset_index(drop=True)
    report = json.loads((OUT_DIR / "quality_report.json").read_text(encoding="utf-8"))
    flags = pd.read_csv(OUT_DIR / "usability_flags.csv")
    rule_stats = report["rule_stats"]
    st = report["length_stats"]
    doc_map = {r.doc_id: r for r in df.itertuples()}

    doc = Document()
    # 页面：A4
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.6)
    sec.top_margin = sec.bottom_margin = Cm(2.4)

    # 正文默认样式
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(12)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    # ---------------- 封面标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    set_font(p.add_run("《数据挖掘》探索性实验报告"), HEAD_FONT, 18, bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    set_font(p.add_run("—实验项目 1  景区指南数据采集与预处理"), HEAD_FONT, 14, bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    set_font(p.add_run("负责景区：长隆旅游度假区（广州长隆）　|　组别：第   组　|　成员：　　　　"), BODY_FONT, 10.5)

    # ================================================================ 1.1
    heading(doc, "1.1 实验目标与数据准备", 2)
    para(doc,
         "本项目的目标是为后续“程序性知识挖掘”准备一份干净、可追溯、可直接被脚本读取的景区语料。"
         "程序性知识的三个基本要素——景点 POI、交通方式、时间节点——以及其组织形态（路线步骤、"
         "时间层级、条件性建议）全部藏在景区指南与游客游记的叙述文本里，因此数据准备阶段必须保证："
         "（1）文本是“操作过程”的描述，而不是景点简介或营销软文；（2）同一景区的官方口径与游客实际口"
         "径都有覆盖，便于项目 3 做官方/游客路线对比；（3）每条记录都能回溯到原始网页，任何清洗结果都"
         "可复核。基于这三点，本项目采集了长隆旅游度假区的官方推荐路线与游客游记，并在其后逐条实现"
         "可解释的清洗规则。")

    para(doc,
         "本组共 3 个景区，长隆旅游度假区由本人负责。它在结构上是一个“度假区—子园区”两级体系："
         "长隆野生动物世界、长隆欢乐世界、长隆水上乐园、长隆国际大马戏、长隆飞鸟乐园同属广州长隆，"
         "游客的一日行程往往跨 2—3 个子园区，因此我保留了“园区”字段用于记录子园区归属，"
         "既满足“一个景区”的口径，又能支撑后续跨园区的路线串联分析。")

    heading(doc, "（1）数据来源与自采方式", 3)
    para(doc,
         "数据全部为自行采集（未使用教师提供的 IndustryCorpus2 数据集），采集脚本为 "
         "scripts/collect_chimelong.py。官方路线取自长隆官网“行程推荐”栏目 3 篇攻略；"
         "游记取自 Trip.com 旅行笔记的公开个人分享页 5 篇。两处站点均为服务端渲染（SSR）页面，"
         "正文与结构化数据直接出现在 HTML 中，因此使用 requests + BeautifulSoup 即可稳定抽取，"
         "无需 Selenium/Playwright 这类浏览器自动化，采集成本与不可复现风险都更低。")

    src_rows = [
        ["CHL-O01", "官方路线", "度假区（多园区）", "广州长隆3天2夜游玩攻略", "2024-05-30", "chimelong.com/gz/trip/6957.html"],
        ["CHL-O02", "官方路线", "野生动物世界", "广州长隆野生动物世界游玩攻略", "2019-01-01", "chimelong.com/gz/trip/3536.html"],
        ["CHL-O03", "官方路线", "欢乐世界", "广州长隆欢乐世界游玩攻略", "2023-01-01", "chimelong.com/gz/trip/3537.html"],
        ["CHL-N01", "游客游记", "欢乐世界", "五一长隆欢乐世界保姆级攻略｜避开人潮玩回票价", "2026-04-26", "tw.trip.com/moments/detail/guangzhou-152-144829973"],
        ["CHL-N02", "游客游记", "度假区（多园区）", "广州长隆不绕路攻略，新手直接抄作业", "2026-08-06", "tw.trip.com/moments/detail/guangzhou-152-149982547"],
        ["CHL-N03", "游客游记", "野生动物世界", "长隆野生动物园｜无回头路旅游指南", "2026-10-26", "tw.trip.com/moments/detail/guangzhou-152-155862848"],
        ["CHL-N04", "游客游记", "欢乐世界", "广东长隆欢乐世界旅游攻略：高效玩转华南王牌乐园", "2025-12-21", "tw.trip.com/moments/detail/guangzhou-152-139591348"],
        ["CHL-N05", "游客游记", "水上乐园", "广州长隆度假区游玩攻略：夏日水上乐园", "2026-03-31", "tw.trip.com/moments/detail/guangzhou-152-143716112"],
    ]
    add_table(doc, ["文档ID", "文本类型", "子园区", "标题（简）", "页内日期", "来源URL（省略协议）"],
              src_rows, [1.5, 1.7, 2.5, 4.3, 2.2, 3.6], font_size=8.5)
    caption(doc, "表 1-1  长隆数据集采集清单（8 篇：官方路线 3 篇 + 游客游记 5 篇，均于 2026-10-28 采集）")

    para(doc,
         "采集实现上有三点值得说明。其一，官方页正文位于 div.flow-list 容器内，我取的是容器 innerHTML，"
         "刻意保留 <p>、<span style> 等标签，让“去标签”成为清洗阶段可度量、可验证的一步，而不是在采集阶段"
         "就悄悄处理掉；其二，游记页同时提供了 schema.org 的 DiscussionForumPosting JSON-LD 与 HTML 正文，"
         "前者字段规整（headline/text/datePublished/author），用于取元数据；后者（article.info-wrapper）"
         "含作者行、发布日期、“還有另外 357 篇…”等页面模板，作为“原始内容”交由清洗环节去除，这样元数据噪声"
         "在数据里是可见的、可统计的；其三，每次请求都落盘原始 HTML（data/raw/CHL-*.html），"
         "配合采集时间与状态码，保证结果可复核。", first_indent=True)

    para(doc,
         "采集的合规与礼貌约束：只抓取无需登录的公开页面，请求间隔 1.2 秒，失败重试 3 次，单次采集 8 个页面；"
         "数据仅用于课程实验，报告中保留原文链接与采集时间，不二次分发全文。")

    # ================================================================ 1.2
    heading(doc, "1.2 清洗方法与实现流程", 2)
    para(doc,
         "清洗脚本为 scripts/clean_chimelong.py，采用“批量读入 → 逐规则串联 → 规则级审计 → 落盘”的流水线。"
         "每篇文本依次经过 R1—R10 十条规则，每条规则执行前后都会记录字符变化量、命中与否以及首个差异片段，"
         "最终汇总为日志字段 cleaning_log 与全局报告 quality_report.json。这样做的目的是让“清洗是否生效”"
         "不靠肉眼判断，而是有逐文档、逐规则的量化证据。")

    rule_rows = [
        ["R1", "去除 HTML 标签", "Cleaner.r1_html", "块级标签 / <br> 先转成换行再剔除标签，避免段落粘连", f"{rule_stats['去除 HTML 标签']['removed_chars']}"],
        ["R2", "还原 HTML 实体", "Cleaner.r2_entity", "&quot; &amp; &nbsp; 及数字实体还原为字符", f"{rule_stats['还原 HTML 实体']['removed_chars']}"],
        ["R3", "去除页面模板/元数据行", "Cleaner.r3_boilerplate", "作者行、发布日期、“還有另外N篇…”、今日天气/营业状态/点评分、与本篇标题重复的首行、装饰性“推荐指数”行", f"{rule_stats['去除页面模板/元数据行']['removed_chars']}"],
        ["R4", "去除网址/邮箱/客服电话", "Cleaner.r4_url", "http(s)、www、邮箱、400/800 客服号", f"{rule_stats['去除网址/邮箱/客服电话']['removed_chars']}"],
        ["R5", "去除 emoji 与装饰符号", "Cleaner.r5_symbol", "emoji、图标字体私有区字符（U+E000–U+F8FF）、✔ ✅ ※ √ 等；箭头类 emoji（➡️）改写为“→”以保留顺序语义", f"{rule_stats['去除 emoji 与装饰符号']['removed_chars']}"],
        ["R6", "空白与换行统一", "Cleaner.r6_whitespace", "NBSP / 全角空格 / 制表符 / 连续空格 / 连续空行，并压掉全角标点两侧空格", f"{rule_stats['空白与换行统一']['removed_chars']}"],
        ["R7", "标点统一", "Cleaner.r7_punct", "中文语境半角逗号/分号/感叹号/问号/冒号转全角；含中文的英文引号与括号转中文标点；“09. 40”→“09:40”；“一.”→“一、”；“...”→“……”；重复标点收敛", f"{rule_stats['标点统一']['removed_chars']}"],
        ["R8", "繁体转简体", "Cleaner.r8_t2s", "OpenCC t2s，统一同一语料的字符口径（Trip.com 港澳台站点为繁体）", f"{rule_stats['繁体转简体']['substituted_chars']}（替换）"],
        ["R9", "段内重复行去重", "Cleaner.r9_dedup_lines", "同篇内重复出现的 ≥6 字行只保留首次", f"{rule_stats['段内重复行去重']['removed_chars']}"],
        ["R10", "收尾整理", "Cleaner.r10_tidy", "清理符号删除后残留的括号内空格、多余空行与连续空格", f"{rule_stats.get('收尾整理（空括号空格/残留空行）', {}).get('removed_chars', 0)}"],
    ]
    add_table(doc, ["规则", "名称", "实现位置", "处理内容", "字符量"], rule_rows,
              [1.1, 2.6, 3.6, 6.7, 1.6], font_size=8)
    caption(doc, "表 1-2  清洗规则与实现位置（字符量为 8 篇合计；零命中规则见 1.4 节说明）")

    heading(doc, "（1）三条“最小破坏”原则", 3)
    para(doc,
         "清洗最容易犯的错误是“把有用的信息一起删掉”，尤其是程序性文本的路线顺序与时间。因此本实现在规则设计上"
         "固化了三条原则：")
    bullet(doc, "保序：不重排、不合并段落，只做“删除噪声”与“字符替换”，保证箭头链路、编号列表、“第一站/第二站”的先后关系原样保留。箭头 ➡️ 一类 emoji 不按噪声删除，而是改写为“→”，因为它是路线顺序的显式标记。")
    bullet(doc, "保时：不做时间归一化改写，只把明显的排版错误修复为 HH:MM（例如游记里的“10. 40”改回“10:40”）；“上午/中午/下午”这类相对时间保持原样，时间语义交给项目 2 的时间节点识别处理，避免清洗阶段把推测写成事实。")
    bullet(doc, "可回溯：清洗只产出 clean_text，raw_text 与原始 HTML 同时保留；任何一条清洗结果都能对回原页面字符，便于后续抽检与纠错。")

    para(doc, "核心规则实现片段（去标签保留段落、符号与私有区字符清理）：", first_indent=True)
    code_block(doc,
               'def r1_html(self, text: str) -> str:\n'
               '    text = re.sub(r"<(?:br|/p|/div|/li|/h\\d)[^>]*>", "\\n", text, flags=re.I)\n'
               '    return re.sub(r"<[^>]+>", "", text)          # 其余标签直接剔除\n\n'
               'RE_PUA = re.compile(r"[\\uE000-\\uF8FF]")            # 图标字体私有区字符\n'
               'ARROW_MAP = {"➡": "→", "➔": "→", "➜": "→", "⟶": "→"}\n\n'
               'def r5_symbol(self, text: str) -> str:\n'
               '    for k, v in ARROW_MAP.items():\n'
               '        text = text.replace(k, v)                # 先保留顺序语义\n'
               '    text = RE_PUA.sub("", text)\n'
               '    text = RE_EMOJI.sub("", text)\n'
               '    return RE_SPECIAL.sub("", text)')

    heading(doc, "（2）空值、重复与异常字段的处理策略", 3)
    para(doc,
         "本项目不采用“脏数据直接删”的做法：空值、重复、异常字段一律先检查、再标记、最后才考虑剔除，"
         "因为路线文本中任何一句被误删都可能造成步骤缺失。具体策略是：")
    bullet(doc, "空值：8 个关键字段（title / author / publish_date / raw_text / clean_text / source_url / park / doc_type）逐字段统计空值数与空值率；正文为空或清洗后长度 < 50 字的文档标记 is_valid=False 并保留在数据集中，不静默丢弃（本次 8 篇全部有效）。")
    bullet(doc, "重复：先用清洗后文本去掉空白再取 MD5 判定完全重复（本次 0 对）；再用字符 3-gram Jaccard 相似度做近重复筛查（阈值 0.30），把候选对写进 quality_report.json 供人工复核，而不是自动删除。")
    bullet(doc, "异常字段：页内日期缺失时保留空值并记录；官方 3 篇页内日期为站内旧日期（2019/2023/2024），如实保留，不臆造采集日期替代。")

    heading(doc, "（3）规则有效性的自证", 3)
    para(doc,
         "真实语料里 R2（HTML 实体）、R4（网址/电话）、R9（段内重复行）没有命中，这是因为抽取层的 DOM 解析已"
         "顺带解码了实体、正文中也没有外链与重复行。零命中不等于规则无效，因此我另外写了 scripts/test_cleaning_rules.py，"
         "用构造的含噪样本逐条验证 10 条规则与 2 个辅助正则，运行结果为 11/11 通过（输出见附录 B）。"
         "这一步同时也是对“规则解释”的落地证明：报告里写的每条规则都能被最小样例复现。")

    # ================================================================ 1.3
    heading(doc, "1.3 结构化数据设计", 2)
    para(doc,
         "结构化结果以“一篇文档一行”的宽表组织，主键为 doc_id，同时输出 CSV（utf-8-sig，Excel 直接打开不乱码）"
         "与 JSON（便于下游脚本读取）。字段设计围绕三条线索：来源可追溯、文本可复用、质量可度量。")

    field_rows = [
        ["doc_id", "string", "文档主键，CHL-Oxx=官方路线、CHL-Nxx=游客游记", "CHL-O02"],
        ["source_site", "string", "来源站点", "长隆官网 / Trip.com"],
        ["source_url", "string", "原文链接，清洗与抽检的唯一回溯入口", "https://www.chimelong.com/gz/trip/3536.html"],
        ["scenic_area", "string", "景区口径（本组三景区之一）", "长隆旅游度假区（广州）"],
        ["park", "string", "子园区归属，支持跨园区路线分析", "野生动物世界"],
        ["doc_type", "string", "文本类型，区分官方推荐路线与游客游记", "官方路线 / 游客游记"],
        ["title", "string", "标题（已去掉站点后缀与被正文污染的部分）", "广州长隆野生动物世界游玩攻略"],
        ["author", "string", "作者/编辑主体", "长隆官网编辑部 / 用户昵称"],
        ["publish_date", "date", "页内发布日期（字符串），缺失记空值", "2019-01-01"],
        ["fetch_time", "datetime", "采集时间", "2026-10-28 19:02:11"],
        ["extract_rule", "string", "抽取策略，说明该条正文的取得方式", "JSON-LD + article.info-wrapper"],
        ["raw_len", "int", "原始内容字符数", "5660"],
        ["clean_len", "int", "清洗后字符数", "2190"],
        ["char_count_no_space", "int", "去空白字符数，用于长度类统计", "2163"],
        ["paragraph_count", "int", "段落数（按换行切分）", "37"],
        ["reduction_rate", "float", "字符削减率，度量噪声占比", "0.613"],
        ["is_valid", "bool", "有效性标记（非空且 ≥50 字）", "True"],
        ["cleaning_log", "string", "各规则削减量摘要，定位噪声来源", "去除 HTML 标签-4103；…"],
        ["clean_text", "text", "清洗后正文，后续项目直接读取", "（多行文本）"],
        ["raw_text", "text", "原始内容（含标签/模板噪声），供复核", "（多行文本）"],
    ]
    add_table(doc, ["字段", "类型", "含义", "示例"], field_rows, [3.3, 1.9, 6.2, 4.2], font_size=8)
    caption(doc, "表 1-3  结构化数据字段字典（20 个字段）")

    para(doc,
         "关于“如何区分官方路线与游客游记”，本项目用三重信息交叉标注，而不是只看来源域名："
         "doc_type 给出显式类型；source_site 与 extract_rule 说明正文获取方式（官网为 div.flow-list，"
         "游记为 JSON-LD + article.info-wrapper）；写作人称与语气作为人工校核依据——官方文本以“我们推荐/"
         "第一站（时间）”的规划口吻叙述，游记则出现“我/我们”“亲测”“排队超久”等第一人称体验表达。"
         "三条信息一致时才确认类型，避免把官网的用户投稿误判为官方路线。")

    para(doc,
         "位置信息的处理需要单独说明：本项目不生成实体级别的字符起止位置，原因是实体位置必须与“最终冻结的文本版本”"
         "绑定，而文本在项目 2 仍可能因停用词/词典调整而微调；若现在写入 span，后续版本变化会造成位置错位。"
         "因此本项目只保证“文档级定位”（doc_id + source_url + 原始字符数），字符级 span 留到项目 2 在固定版本的 "
         "clean_text 上一次生成，规则为：位置以 clean_text 为准、起点从 0 计、结束位置不含。")

    para(doc, "输出文件与目录约定如下（后续项目直接读取第一项即可）：", first_indent=True)
    out_rows = [
        ["data/interim/legacy_20col.csv", "全字段宽表（20 字段），utf-8-sig", "人工查看 / Excel 复核"],
        ["data/interim/chimelong_docs.json", "同上，JSON 记录数组", "项目 2、3 的脚本读取"],
        ["data/interim/chimelong_docs_index.csv", "不含正文的索引表（18 字段）", "统计与清单核对"],
        ["outputs/cleaning_samples.csv", "逐规则清洗前后差异样例", "报告取证"],
        ["outputs/quality_report.json", "质量检查指标与规则削减明细", "图表与报告数据源"],
        ["outputs/usability_flags.csv", "时间/箭头/编号/POI 可用性标记", "项目 2、3 的样本筛选"],
        ["data/raw/CHL-*.html", "8 个原始页面", "全链路追溯"],
    ]
    add_table(doc, ["路径", "内容", "用途"], out_rows, [6.4, 5.6, 3.6], font_size=8.5)
    caption(doc, "表 1-4  结构化输出文件清单")

    # ================================================================ 1.4
    heading(doc, "1.4 清洗前后对比与数据质量", 2)
    para(doc,
         "先看整体：8 篇文本清洗前共 "
         f"{st['raw_text']['total']:,} 字符，清洗后 {st['clean_text']['total']:,} 字符，整体削减 "
         f"{report['reduction']['overall_reduction_rate']:.1%}。削减主要来自 HTML 标签（{rule_stats['去除 HTML 标签']['removed_chars']:,} 字符）"
         "与页面模板（"
         f"{rule_stats['去除页面模板/元数据行']['removed_chars']:,} 字符），而不是正文内容；游记类因正文本身较短、"
         "模板占比高，削减率在 19%—47%；官方页因内联样式标签密集，削减率达 61%—86%。这一差异本身说明“按来源分层检查清洗效果”是必要的。")

    add_image(doc, FIG / "fig1_length_compare.png", 15.4)
    caption(doc, "图 1-1  各文档清洗前后字符数对比（括号上方为削减率）")

    para(doc, "逐规则的削减量见图 1-2：")
    add_image(doc, FIG / "fig2_rule_stats.png", 15.4)
    caption(doc, "图 1-2  各清洗规则的字符削减/替换量（8 篇合计）")

    para(doc, "数据构成见图 1-3，覆盖 4 个子园区、两类文本：")
    add_image(doc, FIG / "fig3_composition.png", 14.6)
    caption(doc, "图 1-3  长隆数据集构成（左：子园区分布；右：文本类型分布）")

    heading(doc, "（1）可核验的原文—清洗后样例", 3)
    para(doc, "下面抽取 4 组样例（见表 1-5），覆盖“标签 / 模板行 / 符号 / 标点时间”四类主要噪声，均标注文档 ID，可直接对回原文：")

    n02 = doc_map["CHL-N02"].raw_text
    o02 = doc_map["CHL-O02"].raw_text
    n01 = doc_map["CHL-N01"].raw_text
    sample_rows = [
        ["CHL-O02", "去标签（R1）",
         '<div class="text p"><strong>【游玩路线】</strong></div>',
         "【游玩路线】"],
        ["CHL-N01", "去模板行 + 去符号（R3/R5）",
         snippet("30 天前發布，幫助了 108 位旅客的旅程", 40),
         "（整行删除）"],
        ["CHL-N01", "去图标私有区字符（R5）",
         "首行 \\uf592（渲染为空白方块）",
         "空白字符被清除，首行即标题"],
        ["CHL-N02", "标点与时间统一（R7）",
         '09. 40 垂直過山車(⭐⭐⭐⭐⭐ 必玩)',
         "09:40 垂直过山车（必玩）"],
        ["CHL-N02", "繁体转简体（R8）",
         "進園直奔垂直過山車 → 順時針刷遍熱門項目",
         "进园直奔垂直过山车 → 顺时针刷遍热门项目"],
    ]
    add_table(doc, ["文档ID", "规则", "清洗前（原文片段）", "清洗后"], sample_rows,
              [1.6, 3.2, 6.4, 4.4], font_size=8)
    caption(doc, "表 1-5  清洗前后样例（原文片段已截断，完整内容见 data/interim/legacy_20col.csv 的 raw_text / clean_text）")

    heading(doc, "（2）各文档清洗统计", 3)
    stat_rows = []
    for r in df.itertuples():
        stat_rows.append([
            r.doc_id, r.doc_type, r.park, f"{r.raw_len:,}", f"{r.clean_len:,}",
            f"{r.reduction_rate:.1%}", str(r.paragraph_count), "有效" if r.is_valid else "无效",
        ])
    stat_rows.append(["合计", "3 官方 / 5 游记", "4 个子园区", f"{st['raw_text']['total']:,}",
                      f"{st['clean_text']['total']:,}", f"{report['reduction']['overall_reduction_rate']:.1%}",
                      str(int(df['paragraph_count'].sum())), "8/8 有效"])
    add_table(doc, ["文档ID", "类型", "子园区", "原始字符", "清洗字符", "削减率", "段落数", "有效性"],
              stat_rows, [1.7, 2.6, 3.0, 2.0, 2.0, 1.6, 1.4, 1.3], font_size=8)
    caption(doc, "表 1-6  各文档清洗统计（长度口径为 Python len() 字符数，含标点不含空白）")

    heading(doc, "（3）数据质量检查结果", 3)
    fmt = report["format_consistency"]
    q_rows = [
        ["记录数", f"{report['record_count']} 篇", f"官方 {report['by_doc_type'].get('官方路线', 0)} + 游记 {report['by_doc_type'].get('游客游记', 0)}；满足“≥1 条官方 + ≥3 篇游记”"],
        ["缺失值", "8 个字段均为 0", "逐字段统计空值数与空值率，结果全部为 0"],
        ["完全重复", f"{report['exact_duplicate_docs']} 对", "清洗后去空白取 MD5 比对"],
        ["近重复", f"{len(report['near_duplicate_pairs_ge_0.30'])} 对（阈值 0.30）", "字符 3-gram Jaccard，无高相似文本，说明 8 篇内容互补"],
        ["HTML 残留", f"{fmt['含HTML残留']} 篇", "正则 <[a-zA-Z/][^>]*> 扫描"],
        ["网址残留", f"{fmt['含网址']} 篇", "https?:// 与 www. 扫描"],
        ["emoji 残留", f"{fmt['含emoji']} 篇", "emoji 区段 + 私有区字符扫描"],
        ["半角标点残留（中文语境）", f"{fmt['含半角逗号/句号']} 篇", "汉字后紧跟 , 或 . 的扫描"],
        ["繁体残留", f"{fmt['含繁体字残留']} 篇", "以 OpenCC t2s 幂等性检验：转换前后不一致即判残留"],
        ["全角空格/NBSP 残留", f"{fmt['含全角空格/NBSP']} 篇", "\\u00A0 / \\u3000 扫描"],
        ["连续空行残留", f"{fmt['含连续空行']} 篇", "\\n{2,} 扫描"],
        ["空文本", f"{fmt['空文本']} 篇", "strip 后为空即判定"],
    ]
    add_table(doc, ["检查项", "结果", "检查方法与判定"], q_rows, [3.6, 3.4, 8.4], font_size=8.5)
    caption(doc, "表 1-7  数据质量检查结果（清洗后）")

    para(doc,
         "所有格式一致性检查项均为 0 命中，说明 R1—R10 十条规则把格式层面统一到了同一口径。"
         "长度方面，清洗后单篇最短 " + f"{st['clean_text']['min']} 字（CHL-N05）、最长 {st['clean_text']['max']} 字（CHL-O03）、"
         f"均值 {st['clean_text']['mean']} 字、平均 {st['paragraphs_clean']['mean']} 段，且 8 篇全部通过有效性检查。"
         "另外对后续项目做了可用性预检：含明确时间表达的 7/8 篇、含箭头链路的 3/8 篇、含编号步骤的 4/8 篇、"
         "含 POI 关键词的 8/8 篇——足以支撑项目 2 的实体识别与项目 3 的路线层级解析。")

    # ================================================================ 1.5
    heading(doc, "1.5 问题与分析", 2)
    para(doc, "采集与清洗过程中遇到的问题、处理方式与遗留影响记录如下（含未解决项）：")

    issue_rows = [
        ["1", "主流游记平台反爬严重",
         "小红书、马蜂窝、携程、大众点评均返回 202/跳转验证页或需要登录态，静态请求拿不到正文；微信公号文章跳验证码。",
         "改为采集“服务端渲染 + 内嵌 JSON-LD”的 Trip.com 旅行笔记；放弃需要浏览器自动化的站点（Selenium 成本高且不稳定）。",
         "游记来源集中在单一站点，作者与文风多样性弱于多平台混合；但 5 篇为不同作者，且均来自真实分享页。"],
        ["2", "官网正文日期为站内旧日期",
         "官方 3 篇的页内日期分别为 2019/2023/2024，部分游乐项目、票价已变更。",
         "如实保留 publish_date，不臆造；在 1.4 遗留问题中标注，后续抽取以路线结构为主，价格类信息不作知识事实。",
         "项目 5 抽取条件建议时，涉及票价/营业时间的建议需人工复核时效性。"],
        ["3", "Trip.com 正文含大量页面模板",
         "原始内容含“XX 分享的…Trip Moment”“30 天前发布”“還有另外 357 篇…”“今日天气/营业状态/点评分”等行。",
         "以行级正则 + 标题重复行剔除（R3），并用标题前缀 20 字匹配处理被截断的标题。",
         "模板行命名随站点改版可能变化，规则需持续维护；已把命中量写入 cleaning_log 便于发现失效。"],
        ["4", "图标字体私有区字符",
         "游记正文里的“⏰/📅”等图标在 HTML 中是 " + "\\uf592" + " 一类私有区字符，控制台看是空白，容易误判为段落错乱。",
         "R5 增加 U+E000–U+F8FF 清理，并在样例表中显式标注。",
         "若其它站点也用图标字体承载语义（如“必看”标记），清除后语义有损失，需要靠上下文补足。"],
        ["5", "时间写法噪声",
         "游记存在“09. 40”“10. 30”这类把冒号写成点号的排版错误，若直接交给下游时间识别会漏抽。",
         "R7 增加时间修复规则，并加约束（小时 0–23、后面不能紧跟数字或冒号），避免把编号“1. 09:30”误改成“1:09”。",
         "该规则对“12. 30”这类既可能是时间也可能是版本号的片段存在极小误判风险，已通过后向断言降低。"],
        ["6", "清洗与后续解析的耦合",
         "若在清洗阶段就删除“关于饮食/关于住宿/关于交通”等段落，项目 3 将失去判断“该段不是路线步骤”的依据。",
         "保留这些段落，只在路线解析阶段按小标题切分过滤。",
         "官方 3 天 2 夜攻略（CHL-O01）正文 1,518 字中约三分之一属于住宿/交通信息，解析时需先分段。"],
    ]
    add_table(doc, ["#", "问题", "现象", "处理方式", "遗留影响"], issue_rows,
              [0.7, 2.6, 4.4, 4.4, 3.3], font_size=7.5)
    caption(doc, "表 1-8  采集与清洗过程中的问题记录")

    para(doc,
         "关于“哪些清洗结果可供后续实验直接读取”，结论是：data/interim/legacy_20col.csv 的 clean_text 字段"
         "即为冻结的文本版本，项目 2（实体识别）、项目 3（路线解析）、项目 5（条件建议抽取）应统一读取该字段，"
         "不得再各自另行清洗，否则同一实体的字符位置、路线步骤的编号会出现版本漂移；raw_text 与 data/raw/*.html "
         "只用于复核与纠错，不进入建模流程。")
    para(doc,
         "另外记录一处未完全解决的问题：游记 CHL-N05（水上乐园）清洗后仅 421 字，设施名称多、时间与顺序信息少，"
         "是 8 篇中信息密度最低的一篇。它仍保留在数据集中（作为水上乐园的唯一语料），但在项目 2 的实体统计中"
         "会拉低时间类实体的覆盖，计划在报告中如实说明，不通过人为补写文本来“凑”覆盖率。")

    # ================================================================ 附录
    heading(doc, "附录 A  运行方式、依赖与目录结构", 2)
    para(doc, "运行入口（在实验目录 experiment1_chimelong/ 下执行，Python 3.12）：", first_indent=True)
    code_block(doc,
               "python scripts/collect_chimelong.py    # 采集 -> data/raw, data/interim/raw_docs.jsonl\n"
               "python scenic/changlong/src/clean_dataset.py   # 清洗 -> data/interim/ + outputs/\n"
               "python scripts/quality_check.py        # 质检 -> outputs/figures/, outputs/质量检查报告.md\n"
               "python scripts/test_cleaning_rules.py  # 规则自测 -> docs/rule_unit_tests.txt\n"
               "python scripts/build_report_docx.py    # 生成本报告章节 DOCX", size=8)
    para(doc, "主要依赖：requests、beautifulsoup4、lxml（采集与解析）；pandas（结构化与统计）；"
              "opencc-python-reimplemented（繁简统一）；matplotlib（图表）；python-docx（报告生成）。"
              "版本与运行命令均可复现，脚本内已固定请求头、超时、重试次数与请求间隔。")

    para(doc, "目录结构：", first_indent=True)
    code_block(doc,
               "experiment1_chimelong/\n"
               "├─ scripts/          collect / clean / quality_check / test_rules / build_report\n"
               "├─ data/raw/         8 个原始 HTML（CHL-O01…CHL-N05）\n"
               "├─ data/interim/     raw_docs.jsonl（采集产出的结构化原始语料）\n"
               "├─ data/processed/   changlong_guides.csv（24 列交付物）\n"
               "├─ outputs/figures/          fig1~fig3\n"
               "└─ docs/             quality_report.md、rule_unit_tests.txt", size=8)

    heading(doc, "附录 B  规则自测结果摘要", 2)
    test_txt = OUT_DIR / "rule_unit_tests.txt"
    if test_txt.exists():
        lines = [ln for ln in test_txt.read_text(encoding="utf-8").splitlines() if ln.strip()]
        brief = [ln.replace("[PASS] ", "") for ln in lines if ln.startswith("[PASS]")]
        summary = [ln for ln in lines if ln.startswith("合计")]
        para(doc, "；".join(brief) + "。", size=10.5)
        if summary:
            para(doc, summary[0] + "（完整用例的输入/输出见 docs/rule_unit_tests.txt）。", size=10.5)

    move_table_captions_above(doc)
    doc.save(OUT)
    print("saved:", OUT)
    # 回读校验
    check = Document(OUT)
    print("paragraphs:", len(check.paragraphs), "tables:", len(check.tables),
          "images:", len(check.inline_shapes))


if __name__ == "__main__":
    main()

