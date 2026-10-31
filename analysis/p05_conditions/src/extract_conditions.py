# -*- coding: utf-8 -*-
"""项目5：从三景区 clean_content 抽取“条件 → 建议”。

设计要点
--------
1. 先按句号/问号/叹号/换行切句，保留绝对字符位置；
2. 显式条件（如果/假如/要是/倘若/一旦/若/如）优先，条件止于逗号或
   “就/则/那/便/建议/可以”等连接词；
3. 隐式条件（带老人/下雨/节假日/体力不好/预算有限/学生…）要求同句
   出现建议标记（建议/最好/记得/一定要/可以/带/穿/提前…）；
4. 同句多个建议按“；”或“，+建议标记”拆分，共享 source_sentence；
5. 去重只标记 is_duplicate，不删除记录；统计同句/近重复/前后缀三类。

输出：
    outputs/conditions.jsonl
    outputs/rejected.jsonl
    outputs/condition_stats.json
    outputs/dedup_report.md
    config/triggers.csv
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from lib.io_utils import read_csv_sig, write_csv_sig, write_json, write_jsonl  # noqa: E402
from lib.paths import SCENIC_AREAS, analysis_dir, scenic_csv  # noqa: E402
from lib.schema import is_true  # noqa: E402

ROOT = analysis_dir("p05_conditions")
OUT = ROOT / "outputs"
CONFIG = ROOT / "config"

AREA_CN = {"changlong": "长隆", "baiyunshan": "白云山", "wugongshan": "武功山"}
TYPE_ORDER = ("天气", "人群", "时间", "体力", "预算", "交通", "其他")

# 类型判定用宽表：只看“条件像哪一类”，不直接决定是否抽取。
CONDITION_PATTERNS: dict[str, list[str]] = {
    "天气": [
        r"下(?:大|小|暴|雷|阵)?雨", r"雨天", r"下雨天", r"阴雨", r"雨衣", r"雨具",
        r"天气(?:不好|差|晴朗|好|炎热|寒冷|多变|预报)?", r"大太阳", r"烈日",
        r"暴晒", r"下雪", r"大雾", r"起雾", r"台风", r"高温", r"低温", r"阴天",
        r"夏天", r"冬天", r"太阳",
    ],
    "人群": [
        r"带(?:着)?(?:老人|小孩|孩子|娃|宝宝|父母|小朋友|家人)",
        r"亲子", r"全家", r"一家人", r"老人", r"小孩", r"孩子", r"儿童",
        r"学生", r"情侣", r"女生", r"男生", r"闺蜜", r"带娃", r"婴儿",
        r"小朋友", r"年轻人", r"长辈", r"朋友", r"胆子小", r"怕累",
    ],
    "时间": [
        r"节假日", r"旺季", r"淡季", r"周末", r"五一", r"国庆", r"春节",
        r"暑假", r"寒假", r"夜爬", r"夜游", r"看日出", r"看日落", r"拍日落",
        r"日出", r"日落", r"早上", r"上午", r"中午", r"下午", r"晚上",
        r"凌晨", r"清晨", r"两天", r"一日", r"半天", r"错峰",
        r"时间(?:差不多|紧|充足|不够|有限)?",
    ],
    "体力": [
        r"体力(?:好|不好|差|较差|一般|不佳|有限|较弱|透支|消耗)?",
        r"省力", r"轻松", r"累", r"膝盖", r"腿脚", r"耐力", r"徒步", r"爬山", r"登山",
    ],
    "预算": [
        r"预算(?:有限|不足|充足|低|高)?", r"省钱", r"便宜", r"价格", r"费用",
        r"门票", r"票价", r"花钱", r"性价比",
    ],
    "交通": [
        r"索道", r"观光车", r"地铁", r"公交", r"高铁", r"火车", r"自驾",
        r"停车", r"接驳", r"大巴", r"缆车", r"交通", r"打车", r"包车", r"拼车",
        r"南门", r"北门", r"西门", r"东门",
    ],
    "其他": [
        r"排队", r"人多", r"人流", r"预约", r"购票", r"住宿", r"露营", r"帐篷",
        r"信号", r"厕所", r"安全", r"拍照",
    ],
}

# 隐式条件只收“游客状态/场景”，不把“索道/徒步/排队”等主题词单独当条件。
IMPLICIT_PATTERNS: dict[str, list[str]] = {
    "天气": [
        r"下(?:大|小|暴|雷|阵)?雨(?:天|季)?", r"雨天", r"下雨天", r"阴雨(?:天)?",
        r"天气(?:不好|差|寒冷|炎热|多变)", r"大太阳", r"烈日", r"暴晒",
        r"下雪", r"大雾", r"台风", r"高温", r"低温", r"夏天", r"冬天",
    ],
    "人群": [
        r"带(?:着)?(?:老人|小孩|孩子|娃|宝宝|父母|小朋友|家人)",
        r"亲子", r"全家", r"一家人", r"老人", r"小孩", r"孩子", r"儿童",
        r"学生", r"情侣", r"闺蜜", r"带娃", r"小朋友", r"长辈",
        r"胆子小", r"怕累",
    ],
    "时间": [
        r"节假日", r"旺季", r"淡季", r"周末", r"五一", r"国庆", r"春节",
        r"暑假", r"寒假", r"夜爬", r"夜游", r"看日出", r"看日落", r"拍日落",
        r"错峰", r"时间(?:差不多|紧|充足|不够|有限)",
    ],
    "体力": [
        r"体力(?:不好|差|较差|一般|不佳|有限|较弱|透支)",
        r"膝盖[^，。；;]{0,8}", r"腿脚[^，。；;]{0,6}", r"不想爬山",
    ],
    "预算": [
        r"预算(?:有限|不足|充足|低|高)", r"不想花钱", r"想省钱", r"省钱",
        r"门票(?:贵|价格)", r"价格(?:超过|在|是|为)",
    ],
    "交通": [
        r"自驾", r"停车",
        r"不想坐索道", r"不坐索道", r"不想走",
    ],
    "其他": [
        r"排队(?:久|时间长|超过[^，。；;]{0,8})",
        r"人多", r"人流(?:大|多)", r"预约不到", r"没预约",
    ],
}

# 显式条件触发词；“如”只在后接条件线索时启用，避免“比如/如果”重复。
EXPLICIT_TRIGGERS = ["如果", "假如", "要是", "倘若", "一旦", "若", "如"]
EXPLICIT_RE = re.compile(r"(?<!宛)(?<!倘)(如果|假如|要是|倘若|一旦|若|如(?=(?:体力|天气|下雨|带|遇|时间|价格|想|不|果)))")

CONNECTORS = ["的话", "那就", "建议", "最好", "记得", "一定要", "需要", "可以", "就", "则", "那", "便", "应", "可"]
CONNECTOR_RE = re.compile("|".join(re.escape(x) for x in CONNECTORS) + r"|[，,；;]")

SUGGESTION_MARKERS = [
    "建议", "推荐", "最好", "一定要", "记得", "务必", "适合", "可以", "需要",
    "不要", "别", "带上", "带好", "带", "穿", "备好", "准备", "提前", "避开",
    "选择", "乘坐", "坐", "走", "按", "凭", "持", "应", "可",
]
MARKER_RE = re.compile(
    "|".join([
        "建议", "推荐", "最好", "一定要", "记得", "务必", "适合", "可以", "需要",
        "不要", r"(?<![特分个级类])别", "带上", "带好", r"带(?!来|动|领|有)", "穿", "备好", "准备",
        "提前", "避开", "选择", "乘坐", "坐", r"(?<!行)走", "按", "凭", "持", "应",
        r"可(?!是|能|见|行|否|供|用|谓|早|惜)", r"(?<![特分个级类])别",
    ])
)

SPLIT_RE = re.compile(
    r"[；;]|(?=(?:，|,)\s*(?:也|还)?(?:建议|推荐|最好|记得|一定要|可以|可|适合|需要|应|务必|不要|别))"
)
ACTION_WORDS = [
    "建议", "推荐", "最好", "记得", "一定要", "可以", "可", "适合", "需要", "应",
    "务必", "不要", "别", "带", "穿", "备", "准备", "提前", "避开", "选择",
    "乘坐", "坐", "走", "买", "订", "预", "查", "看", "拍", "吃", "住", "用",
    "注意", "小心", "防止", "避免", "错峰", "排队", "上山", "下山", "返回",
    "背", "爬", "停", "租", "换", "收", "关", "开", "行", "洗",
]
BAD_SUGGESTION = re.compile(r"点赞|收藏|转发|关注|评论|一夫一妻|殉情|无法想象|难以置信|陷入|绝对是你的|最好的结果|可是|可惜|穿越七尖|担心|不值|走安全|走路线|后台咨询|入住|性价比不错|money|的哦|声临其境|我这里又有一招|主打一个|可以拥有自己的专属小空间|家庭出游千万不要错过")
BAD_CONDITION = re.compile(r"天鹅|这篇纯手搓|一方死亡|无规划|亲眼所见")

CROWD_PATTERNS = {
    "亲子": r"孩子|小孩|娃|亲子|儿童|宝宝|小朋友|婴儿",
    "老人": r"老人|父母|长辈|银发",
    "学生": r"学生|学生证",
    "情侣": r"情侣|男友|女友|对象|男朋友|女朋友|两人",
    "团队": r"全家|一家人|朋友|闺蜜|团队|多人",
}


@dataclass
class Sentence:
    doc_id: str
    area: str
    doc_type: str
    title: str
    source_url: str
    text: str
    start: int
    end: int


def split_sentences(doc: dict) -> list[Sentence]:
    """按句末标点和换行切句；保留绝对位置，去掉首尾空白。"""
    text = doc["clean_content"].replace("\r\n", "\n").replace("\r", "\n")
    out: list[Sentence] = []
    for m in re.finditer(r"[^\n。！？!?]+[。！？!?]?", text):
        raw = m.group(0)
        if not raw.strip():
            continue
        lead = len(raw) - len(raw.lstrip())
        body = raw.strip()
        if len(body) < 4:
            continue
        out.append(Sentence(
            doc_id=doc["doc_id"], area=doc["scenic_area"], doc_type=doc["doc_type"],
            title=doc["title"], source_url=doc["source_url"], text=body,
            start=m.start() + lead, end=m.start() + lead + len(body),
        ))
    return out


def condition_type(text: str, fallback: str = "") -> str:
    for typ in TYPE_ORDER:
        for pat in CONDITION_PATTERNS[typ]:
            if re.search(pat, text):
                return typ
    if fallback:
        for typ in TYPE_ORDER:
            for pat in CONDITION_PATTERNS[typ]:
                if re.search(pat, fallback):
                    return typ
    return "其他"


def looks_like_advice(text: str) -> bool:
    t = text.strip(" ，,。；;！？!?")
    if len(t) < 4 or BAD_SUGGESTION.search(t):
        return False
    if t in {"可以", "推荐", "建议", "适合", "一定要", "记得", "带", "走", "坐"}:
        return False
    if re.fullmatch(r"(?:可以|推荐|建议|适合|一定要|记得|带|走|坐)", t):
        return False
    return any(w in t for w in ACTION_WORDS)


def clean_piece(text: str) -> str:
    return text.strip(" \t，,；;。！？!?")


def find_condition(sent: str) -> tuple[str, int, int, str, str] | None:
    """返回 (condition_type, cond_start, cond_end, trigger, marker_word)。"""
    # 显式条件
    for m in EXPLICIT_RE.finditer(sent):
        trig = m.group(0)
        if trig == "如" and m.start() > 0 and sent[m.start() - 1] == "比":
            continue
        conn = CONNECTOR_RE.search(sent, m.end())
        if not conn:
            continue
        cond_end = conn.start()
        cond_text = sent[m.start():cond_end].strip(" \t，,；;。！？!?")
        if not (2 <= len(cond_text) <= 90):
            continue
        if BAD_CONDITION.search(cond_text):
            continue
        ctype = condition_type(cond_text)
        # “如果发现了”“如果这篇”这类没有条件线索的泛指，不抽
        if ctype == "其他" and len(cond_text) <= 8:
            continue
        return ctype, m.start(), cond_end, trig, trig

    # 隐式条件：只认窄表里的游客状态/场景，且同句必须有建议标记
    TIME_MARKERS = {"建议", "推荐", "最好", "记得", "一定要", "可以", "可", "需要", "应", "务必", "不要", "别", "提前", "避开", "选择"}
    candidates: list[tuple[int, int, int, str, str]] = []
    for typ in TYPE_ORDER:
        for pat in IMPLICIT_PATTERNS[typ]:
            for m in re.finditer(pat, sent):
                if BAD_CONDITION.search(sent):
                    continue
                marker = MARKER_RE.search(sent, m.end())
                if marker:
                    word = marker.group(0)
                    if typ == "时间" and word not in TIME_MARKERS:
                        continue
                    candidates.append((m.start(), m.end(), marker.start(), typ, word))
                else:
                    # 建议标记在条件前：只允许“建议…”开头且同一分句，避免跨句误配
                    pre = MARKER_RE.search(sent, 0, m.start())
                    if (pre and pre.start() <= 3 and ";" not in sent and "；" not in sent
                            and m.start() - pre.start() <= 20):
                        word = pre.group(0)
                        if typ == "时间" and word not in TIME_MARKERS:
                            continue
                        candidates.append((m.start(), m.end(), pre.start(), typ, word))
    if not candidates:
        return None
    # 取离建议标记最近的条件；同一位置按类型优先级
    candidates.sort(key=lambda x: (-x[0], TYPE_ORDER.index(x[3])))
    cond_start, cond_end, _, typ, word = candidates[0]
    cond_text = sent[cond_start:cond_end]
    return typ, cond_start, cond_end, cond_text, word


def split_suggestions(sent: str, start: int) -> list[tuple[int, int, str]]:
    """从 start 起切分建议；按分号或“，+建议标记”拆分。"""
    tail = sent[start:]
    cuts = [0]
    for m in SPLIT_RE.finditer(tail):
        if m.start() > 0:
            cuts.append(m.start())
    cuts.append(len(tail))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        piece_start = start + a
        piece = sent[piece_start:start + b]
        # 去掉分隔符本身
        piece = re.sub(r"^[；;]\s*", "", piece)
        piece = clean_piece(piece)
        if len(piece) < 2:
            continue
        # 重新定位 trim 后的起点
        offset = sent.find(piece, piece_start, start + b)
        if offset < 0:
            offset = piece_start
        out.append((offset, offset + len(piece), piece))
    return out


def expand_suggestion_start(sent: str, cstart: int, cend: int, sstart: int, marker_word: str) -> int:
    """把“厚衣服一定要带上”“婴儿车可租”这类前置宾语并入建议。"""
    if marker_word not in {"一定要", "记得", "带上", "带好", "带", "穿", "备好", "准备", "提前", "避开", "选择", "乘坐", "坐", "走", "按", "凭", "持", "可", "可以", "需要", "应", "务必", "不要", "别"}:
        return sstart
    left = max((sent.rfind(ch, 0, sstart) for ch in "，,；;。！？!?：:"), default=-1)
    seg = sent[left + 1:sstart]
    prefix = seg.strip()
    if not (1 <= len(prefix) <= 8):
        return sstart
    if cend > cstart and (sent[cstart:cend] in prefix or prefix in sent[cstart:cend]):
        return sstart
    # 去掉“所以/因此/但/而且”等连接词，保留宾语
    prefix_wo_conn = re.sub(r"^(?:所以|因此|但是|但|而且|然后|就|也|还|再|并|且)\s*", "", prefix)
    if not prefix_wo_conn:
        return sstart
    m = re.search(r"(?:所以|因此|但是|但|而且|然后|就|也|还|再|并|且)\s*$", seg[:len(prefix) - len(prefix_wo_conn)])
    new_start = sstart - len(prefix_wo_conn)
    return max(left + 1, new_start)

def extract_from_sentence(sent: Sentence) -> tuple[list[dict], list[dict]]:
    got = find_condition(sent.text)
    if not got:
        return [], []
    typ, cstart, cend, trigger, marker_word = got
    cond = clean_piece(sent.text[cstart:cend])
    if not cond:
        return [], []

    # 显式条件的建议从连接词后开始；隐式条件从建议标记开始。
    if trigger in EXPLICIT_TRIGGERS:
        conn = CONNECTOR_RE.search(sent.text, cend)
        if not conn:
            return [], []
        sstart = conn.end()
        # 跳过逗号后的“那/就/则/便/也/还”
        while sstart < len(sent.text) and sent.text[sstart] in " \t，,；;":
            sstart += 1
        for word in ("那就", "那", "就", "则", "便", "也", "还"):
            if sent.text.startswith(word, sstart):
                sstart += len(word)
                break
    else:
        marker = MARKER_RE.search(sent.text, cend)
        if marker:
            sstart = expand_suggestion_start(sent.text, cstart, cend, marker.start(), marker_word)
        else:
            pre = MARKER_RE.search(sent.text, 0, cstart)
            if pre and pre.start() <= 3:
                sstart = expand_suggestion_start(sent.text, cstart, cend, pre.start(), pre.group(0))
            else:
                return [], []
    suggestions = split_suggestions(sent.text, sstart)
    if not suggestions:
        return [], []

    rows, rejected = [], []
    for sstart, send, sugg in suggestions:
        if len(sugg) > 120:
            rejected.append({"doc_id": sent.doc_id, "source_sentence": sent.text,
                             "condition_text": cond, "suggestion_text": sugg,
                             "reason": "suggestion_too_long"})
            continue
        if not looks_like_advice(sugg):
            rejected.append({"doc_id": sent.doc_id, "source_sentence": sent.text,
                             "condition_text": cond, "suggestion_text": sugg,
                             "reason": "suggestion_not_actionable"})
            continue
        # 条件不能为空、不能与建议完全重叠
        if cond in sugg and len(cond) == len(sugg):
            rejected.append({"doc_id": sent.doc_id, "source_sentence": sent.text,
                             "condition_text": cond, "suggestion_text": sugg,
                             "reason": "condition_equals_suggestion"})
            continue
        ctype = typ if typ != "其他" else condition_type(cond, sugg)
        rows.append({
            "cond_id": "",
            "doc_id": sent.doc_id,
            "scenic_area": sent.area,
            "condition_type": ctype,
            "condition_text": cond,
            "suggestion_text": sugg,
                "trigger_word": trigger if trigger in EXPLICIT_TRIGGERS else (marker_word or cond),
            "source_sentence": sent.text,
            "char_start": sent.start + cstart,
            "char_end": sent.start + cend,
            "is_duplicate": False,
            "extract_rule": "explicit_if" if trigger in EXPLICIT_TRIGGERS else "implicit_condition",
            "sentence_start": sent.start,
            "sentence_end": sent.end,
            "suggestion_start": sent.start + sstart,
            "suggestion_end": sent.start + send,
            "confidence": 0.95 if trigger in EXPLICIT_TRIGGERS else 0.85,
        })
    return rows, rejected


def norm(text: str) -> str:
    return re.sub(r"[\s，,。！？!?；;：:、（）()\[\]【】“”\"'·\-]", "", text or "")


def mark_duplicates(rows: list[dict]) -> dict:
    seen: dict[tuple[str, str, str], int] = {}
    uniques: list[dict] = []
    stats = Counter()
    for r in rows:
        key = (r["condition_type"], norm(r["condition_text"]), norm(r["suggestion_text"]))
        if key in seen:
            r["is_duplicate"] = True
            r["duplicate_reason"] = "exact"
            stats["exact"] += 1
            continue
        text = key[1] + "|" + key[2]
        reason = ""
        for u in uniques:
            if u["condition_type"] != r["condition_type"]:
                continue
            other = norm(u["condition_text"]) + "|" + norm(u["suggestion_text"])
            if not text or not other:
                continue
            if (text.startswith(other) or other.startswith(text)
                    or text.endswith(other) or other.endswith(text)) and min(len(text), len(other)) >= 8:
                reason = "prefix_suffix"
                break
            if SequenceMatcher(None, text, other).ratio() >= 0.90:
                reason = "near"
                break
        if reason:
            r["is_duplicate"] = True
            r["duplicate_reason"] = reason
            stats[reason] += 1
        else:
            r["is_duplicate"] = False
            r["duplicate_reason"] = ""
            uniques.append(r)
        seen[key] = 1
    stats["unique"] = sum(1 for r in rows if not r["is_duplicate"])
    stats["total"] = len(rows)
    return dict(stats)


def crowd_tag(text: str) -> str:
    for tag, pat in CROWD_PATTERNS.items():
        if re.search(pat, text):
            return tag
    return "一般"


def write_triggers() -> None:
    rows = []
    for i, w in enumerate(EXPLICIT_TRIGGERS, 1):
        rows.append({
            "trigger_id": f"T{i:02d}", "category": "显式条件", "trigger_word": w,
            "regex": "见 EXPLICIT_RE", "default_type": "按条件线索判定",
            "priority": 1, "note": "条件止于逗号或就/则/那/便/建议/可以等连接词",
        })
    for i, w in enumerate(SUGGESTION_MARKERS, 1):
        rows.append({
            "trigger_id": f"S{i:02d}", "category": "建议标记", "trigger_word": w,
            "regex": "见 MARKER_RE", "default_type": "不单独决定类型",
            "priority": 2, "note": "隐式条件必须同句出现建议标记；建议可为祈使动作",
        })
    for typ in TYPE_ORDER:
        rows.append({
            "trigger_id": f"C{TYPE_ORDER.index(typ)+1:02d}", "category": "条件线索",
            "trigger_word": typ, "regex": " | ".join(CONDITION_PATTERNS[typ]),
            "default_type": typ, "priority": 3,
            "note": "按 天气→人群→时间→体力→预算→交通→其他 顺序判定",
        })
    write_csv_sig(CONFIG / "triggers.csv", rows,
                  ["trigger_id", "category", "trigger_word", "regex", "default_type", "priority", "note"])


def main() -> int:
    CONFIG.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    write_triggers()

    rows_all: list[dict] = []
    rejected_all: list[dict] = []
    docs_total = docs_valid = 0
    docs_with = set()
    per_doc = []
    for area in SCENIC_AREAS:
        docs, _ = read_csv_sig(scenic_csv(area))
        for doc in docs:
            docs_total += 1
            if not is_true(doc.get("is_valid")):
                continue
            docs_valid += 1
            sents = split_sentences(doc)
            got_doc = 0
            for sent in sents:
                got, rejected = extract_from_sentence(sent)
                if got:
                    rows_all.extend(got)
                    got_doc += len(got)
                    docs_with.add(doc["doc_id"])
                rejected_all.extend(rejected)
            per_doc.append({"doc_id": doc["doc_id"], "scenic_area": area,
                            "doc_type": doc["doc_type"], "sentences": len(sents),
                            "conditions": got_doc})

    # 稳定排序 + 编号
    rows_all.sort(key=lambda r: (r["scenic_area"], r["doc_id"], r["char_start"],
                                 r["suggestion_start"], r["suggestion_text"]))
    for i, r in enumerate(rows_all, 1):
        r["cond_id"] = f"CND-{i:04d}"

    dedup = mark_duplicates(rows_all)
    for r in rows_all:
        r["crowd_tag"] = crowd_tag(r["condition_text"] + r["suggestion_text"])
        r["area_cn"] = AREA_CN.get(r["scenic_area"], r["scenic_area"])

    # 输出 JSONL（保留全部，is_duplicate 标记）
    write_jsonl(OUT / "conditions.jsonl", rows_all)
    write_jsonl(OUT / "rejected.jsonl", rejected_all)

    by_type = Counter(r["condition_type"] for r in rows_all)
    by_area = Counter(r["scenic_area"] for r in rows_all)
    by_doc_type = Counter(r["extract_rule"] for r in rows_all)
    by_trigger = Counter(r["trigger_word"] for r in rows_all)
    by_crowd = Counter(r["crowd_tag"] for r in rows_all if r["condition_type"] == "人群")
    by_area_type = defaultdict(Counter)
    for r in rows_all:
        by_area_type[r["scenic_area"]][r["condition_type"]] += 1

    stats = {
        "docs_total": docs_total,
        "docs_valid": docs_valid,
        "docs_with_conditions": len(docs_with),
        "coverage": round(len(docs_with) / docs_valid, 4) if docs_valid else 0,
        "total": len(rows_all),
        "unique": dedup["unique"],
        "duplicates": {k: v for k, v in dedup.items() if k in ("exact", "near", "prefix_suffix")},
        "dedup": dedup,
        "by_type": dict(by_type),
        "by_area": dict(by_area),
        "by_area_type": {k: dict(v) for k, v in by_area_type.items()},
        "by_rule": dict(by_doc_type),
        "by_trigger": dict(by_trigger.most_common()),
        "by_crowd": dict(by_crowd),
        "per_doc": per_doc,
    }
    write_json(OUT / "condition_stats.json", stats)

    # 去重前后统计
    lines = [
        "# 项目5 去重统计", "",
        f"- 去重前：{dedup['total']} 条",
        f"- 完全重复（同类型+条件+建议去标点后相同）：{dedup.get('exact', 0)} 条",
        f"- 近重复（SequenceMatcher ≥ 0.90）：{dedup.get('near', 0)} 条",
        f"- 前后缀包含：{dedup.get('prefix_suffix', 0)} 条",
        f"- 去重后唯一：{dedup['unique']} 条（保留原记录并标记 is_duplicate）", "",
        "## 按类型", "",
        "| 类型 | 数量 |", "|---|---:|",
    ]
    for typ in TYPE_ORDER:
        lines.append(f"| {typ} | {by_type.get(typ, 0)} |")
    lines += ["", "## 按景区", "", "| 景区 | 数量 | 唯一 |", "|---|---:|---:|"]
    for area in SCENIC_AREAS:
        uniq = sum(1 for r in rows_all if r["scenic_area"] == area and not r["is_duplicate"])
        lines.append(f"| {AREA_CN[area]} | {by_area.get(area, 0)} | {uniq} |")
    (OUT / "dedup_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"docs: {docs_total} total / {docs_valid} valid / {len(docs_with)} with conditions")
    print(f"conditions: {len(rows_all)} total / {dedup['unique']} unique")
    print("type:", dict(by_type))
    print("area:", dict(by_area))
    print("dedup:", dedup)
    print("outputs ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())