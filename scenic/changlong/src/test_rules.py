# -*- coding: utf-8 -*-
"""
清洗规则单元测试（自我验证）
============================
目的：真实语料里有些规则（HTML 实体还原、网址/电话去除、段内重复行去重）没有命中，
      不等于规则无效。这里用构造的“含噪样本”逐条验证规则确实生效，
      并把结果写入 docs/rule_unit_tests.txt，作为报告中“规则有效性”的证据。

运行：python scripts/test_cleaning_rules.py
"""
from __future__ import annotations

import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))

from clean_dataset import (  # noqa: E402
    Cleaner,
    PUNCT_MAP,
    RE_PHONE,
    RE_URL,
)

OUT = BASE / "outputs" / "rule_unit_tests.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)

CASES = [
    # 块级标签与 <br> 都转为换行，连续多个换行由 R6 再压成单个
    ("R1 去除HTML标签", "r1_html", '<p style="x">第一站</p><br/>小火车<b>游览</b>', "第一站\n\n小火车游览"),
    ("R2 还原HTML实体", "r2_entity", "首冲&quot;超级激流&quot;&amp;飞虎跳&nbsp;", '首冲"超级激流"&飞虎跳 '),
    (
        "R3 去除模板行",
        "r3_boilerplate",
        "30 天前發布，幫助了 108 位旅客的旅程\n姊妹們快看\n還有另外 357 篇關於 長隆歡樂世界 的 Trip Moment，可為你的旅程提供更多參考",
        "姊妹們快看",
    ),
    ("R4 去除网址与电话", "r4_url", "详见 https://www.chimelong.com/gz/ 或致电 400-883-0083 咨询", "详见  或致电  咨询"),
    ("R5 去除emoji与私有区字符", "r5_symbol", "冲鸭🏃‍♀️‼️\uf592门票⭐✔️", "冲鸭门票"),
    ("R6 空白统一", "r6_whitespace", "上午：\u3000尖叫地带\u00a0\u00a0 第一站   \n\n\n中午：餐厅", "上午：尖叫地带 第一站\n中午：餐厅"),
    (
        "R7 标点统一",
        "r7_punct",
        '必做:提前到达,垂直过山车(必玩) 时间09. 40\n一. 行前准备',
        "必做：提前到达，垂直过山车（必玩） 时间09:40\n一、行前准备",
    ),
    ("R8 繁体转简体", "r8_t2s", "廣州長隆歡樂世界，體驗超棒", "广州长隆欢乐世界，体验超棒"),
    ("R9 段内重复行去重", "r9_dedup_lines", "上午：尖叫地带\n中午：椰林餐厅\n上午：尖叫地带", "上午：尖叫地带\n中午：椰林餐厅"),
    # 符号删除后常在括号内留下空格，由收尾规则清理
    ("R10 收尾整理", "r10_tidy", "垂直过山车（ 必玩）\n\n\n", "垂直过山车（必玩）"),
]


def run() -> int:
    lines = ["清洗规则单元测试结果", "=" * 40, ""]
    failed = 0
    for name, method, src, expected in CASES:
        cleaner = Cleaner(title="")
        got = getattr(cleaner, method)(src)
        ok = got == expected
        failed += 0 if ok else 1
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
        lines.append(f"    输入: {src!r}")
        lines.append(f"    输出: {got!r}")
        if not ok:
            lines.append(f"    期望: {expected!r}")
        lines.append("")

    # 正则类规则单测
    assert RE_URL.sub("", "见 https://a.com/x 谢谢") == "见  谢谢"
    assert RE_PHONE.sub("", "电话 400-883-0083") == "电话 "
    lines.append("[PASS] 辅助正则：URL / 客服电话 可被命中")
    lines.append("")

    total = len(CASES) + 1
    lines.append(f"合计 {total} 项，通过 {total - failed} 项，失败 {failed} 项")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
