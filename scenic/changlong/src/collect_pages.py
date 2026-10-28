# -*- coding: utf-8 -*-
"""
实验项目一 · 数据采集脚本 —— 长隆旅游度假区（广州）
=================================================
实验目标：为后续实体识别(项目2)、路线层级挖掘(项目3)等提供原始语料。

采集对象
  A. 官方推荐路线（chimelong.com 官网「行程推荐」栏目）  3 篇
  B. 游客游记（Trip.com 旅行笔记，公开个人分享页）       5 篇

实现要点
  1. requests + BeautifulSoup 抓取，带 UA、超时与 3 次重试，请求间隔 1.2s（礼貌抓取）；
  2. 原始 HTML 全量落盘到 data/raw/，保证可追溯、可复核（报告要求“结果能与代码、文件对应”）；
  3. 官方页：定位 div.flow-list 正文容器，取 innerHTML 作为「原始内容」（保留标签，留给清洗阶段去除）；
  4. 游记页：优先解析页面内嵌 JSON-LD（schema.org DiscussionForumPosting），字段稳定，
     可直接拿到 headline / text / datePublished / author，避免把导航、推荐位当成正文；
  5. 抽取结果写入 data/interim/raw_docs.jsonl，每行一条文档，附带来源、抓取时间等元数据。

运行：
  python scripts/collect_chimelong.py
输出：
  data/raw/*.html              原始页面
  data/interim/raw_docs.jsonl  结构化原始语料
"""
from __future__ import annotations

import json
import pathlib
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE = pathlib.Path(__file__).resolve().parents[1]
RAW_DIR = BASE / "data" / "raw"
INTERIM_DIR = BASE / "data" / "interim"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
RETRIES = 3
DELAY = 1.2  # 秒，爬虫礼貌间隔

# ---------------------------------------------------------------- 采集清单
# doc_type: 官方路线 / 游客游记
TARGETS = [
    # ---------------- A. 官方推荐路线 ----------------
    dict(
        doc_id="CHL-O01",
        doc_type="官方路线",
        park="度假区（多园区）",
        url="https://www.chimelong.com/gz/trip/6957.html",
        note="广州长隆3天2夜游玩攻略（第一站/第二站…多日串联）",
    ),
    dict(
        doc_id="CHL-O02",
        doc_type="官方路线",
        park="野生动物世界",
        url="https://www.chimelong.com/gz/trip/3536.html",
        note="野生动物世界情侣游攻略（箭头链路 + 第一站(时间) 编号）",
    ),
    dict(
        doc_id="CHL-O03",
        doc_type="官方路线",
        park="欢乐世界",
        url="https://www.chimelong.com/gz/trip/3537.html",
        note="欢乐世界游玩攻略（上午/中午 时间分段）",
    ),
    # ---------------- B. 游客游记 ----------------
    dict(
        doc_id="CHL-N01",
        doc_type="游客游记",
        park="欢乐世界",
        url="https://tw.trip.com/moments/detail/guangzhou-152-144829973/",
        note="五一欢乐世界保姆级攻略（分时段行程）",
    ),
    dict(
        doc_id="CHL-N02",
        doc_type="游客游记",
        park="度假区（多园区）",
        url="https://tw.trip.com/moments/detail/guangzhou-152-149982547/",
        note="广州长隆不绕路攻略（多园区串联）",
    ),
    dict(
        doc_id="CHL-N03",
        doc_type="游客游记",
        park="野生动物世界",
        url="https://tw.trip.com/moments/detail/guangzhou-152-155862848/",
        note="野生动物园无回头路旅游指南（带时刻的站点顺序）",
    ),
    dict(
        doc_id="CHL-N04",
        doc_type="游客游记",
        park="欢乐世界",
        url="https://tw.trip.com/moments/detail/guangzhou-152-139591348/",
        note="欢乐世界长文攻略（设施+排队经验）",
    ),
    dict(
        doc_id="CHL-N05",
        doc_type="游客游记",
        park="水上乐园",
        url="https://tw.trip.com/moments/detail/guangzhou-152-143716112/",
        note="度假区夏日水上乐园体验",
    ),
]


def fetch(url: str) -> tuple[int, str]:
    """带重试的 GET，返回 (状态码, HTML 文本)。"""
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.encoding = "utf-8"
            if resp.status_code == 200 and resp.text:
                return resp.status_code, resp.text
            last_err = f"HTTP {resp.status_code}"
        except requests.RequestException as exc:  # 网络异常
            last_err = f"{type(exc).__name__}: {exc}"
        time.sleep(DELAY * attempt)
    raise RuntimeError(f"抓取失败 {url} -> {last_err}")


def clean_title(text: str, limit: int = 60) -> str:
    """标题规整：去掉 Trip.com 后缀、截断被正文污染的超长标题。"""
    text = re.sub(r"\s*[|｜]\s*Trip\.com.*$", "", text or "")
    text = re.split(r"\s{2,}|\n", text.strip())[0].strip()
    return text if len(text) <= limit else text[:limit] + "…"


def extract_official(html: str) -> dict:
    """官方页：正文在 div.flow-list 内，取 innerHTML 作为原始内容。"""
    soup = BeautifulSoup(html, "lxml")
    container = (
        soup.select_one("div.flow-list")
        or soup.select_one("div.c--static-flow")
        or soup.select_one("#main-wrap")
    )
    if container is None:
        raise RuntimeError("未找到官方正文容器")
    body_html = "".join(str(child) for child in container.children)
    page_title = soup.title.get_text(strip=True) if soup.title else ""
    # 发布日期在正文容器外：抓 h5.static-flow-head 旁的 span.time
    publish_date = ""
    head = soup.select_one("h5.static-flow-head")
    if head is not None:
        scope = head.find_parent("div") or soup
        time_node = scope.select_one("span.time")
        if time_node:
            publish_date = time_node.get_text(strip=True)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", publish_date or ""):
        date_match = re.search(
            r"(20\d{2})-(\d{1,2})-(\d{1,2})", soup.get_text(" ", strip=True)
        )
        publish_date = (
            f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
            if date_match
            else ""
        )
    return dict(
        title=clean_title(page_title.split("|")[0]),
        author="长隆官网编辑部",
        publish_date=publish_date,
        raw_text=body_html,
        extract_rule="BeautifulSoup 定位 div.flow-list 取 innerHTML",
    )


def extract_note(html: str) -> dict:
    """游记页：JSON-LD 取元数据，article.info-wrapper 取正文区文本（含页面模板噪声）。"""
    meta = None
    for block in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "DiscussionForumPosting":
            meta = data
            break

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    wrapper = soup.select_one("article.info-wrapper")
    if wrapper is not None:
        raw_text = wrapper.get_text("\n", strip=True)
        rule = "JSON-LD 取标题/作者/时间 + article.info-wrapper 取正文区文本"
    else:
        body = soup.select_one("article.info-wrapper div.content_expand")
        raw_text = str(body) if body is not None else (meta or {}).get("text", "")
        rule = "回退 DOM: article.info-wrapper div.content_expand"

    author = (meta or {}).get("author") or {}
    return dict(
        title=clean_title((meta or {}).get("headline") or (soup.title.get_text(strip=True) if soup.title else "")),
        author=(author.get("name") if isinstance(author, dict) else "") or "",
        publish_date=((meta or {}).get("datePublished") or "")[:10],
        raw_text=raw_text,
        extract_rule=rule,
    )


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for target in TARGETS:
        status, html = fetch(target["url"])
        raw_path = RAW_DIR / f"{target['doc_id']}.html"
        raw_path.write_text(html, encoding="utf-8")
        meta = (
            extract_official(html)
            if target["doc_type"] == "官方路线"
            else extract_note(html)
        )
        record = {
            "doc_id": target["doc_id"],
            "source_site": "长隆官网" if "chimelong.com" in target["url"] else "Trip.com",
            "source_url": target["url"],
            "scenic_area": "长隆旅游度假区（广州）",
            "park": target["park"],
            "doc_type": target["doc_type"],
            "title": meta["title"],
            "author": meta["author"],
            "publish_date": meta["publish_date"],
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "http_status": status,
            "raw_html_path": str(raw_path.relative_to(BASE)).replace("\\", "/"),
            "extract_rule": meta["extract_rule"],
            "raw_text": meta["raw_text"],
        }
        records.append(record)
        print(
            f"[OK] {record['doc_id']} {record['doc_type']:<4} "
            f"{len(record['raw_text']):>5} chars  {record['title'][:32]}"
        )
        time.sleep(DELAY)

    out = INTERIM_DIR / "raw_docs.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 采集清单：URL / 状态 / 字节 / SHA256 / 采集时间（HTML 快照不入库，靠这份清单追溯）
    import csv
    import hashlib

    manifest = RAW_DIR / "manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["doc_id", "source_url", "http_status", "bytes", "sha256", "fetch_time"],
            lineterminator="\n",
        )
        writer.writeheader()
        for rec in records:
            path = RAW_DIR / f"{rec['doc_id']}.html"
            data = path.read_bytes()
            writer.writerow(
                {
                    "doc_id": rec["doc_id"],
                    "source_url": rec["source_url"],
                    "http_status": rec["http_status"],
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "fetch_time": rec["fetch_time"],
                }
            )
    print(f"\n共采集 {len(records)} 篇 -> {out}")
    print(f"采集清单 -> {manifest}")


if __name__ == "__main__":
    main()
