# -*- coding: utf-8 -*-
"""正文抽取：从原始 HTML 中定位正文容器，输出未清洗的原始正文（interim JSONL）。

策略：
1. 站点规则优先（官网 / 豆瓣 / 8264 / 简书 / 搜狐），规则稳定、准确率高；
2. 规则未命中时用「文本密度 + 链接密度」的通用兜底：文本越长、链接占比越低，
   越可能是正文容器；
3. 抽取时剔除 script/style/nav/footer/评论/推荐等噪声节点，保留段落换行。

用法：
    python src/extract.py
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from lxml import html as LH, etree

from common import (
    EXTRACTED_JSONL, INTERIM_DIR, MANIFEST_CSV, RAW_HTML_DIR, read_sources,
    setup_logging, write_csv,
)

log = logging.getLogger("extract")

BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "li", "ul", "ol", "tr", "td",
    "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "br", "hr",
}
NOISE_TAGS = {"script", "style", "noscript", "iframe", "svg", "form", "button", "input"}
NOISE_ATTR = re.compile(
    r"(nav|footer|header|sidebar|comment|recommend|related|breadcrumb|share|"
    r"advert|banner|toolbar|pagination|copyright|qrcode|login|popup|modal)", re.I
)

# (域名关键字, 正文 XPath, 规则名)
SITE_RULES: list[tuple[str, list[str], str]] = [
    ("wugongshan.cn", ["//div[contains(@class,'raid-main')]"], "官网-富文本div.raid-main"),
    ("douban.com", [
        "//div[contains(@class,'topic-richtext')]",
        "//div[contains(@class,'topic-content')][not(contains(@class,'clearfix'))]",
        "//div[@id='link-report']",
    ], "豆瓣-topic-richtext"),
    ("8264.com", [
        "//td[contains(@class,'t_f')]",
        "//div[contains(@class,'pcb')]",
    ], "8264-首帖td.t_f"),
    ("jianshu.com", ["//article", "//div[contains(@class,'show-content')]"], "简书-article"),
    ("sohu.com", ["//article", "//div[contains(@class,'article-content')]"], "搜狐-article"),
]


def node_text(el: etree._Element) -> str:
    """段落感知的文本抽取：块级元素后补换行，保留原文分段。"""
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        if not isinstance(node.tag, str):   # 跳过 HTML 注释（如 <!--富文本 start-->）
            return
        if node.tag in NOISE_TAGS:
            return
        cls_id = f"{node.get('class', '')} {node.get('id', '')}"
        if cls_id.strip() and NOISE_ATTR.search(cls_id) and node is not el:
            return
        if node.tag == "br":
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if node.tag in BLOCK_TAGS:
            parts.append("\n")

    walk(el)
    text = "".join(parts)
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()


def pick_container(doc: etree._Element, url: str) -> tuple[etree._Element, str]:
    """按站点规则取正文；失败则用文本密度兜底。"""
    for domain, xpaths, name in SITE_RULES:
        if domain not in url:
            continue
        for xp in xpaths:
            for el in doc.xpath(xp):
                # 站点规则命中即用；即使文本很短（如图片为主的帖子）也保留，
                # 交给质量检查标记“文本过短”，避免静默丢样本。
                if node_text(el).strip():
                    return el, name
        log.warning("站点规则未命中，转通用兜底：%s", url)

    best, best_score = None, 0.0
    for el in doc.iter("div", "article", "section", "td", "main"):
        txt = node_text(el)
        if len(txt) < 150:
            continue
        link_len = sum(len("".join(a.text_content().split())) for a in el.iter("a"))
        score = len(txt) - 2.0 * link_len
        if score > best_score:
            best, best_score = el, score
    if best is None:
        raise RuntimeError(f"未找到正文容器：{url}")
    return best, "通用-文本密度兜底"


def meta_content(doc: etree._Element, *names: str) -> str:
    for name in names:
        vals = doc.xpath(
            f"//meta[@property='{name}']/@content | //meta[@name='{name}']/@content"
        )
        if vals and vals[0].strip():
            return vals[0].strip()
    return ""


def clean_title(raw: str, site: str) -> str:
    raw = re.sub(r"\s+", " ", raw or "").strip()
    for sep in (" - ", "_", "|"):
        if sep in raw:
            head = raw.split(sep)[0].strip()
            if len(head) >= 4:
                return head
    return raw


def site_meta(doc: etree._Element, url: str) -> dict:
    """抽取站点特有的作者/日期（仅作为人工配置缺失时的补充）。"""
    info = {"author": "", "publish_date": "", "title": ""}
    if "jianshu.com" in url:
        info["author"] = (doc.xpath("string(//div[contains(@class,'author')]//span[contains(@class,'name')])") or "").strip()
        dates = doc.xpath("//time/@datetime")
        info["publish_date"] = dates[0][:10] if dates else ""
    elif "douban.com" in url:
        info["author"] = (doc.xpath("string(//span[contains(@class,'from')]//a)") or "").strip()
        d = doc.xpath("string(//span[contains(@class,'create-time')])")
        info["publish_date"] = d.strip()[:10] if d.strip() else ""
    elif "8264.com" in url:
        info["author"] = (doc.xpath("string(//div[contains(@class,'authi')]//a)") or "").strip()
        d = doc.xpath("string(//em[contains(@id,'authorposton')])")
        m = re.search(r"\d{4}-\d{1,2}-\d{1,2}", d)
        info["publish_date"] = m.group(0) if m else ""

    # 通用兜底：很多站点把发布时间放在 meta / JSON-LD 中
    if not info["publish_date"]:
        raw_date = meta_content(
            doc, "article:published_time", "bytedance:published_time",
            "og:release_date", "datePublished", "dateUpdate", "publish_date",
        )
        m = re.search(r"\d{4}-\d{2}-\d{2}", raw_date)
        if m:
            info["publish_date"] = m.group(0)
    if not info["author"]:
        info["author"] = meta_content(doc, "author", "og:author", "article:author")
    if not info["title"]:
        info["title"] = meta_content(doc, "og:title")
    return info


def main() -> None:
    setup_logging()
    sources = {s["doc_id"]: s for s in read_sources()}
    records: list[dict] = []
    report: list[dict] = []

    for doc_id, src in sources.items():
        html_file = RAW_HTML_DIR / f"{doc_id}.html"
        if not html_file.exists():
            log.warning("缺少原始文件，跳过：%s", doc_id)
            continue
        doc = LH.fromstring(html_file.read_text(encoding="utf-8", errors="ignore"))
        try:
            container, rule = pick_container(doc, src["source_url"])
            raw_content = node_text(container)
        except Exception as e:
            log.error("抽取失败 %s: %s", doc_id, e)
            report.append({"doc_id": doc_id, "status": "failed", "rule": "", "chars": 0, "error": str(e)})
            continue

        meta = site_meta(doc, src["source_url"])
        page_title = (doc.findtext(".//title") or "").strip()
        title = src["title"] or meta["title"] or clean_title(page_title, src["source_site"])
        author = src["author"] or meta["author"]
        publish_date = src["publish_date"] or meta["publish_date"]

        rec = {
            "doc_id": doc_id,
            "scenic_area": src["scenic_area"],
            "doc_type": src["doc_type"],
            "subtype": src["subtype"],
            "title": title,
            "author": author,
            "publish_date": publish_date,
            "source_site": src["source_site"],
            "source_url": src["source_url"],
            "extract_rule": rule,
            "raw_content": raw_content,
            "char_count": len(raw_content),
        }
        records.append(rec)
        report.append({
            "doc_id": doc_id, "status": "ok", "rule": rule,
            "chars": len(raw_content), "paragraphs": raw_content.count("\n") + 1,
            "title": title, "error": "",
        })
        log.info("%s | %-28s | %6d 字 | %s", doc_id, rule, len(raw_content), title[:40])

    with open(EXTRACTED_JSONL, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    write_csv(INTERIM_DIR / "extract_report.csv", report)
    log.info("抽取完成：%d 条 -> %s", len(records), EXTRACTED_JSONL)


if __name__ == "__main__":
    main()
