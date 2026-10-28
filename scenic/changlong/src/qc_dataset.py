# -*- coding: utf-8 -*-
"""
实验项目一 · 数据质量检查与可视化脚本
=====================================
输入：data/interim/legacy_20col.csv、outputs/quality_report.json
输出：figures/*.png、docs/quality_report.md

检查项
  1. 记录规模与构成（景区 / 文本类型 / 来源）
  2. 缺失值（空标题、空作者、空日期、空正文）
  3. 重复（完全重复 MD5、近重复 3-gram Jaccard）
  4. 格式一致性（HTML 残留、网址、emoji、半角标点、繁体残留、全角空格、连续空行）
  5. 长度分布与清洗削减率
  6. 后续项目可用性（是否含时间表达、箭头链路、编号列表）
"""
from __future__ import annotations

import json
import pathlib
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

BASE = pathlib.Path(__file__).resolve().parents[1]
INTERIM_DIR = BASE / "data" / "interim"
OUT_DIR = BASE / "outputs"
FIG_DIR = OUT_DIR / "figures"
DOCS = OUT_DIR

# 中文字体
for candidate in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
    if pathlib.Path(candidate).exists():
        font_manager.fontManager.addfont(candidate)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=candidate).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False


def usability_flags(text: str) -> dict:
    return {
        "has_time": bool(re.search(r"\b\d{1,2}[:：]\d{2}\b|上午|中午|下午|傍晚|晚上", text)),
        "has_arrow": "→" in text,
        "has_numbering": bool(re.search(r"^(第[一二三四五六七八九十]+站|\d{1,2}[.、．])", text, re.M)),
        "has_poi_keyword": bool(re.search(r"园区|乐园|景点|广场|馆|园|宫|剧场|餐厅|站", text)),
    }


def fig_length_compare(df: pd.DataFrame) -> pathlib.Path:
    fig, ax = plt.subplots(figsize=(8.2, 4.2), dpi=200)
    x = range(len(df))
    w = 0.38
    ax.bar([i - w / 2 for i in x], df["raw_len"], width=w, label="清洗前（原始内容）", color="#9aa5b1")
    ax.bar([i + w / 2 for i in x], df["clean_len"], width=w, label="清洗后", color="#2f7ed8")
    ax.set_xticks(list(x))
    ax.set_xticklabels(df["doc_id"], rotation=0, fontsize=8)
    ax.set_ylabel("字符数")
    ax.legend(fontsize=8)
    for i, (r, cl) in enumerate(zip(df["raw_len"], df["clean_len"])):
        ax.text(i, max(r, cl) + 150, f"-{1 - cl / r:.0%}", ha="center", fontsize=7, color="#c0392b")
    ax.set_ylim(0, df["raw_len"].max() * 1.18)
    fig.tight_layout()
    out = FIG_DIR / "fig1_length_compare.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_rule_stats(report: dict) -> pathlib.Path:
    stats = report["rule_stats"]
    names = list(stats)[::-1]
    removed = [stats[n]["removed_chars"] for n in names]
    substituted = [stats[n]["substituted_chars"] for n in names]
    fig, ax = plt.subplots(figsize=(8.2, 4.0), dpi=200)
    y = range(len(names))
    ax.barh([i for i in y], removed, color="#2f7ed8", label="删除字符数")
    ax.barh([i for i in y], substituted, left=removed, color="#f39c12", label="替换字符数")
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("字符数")
    ax.legend(fontsize=8)
    for i, (a, b) in enumerate(zip(removed, substituted)):
        ax.text(a + b + 200, i, f"{a + b}", va="center", fontsize=7)
    ax.set_xlim(0, max(r + s for r, s in zip(removed, substituted)) * 1.18)
    fig.tight_layout()
    out = FIG_DIR / "fig2_rule_stats.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_composition(df: pd.DataFrame) -> pathlib.Path:
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.4), dpi=200)
    park_counts = df["park"].value_counts()
    axes[0].bar(park_counts.index, park_counts.values, color="#2f7ed8")
    axes[0].set_title("按园区分布", fontsize=9)
    axes[0].set_ylabel("文档数")
    axes[0].yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    axes[0].tick_params(axis="x", labelsize=7, rotation=20)
    for i, v in enumerate(park_counts.values):
        axes[0].text(i, v + 0.05, str(v), ha="center", fontsize=8)

    type_counts = df["doc_type"].value_counts()
    axes[1].pie(
        type_counts.values, labels=type_counts.index, autopct="%1.0f%%",
        colors=["#2f7ed8", "#f39c12"], textprops={"fontsize": 9},
    )
    axes[1].set_title("按文本类型分布", fontsize=9)
    fig.tight_layout()
    out = FIG_DIR / "fig3_composition.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(INTERIM_DIR / "legacy_20col.csv").sort_values("doc_id")
    report = json.loads((OUT_DIR / "quality_report.json").read_text(encoding="utf-8"))

    # 可用性标记
    flags = df["clean_text"].apply(usability_flags).apply(pd.Series)
    df_flags = pd.concat([df[["doc_id", "doc_type", "park"]], flags], axis=1)
    df_flags.to_csv(OUT_DIR / "usability_flags.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    coverage = {c: f"{int(flags[c].sum())}/{len(df)}" for c in flags.columns}

    f1 = fig_length_compare(df)
    f2 = fig_rule_stats(report)
    f3 = fig_composition(df)

    # ------------------------------------------------------------ Markdown 报告
    L = []
    L.append("# 长隆旅游度假区数据集质量检查报告\n")
    L.append(f"- 数据集：`data/interim/legacy_20col.csv`（{len(df)} 篇）")
    L.append("- 生成脚本：`scripts/clean_chimelong.py` → `scripts/quality_check.py`")
    L.append("- 采集时间：2026-10-28；采集方式：requests + BeautifulSoup 抓取公开页面\n")

    L.append("## 1. 数据规模与构成\n")
    L.append("| 维度 | 分布 |\n|---|---|")
    L.append(f"| 文本类型 | " + "；".join(f"{k} {v} 篇" for k, v in report["by_doc_type"].items()) + " |")
    L.append(f"| 来源站点 | " + "；".join(f"{k} {v} 篇" for k, v in report["by_source"].items()) + " |")
    L.append(f"| 园区 | " + "；".join(f"{k} {v} 篇" for k, v in report["by_park"].items()) + " |\n")

    L.append("## 2. 缺失值检查\n")
    L.append("| 字段 | 空值数 | 空值率 |\n|---|---|---|")
    for k, v in report["missing_values"].items():
        L.append(f"| {k} | {v} | {report['missing_rate'][k]:.0%} |")
    L.append("")

    L.append("## 3. 重复检查\n")
    L.append(f"- 完全重复文档（清洗后去空白 MD5 相同）：**{report['exact_duplicate_docs']}** 对")
    pairs = report["near_duplicate_pairs_ge_0.30"]
    L.append(f"- 近重复候选（字符 3-gram Jaccard ≥ 0.30）：**{len(pairs)}** 对")
    if pairs:
        L.append("\n| 文档A | 文档B | Jaccard |\n|---|---|---|")
        for p in pairs:
            L.append(f"| {p['doc_a']} | {p['doc_b']} | {p['jaccard_3gram']} |")
    L.append("")

    L.append("## 4. 格式一致性检查（清洗后）\n")
    L.append("| 检查项 | 命中文档数 | 判定 |\n|---|---|---|")
    for k, v in report["format_consistency"].items():
        L.append(f"| {k} | {v} | {'通过' if v == 0 else '需关注'} |")
    L.append("")

    L.append("## 5. 长度与削减率\n")
    st = report["length_stats"]
    L.append("| 指标 | 原始内容 | 清洗后 |\n|---|---|---|")
    L.append(f"| 总字符数 | {st['raw_text']['total']} | {st['clean_text']['total']} |")
    L.append(f"| 单篇最小 | {st['raw_text']['min']} | {st['clean_text']['min']} |")
    L.append(f"| 单篇最大 | {st['raw_text']['max']} | {st['clean_text']['max']} |")
    L.append(f"| 单篇均值 | {st['raw_text']['mean']} | {st['clean_text']['mean']} |")
    L.append(f"| 段落数（均值） | - | {st['paragraphs_clean']['mean']} |")
    L.append(f"\n整体削减率：**{report['reduction']['overall_reduction_rate']:.1%}**\n")

    L.append("## 6. 规则削减明细\n")
    L.append("| 规则 | 删除字符 | 替换字符 | 命中文档数 |\n|---|---|---|---|")
    for name, s in report["rule_stats"].items():
        L.append(f"| {name} | {s['removed_chars']} | {s['substituted_chars']} | {s['docs_fired']} |")
    L.append("")

    L.append("## 7. 后续项目可用性\n")
    L.append(f"- 含明确时间表达（HH:MM / 上午·中午·下午）：{coverage['has_time']}")
    L.append(f"- 含箭头链路（→）：{coverage['has_arrow']}")
    L.append(f"- 含编号步骤（第N站 / 1. 2. 3.）：{coverage['has_numbering']}")
    L.append(f"- 含 POI 关键词：{coverage['has_poi_keyword']}\n")

    L.append("## 8. 遗留问题（如实记录）\n")
    L.append("1. 官网三篇攻略的站内发布日期较早（2019/2023/2024），部分项目名称与票价可能已变更，后续抽取以路线结构为主，价格类信息不作为知识事实。")
    L.append("2. 游记 CHL-N05（水上乐园）正文较短（421 字），实体与路线信息密度低，在项目2/3 中作为补充语料而非主样本。")
    L.append("3. 官网 CHL-O01 为 3 天 2 夜综合攻略，正文含“关于饮食/关于住宿/关于交通”等非路线段落，需在项目3 解析时按小标题切分后再抽取步骤。")
    L.append("4. 游记原文多为繁体（Trip.com 港澳台站点），已用 OpenCC t2s 统一为简体；个别粤语/台语用词（如“跟著走”“超了”）保留原貌，未做同义改写。")
    L.append("5. 三篇官方攻略正文含内联样式标签（font/span），已按标签剔除；图片 alt 文本在源页面为空，故无图注信息可保留。\n")

    (DOCS / "质量检查报告.md").write_text("\n".join(L), encoding="utf-8")

    print("图表：")
    for f in (f1, f2, f3):
        print("  ", f)
    print("\n可用性覆盖：", coverage)
    print("报告：", DOCS / "质量检查报告.md")


if __name__ == "__main__":
    main()
