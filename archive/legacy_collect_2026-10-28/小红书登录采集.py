#!/usr/bin/env python3
"""经用户在可见 Chrome 窗口登录后，采集已填写的小红书公开笔记链接。"""
import csv
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from 采集 import OUT, Parser, XHS_INPUT, load_xiaohongshu_links

BASE = Path(__file__).resolve().parent
PROFILE = BASE / '.xhs_browser_profile'  # Chrome 的本地登录会话，不会上传或提交
CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


def text_from_html(html):
    parser = Parser()
    parser.feed(html)
    body = '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
    return ''.join(parser.titles).strip(), body


def save(rows, failures):
    OUT.mkdir(exist_ok=True)
    fields = ['景区', '类型', '标题', '来源链接', '采集时间', '正文']
    with (OUT / '小红书采集结果.json').open('w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with (OUT / '小红书采集结果.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (OUT / '小红书失败记录.json').open('w', encoding='utf-8') as f:
        json.dump(failures, f, ensure_ascii=False, indent=2)


def input_links_after_login():
    """让用户从已登录的网页复制公开分享链接，不自动搜索或选择笔记。"""
    links = []
    print('\n链接表为空。请在 Chrome 内搜索景区，打开公开笔记后使用“分享—复制链接”，再粘贴到此处。')
    for attraction in ('广州白云山', '广州长隆欢乐世界', '萍乡武功山'):
        print(f'\n{attraction}：最多粘贴 5 条，直接按回车进入下一个景区。')
        for number in range(1, 6):
            url = input(f'第 {number} 条链接：').strip()
            if not url:
                break
            if not url.startswith(('https://www.xiaohongshu.com/', 'https://xhslink.com/')):
                print('不是小红书公开分享链接，未保存。')
                continue
            links.append((attraction, '游客游记（小红书）', url))
    if links:
        with XHS_INPUT.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['景区', '公开分享链接', '备注'])
            writer.writeheader()
            writer.writerows({'景区': a, '公开分享链接': u, '备注': '登录后手动粘贴'} for a, _, u in links)
        print(f'已保存 {len(links)} 条链接到 {XHS_INPUT.name}。')
    return links


def main():
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        print('缺少 Playwright。请先执行：python3 -m pip install playwright')
        return
    if not CHROME.exists():
        print('未在默认位置找到 Google Chrome，请安装 Chrome 后重试。')
        return

    rows, failures = [], []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), executable_path=str(CHROME), headless=False,
            locale='zh-CN', viewport={'width': 1440, 'height': 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto('https://www.xiaohongshu.com/explore', wait_until='domcontentloaded', timeout=30000)
        input('请在打开的 Chrome 中自行完成小红书登录；确认登录完成后，回到此终端按回车开始采集。')
        links = load_xiaohongshu_links()
        if not links:
            links = input_links_after_login()
        if not links:
            print('没有输入链接，本次不采集。')
            context.close()
            return
        for attraction, kind, url in links:
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(random.randint(3500, 6000))
                title, body = text_from_html(page.content())
                if len(body) < 150 or ('登录' in body[:300] and '笔记' not in body[:300]):
                    raise ValueError('未取得笔记正文；页面可能需要验证、已失效或未登录')
                rows.append({
                    '景区': attraction, '类型': kind, '标题': title, '来源链接': page.url,
                    '采集时间': datetime.now(timezone.utc).isoformat(), '正文': body,
                })
                print('成功', attraction, url)
            except PlaywrightTimeout:
                failures.append({'景区': attraction, '类型': kind, '链接': url, '原因': '页面加载超时'})
                print('失败', url, '页面加载超时')
            except Exception as e:
                failures.append({'景区': attraction, '类型': kind, '链接': url, '原因': str(e)})
                print('失败', url, e)
        context.close()
    save(rows, failures)
    print(f'小红书成功 {len(rows)} 条；失败 {len(failures)} 条。')


if __name__ == '__main__':
    main()
