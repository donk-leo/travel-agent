# -*- coding: utf-8 -*-
"""项目 3 · 把三景区 clean_content 解析为统一路线结构（routes.jsonl）。

支持四种显式格式 + 两种弱结构兜底：
  station       「第一站（10:00）：小火车游览」            CL-O-02 / CL-O-01
  time_leading  「09:00 入园 / 安检入口」                  CL-T-02 / CL-T-03
  chain         「北门——小火车游览区——青龙山——…」         CL-O-02 / WGS-O-01 / BYS-T-03
  period        「上午——尖叫地带」                        CL-O-03
  day           「D1：/ DAY-1」+ 段内 POI 出现顺序         WGS-O-03/04/05/06
  prose         以上都没有 → 整篇 1 个步骤（只记"存在路线"）BYS-O-02 等

硬约束：
  * 缺失时间一律 time_source=absent 且 time_norm 为空（不把推断写成原文事实）；
  * 同 route_id 内 step_no 从 1 连续递增；
  * source_span 以 CSV 原样 clean_content 为准，起点 0 计、结束不含。

用法：
    python analysis/p03_routes/src/parse_routes.py [--areas changlong ...]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.io_utils import read_csv_sig  # noqa: E402
from lib.paths import SCENIC_AREAS, scenic_csv  # noqa: E402

PROJECT = ROOT / "analysis" / "p03_routes"
CONFIG = PROJECT / "config"
OUTPUTS = PROJECT / "outputs"
AREAS = ("changlong", "baiyunshan", "wugongshan")
AREA_NAME = {"changlong": "长隆", "baiyunshan": "广州白云山", "wugongshan": "武功山"}

# 名称中"动作/交通"词：出现在节点开头时说明它是活动而不是景点
ACTIVITY_PREFIX = ("索道", "缆车", "观光车", "小火车", "大巴", "公交", "地铁", "步行",
                   "徒步", "返回", "前往", "乘车", "乘坐", "坐", "下山", "上山", "出园")
NOT_POI = {"出园", "入园", "结束", "离开", "返程", "自由活动", "午餐", "晚餐", "早餐"}

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15}

CLOCK_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(前|后)?")
PERIOD_WORDS = {"上午": ("AM", "上午"), "早上": ("AM", "上午"), "早晨": ("AM", "上午"),
                "清晨": ("AM", "上午"), "凌晨": ("AM", "上午"),
                "中午": ("NOON", "中午"), "正午": ("NOON", "中午"),
                "下午": ("PM", "下午"),
                "傍晚": ("PM", "晚上"), "晚上": ("PM", "晚上"),
                "夜晚": ("PM", "晚上"), "夜里": ("PM", "晚上")}
PERIOD_RE = re.compile("|".join(PERIOD_WORDS))

DURATION_MIN_RE = re.compile(r"(?:约|大概|大约)?\s*(\d{1,3})\s*分钟")
DURATION_HOU_RE = re.compile(r"(?:约|大概|大约)?\s*(\d+(?:\.\d+)?)\s*(?:个)?小时")

SEP_RE = re.compile(r"(?:——|—{1,2}|–{2}|-{2,}|→|➡|►|＞|>)")
OPEN_BR = "（(【[「『"
CLOSE_BR = "）)】]」』"

STATION_RE = re.compile(
    r"^\s*第([一二三四五六七八九十\d]{1,3})站\s*(?:[（(]\s*([^）)]{0,14})\s*[）)])?\s*[：:]\s*(.*)$")
TIME_LEAD_RE = re.compile(r"^\s*(?:(\d{1,2})\s*[.、]\s*)?(\d{1,2})[:：](\d{2})\s+(.{1,40})$")
TIME_RANGE_RE = re.compile(
    r"^\s*(?:(\d{1,2})\s*[.、]\s*)?(\d{1,2})[:：](\d{2})\s*[-–—~至]\s*(\d{1,2})[:：](\d{2})\s+(.{1,40})$")
SECTION_STOP_RE = re.compile(r"^\s*(关于|【交通|【门票|温馨提示|备注|小贴士|实用信息|票价)")


@dataclass
class Step:
    poi_raw: str = ""
    poi: str = ""
    activity: str = ""
    time_raw: str = ""
    time_norm: str = ""
    time_source: str = "absent"
    time_period: str = "未知"
    duration_min: int | None = None
    span: list[int] = field(default_factory=list)


@dataclass
class Route:
    doc_id: str
    scenic_area: str
    doc_type: str
    subtype: str
    title: str
    fmt: str
    steps: list[Step] = field(default_factory=list)


# ---------------------------------------------------------------- 基础工具
def cn_to_int(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    return CN_NUM.get(s, 0)


def iter_lines(text: str):
    """按 \\n 切行并给出每行的绝对偏移。"""
    off = 0
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        yield line, off
        off += len(raw) + 1


def clean_name(s: str) -> str:
    """去掉括号补充（含嵌套）、【】内容与引号，用于归一化匹配。"""
    s = re.sub(r"【[^】]*】", "", s)
    prev = None
    while prev != s:  # 由内向外逐层去掉括号内容
        prev = s
        s = re.sub(r"[（(][^（()）]*[）)]", "", s)
    s = re.sub(r"[「」『』\[\]“”‘’\"]", "", s)
    s = s.replace(" ", "").replace("\u3000", "")
    return s.strip(" ·・,，。；;:：、-—|｜+")


def sim(a: str, b: str) -> float:
    a, b = clean_name(a), clean_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def period_from_hour(hour: int) -> str:
    if 6 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    return "晚上"


def parse_time(text: str) -> tuple[str, str, str, str]:
    """返回 (time_raw, time_norm, time_source, time_period)。找不到则全部空/absent。"""
    m = CLOCK_RE.search(text)
    if m:
        raw = m.group(0)
        norm = f"{int(m.group(1)):02d}:{m.group(2)}"
        return raw, norm, "explicit", period_from_hour(int(m.group(1)))
    m = PERIOD_RE.search(text)
    if m:
        word = m.group(0)
        norm, period = PERIOD_WORDS[word]
        return word, norm, "explicit", period
    return "", "", "absent", "未知"


def parse_duration(text: str) -> int | None:
    m = DURATION_MIN_RE.search(text)
    if m:
        return int(m.group(1))
    m = DURATION_HOU_RE.search(text)
    if m:
        return int(round(float(m.group(1)) * 60))
    return None


def split_chain(line: str, min_sep: int = 2, min_nodes: int = 3) -> list[tuple[str, int, int]] | None:
    """按顶层（忽略括号内）分隔符切链；节点不足返回 None。"""
    nodes, depth, start, i = [], 0, 0, 0
    n_sep = 0
    while i < len(line):
        ch = line[i]
        if ch in OPEN_BR:
            depth += 1
        elif ch in CLOSE_BR:
            depth = max(0, depth - 1)
        elif depth == 0:
            m = SEP_RE.match(line, i)
            if m and i > start:
                nodes.append((line[start:i], start, i))
                n_sep += 1
                i = m.end()
                start = i
                continue
        i += 1
    nodes.append((line[start:], start, len(line)))
    if n_sep < min_sep:
        return None
    cleaned = []
    for text, s, e in nodes:
        t = text.strip()
        # 去掉"路线："、"第一天："这类标签前缀并同步修正偏移
        m = re.match(r"^(?:路线设计|推荐路线|路线|行程|简要行程|核心思路|"
                     r"第[一二三四五六七八九十\d]{1,2}天|DAY\s*[-－]?\s*\d+|D\s*[-－]?\s*\d+)\s*[：:]\s*", t)
        if m:
            s += m.end()
            t = t[m.end():].strip()
        # 顶层"；"之后不是路线节点
        cut = t.find("；")
        if cut > 0:
            t, e = t[:cut], s + cut
        # 节点内的"|"是说明（时长/票价），不是路线节点
        for bar in ("|", "｜"):
            pos = t.find(bar)
            if pos > 0:
                t, e = t[:pos], s + pos
                break
        t = t.strip().rstrip("。").strip()
        # 节点尾部的时长说明（如"摩星岭 3-4小时"）
        t = re.sub(r"\s*\d+(?:\.\d+)?(?:\s*[-–—~至]\s*\d+(?:\.\d+)?)?\s*(?:小时|分钟|h|H)\+?\s*$", "", t).strip()
        if len(t) > 30 and any(ch in t for ch in "。，,；"):
            t = re.split(r"[。，,；]", t)[0].strip()
        t = t.rstrip("。").strip()
        if t:
            cleaned.append((t, s, s + len(t)))
    if len(cleaned) < min_nodes:
        return None
    short = sum(1 for t, _, _ in cleaned if len(clean_name(t)) <= 14)
    if short < max(2, int(len(cleaned) * 0.6)):
        return None
    return cleaned


def classify_node(node: str, known_poi: set[str]) -> tuple[str, str]:
    """返回 (poi, activity)。已知 POI 优先；动作词开头/结尾判为活动。"""
    name = clean_name(node)
    if name in known_poi:
        return name, ""
    if name in NOT_POI:
        return "", name
    for sep in ("/", "|", "｜", "+", "＋"):
        if sep in name:
            parts = [p for p in name.split(sep) if p]
            for p in parts:
                if p in known_poi:
                    return p, ""
            for p in parts:
                if p in NOT_POI:
                    continue
                if not any(p.startswith(w) for w in ACTIVITY_PREFIX):
                    return p, ""
            return "", name
    for w in ACTIVITY_PREFIX:
        if name.startswith(w):
            rest = name[len(w):]
            rest = re.split(r"[，,、。；;]", rest)[0]
            if len(rest) >= 2 and not any(rest.startswith(x) for x in ("上", "下", "返", "入", "出")):
                return rest, w
            return "", name
    m = re.match(r"^(?:可选择|可以选择|可选|建议)(.+)$", name)
    if m:
        rest = m.group(1)
        if any(rest.startswith(w) for w in ACTIVITY_PREFIX) or rest.startswith(("走", "游")):
            return "", name
    for suf in ("入园", "出园", "下山", "上山", "返程", "结束", "坐", "乘", "搭"):
        if name.endswith(suf) and 2 <= len(name) - len(suf) <= 8:
            return name[:-len(suf)], suf
    return name, ""


def chain_established(chain, known_poi: set[str]) -> bool:
    """链式候选过滤：至少 2 个节点是"已确证 POI"，或节点多且都很短。"""
    names = [clean_name(t) for t, _, _ in chain["nodes"]]
    hits = sum(1 for n in names if n in known_poi)
    if hits >= 2:
        return True
    if len(names) >= 5:
        short = sum(1 for n in names if 2 <= len(n) <= 10)
        if short >= len(names) * 0.6:
            return True
    return False


def split_top(text: str, seps: str) -> list[tuple[str, int, int]]:
    """按顶层分隔符集合切分（忽略括号内），返回 (片段, 起点, 终点)。"""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in OPEN_BR:
            depth += 1
        elif ch in CLOSE_BR:
            depth = max(0, depth - 1)
        elif depth == 0 and ch in seps:
            if i > start:
                out.append((text[start:i], start, i))
            start = i + 1
    if start < len(text):
        out.append((text[start:], start, len(text)))
    return out


# ---------------------------------------------------------------- 名词典
def load_alias() -> tuple[dict[tuple[str, str], str], set[str]]:
    """读取 config/alias.csv：alias,canonical,relation,scenic_area,note。"""
    path = CONFIG / "alias.csv"
    table: dict[tuple[str, str], str] = {}
    canon: set[str] = set()
    if not path.exists():
        return table, canon
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            alias = (row.get("alias") or "").strip()
            canonical = (row.get("canonical") or "").strip()
            area = (row.get("scenic_area") or "").strip()
            if not alias or not canonical:
                continue
            table[(area, alias)] = canonical
            table[(area, clean_name(alias))] = canonical
            canon.add(canonical)
            canon.add(clean_name(canonical))
    return table, canon


def normalize(poi: str, area_name: str, alias: dict[tuple[str, str], str]) -> str:
    key = clean_name(poi)
    return (alias.get((area_name, key)) or alias.get(("*", key))
            or alias.get((area_name, poi.strip())) or key)


# ---------------------------------------------------------------- 各格式解析
def detect_stations(lines):
    out = []
    for idx, (line, off) in enumerate(lines):
        m = STATION_RE.match(line)
        if not m:
            continue
        out.append({"idx": idx, "off": off, "no": cn_to_int(m.group(1)),
                    "time": (m.group(2) or "").strip(), "poi_raw": m.group(3).strip(),
                    "line": line})
    return out


def detect_time_leading(lines):
    out = []
    for line, off in lines:
        m = TIME_RANGE_RE.match(line)
        if m:
            h, mi, eh, em, rest = (int(m.group(2)), m.group(3), int(m.group(4)),
                                   int(m.group(5)), m.group(6).strip())
            if 2 <= len(rest) <= 40:
                out.append({"off": off, "hour": h, "minute": mi, "end_min": eh * 60 + em,
                            "raw": f"{h:02d}:{mi}-{eh:02d}:{em:02d}", "rest": rest, "line": line})
                continue
        m = TIME_LEAD_RE.match(line)
        if not m:
            continue
        rest = m.group(4).strip()
        if len(rest) < 2 or len(rest) > 40:
            continue
        if SECTION_STOP_RE.match(rest):
            continue
        h, mi = int(m.group(2)), m.group(3)
        out.append({"off": off, "hour": h, "minute": mi, "end_min": None,
                    "raw": f"{h:02d}:{mi}", "rest": rest, "line": line})
    return out


def detect_periods(lines):
    out = []
    for line, off in lines:
        m = re.match(r"^\s*(上午|早上|中午|下午|傍晚|晚上)\s*(?:——|—|--|-|～|~)?\s*[：:—\-]*\s*(.{1,40})$", line)
        if not m:
            continue
        rest = m.group(2).strip(" ——-—：:")
        if not rest or len(rest) > 30:
            continue
        out.append({"off": off, "period_word": m.group(1), "rest": rest, "line": line})
    return out


def detect_day_heads(lines):
    out = []
    for line, off in lines:
        t = line.strip()
        m = re.match(r"^(?:D|DAY|Day|day)\s*[-－]?\s*(\d+)\s*[：:]?\s*$", t) or \
            re.match(r"^第([一二三四五六七八九十\d]{1,2})天\s*[：:]?\s*(.{0,30})$", t)
        if m:
            out.append({"off": off, "line": line, "label": t})
    return out


def chain_lines(lines):
    out = []
    for idx, (line, off) in enumerate(lines):
        nodes = split_chain(line)
        if not nodes:
            continue
        # 路线标题：上一行较短且像标题
        title = ""
        if idx > 0:
            prev = lines[idx - 1][0].strip()
            if 0 < len(prev) <= 30 and not split_chain(prev):
                title = prev
        out.append({"idx": idx, "off": off, "nodes": nodes, "title": title, "line": line})
    return out


def steps_from_chain(nodes, off, known_poi, area_name, alias):
    steps = []
    for text, s, e in nodes:
        poi, act = classify_node(text, known_poi)
        steps.append(Step(poi_raw=text, poi=normalize(poi, area_name, alias) if poi else "",
                          activity=act, time_source="absent", time_period="未知",
                          span=[off + s, off + e]))
    return steps


def build_station_route(doc, stations, chains, known_poi, alias):
    area_name = AREA_NAME[doc["area"]]
    # 第一个"关于饮食/住宿/交通"类小标题之后的段落不是路线步骤（CL-O-01 的已知坑）
    stop_off = len(doc["text"])
    for line, off in doc["lines"]:
        if STATION_RE.match(line):
            continue
        if SECTION_STOP_RE.match(line):
            stop_off = off
            break
    steps = []
    for st in stations:
        if st["off"] >= stop_off:
            continue
        time_raw, time_norm, src, period = parse_time(st["time"]) if st["time"] else ("", "", "absent", "未知")
        if not time_raw and st["time"]:
            time_raw = st["time"]
        poi_raw = st["poi_raw"]
        poi = normalize(poi_raw, area_name, alias)
        dur = parse_duration(doc["text"][st["off"]: st["off"] + 320])
        steps.append(Step(poi_raw=poi_raw, poi=poi, activity="",
                          time_raw=time_raw, time_norm=time_norm, time_source=src,
                          time_period=period, duration_min=dur,
                          span=[st["off"], st["off"] + len(st["line"].strip())]))

    merged = False
    if chains and len(steps) >= 3:
        chain = max(chains, key=lambda c: len(c["nodes"]))
        anchor = []
        used = set()
        for i, st in enumerate(steps):
            best_i, best = None, 0.0
            for j, (text, _, _) in enumerate(chain["nodes"]):
                r = sim(st.poi_raw, text)
                if r > best:
                    best, best_i = r, j
            if best >= 0.6 and best_i is not None and best_i not in used:
                anchor.append((i, best_i))
                used.add(best_i)
        if len(anchor) >= max(3, int(len(steps) * 0.6)):
            first_c = anchor[0][1]
            last_c = anchor[-1][1]
            prefix, suffix = [], []
            for text, s, e in chain["nodes"][:first_c]:
                if clean_name(text) not in NOT_POI:
                    prefix.append((text, s, e))
            for text, s, e in chain["nodes"][last_c + 1:]:
                if clean_name(text) not in NOT_POI:
                    suffix.append((text, s, e))
            new_steps = []
            for text, s, e in prefix:
                poi, act = classify_node(text, known_poi)
                new_steps.append(Step(poi_raw=text, poi=normalize(poi, area_name, alias) if poi else "",
                                      activity=act, span=[chain["off"] + s, chain["off"] + e]))
            new_steps.extend(steps)
            for text, s, e in suffix:
                poi, act = classify_node(text, known_poi)
                new_steps.append(Step(poi_raw=text, poi=normalize(poi, area_name, alias) if poi else "",
                                      activity=act, span=[chain["off"] + s, chain["off"] + e]))
            steps = new_steps
            merged = True
    fmt = "station+chain" if merged else "station"
    return Route(doc_id=doc["doc_id"], scenic_area=area_name, doc_type=doc["doc_type"],
                 subtype=doc.get("subtype", ""), title=doc.get("title", ""), fmt=fmt, steps=steps)


def split_inner_chain(rest, known_poi) -> list[str] | None:
    nodes = split_chain(rest, min_sep=1, min_nodes=2)
    if not nodes:
        return None
    return [t for t, _, _ in nodes]


def build_time_leading_route(doc, hits, known_poi, alias):
    area_name = AREA_NAME[doc["area"]]
    steps = []
    for h in hits:
        norm = h["raw"]
        period = period_from_hour(h["hour"])
        dur = None
        if h.get("end_min"):
            dur = h["end_min"] - (h["hour"] * 60 + int(h["minute"]))
            dur = dur if dur > 0 else None
        rest = h["rest"]
        inner = split_inner_chain(rest, known_poi)
        if inner:
            for text in inner:
                poi, act = classify_node(text, known_poi)
                s = doc["text"].find(text, h["off"])
                s = s if s >= 0 else h["off"]
                steps.append(Step(poi_raw=text, poi=normalize(poi, area_name, alias) if poi else "",
                                  activity=act, time_raw=norm, time_norm=norm,
                                  time_source="explicit", time_period=period,
                                  duration_min=dur, span=[s, s + len(text)]))
        else:
            poi, act = classify_node(rest, known_poi)
            steps.append(Step(poi_raw=rest, poi=normalize(poi, area_name, alias) if poi else "",
                              activity=act, time_raw=norm, time_norm=norm,
                              time_source="explicit", time_period=period, duration_min=dur,
                              span=[h["off"], h["off"] + len(h["line"].strip())]))
    return Route(doc_id=doc["doc_id"], scenic_area=area_name, doc_type=doc["doc_type"],
                 subtype=doc.get("subtype", ""), title=doc.get("title", ""),
                 fmt="time_leading", steps=steps)


def build_period_route(doc, hits, alias, known_poi):
    area_name = AREA_NAME[doc["area"]]
    steps = []
    for h in hits:
        norm, period = PERIOD_WORDS[h["period_word"]]
        raw = h["rest"]
        dur = parse_duration(doc["text"][h["off"]: h["off"] + 320])
        # 小标题里可能带时间段，如"上午（9:00–12:00）：冲刺王牌刺激项"
        m = re.search(r"(\d{1,2})[:：](\d{2})\s*[-–—~至]\s*(\d{1,2})[:：](\d{2})", raw)
        if m:
            norm = f"{int(m.group(1)):02d}:{m.group(2)}"
            dur = (int(m.group(3)) * 60 + int(m.group(4))) - (int(m.group(1)) * 60 + int(m.group(2)))
            period = period_from_hour(int(m.group(1)))
            raw = m.group(0)
            h = dict(h, rest=re.sub(r"^[（(][^）)]*[）)]\s*[：:]?", "", h["rest"]).strip())
        first = re.split(r"[+＋、/｜|]", h["rest"])[0].strip() or h["rest"]
        if clean_name(first) in known_poi:
            poi, act = normalize(first, area_name, alias), ""
        else:  # 分段时间的小标题是活动描述，不硬当景点
            poi, act = "", h["rest"]
        steps.append(Step(poi_raw=h["rest"], poi=poi, activity=act,
                          time_raw=raw, time_norm=norm if norm else "",
                          time_source="explicit", time_period=period,
                          duration_min=dur if dur and dur > 0 else None,
                          span=[h["off"], h["off"] + len(h["line"].strip())]))
    return Route(doc_id=doc["doc_id"], scenic_area=area_name, doc_type=doc["doc_type"],
                 subtype=doc.get("subtype", ""), title=doc.get("title", ""),
                 fmt="period", steps=steps)


def detect_poi_list(text: str):
    """枚举式路线：'首先步行游览A、B、C等景点' → 按出现顺序取 POI。"""
    JUNK = re.compile(r"[0-9０-９]|公里|小时|分钟|门票|票价|约|左右")
    BAD_START = ("了解", "这里", "以及", "有", "自古", "景色", "全程", "长度", "距离", "建议")
    found = []
    for m in re.finditer(r"游览(?!路线|观光|车|时间|方式|的)([^。；]{4,160})", text):
        seg = m.group(1)
        cut = re.search(r"等(?:主要|著名)?(?:景点|景区)", seg)
        if cut:
            seg = seg[:cut.start()]
        base = m.start(1)
        for part, s, e in split_top(seg, "、，,"):
            t = part.strip()
            if not t:
                continue
            inner = re.match(r"^含(.+)$", t)
            if inner:  # “含A、B、C” → 子景点
                sub_base = s + inner.start(1)
                for sub, ss, se in split_top(inner.group(1), "、，,"):
                    st = sub.strip()
                    if 2 <= len(clean_name(st)) <= 12 and not JUNK.search(st):
                        found.append((st, base + sub_base + ss, base + sub_base + se))
                continue
            nm = clean_name(t)
            if 2 <= len(nm) <= 12 and nm not in NOT_POI and not JUNK.search(nm) \
                    and not nm.startswith(BAD_START):
                found.append((nm, base + s, base + e))
    return found


def build_poi_list_route(doc, items, alias):
    area_name = AREA_NAME[doc["area"]]
    steps = []
    for text, s, e in items:
        steps.append(Step(poi_raw=text, poi=normalize(text, area_name, alias), activity="",
                          time_source="absent", time_period="未知", span=[s, e]))
    return Route(doc_id=doc["doc_id"], scenic_area=area_name, doc_type=doc["doc_type"],
                 subtype=doc.get("subtype", ""), title=doc.get("title", ""),
                 fmt="poi_list", steps=steps)


def build_chain_routes(doc, chains, known_poi, alias, with_period_hint: bool):
    area_name = AREA_NAME[doc["area"]]
    routes = []
    for c in chains:
        steps = steps_from_chain(c["nodes"], c["off"], known_poi, area_name, alias)
        title = c["title"]
        if title.startswith("【") or title in {"简要行程", "路线", "行程"}:
            title = ""
        routes.append(Route(doc_id=doc["doc_id"], scenic_area=area_name,
                            doc_type=doc["doc_type"], subtype=doc.get("subtype", ""),
                            title=title, fmt="chain", steps=steps))
    return routes


def build_day_route(doc, heads, known_poi, alias):
    """按天切段，段内按已知 POI 出现顺序近似成步（不推断时间）。"""
    area_name = AREA_NAME[doc["area"]]
    text = doc["text"]
    starts = [h["off"] for h in heads]
    if not starts:
        return None
    bounds = [(starts[i], starts[i + 1] if i + 1 < len(starts) else len(text))
              for i in range(len(starts))]
    surfaces = sorted(known_poi, key=len, reverse=True)
    steps = []
    for (s, e) in bounds:
        seg = text[s:e]
        found = []
        for surf in surfaces:
            if len(surf) < 2 or surf in NOT_POI:
                continue
            for m in re.finditer(re.escape(surf), seg):
                found.append((m.start(), m.end(), surf))
        found.sort(key=lambda x: (x[0], -x[1], -len(x[2])))
        # 同一位置优先保留更长的表达（如"金顶索道"优于"金顶"）
        kept = []
        for a, b, surf in found:
            if kept and a < kept[-1][1]:
                continue
            kept.append([a, b, surf])
        # 相邻且更短的前缀（如"中庵"紧跟"紫极宫"）只保留后者
        merged = []
        for item in kept:
            if merged and merged[-1][1] == item[0] and len(item[2]) > len(merged[-1][2]):
                merged[-1] = item
                continue
            merged.append(item)
        for a, b, surf in merged:
            poi = normalize(surf, area_name, alias)
            if steps and steps[-1].poi == poi:  # 连续重复不重复计步
                continue
            steps.append(Step(poi_raw=surf, poi=poi, activity="",
                              time_source="absent", time_period="未知",
                              duration_min=parse_duration(seg[b:b + 16]),
                              span=[s + a, s + b]))
    if len(steps) < 2:
        return None
    return Route(doc_id=doc["doc_id"], scenic_area=area_name, doc_type=doc["doc_type"],
                 subtype=doc.get("subtype", ""), title=doc.get("title", ""),
                 fmt="day_sequence", steps=steps)


def build_prose_route(doc, alias):
    """兜底：整篇记为 1 个"存在路线"步骤，不编造顺序。"""
    area_name = AREA_NAME[doc["area"]]
    text = doc["text"].strip()
    title = doc.get("title", "") or doc["doc_id"]
    step = Step(poi_raw="", poi="", activity=f"整篇路线概述（未结构化）｜{title}",
                time_source="absent", time_period="未知", span=[0, min(len(text), 60)])
    return Route(doc_id=doc["doc_id"], scenic_area=area_name, doc_type=doc["doc_type"],
                 subtype=doc.get("subtype", ""), title=doc.get("title", ""),
                 fmt="prose", steps=[step])


# ---------------------------------------------------------------- 主流程
def load_docs(areas):
    docs = []
    for area in areas:
        rows, _ = read_csv_sig(scenic_csv(area))
        for r in rows:
            text = r.get("clean_content") or ""
            if not text.strip():
                continue
            docs.append({
                "area": area, "doc_id": (r.get("doc_id") or "").strip(),
                "doc_type": (r.get("doc_type") or "").strip(),
                "subtype": (r.get("subtype") or "").strip(),
                "title": (r.get("title") or "").strip(),
                "text": text, "lines": list(iter_lines(text)),
            })
    return docs


def parse_doc(doc, alias, known_poi):
    area_name = AREA_NAME[doc["area"]]
    stations = detect_stations(doc["lines"])
    chains = [c for c in chain_lines(doc["lines"]) if chain_established(c, known_poi)]
    times = detect_time_leading(doc["lines"])
    periods = detect_periods(doc["lines"])
    days = detect_day_heads(doc["lines"])
    poi_items = detect_poi_list(doc["text"])

    routes: list[Route] = []
    if stations and len(stations) >= 2:
        routes = [build_station_route(doc, stations, chains, known_poi, alias)]
    elif len(times) >= 3:
        routes = [build_time_leading_route(doc, times, known_poi, alias)]
    elif chains:
        routes = build_chain_routes(doc, chains, known_poi, alias, with_period_hint=False)
    elif len(periods) >= 2:
        routes = [build_period_route(doc, periods, alias, known_poi)]
    elif days:
        r = build_day_route(doc, days, known_poi, alias)
        routes = [r] if r else [build_prose_route(doc, alias)]
    elif len(poi_items) >= 4 and len(doc["text"]) >= 150:
        routes = [build_poi_list_route(doc, poi_items, alias)]
    else:
        routes = [build_prose_route(doc, alias)]

    # 去掉空步骤路线
    routes = [r for r in routes if r.steps]
    return routes


def main() -> int:
    parser = argparse.ArgumentParser(description="P3：路线结构解析")
    parser.add_argument("--areas", nargs="+", choices=list(AREAS), default=list(AREAS))
    args = parser.parse_args()

    alias, canon = load_alias()
    docs = load_docs(args.areas)

    # 第 1 遍：统计每个链节点出现在几篇文档里，"≥2 篇文档出现"或 alias 中的名字才算确证 POI，
    # 用它过滤掉"悦己→热恋→童梦"这类被误当链路的修辞句。
    node_docs: dict[str, set[str]] = defaultdict(set)
    for doc in docs:
        for c in chain_lines(doc["lines"]):
            for text, _, _ in c["nodes"]:
                nm = clean_name(text)
                if nm and len(nm) >= 2 and nm not in NOT_POI:
                    node_docs[nm].add(doc["doc_id"])
    established = set(canon) | {nm for nm, ds in node_docs.items() if len(ds) >= 2}

    all_rows = []
    meta = []
    for doc in docs:
        routes = parse_doc(doc, alias, established)
        for k, route in enumerate(routes, start=1):
            route_id = f"{doc['doc_id']}-r{k}"
            meta.append({"route_id": route_id, "doc_id": doc["doc_id"],
                         "scenic_area": route.scenic_area, "doc_type": route.doc_type,
                         "title": route.title, "format": route.fmt,
                         "n_steps": len(route.steps)})
            for no, st in enumerate(route.steps, start=1):
                row = {"doc_id": doc["doc_id"], "route_id": route_id, "step_no": no}
                if st.poi:
                    row["poi"] = st.poi
                if st.poi_raw:
                    row["poi_raw"] = st.poi_raw
                if st.activity:
                    row["activity"] = st.activity
                if st.time_raw:
                    row["time_raw"] = st.time_raw
                if st.time_norm:
                    row["time_norm"] = st.time_norm
                row["time_source"] = st.time_source
                row["time_period"] = st.time_period
                if st.duration_min:
                    row["duration_min"] = st.duration_min
                row["source_span"] = st.span
                row["format"] = route.fmt
                all_rows.append(row)

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    # 显式 LF：本机默认 newline 会把 \n 写成 CRLF，导致重跑后产生"假修改"
    with (OUTPUTS / "routes.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"写入 {OUTPUTS / 'routes.jsonl'}：{len(all_rows)} 个步骤 / {len(meta)} 条路线")
    print("格式分布：", dict(Counter(m["format"] for m in meta)))
    print("景区分布：", dict(Counter(m["scenic_area"] for m in meta)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
