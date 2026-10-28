# -*- coding: utf-8 -*-
"""
实验项目一 · 数据清洗与结构化脚本 —— 长隆旅游度假区（广州）
=========================================================
输入：data/interim/raw_docs.jsonl（采集脚本产出，raw_text 为「原始内容」）
输出：data/interim/legacy_20col.csv / .json         清洗后的中间表（20 列）
      outputs/cleaning_samples.csv                   清洗前后样例（逐规则）
      outputs/quality_report.json                    质量检查指标

清洗流水线（每条规则都记录字符削减量与命中次数，便于报告溯源）
  R1  去除 HTML 标签（块级标签先转成换行，避免段落粘连）
  R2  HTML 实体还原（&quot; &amp; &nbsp; 等）
  R3  去除页面模板 / 元数据行（发布日期、版权、图片署名、“相關貼文”等）
  R4  去除网址、邮箱、客服电话
  R5  去除 emoji、零宽字符、装饰性符号（✔ ✅ ❗ ※ √ 等）
  R6  空白与换行统一（NBSP / 全角空格 / 制表符 / 连续空行）
  R7  标点统一（中文语境下半角转全角、重复标点收敛、... → ……）
  R8  繁体 → 简体（OpenCC t2s），统一字符编码口径
  R9  段内重复行去重
  R10 收尾整理（符号删除后残留的空格/空行）
  R11 跨文档完全重复检测（MD5）
  R12 近重复检测（字符 3-gram Jaccard）
  R13 空值 / 过短 / 缺失字段检查

设计原则：不做“一刀切删除”——凡涉及路线顺序、时间的 token 一律保留；
删除只针对模板噪声；异常字段标记为 invalid 而不是静默丢弃。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter

import pandas as pd
from opencc import OpenCC

BASE = pathlib.Path(__file__).resolve().parents[1]
INTERIM = BASE / "data" / "interim" / "raw_docs.jsonl"
INTERIM_DIR = BASE / "data" / "interim"   # 中间产物
OUT_DIR = BASE / "outputs"                        # 质量报告与样例
OUT_DIR.mkdir(parents=True, exist_ok=True)
CC = OpenCC("t2s")

# ---------------------------------------------------------------- 规则定义
# R3 页面模板/元数据行：整行命中即删除
BOILERPLATE_PATTERNS = [
    r"^\s*發佈日期[：:].*$",
    r"^\s*发布日期[：:].*$",
    r"^\s*提交\s*$",
    r"^\s*於這篇?Moment中提及\s*$",
    r"^\s*顯示更多\s*$",
    r"^\s*查看原文\s*$",
    r"^\s*相關貼文\s*$",
    r"^\s*更多推薦\s*$",
    r"^\s*熱門 Trip Moments\s*$",
    r"^\s*人氣旅遊部落格\s*$",
    r"^\s*熱門目的地\s*$",
    r"^\s*图片[：:].*$",
    r"^\s*文字[：:].*$",
    r"^\s*备注[：:].*$",
    r".*轉載請註明出處.*$",
    r".*转载请注明出处.*$",
    r".*本文由.{0,20}原创.*$",
    r"^\s*【?广告】?\s*$",
    # Trip.com 游记页模板行
    r"^.*分享的\s*.{0,24}?\s*Trip Moment\s*$",
    r"^\s*\d+\s*(?:天|小時|小时|分鐘|分钟)前發布.*$",
    r"^.*幫助了\s*\d+\s*位旅客的旅程\s*$",
    r"^\s*還有另外\s*\d+\s*篇.*$",
    r"^\s*\d{4}\.\d{2}\.\d{2}\s*.*即時旅遊資訊\s*$",
    r"^\s*今日天氣[：:].*$",
    r"^\s*今日營業狀態[：:].*$",
    r"^\s*點評分[：:].*$",
    r"^\s*点赞\s*\d+.*$",
    r"^\s*\d+\s*位旅客[与與]此.*$",
    # 官方页的装饰性评分行（“推荐指数：※※※※※”），对程序性知识抽取无信息量
    r"^.{0,24}?(?:推荐|推薦|尖叫|好吃|浪漫|好看)指数[：:]?[※☆★\d]*\s*$",
]
# 正文内联的模板短语
BOILERPLATE_INLINE = [
    r"Trip\.com\s*廣州",
    r"Trip\.com",
    r"Trip\s*Moments?",
    r"分享的\s*\S{0,12}\s*Trip Moment",
    r"還有另外\s*\d+\s*篇關於\s*\S+\s*的\s*Trip Moment.*?參考",
    r"\d{4}\.\d{2}\.\d{2}\s*即時旅遊資訊",
    r"今日天氣[：:].*?$",
    r"今日營業狀態[：:].*?$",
    r"點評分[：:]\s*[\d.]+/5.*?$",
]
RE_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RE_PHONE = re.compile(r"(?:400|800)[-\s]?\d{3}[-\s]?\d{4}")
RE_EMOJI = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U0001F1E6-\U0001F1FF" "\u2300-\u27BF"
    "\u2B00-\u2BFF" "\u203C\u2049" "\uFE0F" "\u200B-\u200F" "\uFEFF" "]"
)
# 图标字体私有区字符（爬到的页面里表现为“空白方块”，必须清除）
RE_PUA = re.compile(r"[\uE000-\uF8FF]")
# 装饰性箭头 emoji 保留其“顺序”语义，换成普通箭头
ARROW_MAP = {"➡": "→", "➔": "→", "➜": "→", "⟶": "→", "⇒": "→"}
# 注意：箭头（→ ← ↑ ↓）承载路线先后语义，绝不能当装饰符号删除
RE_SPECIAL = re.compile(r"[※√✔✅◦•◆◇■□●○▪▫★☆♥♡]")
RE_SPACE = re.compile(r"[\u00A0\u3000\t\u2002-\u200A\u202F\u205F]")
RE_MULTI_NL = re.compile(r"\n{2,}")
RE_MULTI_SPACE = re.compile(r"[ ]{2,}")
# 中文语境下半角标点 → 全角
CJK = r"\u4e00-\u9fff"
# 标点前可以视为“中文语境”的字符（含引号、括号、省略号等收尾符号）
PREV = r"\u4e00-\u9fff”’」』）】…\)\]\""
PUNCT_MAP = [
    (re.compile(rf"(?<=[{PREV}]),"), "，"),
    (re.compile(rf"(?<=[{PREV}]);"), "；"),
    (re.compile(rf"(?<=[{PREV}])!"), "！"),
    (re.compile(rf"(?<=[{PREV}])\?"), "？"),
    (re.compile(rf"(?<=[{CJK}]):"), "："),
]
# 含中文的英文引号/括号 → 中文引号/全角括号
RE_QUOTE_CJK = re.compile(r'"([^"\n]{1,40}?)"')
RE_PAREN_CJK = re.compile(r"\(([^()\n]{0,40}?[\u4e00-\u9fff][^()\n]{0,40}?)\)")
# “09. 40”这类时间排版噪声；后面紧跟数字或冒号的（如编号“1. 09:30”）不算
RE_TIME_DOT = re.compile(r"(?<![\d:])(\d{1,2})\s*[.．]\s*(\d{2})(?![\d:])")
RE_ENUM_DOT = re.compile(r"^\s*([一二三四五六七八九十]+)\s*[.．]\s*")
RE_DUP_PUNCT = re.compile(r"([，。、；：！？])\1+")
RE_ELLIPSIS = re.compile(r"\.{3,}")
RE_TRAIL = re.compile(r"[，、；：\s]+$")


class Cleaner:
    """按规则顺序清洗单篇文本，并记录每条规则的削减/替换量。"""

    def __init__(self, title: str = "") -> None:
        self.log: list[dict] = []
        self.samples: list[dict] = []
        self.doc_id = ""
        self.title = title

    def step(self, rule: str, text: str, func, desc: str) -> str:
        before = text
        after = func(before)
        removed = max(0, len(before) - len(after))
        # 长度不变时（如繁简转换）统计“被替换的字符数”，避免规则看起来没生效
        substituted = 0
        if len(before) == len(after):
            substituted = sum(1 for a, b in zip(before, after) if a != b)
        changed = max(removed, substituted)
        self.log.append(
            {
                "rule": rule,
                "desc": desc,
                "removed_chars": removed,
                "substituted_chars": substituted,
                "changed_chars": changed,
                "fired": before != after,
            }
        )
        if before != after and len(self.samples) < 4:
            diff = self._first_diff(before, after)
            self.samples.append(
                {
                    "doc_id": self.doc_id, "rule": rule, "desc": desc,
                    "before": diff[0], "after": diff[1],
                }
            )
        return after

    @staticmethod
    def _first_diff(before: str, after: str) -> tuple[str, str]:
        idx = 0
        limit = min(len(before), len(after))
        while idx < limit and before[idx] == after[idx]:
            idx += 1
        start = max(0, idx - 20)
        return before[start : idx + 60].replace("\n", "⏎"), after[start : idx + 60].replace("\n", "⏎")

    # ------------------------------------------------------------ 各规则
    def r1_html(self, text: str) -> str:
        text = re.sub(r"<(?:br|/p|/div|/li|/h\d)[^>]*>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        return text

    def r2_entity(self, text: str) -> str:
        table = {
            "&quot;": '"', "&amp;": "&", "&nbsp;": " ", "&lt;": "<", "&gt;": ">",
            "&#39;": "'", "&ldquo;": "“", "&rdquo;": "”", "&hellip;": "…",
        }
        for k, v in table.items():
            text = text.replace(k, v)
        return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)

    def r3_boilerplate(self, text: str) -> str:
        lines = text.split("\n")
        kept = [ln for ln in lines if not any(re.match(p, ln) for p in BOILERPLATE_PATTERNS)]
        # 去掉正文区开头的空行/图标字符行后再比对标题
        while kept and not re.sub(r"\s+", "", kept[0]):
            kept.pop(0)
        # 正文区首行常与标题重复：标题已在独立字段保存，正文中去掉重复项
        title_key = re.sub(r"\s+", "", self.title)[:20]
        while kept and title_key and re.sub(r"\s+", "", kept[0])[:20] == title_key:
            kept.pop(0)
        text = "\n".join(kept)
        for pat in BOILERPLATE_INLINE:
            text = re.sub(pat, "", text)
        return text

    def r4_url(self, text: str) -> str:
        text = RE_URL.sub("", text)
        text = RE_EMAIL.sub("", text)
        return RE_PHONE.sub("", text)

    def r5_symbol(self, text: str) -> str:
        for k, v in ARROW_MAP.items():
            text = text.replace(k, v)
        text = RE_PUA.sub("", text)
        text = RE_EMOJI.sub("", text)
        text = RE_SPECIAL.sub("", text)
        # 装饰性变体选择符 / 竖线分隔符
        return re.sub(r"[|｜]{2,}", "｜", text)

    def r6_whitespace(self, text: str) -> str:
        text = RE_SPACE.sub(" ", text)
        text = "\n".join(ln.strip() for ln in text.split("\n"))
        text = RE_MULTI_SPACE.sub(" ", text)
        # 中文标点两侧不留空格（游记里 “必做： 提前到达” 很常见）
        text = re.sub(r"(?<=[，。、；：！？）】”…])[ \t]+", "", text)
        text = re.sub(r"[ \t]+(?=[，。、；：！？）】”…])", "", text)
        text = RE_MULTI_NL.sub("\n", text)
        return text.strip()

    def r7_punct(self, text: str) -> str:
        for pat, rep in PUNCT_MAP:
            text = pat.sub(rep, text)
        # 英文引号/括号内含中文 → 中文标点（游记里半角混排极常见）
        text = RE_QUOTE_CJK.sub(lambda m: f"“{m.group(1)}”", text)
        text = RE_PAREN_CJK.sub(lambda m: f"（{m.group(1)}）", text)
        # 时间噪声：“09. 40” → “09:40”（仅对 0–23 点生效，避免误改小数）
        text = RE_TIME_DOT.sub(
            lambda m: f"{m.group(1)}:{m.group(2)}"
            if 0 <= int(m.group(1)) <= 23
            else m.group(0),
            text,
        )
        # 中文枚举序号统一：“一.” → “一、”
        text = "\n".join(RE_ENUM_DOT.sub(r"\1、", ln) for ln in text.split("\n"))
        text = RE_ELLIPSIS.sub("……", text)
        text = RE_DUP_PUNCT.sub(r"\1", text)
        text = "\n".join(RE_TRAIL.sub("", ln) for ln in text.split("\n"))
        return text

    def r8_t2s(self, text: str) -> str:
        return CC.convert(text)

    def r9_dedup_lines(self, text: str) -> str:
        seen: Counter = Counter()
        out = []
        for ln in text.split("\n"):
            key = re.sub(r"\s+", "", ln)
            if len(key) >= 6 and seen[key] >= 1:
                continue  # 段内重复行只保留首次
            seen[key] += 1
            out.append(ln)
        return "\n".join(out)

    def r10_tidy(self, text: str) -> str:
        """收尾整理：符号删除后才暴露出来的空括号空格、残留空行等。"""
        text = re.sub(r"(?<=[（【《“])[ \t]+", "", text)
        text = re.sub(r"[ \t]+(?=[）】》，。、；：！？])", "", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = "\n".join(ln.strip() for ln in text.split("\n") if ln.strip())
        return text


def clean_text(raw: str, doc_id: str, title: str = "") -> tuple[str, Cleaner]:
    c = Cleaner(title=title)
    c.doc_id = doc_id
    t = raw
    t = c.step("R1", t, c.r1_html, "去除 HTML 标签")
    t = c.step("R2", t, c.r2_entity, "还原 HTML 实体")
    t = c.step("R3", t, c.r3_boilerplate, "去除页面模板/元数据行")
    t = c.step("R4", t, c.r4_url, "去除网址/邮箱/客服电话")
    t = c.step("R5", t, c.r5_symbol, "去除 emoji 与装饰符号")
    t = c.step("R6", t, c.r6_whitespace, "空白与换行统一")
    t = c.step("R7", t, c.r7_punct, "标点统一")
    t = c.step("R8", t, c.r8_t2s, "繁体转简体")
    t = c.step("R9", t, c.r9_dedup_lines, "段内重复行去重")
    t = c.step("R10", t, c.r10_tidy, "收尾整理（空括号空格/残留空行）")
    return t, c


# ---------------------------------------------------------------- 质量检查
def ngrams(text: str, n: int = 3) -> set[str]:
    s = re.sub(r"\s+", "", text)
    return {s[i : i + n] for i in range(max(0, len(s) - n + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def run_quality_checks(df: pd.DataFrame) -> dict:
    report: dict = {}
    report["record_count"] = int(len(df))
    report["by_doc_type"] = df["doc_type"].value_counts().to_dict()
    report["by_park"] = df["park"].value_counts().to_dict()
    report["by_source"] = df["source_site"].value_counts().to_dict()

    # 缺失值检查
    fields = ["title", "author", "publish_date", "raw_text", "clean_text", "source_url", "park", "doc_type"]
    missing = {}
    for f in fields:
        blank = df[f].isna() | (df[f].astype(str).str.strip() == "")
        missing[f] = int(blank.sum())
    report["missing_values"] = missing
    report["missing_rate"] = {k: round(v / len(df), 4) for k, v in missing.items()}

    # 完全重复
    hashes = df["clean_text"].map(lambda s: hashlib.md5(re.sub(r"\s+", "", s).encode()).hexdigest())
    dup_mask = hashes.duplicated(keep=False)
    report["exact_duplicate_docs"] = int(hashes.duplicated().sum())
    report["exact_duplicate_ids"] = df.loc[dup_mask, "doc_id"].tolist()

    # 近重复
    grams = {r.doc_id: ngrams(r.clean_text) for r in df.itertuples()}
    pairs = []
    ids = list(grams)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sim = jaccard(grams[ids[i]], grams[ids[j]])
            if sim >= 0.30:
                pairs.append({"doc_a": ids[i], "doc_b": ids[j], "jaccard_3gram": round(sim, 3)})
    report["near_duplicate_pairs_ge_0.30"] = sorted(pairs, key=lambda d: -d["jaccard_3gram"])

    # 格式一致性
    fmt = {}
    fmt["含HTML残留"] = int(df["clean_text"].str.contains(r"<[a-zA-Z/][^>]*>", regex=True).sum())
    fmt["含网址"] = int(df["clean_text"].str.contains(r"https?://|www\.", regex=True).sum())
    fmt["含emoji"] = int(df["clean_text"].apply(lambda s: bool(RE_EMOJI.search(s))).sum())
    fmt["含半角逗号/句号"] = int(df["clean_text"].str.contains(r"[\u4e00-\u9fff],|[\u4e00-\u9fff]\.", regex=True).sum())
    fmt["含繁体字残留"] = int(df["clean_text"].apply(lambda s: CC.convert(s) != s).sum())
    fmt["含全角空格/NBSP"] = int(df["clean_text"].str.contains(r"[\u00a0\u3000]", regex=True).sum())
    fmt["含连续空行"] = int(df["clean_text"].str.contains(r"\n{2,}", regex=True).sum())
    fmt["空文本"] = int((df["clean_text"].str.strip() == "").sum())
    report["format_consistency"] = fmt

    # 长度统计
    stats = {}
    for t in ["raw_text", "clean_text"]:
        s = df[t].str.len()
        stats[t] = {
            "min": int(s.min()), "max": int(s.max()),
            "mean": round(float(s.mean()), 1), "median": float(s.median()),
            "total": int(s.sum()),
        }
    stats["paragraphs_clean"] = {
        "min": int(df["paragraph_count"].min()), "max": int(df["paragraph_count"].max()),
        "mean": round(float(df["paragraph_count"].mean()), 1),
    }
    report["length_stats"] = stats
    report["reduction"] = {
        "total_raw": int(df["raw_len"].sum()),
        "total_clean": int(df["clean_len"].sum()),
        "overall_reduction_rate": round(
            1 - df["clean_len"].sum() / max(1, df["raw_len"].sum()), 4
        ),
    }
    # 规则级削减量汇总
    rule_removed: Counter = Counter()
    rule_substituted: Counter = Counter()
    rule_hits: Counter = Counter()
    for log in df["_rule_log"]:
        for item in log:
            rule_removed[item["desc"]] += item["removed_chars"]
            rule_substituted[item["desc"]] += item.get("substituted_chars", 0)
            rule_hits[item["desc"]] += int(item.get("fired", False))
    report["rule_stats"] = {
        desc: {
            "removed_chars": rule_removed[desc],
            "substituted_chars": rule_substituted[desc],
            "docs_fired": rule_hits[desc],
        }
        for desc in rule_removed
    }
    return report


def main() -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = [json.loads(line) for line in INTERIM.open(encoding="utf-8")]
    rows, samples = [], []
    for rec in records:
        cleaned, cleaner = clean_text(rec["raw_text"], rec["doc_id"], rec.get("title", ""))
        rec["clean_text"] = cleaned
        rec["raw_len"] = len(rec["raw_text"])
        rec["clean_len"] = len(cleaned)
        rec["char_count_no_space"] = len(re.sub(r"\s+", "", cleaned))
        rec["paragraph_count"] = len([p for p in cleaned.split("\n") if p.strip()])
        rec["reduction_rate"] = round(1 - rec["clean_len"] / max(1, rec["raw_len"]), 3)
        rec["cleaning_log"] = "；".join(
            f"{i['desc']}-{i['removed_chars']}" for i in cleaner.log if i["removed_chars"]
        )
        rec["is_valid"] = bool(cleaned.strip()) and rec["clean_len"] >= 50
        rec["_rule_log"] = cleaner.log
        samples.extend(cleaner.samples)
        rows.append(rec)

    df = pd.DataFrame(rows)
    report = run_quality_checks(df)

    # 输出：结构化语料（CSV 供 Excel 直接打开，JSON 供后续项目读取）
    out_cols = [
        "doc_id", "source_site", "source_url", "scenic_area", "park", "doc_type",
        "title", "author", "publish_date", "fetch_time", "extract_rule",
        "raw_len", "clean_len", "char_count_no_space", "paragraph_count",
        "reduction_rate", "is_valid", "cleaning_log", "clean_text", "raw_text",
    ]
    df_out = df[out_cols].sort_values("doc_id")
    df_out.to_csv(INTERIM_DIR / "legacy_20col.csv", index=False, encoding="utf-8-sig", lineterminator="
")
    df_out.to_json(INTERIM_DIR / "chimelong_docs.json", orient="records", force_ascii=False, indent=2)
    # 供后续项目直接读取的精简表（只留清洗文本，避免下游误用原始 HTML）
    df_out[out_cols[:18]].to_csv(
        INTERIM_DIR / "chimelong_docs_index.csv", index=False, encoding="utf-8-sig"
    )

    pd.DataFrame(samples).to_csv(
        OUT_DIR / "cleaning_samples.csv", index=False, encoding="utf-8-sig"
    )
    with (OUT_DIR / "quality_report.json").open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    # 控制台摘要
    print(df_out[["doc_id", "doc_type", "park", "raw_len", "clean_len", "reduction_rate", "is_valid"]].to_string(index=False))
    print("\n规则削减量：")
    for k, v in report["rule_stats"].items():
        print(f"  {k:<22} 删除 {v['removed_chars']:>6}  替换 {v['substituted_chars']:>5}  命中 {v['docs_fired']} 篇")
    print("\n质量检查：")
    print(json.dumps({k: report[k] for k in ("missing_values", "exact_duplicate_docs",
                                             "format_consistency", "reduction")}, ensure_ascii=False, indent=2))
    print(f"\n输出目录：{INTERIM_DIR} / {OUT_DIR}")


if __name__ == "__main__":
    main()
