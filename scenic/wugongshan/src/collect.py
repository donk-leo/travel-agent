# -*- coding: utf-8 -*-
"""采集脚本：抓取武功山官方路线与游客游记页面，保存原始 HTML 与采集清单。

用法：
    python src/collect.py                # 采集清单中的全部页面
    python src/collect.py --only WGS-O-01 WGS-T-06
    python src/collect.py --force        # 已有原始文件时仍重新抓取

设计要点：
1. 只用标准库 + 明确的 UA/Accept-Language，不依赖第三方爬虫框架，降低环境门槛；
2. 每次请求间隔 2 秒、失败重试 3 次，避免对站点造成压力；
3. 原始 HTML 原样落盘（统一转 UTF-8），并记录 HTTP 状态、字节数、SHA256，
   保证“抓取—抽取—清洗”链路可追溯；
4. 某个站点反爬失败不影响其他页面，失败信息写入 manifest，供报告“问题与处理”引用。
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import re
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

from common import MANIFEST_CSV, RAW_HTML_DIR, RAW_DIR, read_sources, setup_logging, write_csv

log = logging.getLogger("collect")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}
REQUEST_INTERVAL = 2.0   # 秒，礼貌采集
TIMEOUT = 30
RETRIES = 3
MANIFEST_FIELDS = [
    "doc_id", "scenic_area", "doc_type", "title", "source_site", "source_url",
    "http_status", "content_bytes", "charset", "fetch_time", "sha256",
    "raw_file", "status", "error",
]


def _decode(raw: bytes, content_type: str) -> tuple[str, str]:
    """解码 HTML。

    很多站点（如 8264）响应头声明 ISO-8859-1，但页面 meta 实际是 GBK；
    仅信任响应头会得到「Îä¹¦É½」式乱码。这里把所有候选编码都试一遍，
    用「汉字数量 - 乱码字符数量」打分，选得分最高者。
    """
    candidates: list[str] = []
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if m:
        candidates.append(m.group(1).lower())
    for mm in re.finditer(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:8192], re.I):
        candidates.append(mm.group(1).decode("ascii", "ignore").lower())
    candidates += ["utf-8", "gb18030", "gbk", "big5", "latin-1"]

    def score(text: str) -> int:
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        bad = text.count("\ufffd")
        # UTF-8 被当成 Latin-1 解码时的典型高位字符
        mojibake = len(re.findall(r"[\u00c0-\u00ff]", text))
        return cjk * 2 - bad * 50 - mojibake * 3

    best: tuple[int, str, str] | None = None
    seen: set[str] = set()
    for enc in candidates:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            text = raw.decode(enc)
        except LookupError:
            continue
        except UnicodeDecodeError:
            # 页面可能混用 GBK/UTF-8，严格解码失败时用替换符兜底，
            # 只要替换符不多，仍优于把整页当 Latin-1 的乱码结果。
            text = raw.decode(enc, "replace")
            if text.count("\ufffd") > len(text) * 0.01:
                continue
        s = score(text)
        if best is None or s > best[0]:
            best = (s, text, enc)
    if best is None:
        return raw.decode("utf-8", "replace"), "utf-8(replace)"
    return best[1], best[2]


def fetch(url: str) -> tuple[str, int, str, int]:
    """抓取单页，返回 (解码文本, HTTP 状态, 编码, 原始字节数)。"""
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                encoding = (resp.headers.get("Content-Encoding") or "").lower()
                if encoding == "gzip":
                    raw = gzip.decompress(raw)
                elif encoding == "deflate":
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                text, charset = _decode(raw, resp.headers.get("Content-Type", ""))
                return text, resp.status, charset, len(raw)
        except urllib.error.HTTPError as e:
            last_err = e
            log.warning("HTTP %s: %s（第 %d/%d 次）", e.code, url, attempt, RETRIES)
            if e.code in (403, 404, 410):   # 反爬或不存在，重试无意义
                break
        except Exception as e:  # 超时、DNS、连接重置等
            last_err = e
            log.warning("%s: %s（第 %d/%d 次）", type(e).__name__, url, attempt, RETRIES)
        time.sleep(REQUEST_INTERVAL * attempt)
    raise RuntimeError(f"抓取失败：{url} -> {last_err!r}")


def _load_manifest() -> dict[str, dict]:
    """读取已有清单，按 doc_id 建索引，支持 --only 增量采集后合并。"""
    if not MANIFEST_CSV.exists():
        return {}
    import csv
    with open(MANIFEST_CSV, "r", encoding="utf-8-sig", newline="") as f:
        return {row["doc_id"]: row for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=None, help="仅采集指定 doc_id")
    parser.add_argument("--force", action="store_true", help="已有文件时强制重新抓取")
    args = parser.parse_args()

    setup_logging()
    all_sources = read_sources()
    sources = [s for s in all_sources if not args.only or s["doc_id"] in set(args.only)]
    log.info("待采集 %d 个页面", len(sources))

    previous = _load_manifest()
    rows: list[dict] = []
    for i, src in enumerate(sources, 1):
        doc_id = src["doc_id"]
        url = src["source_url"]
        out_file = RAW_HTML_DIR / f"{doc_id}.html"
        base = {
            "doc_id": doc_id,
            "scenic_area": src["scenic_area"],
            "doc_type": src["doc_type"],
            "title": src["title"],
            "source_site": src["source_site"],
            "source_url": url,
        }

        if out_file.exists() and not args.force:
            raw = out_file.read_bytes()
            old = previous.get(doc_id, {})
            log.info("[%d/%d] 已存在，跳过：%s", i, len(sources), doc_id)
            rows.append({
                **base,
                "http_status": old.get("http_status") or 200,
                "content_bytes": old.get("content_bytes") or len(raw),
                "charset": old.get("charset") or "utf-8",
                "fetch_time": old.get("fetch_time")
                or datetime.fromtimestamp(out_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "sha256": old.get("sha256") or hashlib.sha256(raw).hexdigest(),
                "raw_file": out_file.relative_to(RAW_DIR.parent.parent).as_posix(),
                "status": "cached",
                "error": "",
            })
            continue

        try:
            text, status, charset, nbytes = fetch(url)
            out_file.write_text(text, encoding="utf-8")
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            log.info("[%d/%d] OK %s  %s  %d bytes", i, len(sources), doc_id, status, nbytes)
            rows.append({
                **base,
                "http_status": status,
                "content_bytes": nbytes,
                "charset": charset,
                "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sha256": sha,
                "raw_file": out_file.relative_to(RAW_DIR.parent.parent).as_posix(),
                "status": "ok",
                "error": "",
            })
        except Exception as e:
            log.error("[%d/%d] FAIL %s -> %s", i, len(sources), doc_id, e)
            rows.append({
                **base,
                "http_status": "",
                "content_bytes": 0,
                "charset": "",
                "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sha256": "",
                "raw_file": "",
                "status": "failed",
                "error": str(e)[:300],
            })
        time.sleep(REQUEST_INTERVAL)

    merged = {**previous, **{r["doc_id"]: r for r in rows}}
    ordered = [merged[s["doc_id"]] for s in all_sources if s["doc_id"] in merged]
    write_csv(MANIFEST_CSV, ordered, MANIFEST_FIELDS)
    ok = sum(r["status"] in ("ok", "cached") for r in ordered)
    log.info("采集结束：成功 %d / %d，清单 -> %s", ok, len(ordered), MANIFEST_CSV)
    if ok < len(ordered):
        log.warning("存在失败页面，请查看 manifest.csv；抽取阶段会跳过缺失文件。")


if __name__ == "__main__":
    main()
