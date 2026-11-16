# -*- coding: utf-8 -*-
"""T3.8 访客端（首页 / 进度 / 结果 / 评审 / 错误）移动端与无障碍验收。

只测**渲染结果**与样式表，不调模型、不改业务判定：
- HTML 语义：doctype / lang / viewport / 唯一 title 与 h1 / 标题层级 / 地标 /
  跳过链接 / label / button type / aria-live / aria-current / SVG title；
- CSS 契约：:focus-visible、prefers-reduced-motion、375px 防溢出规则；
- 对比度：从 :root 变量与样式表字面色值复算 WCAG 比值（文本 4.5、控件 3.0）。

375px 的真实滚动宽度由仓库外 CDP 工具留证，本文件不伪造视口数字。
"""

import os
import re
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 与 test_workflow / test_progress 一致：本模块只测 Web 渲染，关闭 agent 结果缓存。
os.environ["P07_RESULT_CACHE"] = "0"

import web_app  # noqa: E402
from flask import render_template  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
CSS = (BASE / "static" / "style.css").read_text(encoding="utf-8")
QUERY = "带孩子去长隆玩一天，游玩为主，少走路"
JOB_ID = "a" * 32

# 用于结果页的确定性示意图数据（测试内构造，不读真实图谱）。
DIAGRAM = {
    "days": [{
        "day": 1,
        "nodes": [
            {"node_id": "POI|长隆|熊猫乐园", "name": "熊猫乐园", "in_graph": True},
            {"node_id": "POI|长隆|小火车", "name": "小火车", "in_graph": False},
        ],
    }],
    "edges": [{
        "from_id": "POI|长隆|熊猫乐园",
        "to_id": "POI|长隆|小火车",
        "from_name": "熊猫乐园",
        "to_name": "小火车",
        "doc_ids": ["CL-T-01"],
    }],
    "missing": [],
}


def _block(text, marker):
    """返回从 marker 起、配对花括号内的 CSS 规则块。"""
    start = text.index(marker)
    open_at = text.index("{", start)
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise AssertionError(f"CSS 块未闭合：{marker}")


def _root_vars():
    root = _block(CSS, ":root {")
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", root))


VARS = _root_vars()


def _rgb(value):
    if value.startswith("#"):
        value = value[1:]
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb):
    def channel(value):
        value = value / 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    red, green, blue = [channel(item) for item in rgb]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(fg, bg):
    """WCAG 2.x 对比度；fg/bg 可为 #RRGGBB 或 :root 变量名。"""
    fg = VARS.get(fg, fg)
    bg = VARS.get(bg, bg)
    first, second = _luminance(_rgb(fg)), _luminance(_rgb(bg))
    high, low = max(first, second), min(first, second)
    return round((high + 0.05) / (low + 0.05), 2)


def _head(html):
    match = re.search(r"<head>(.*?)</head>", html, re.S)
    return match.group(1) if match else ""


def _body(html):
    match = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    return match.group(1) if match else ""


def _headings(html):
    return [int(level) for level in re.findall(r"<h([1-6])\b", html)]


def _first_focusable(html):
    match = re.search(
        r"<(a|button|input|textarea|select|summary)\b[^>]*>",
        _body(html),
        re.I,
    )
    return match.group(0) if match else ""


def _ids(html):
    return re.findall(r'\sid="([^"]+)"', html)


def _progress_html():
    stages = []
    for index, (stage, label) in enumerate(web_app.PROGRESS_STAGES):
        if index == 0:
            state = "done"
        elif stage == "tools":
            state = "active"
        else:
            state = "waiting"
        stages.append({
            "stage": stage,
            "label": label,
            "state": state,
            "state_text": web_app.PROGRESS_STATE_TEXT[state],
            "icon": web_app.PROGRESS_STATE_ICONS[state],
            "is_current": state == "active",
            "elapsed_ms": 900 if state == "done" else 0,
            "elapsed_s": "0.9",
        })
    with web_app.app.test_request_context(f"/run/{JOB_ID}?view=visitor"):
        return render_template(
            "progress.html",
            view="visitor",
            job_id=JOB_ID,
            query=QUERY,
            stages=stages,
            current_label="查询图谱",
            elapsed_s="1.2",
            job_status="running",
        )


def _result_fixture(**overrides):
    result = {
        "query": QUERY,
        "status": "verified",
        "reasons": [],
        "message": "已按图谱顺序排好行程。",
        "route": {
            "proposal": {
                "node_ids": ["POI|长隆|熊猫乐园", "POI|长隆|小火车"],
                "node_names": {
                    "POI|长隆|熊猫乐园": "熊猫乐园",
                    "POI|长隆|小火车": "小火车",
                },
                "explanation": "按资料顺序连接。",
                "duration_days": 1,
                "uncertainties": ["排队时长未核验"],
            },
            "validation": {
                "valid": True,
                "fully_verified": True,
                "segments": [{
                    "from_name": "熊猫乐园",
                    "to_name": "小火车",
                    "source_doc_ids": ["CL-T-01"],
                }],
            },
        },
        "itinerary": {
            "days": [{
                "day": 1,
                "plan_note": "园内步行。",
                "periods": [{
                    "period": "上午",
                    "time_range": "09:00-12:00",
                    "time_source": "explicit",
                    "title": "看熊猫",
                    "text": "先去熊猫乐园，再坐小火车。",
                    "stops": [
                        {"node_id": "POI|长隆|熊猫乐园", "name": "熊猫乐园"},
                        {"node_id": "POI|长隆|小火车", "name": "小火车"},
                    ],
                    "duration_hint": "约 2 小时",
                    "duration_source": "模板估算",
                    "unknowns": ["排队时长未核验"],
                    "fatigue_note": "带孩子注意休息。",
                }, {
                    "period": "中午",
                    "title": "午餐",
                    "text": "在园区用餐。",
                    "meal": {"inserted": True, "note": "园内餐厅，营业时间未核验。"},
                    "rest": {"inserted": False, "note": ""},
                    "unknowns": [],
                }],
            }],
            "note": "",
        },
        "alternatives": [{
            "alt_id": "alt-1",
            "source_doc_id": "CL-T-02",
            "source_title": "另一篇来源",
            "node_names": ["熊猫乐园", "小火车"],
            "status": "partial",
            "reason": "跨来源。",
            "segments": [{
                "from_name": "熊猫乐园",
                "to_name": "小火车",
                "source_doc_ids": ["CL-T-02"],
            }],
        }],
        "suggestions": [{
            "condition": {"condition_text": "带孩子", "suggestion_text": "先看熊猫"},
            "reason": "上午人少。",
            "needs_verification": True,
            "evidence": [{"anchor_name": "熊猫乐园", "source_doc_ids": ["CL-T-01"]}],
        }],
        "poi_results": [{"name": "熊猫乐园", "scenic_area": "长隆"}],
        "poi_list_all": False,
        "what_verified": {
            "scope": "CL",
            "segments_checked": 1,
            "source_doc_ids": ["CL-T-01"],
            "note": "逐段核验。",
        },
        "trace_json": "[]",
        "trace_file": "E:/tmp/" + ("session_" + "a" * 80) + ".json",
        "trace_error": "",
        "error": "",
        "decision": None,
        "tool_decisions": [],
        "intent": {"scenic_area": "长隆"},
        "needs_followup": False,
    }
    result.update(overrides)
    return result


def _render_result(view="visitor", **overrides):
    with ExitStack() as stack:
        stack.enter_context(patch.object(web_app, "_build_point_evidence", return_value={}))
        stack.enter_context(patch.object(web_app, "_build_segment_evidence", return_value=[]))
        stack.enter_context(patch.object(web_app, "_build_diagram", return_value=DIAGRAM))
        stack.enter_context(web_app.app.test_request_context("/"))
        return web_app._render_result(_result_fixture(**overrides), view, QUERY)


def _error_html():
    with web_app.app.test_request_context("/"):
        return render_template(
            "error.html",
            view="visitor",
            query=QUERY,
            status="error",
            reasons=[{"code": "model_error", "text": "服务暂时不可用，本次没有生成行程。"}],
            message="服务暂时不可用，请稍后重试。",
        )


def _pages():
    with web_app.app.test_client() as client:
        index = client.get("/").get_data(as_text=True)
    return {
        "index": index,
        "progress": _progress_html(),
        "result": _render_result("visitor"),
        "auditor": _render_result("auditor"),
        "error": _error_html(),
    }


class HtmlSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = _pages()

    def test_document_skeleton_on_every_page(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                self.assertRegex(html.lstrip(), r"(?i)^<!doctype html>")
                self.assertIn('<html lang="zh-CN">', html)
                self.assertIn(
                    'name="viewport" content="width=device-width, initial-scale=1"',
                    html,
                )
                self.assertEqual(
                    len(re.findall(r"<title>", _head(html))), 1,
                    f"{name}: <head> 必须只有一个 <title>",
                )
                self.assertEqual(len(re.findall(r"<h1\b", html)), 1)
                for tag in ("header", "main", "footer"):
                    self.assertRegex(html, rf"<{tag}\b")
                self.assertIn('id="main-content"', html)

    def test_skip_link_is_first_focusable_and_targets_main(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                first = _first_focusable(html)
                self.assertIn("skip-link", first, f"{name}: 第一个可聚焦元素不是跳过链接：{first}")
                self.assertIn('href="#main-content"', first)
                # 链接文字在开始标签之后，取 body 开头一小段验证可读文本
                self.assertIn("跳到主要内容", _body(html)[:200])

    def test_heading_order_never_skips_a_level(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                levels = _headings(html)
                self.assertTrue(levels, f"{name}: 没有标题")
                self.assertEqual(levels[0], 1, f"{name}: 首个标题不是 h1")
                for previous, current in zip(levels, levels[1:]):
                    self.assertLessEqual(
                        current, previous + 1,
                        f"{name}: 标题从 h{previous} 跳到 h{current}",
                    )

    def test_visible_form_controls_have_labels_and_buttons_have_type(self):
        for name in ("index", "error"):
            html = self.pages[name]
            with self.subTest(page=name):
                textarea_ids = re.findall(r'<textarea\b[^>]*\bid="([^"]+)"', html)
                self.assertTrue(textarea_ids, f"{name}: 没有 textarea")
                for control_id in textarea_ids:
                    labelled = re.search(
                        rf'<label\b[^>]*\bfor="{re.escape(control_id)}"', html
                    ) or re.search(
                        rf'<textarea\b[^>]*\bid="{re.escape(control_id)}"[^>]*aria-label=',
                        html,
                    )
                    self.assertIsNotNone(labelled, f"{name}: {control_id} 没有 label")
                for attrs, inner in re.findall(r"<button\b([^>]*)>(.*?)</button>", html, re.S):
                    self.assertIn("type=", attrs, f"{name}: button 缺少 type")
                    text = re.sub(r"<[^>]+>", " ", inner)
                    self.assertTrue(text.strip(), f"{name}: button 没有可读文本")

    def test_live_regions_and_status_badge(self):
        self.assertIn('aria-live="polite"', self.pages["index"])
        progress = self.pages["progress"]
        self.assertIn('class="progress__live" aria-live="polite"', progress)
        self.assertEqual(progress.count('aria-current="step"'), 1)
        self.assertIn('aria-label="处理阶段"', progress)
        result = self.pages["result"]
        self.assertIn("status-area", result)
        self.assertIn('aria-live="polite"', result)
        self.assertIn('data-status="verified"', result)
        self.assertIn("图谱连接核验通过", result)
        self.assertIn('data-status="error"', self.pages["error"])

    def test_decorative_icons_are_hidden_from_assistive_tech(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                for icon in ("status-badge__icon", "stepper__icon"):
                    for match in re.findall(
                        rf'<span class="{icon}"([^>]*)>', html
                    ):
                        self.assertIn('aria-hidden="true"', match)

    def test_svg_has_accessible_name_and_details_have_summaries(self):
        result = self.pages["result"]
        self.assertIn("<svg", result)
        self.assertRegex(result, r"<svg[^>]*role=\"group\"")
        self.assertRegex(result, r"<svg[^>]*aria-labelledby=\"route-diagram-caption\"")
        self.assertIn("<title>路线顺序示意图", result)
        self.assertIn('<div class="diagram__scroll" role="region"', result)
        self.assertIn('tabindex="0"', result)
        self.assertRegex(result, r'<g[^>]*class="diagram__node"[^>]*aria-label="')
        self.assertGreaterEqual(result.count("<details"), 1)
        for summary in re.findall(r"<summary\b[^>]*>(.*?)</summary>", result, re.S):
            self.assertTrue(re.sub(r"<[^>]+>", " ", summary).strip())
        self.assertIn('aria-label="本时段停留点（按图谱顺序）"', result)
        self.assertIn("不是地图", result)
        self.assertIn('<section class="point-evidence"', result)
        self.assertIn('class="evidence-card__missing"', result)

    def test_evidence_card_macro_keeps_quote_semantics(self):
        card = {
            "doc_id": "CL-T-01",
            "title": "来源标题",
            "source_url": "https://example.invalid/CL-T-01",
            "publish_date": "2025-01-01",
            "source_site": "示例站",
            "quote": {
                "text": "9:00-12:00 是黄金时段。",
                "char_start": 5,
                "char_end": 26,
            },
            "found": True,
        }
        with web_app.app.test_request_context("/"):
            template = web_app.app.jinja_env.from_string(
                "{% from '_evidence_card.html' import evidence_card %}{{ evidence_card(card) }}"
            )
            html = template.render(card=card)
        self.assertIn("<blockquote", html)
        self.assertIn("9:00-12:00 是黄金时段。", html)
        self.assertIn("<dl", html)
        self.assertIn("<dt", html)

    def test_no_duplicate_ids(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                ids = _ids(html)
                duplicates = sorted({value for value in ids if ids.count(value) > 1})
                self.assertEqual(duplicates, [], f"{name}: 重复 id {duplicates}")

    def test_no_external_resources_or_inline_handlers(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                self.assertNotRegex(html, r'(?:src|href)=["\']https?://')
                self.assertNotRegex(html, r"\son[a-z]+\s*=")
                self.assertNotIn("javascript:", html)
                self.assertIn("/static/style.css", html)

    def test_only_progress_page_has_script_and_it_is_inline(self):
        self.assertEqual(self.pages["index"].count("<script"), 0)
        self.assertEqual(self.pages["result"].count("<script"), 0)
        self.assertEqual(self.pages["auditor"].count("<script"), 0)
        self.assertEqual(self.pages["error"].count("<script"), 0)
        progress = self.pages["progress"]
        self.assertEqual(progress.count("<script"), 1)
        self.assertNotRegex(progress, r"<script[^>]+src=")

    def test_progress_keeps_meta_refresh_without_javascript(self):
        progress = self.pages["progress"]
        self.assertIn('<meta http-equiv="refresh" content="2">', progress)
        self.assertIn("立即刷新进度", progress)

    def test_result_page_is_readable_without_javascript(self):
        result = self.pages["result"]
        self.assertIn("<details", result)
        self.assertIn("<summary", result)
        self.assertIn("你的需求", result)
        self.assertIn("建议行程", result)
        self.assertNotIn("<script", result)


class StyleSheetContractTests(unittest.TestCase):
    def test_focus_visible_has_3px_outline(self):
        rule = _block(CSS, ":focus-visible {")
        self.assertIn("outline: 3px solid var(--color-focus)", rule)
        self.assertIn("outline-offset: 2px", rule)
        width = float(re.search(r"outline:\s*([\d.]+)px", rule).group(1))
        self.assertGreaterEqual(width, 2.0)

    def test_reduced_motion_disables_transition_and_animation(self):
        rule = _block(CSS, "@media (prefers-reduced-motion: reduce) {")
        self.assertIn("scroll-behavior: auto", rule)
        self.assertIn("transition: none !important", rule)
        self.assertIn("animation: none !important", rule)

    def test_375px_overflow_guards(self):
        checks = {
            "canvas {": "max-width: 100%",
            ".route-chain {": "overflow-wrap: anywhere",
            ".query-echo__text {": "overflow-wrap: anywhere",
            ".evidence-card__quote {": "overflow-wrap: anywhere",
            ".audit-panels .muted {": "overflow-wrap: anywhere",
            ".table-scroll {": "overflow-x: auto",
            ".diagram__scroll {": "overflow-x: auto",
        }
        for selector, declaration in checks.items():
            with self.subTest(selector=selector):
                self.assertIn(declaration, _block(CSS, selector))

    def test_skip_link_is_a_44px_touch_target(self):
        rule = _block(CSS, ".skip-link {\n  display: inline-flex")
        self.assertIn("min-height: 2.75rem", rule)

    def test_waiting_stage_border_meets_control_contrast(self):
        rule = _block(CSS, ".stepper__step--waiting {")
        self.assertIn("border-color: var(--color-line-strong)", rule)
        self.assertGreaterEqual(contrast("#7C8791", "#FFFFFF"), 3.0)

    def test_focus_ring_contrast(self):
        self.assertGreaterEqual(contrast(VARS["--color-focus"], VARS["--color-surface"]), 3.0)
        self.assertGreaterEqual(contrast(VARS["--color-focus"], VARS["--color-canvas"]), 3.0)


class ContrastTests(unittest.TestCase):
    TEXT_PAIRS = [
        ("正文/画布", "--color-ink", "--color-canvas"),
        ("次要文本/画布", "--color-ink-soft", "--color-canvas"),
        ("次要文本/白底", "--color-ink-soft", "--color-surface"),
        ("主按钮文字", "#FFFFFF", "--color-accent"),
        ("品牌链接/白底", "--color-accent", "--color-surface"),
        ("标签文字", "--color-accent", "--color-accent-soft"),
        ("状态-verified", "--status-verified-fg", "--status-verified-bg"),
        ("状态-partial", "--status-partial-fg", "--status-partial-bg"),
        ("状态-clarify", "--status-clarify-fg", "--status-clarify-bg"),
        ("状态-error", "--status-error-fg", "--status-error-bg"),
        ("页脚文字", "#3C4650", "#E8EDF1"),
        ("证据卡摘句", "#2B333B", "#F2F5F7"),
        ("未找到来源", "#8A5A00", "#FFFFFF"),
        ("等待阶段文字", "--color-ink-soft", "--color-surface"),
        ("进度页活动阶段", "--status-clarify-fg", "--status-clarify-bg"),
        ("进度页完成阶段", "--status-verified-fg", "--status-verified-bg"),
        ("行程可行性提示", "--status-partial-fg", "--status-partial-bg"),
        ("资料时间", "--color-ink", "--color-accent-soft"),
    ]

    CONTROL_PAIRS = [
        ("焦点环/白底", "--color-focus", "--color-surface"),
        ("焦点环/画布", "--color-focus", "--color-canvas"),
        ("控件边框/白底", "--color-line-strong", "--color-surface"),
        ("控件边框/画布", "--color-line-strong", "--color-canvas"),
        ("次按钮文字/白底", "--color-accent", "--color-surface"),
        ("状态徽标边框/底色", "--status-verified-fg", "--status-verified-bg"),
        ("错误徽标边框/底色", "--status-error-fg", "--status-error-bg"),
    ]

    def test_text_pairs_meet_4_5(self):
        for name, fg, bg in self.TEXT_PAIRS:
            with self.subTest(pair=name):
                ratio = contrast(fg, bg)
                self.assertGreaterEqual(ratio, 4.5, f"{name}: {fg} on {bg} = {ratio}")

    def test_control_pairs_meet_3_0(self):
        for name, fg, bg in self.CONTROL_PAIRS:
            with self.subTest(pair=name):
                ratio = contrast(fg, bg)
                self.assertGreaterEqual(ratio, 3.0, f"{name}: {fg} on {bg} = {ratio}")

    def test_status_badge_css_uses_the_audited_literals(self):
        # 徽标色值必须与 PRODUCT_SPEC §5.3 的四个状态逐字一致。
        pairs = {
            "verified": ("#1E6B34", "#E8F5EC"),
            "partial": ("#8A5A00", "#FFF4D6"),
            "clarify": ("#1F5FA8", "#E7F0FB"),
            "error": ("#A12622", "#FDECEA"),
        }
        for status, (fg, bg) in pairs.items():
            with self.subTest(status=status):
                rule = _block(CSS, f".status-badge--{status} {{")
                self.assertIn(f"color: {fg}", rule)
                self.assertIn(f"background-color: {bg}", rule)
                self.assertGreaterEqual(contrast(fg, bg), 4.5)


if __name__ == "__main__":
    unittest.main()
