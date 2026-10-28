# -*- coding: utf-8 -*-
"""数据清洗：把抽取出的原始正文清洗为可用于后续挖掘的规范文本。

清洗规则（与报告“清洗规则表”一一对应）：
R1 HTML 残留：删除残余标签与实体；
R2 站点噪声：删除导航、按钮、版权、推荐、附件、日期行等非正文行；
R3 链接与联系方式：删除 URL、邮箱、社交账号导流；
R4 表情与异常符号：删除 emoji、零宽字符、控制符；
R5 空白规范化：统一换行/空格，去首尾空白与连续空行；
R6 标点规范化：合并重复标点、全角字母数字转半角、去掉中文间多余空格；
R7 段落去重：删除完全重复及高相似度重复段落；
R8 编码与空值：清理替换符，作者/日期缺失显式标注“未知”并打质量标记。

输出：
    data/processed/wugongshan_guides.csv   （主数据集）
    data/interim/clean_stats.json          （逐篇清洗统计，供报告引用）

用法：
    python src/clean.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from common import (
    DATASET_CSV, EXTRACTED_JSONL, INTERIM_DIR, PROCESSED_DIR, SCENIC_AREA,
    setup_logging,
)

log = logging.getLogger("clean")

# ---------- 规则常量 ----------
URL_RE = re.compile(r"(https?://[^\s，。；、）)】\]]+|www\.[^\s，。；、）)】\]]+)", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]{0,200}>")
HTML_ENTITY_RE = re.compile(r"&(nbsp|amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);")
EMOJI_RE = re.compile(
    "[" 
    "\U0001F000-\U0001FAFF"   # 表情、符号、旗帜
    "\U00002600-\U000027BF"   # 杂项符号与装饰符
    "\U0001F1E6-\U0001F1FF"   # 区域旗帜
    "\uFE0F\u200D\u20E3"      # 变体选择符、零宽连接、键帽
    "\u2B00-\u2BFF\u203C\u2049\u2122\u2139"
    "]"
)
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# 以“整行”为单位的站点噪声（行内出现且行较短时删除）
NOISE_LINE_RE = re.compile(
    r"(豆瓣小站|豆瓣小组|新浪微博|微信公众号|扫码|长按识别|点击关注|关注我们|"
    r"阅读原文|返回搜狐|来源网络|版权声明|未经允许|不得转载|作者简介|"
    r"^编辑[:：]|^责编[:：]|^原标题|本文来自|侵删|操作按钮|投诉按钮|"
    r"小组帖视频|^正文内容$|热门推荐|相关推荐|猜你喜欢|上一篇|下一篇|"
    r"返回顶部|^登录$|^注册$|下载APP|打开APP|下载积分|^下载|^上传$|附件|"
    r"本帖最后由|^\d{4}-\d{2}-\d{2}|^发表于|^\d+人(阅读|参与)|^阅读\s*\d+|"
    r"^点赞|^收藏|^评论|^回复$|^分享$|^\[\d+\]$|^图片\d*$)"
)
# 无条件删除的强噪声行（含版权/导流语义）
HARD_NOISE_RE = re.compile(
    r"(版权所有|Copyright|All Rights Reserved|免责声明|转载请注明|"
    r"更多精彩.*(微信|公众号)|扫描二维码|点击.*查看更多)"
)

TRADITIONAL_CHARS = set(
    "這個們說時間過還讓給從來對開關麼樣點線車門陽雲風龍頭體髮鬥穀於與為將屬團園國學實現發經歷遊覽觀見覺認識語讀寫聽買賣費價錢銀鐵銅長問陰隊際隨雖難霧靜響頁頂項順須顏飛餐館駕駛騎麗黃黑"
)


def normalize_punctuation(text: str) -> str:
    """R6 标点与字符宽度规范化。"""
    # 全角 ASCII -> 半角（保留中文标点）
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E and ch not in "，。！？；：、（）【】《》“”‘’｜":
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    text = "".join(out)
    text = re.sub(r"([！？])\1{1,}", r"\1", text)          # ！！！ -> ！
    text = re.sub(r"。{2,}", "……", text)                   # 。。。 -> ……
    text = re.sub(r"，{2,}", "，", text)
    text = re.sub(r"[ \t]+([，。！？；：、）】》”’])", r"\1", text)
    text = re.sub(r"([（【《“‘])\s+", r"\1", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def is_junk_line(line: str) -> bool:
    """识别论坛签名、分隔线、表情堆叠等低信息量行。"""
    if len(line) < 6:
        return False
    chars = [c for c in line if not c.isspace()]
    meaningful = sum(1 for c in chars if c.isalnum() or "\u4e00" <= c <= "\u9fff")
    if meaningful / max(len(chars), 1) < 0.35:
        return True
    if re.fullmatch(r"[-=_*~—\s]{6,}", line):
        return True
    if re.search(r"^\d{4}-\d{2}-\d{2}.*(上传|编辑|发表|更新)$", line):
        return True
    return False


def strip_noise_lines(text: str) -> tuple[str, dict]:
    """R1-R4：逐行删除站点噪声/链接/表情，返回文本与计数。"""
    stats = {"noise_lines": 0, "urls": 0, "emails": 0, "emoji": 0, "html": 0}
    kept: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if is_junk_line(line):
            stats["noise_lines"] += 1
            continue

        tags = HTML_TAG_RE.findall(line)
        if tags:
            stats["html"] += len(tags)
            line = HTML_TAG_RE.sub("", line)
        if HTML_ENTITY_RE.search(line):
            stats["html"] += 1
            line = HTML_ENTITY_RE.sub(" ", line)

        # 整行噪声：按钮、导航、版权、下载信息等
        if NOISE_LINE_RE.search(line) or HARD_NOISE_RE.search(line):
            stats["noise_lines"] += 1
            continue
        # 以链接为主的行（如“游记详帖：http://...”）
        urls = URL_RE.findall(line)
        if urls:
            stats["urls"] += len(urls)
            if len(URL_RE.sub("", line).strip(" ：:，。")) <= 6:
                stats["noise_lines"] += 1
                continue
            line = URL_RE.sub("", line)
        if EMAIL_RE.search(line):
            stats["emails"] += len(EMAIL_RE.findall(line))
            line = EMAIL_RE.sub("", line)

        # 键帽数字（1️⃣）先还原为列表序号，避免去 emoji 后出现“1证件”粘连
        line = re.sub(r"([0-9])\ufe0f?\u20e3", r"\1. ", line)
        before = len(line)
        line = EMOJI_RE.sub("", line)
        stats["emoji"] += before - len(line)
        line = ZERO_WIDTH_RE.sub("", line)
        line = CTRL_RE.sub("", line)

        line = re.sub(r"\s+", " ", line).strip()
        line = strip_trailing_junk(line)
        if line:
            kept.append(line)
    return "\n".join(kept), stats


def strip_trailing_junk(line: str) -> str:
    """去掉句末粘附的时间戳/论坛签名（如“…… 2014-11-24 18:20 上传”）。"""
    line = re.sub(
        r"\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?\s*(上传|编辑|发表)?\s*$", "", line
    )
    m = re.search(r"[。！？…”]\s*([^\u4e00-\u9fff]{6,60})$", line)
    if m:
        seg = m.group(1)
        symbols = sum(1 for c in seg if not c.isalnum() and not c.isspace())
        if symbols / max(len(seg), 1) > 0.25:
            line = line[: m.start(1)].rstrip()
    return line


def dedupe_paragraphs(text: str) -> tuple[str, int]:
    """R7：删除完全重复与高相似（>=0.90）的段落，保留首次出现。"""
    paras = [p.strip() for p in text.splitlines() if p.strip()]
    kept: list[str] = []
    seen_norm: set[str] = set()
    removed = 0
    for p in paras:
        norm = re.sub(r"[\s\W_]+", "", p)
        if len(norm) < 8:
            kept.append(p)
            continue
        if norm in seen_norm:
            removed += 1
            continue
        # 与最近 3 段做相似度比较，处理轻微改写的重复段落
        dup = False
        for prev in kept[-3:]:
            prev_norm = re.sub(r"[\s\W_]+", "", prev)
            if not prev_norm:
                continue
            if abs(len(prev_norm) - len(norm)) / max(len(prev_norm), len(norm)) > 0.3:
                continue
            if SequenceMatcher(None, prev_norm, norm).ratio() >= 0.90:
                dup = True
                break
        if dup:
            removed += 1
            continue
        seen_norm.add(norm)
        kept.append(p)
    return "\n".join(kept), removed


def has_traditional(text: str) -> bool:
    return sum(1 for ch in text if ch in TRADITIONAL_CHARS) >= 20


def clean_one(rec: dict) -> dict:
    raw = rec["raw_content"]
    text, stats = strip_noise_lines(raw)
    text = unicodedata.normalize("NFC", text)
    text = normalize_punctuation(text)
    text, dup_removed = dedupe_paragraphs(text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = text.replace("\ufffd", "")

    flags: list[str] = []
    if stats["html"]:
        flags.append("HTML残留已清理")
    if stats["noise_lines"]:
        flags.append("站点噪声已清理")
    if stats["urls"] or stats["emails"]:
        flags.append("链接已清理")
    if stats["emoji"]:
        flags.append("表情符号已清理")
    if dup_removed:
        flags.append("重复段落已去除")
    if has_traditional(text):
        flags.append("含繁体字")

    char_clean = len(re.sub(r"\s", "", text))
    char_raw = len(re.sub(r"\s", "", raw))
    if not rec.get("author"):
        flags.append("作者缺失")
    if not rec.get("publish_date"):
        flags.append("日期缺失")

    is_valid = True
    if rec["doc_type"] == "官方路线" and char_clean < 60:
        flags.append("文本过短")
        is_valid = False
    if rec["doc_type"] == "游客游记" and char_clean < 300:
        flags.append("文本过短")
        flags.append("图片为主")
        is_valid = False

    return {
        **{k: v for k, v in rec.items() if k != "raw_content"},
        "raw_content": raw,
        "clean_content": text,
        "char_raw": char_raw,
        "char_clean": char_clean,
        "para_raw": len([p for p in raw.splitlines() if p.strip()]),
        "para_clean": len([p for p in text.splitlines() if p.strip()]),
        "removed_char_ratio": round(1 - char_clean / char_raw, 4) if char_raw else 0,
        "noise_lines_removed": stats["noise_lines"],
        "emoji_removed": stats["emoji"],
        "urls_removed": stats["urls"] + stats["emails"],
        "dup_paragraphs_removed": dup_removed,
        "quality_flags": "；".join(flags) if flags else "无",
        "is_valid": is_valid,
        "clean_hash": hashlib.sha1(text.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    setup_logging()
    records = [json.loads(line) for line in open(EXTRACTED_JSONL, encoding="utf-8")]
    cleaned = [clean_one(r) for r in records]
    df = pd.DataFrame(cleaned)

    # 文档级完全重复检查（同一文本被不同 URL 转载等）
    dup_ids = df[df.duplicated("clean_hash", keep=False)]["doc_id"].tolist()
    if dup_ids:
        df.loc[df["doc_id"].isin(dup_ids), "quality_flags"] += "；文档级重复"
        log.warning("发现文档级重复：%s", dup_ids)

    # 列顺序：元数据 -> 文本 -> 统计 -> 质量
    cols = [
        "doc_id", "scenic_area", "doc_type", "subtype", "title", "author",
        "publish_date", "source_site", "source_url", "extract_rule",
        "raw_content", "clean_content", "char_raw", "char_clean",
        "para_raw", "para_clean", "removed_char_ratio", "noise_lines_removed",
        "emoji_removed", "urls_removed", "dup_paragraphs_removed",
        "quality_flags", "is_valid", "clean_hash",
    ]
    df = df[cols]
    df.to_csv(DATASET_CSV, index=False, encoding="utf-8-sig", lineterminator="
")

    summary = {
        "records": len(df),
        "valid": int(df["is_valid"].sum()),
        "raw_chars": int(df["char_raw"].sum()),
        "clean_chars": int(df["char_clean"].sum()),
        "noise_lines_removed": int(df["noise_lines_removed"].sum()),
        "emoji_removed": int(df["emoji_removed"].sum()),
        "urls_removed": int(df["urls_removed"].sum()),
        "dup_paragraphs_removed": int(df["dup_paragraphs_removed"].sum()),
        "per_doc": df[[
            "doc_id", "title", "doc_type", "char_raw", "char_clean",
            "removed_char_ratio", "noise_lines_removed", "emoji_removed",
            "urls_removed", "dup_paragraphs_removed", "quality_flags", "is_valid",
        ]].to_dict(orient="records"),
    }
    with open(INTERIM_DIR / "clean_stats.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log.info(
        "清洗完成：%d 条（有效 %d），原始 %d 字 -> 清洗后 %d 字，去噪行 %d，去重段 %d",
        len(df), summary["valid"], summary["raw_chars"], summary["clean_chars"],
        summary["noise_lines_removed"], summary["dup_paragraphs_removed"],
    )
    log.info("主数据集 -> %s", DATASET_CSV)


if __name__ == "__main__":
    main()
