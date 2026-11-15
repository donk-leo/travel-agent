# -*- coding: utf-8 -*-
"""T1.4 节点分类器：把 P6 的「地点节点」映射到 6 值 `node_class` 枚举。

范围（唯一口径，见 docs/optimization/NODE_CLASSIFICATION.md）：
    地点节点 = graph_nodes.csv 中 node_type ∈ {SCENIC_AREA, POI, TRANSPORT}
    非地点节点 = node_type ∈ {TIME, ACTIVITY, CONDITION}（按 node_type 显式排除，不分类、不静默丢弃）
当前基线：SCENIC_AREA 3 + POI 141 + TRANSPORT 8 = 152；TIME 32 + ACTIVITY 12 + CONDITION 33 = 77；152 + 77 = 229。

`node_class` 枚举（6 值，不得新增）：
    attraction 可游览/可参观的具体景点、展馆、表演、游乐项目
    food       餐饮点
    transport  交通方式/交通设施（索道站、缆车站、车站、码头、停车场、乘车点）
    shop       购物点
    facility   服务设施与出入口（大门/闸口/游客中心/厕所/医疗/酒店住宿/观景平台/休息区）
    area       大范围空间单元（景区/园区/片区/街区/游览区/度假区/湖/谷/岛/山/岭/水库/界）

用法（仓库根目录，或任意目录均可）：
    python analysis/p06_graph/outputs/classify_nodes.py --check   # 只校验，不写盘；不满足 DoD 非 0 退出
    python analysis/p06_graph/outputs/classify_nodes.py --write   # 重写 node_classification.csv（确定性）

约束：不联网、不读时间戳、不用随机数；同一 graph_nodes.csv 输入必得同一字节输出（--write 幂等）。
T1.5 重跑 P6 后直接 --write 重建；若节点集合变化，--check 会提示同步更新 docs 与 50 抽样表。
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.io_utils import read_csv_sig, write_csv_sig  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
NODES_PATH = OUT_DIR / "graph_nodes.csv"
CLASS_PATH = OUT_DIR / "node_classification.csv"
SAMPLE_PATH = ROOT / "analysis/p02_entities/outputs/node_noise_sample50.csv"
DOCS_PATH = ROOT / "docs/optimization/NODE_CLASSIFICATION.md"

COLUMNS = ["node_id", "node_type", "name", "scenic_area",
           "node_class", "confidence", "method", "quality_flags"]
SAMPLE_COLUMNS = ["sample_no", "node_id", "name", "scenic_area", "evidence_sentence",
                  "node_class", "is_noise", "noise_reason", "quality_flags"]

CLASSES = ("attraction", "food", "transport", "shop", "facility", "area")
LOCATION_TYPES = ("SCENIC_AREA", "POI", "TRANSPORT")
EXCLUDED_TYPES = ("TIME", "ACTIVITY", "CONDITION")

#: 基线规模（写进 docs；T1.5 若增删节点，--check 会要求同步更新）
BASELINE = {"SCENIC_AREA": 3, "POI": 141, "TRANSPORT": 8,
            "TIME": 32, "ACTIVITY": 12, "CONDITION": 33}
SAMPLE_SEED = 20261115
SAMPLE_N = 50
NOISE_RATE_LIMIT = 0.10

#: quality_flags 受控词表（顺序即输出顺序，分号分隔）
FLAG_ORDER = (
    "class_uncertain",      # 类别有 ≥2 种合理解释，取了保守值
    "scope_ambiguous",      # 大范围(area) 与小点位(attraction) 判据互相冲突
    "multi_class_name",     # 名称同时命中两类词（如「小火车游览区」= 交通 + 游览区）
    "alias_mismatch",       # 节点名与原始写法/同址别名不一致
    "name_from_animal",     # 节点名是动物名而非地名（原文以「XX区域」指代展区）
    "activity_like",        # 名称是活动/表演而非固定地点（保留节点，归 attraction）
    "off_park_boundary",    # 名称位于景区范围外（市区/另一景区），不删只标注
    "p3_pseudo_poi_kept",   # P3 曾判为伪 POI，按 P6 KEEP_POI_NOTE 保留（6 条）
    "low_evidence",         # 证据只有路线串联/打卡列表，没有描述性语句
)
FLAG_SET = set(FLAG_ORDER)

# --------------------------------------------------------------------------- #
# 词表（有序：food > shop > transport > facility > 出入口门 > 成对景点 > 片区 > 地理单元 > 景点）
# --------------------------------------------------------------------------- #
FOOD_RE = re.compile(r"餐厅|茶餐厅|咖啡|小吃|美食|饭店|酒楼|餐饮|烧烤|糖水|豆腐花|面馆|火锅|餐吧|食堂|快餐")
SHOP_RE = re.compile(r"商店|商场|超市|购物|纪念品|便利店|市集|文创|专卖店")
TRANSPORT_RE = re.compile(r"索道|缆车|车站|火车站|码头|停车场|摆渡|接驳|乘车点")
FACILITY_RE = re.compile(r"入口|大门|闸口|游客中心|服务中心|厕所|卫生间|医疗|酒店|宾馆|客栈|旅舍|别墅|民宿|观景台|眺台|休息区|驿站|售票处")
#: 片区/园区等「容器」词
AREA_RE = re.compile(r"景区|度假区|园区|片区|区域|地带|天地|街区|街段|游览区|乐园|世界|王国|公园")
#: 自然地理单元（大范围）——只匹配结尾，避免「界碑」被当成「界」
GEO_AREA_RE = re.compile(r"(湖|水库|谷|岛|岭|山|界|宕)$")
#: 具体点位/游乐项目/展演的词（不足以判 area）
ATTRACTION_RE = re.compile(
    r"影院|剧场|马戏|表演|巡游|纪念馆|博物馆|展馆|馆|寺|宫|庵|祠|坟|墓|楼|阁|塔|桥|瀑|泉|潭|涧|石|碑|洞|亭|台|"
    r"园|广场|栈道|滑道|过山车|摆锤|海盗船|激流|转马|滑板|跳|峰|岩|坡|顶|村|林|坛|廊|温室|中心"
)

#: 逐条人工判定（只在名称规则会判错/需要降置信时使用；每条都写理由，docs 逐条列出）
OVERRIDES = {
    ("长隆", "金猴王国"): dict(
        cls="attraction", conf=0.80, flags=["scope_ambiguous"],
        reason="原文「金猴王国猴子种类超多，上午最活泼」= 可参观动物展区；不是独立售票园区，故不按「王国」归 area"),
    ("长隆", "青龙山"): dict(
        cls="area", conf=0.90, flags=[],
        reason="原文「侏罗纪风格区域，恐龙模型」明确是园内区域"),
    ("长隆", "花果山"): dict(
        cls="area", conf=0.70, flags=["scope_ambiguous"],
        reason="原文只给「花果山是花车巡游起点」「花果山道路两边占位置」= 园内片区；无独立景点描述"),
    ("长隆", "百虎山"): dict(
        cls="attraction", conf=0.85, flags=[],
        reason="原文「百虎山|看【白虎跳水】」= 展区/演出点，不是大范围山体"),
    ("长隆", "天鹅湖"): dict(
        cls="area", conf=0.85, flags=[],
        reason="原文「缆车低空横跨天鹅湖和鸳鸯湖，俯瞰整个天鹅湖」「天鹅湖线」= 湖面片区"),
    ("长隆", "奇妙岛"): dict(
        cls="area", conf=0.70, flags=["scope_ambiguous"],
        reason="原文「饭后逛『奇妙岛』拍照打卡」= 园内打卡片区；范围介于点位与片区"),
    ("长隆", "动物幼儿园"): dict(
        cls="attraction", conf=0.85, flags=[],
        reason="原文「奶萌小羊、小老虎、小猴子，很适合拍照」= 可参观动物育幼展区"),
    ("长隆", "火烈鸟"): dict(
        cls="attraction", conf=0.80, flags=["name_from_animal"],
        reason="节点名是动物名，原文以「火烈鸟区域」「看火烈鸟」指代展区"),
    ("广州白云山", "松涛别院"): dict(
        cls="attraction", conf=0.55, flags=["class_uncertain", "low_evidence"],
        reason="原文只有路线串联「西门→黄婆洞水库→梅花谷→松涛别院→摩星岭」；「别院」也可能是住宿/餐饮建筑，无法判定"),
    ("广州白云山", "山庄旅舍"): dict(
        cls="facility", conf=0.70, flags=["class_uncertain"],
        reason="「旅舍」= 住宿设施；但原文把它列入「途经游览…等景点」"),
    ("广州白云山", "双溪别墅"): dict(
        cls="facility", conf=0.60, flags=["class_uncertain"],
        reason="「别墅」= 住宿/接待建筑；原文仅列为途经景点，无功能描述"),
    ("广州白云山", "山顶公园"): dict(
        cls="area", conf=0.75, flags=["scope_ambiguous"],
        reason="「公园」为片区，但原文又把它与山顶广场并列为「主要景点」"),
    ("广州白云山", "黄婆洞水库"): dict(
        cls="area", conf=0.80, flags=[],
        reason="原文「乘观光车到黄婆洞水库」「西门/北门→黄婆洞水库」= 水库片区"),
    ("武功山", "金顶"): dict(
        cls="attraction", conf=0.65, flags=["scope_ambiguous"],
        reason="官方 WGS-O-03 把它列为「四大景区」之一；但它同时是海拔 1918 米主峰/登顶目的地（freq=13，无下级 POI），按具体目的地归 attraction，争议保留"),
    ("武功山", "发云界"): dict(
        cls="area", conf=0.85, flags=[],
        reason="官方「景区分为金顶、九龙山、发云界、羊狮幕四大景区」= 高山区段"),
    ("武功山", "观音宕"): dict(
        cls="area", conf=0.85, flags=[],
        reason="原文「观音宕地处武功山中段…海拔1600米…两个非常开阔的盆地…帐篷节营地」= 山间盆地区域"),
    ("武功山", "中庵"): dict(
        cls="attraction", conf=0.70, flags=["alias_mismatch"],
        reason="原文「紫极宫（中庵）」= 与紫极宫同址的别名；P6 未合并，保留双节点"),
    ("武功山", "沈家大院"): dict(
        cls="attraction", conf=0.85, flags=[],
        reason="原文「原本计划探访的沈家大院旧屋遗迹」= 遗迹景点，不是住宿设施"),
    ("武功山", "玻璃眺台"): dict(
        cls="facility", conf=0.65, flags=["class_uncertain"],
        reason="「眺台」= 观景平台（设施）；但它同时是武功山核心打卡点，下游若按「景点」取用可并入 attraction"),
    ("武功山", "猴谷"): dict(
        cls="attraction", conf=0.80, flags=[],
        reason="原文「在猴谷很容易看到猴群活动」= 动物观赏点，不是大范围山谷"),
    ("武功山", "福星谷"): dict(
        cls="area", conf=0.80, flags=[],
        reason="原文把「福星谷」与谷内「福星谷栈道」「许愿桥」「玻璃眺台」并列 = 谷内片区"),
    ("武功山", "明月山6281梯"): dict(
        cls="attraction", conf=0.60, flags=["p3_pseudo_poi_kept", "low_evidence"],
        reason="6281 级阶梯段，原文只作路线终点前的串联；P6 已按 KEEP_POI_NOTE 保留"),
    ("武功山", "途经好汉坡"): dict(
        cls="attraction", conf=0.70, flags=["alias_mismatch"],
        reason="节点名含动词「途经」，与「好汉坡」重复（原文「途经好汉坡」）；保留节点不删"),
}

#: 规则判类正确、但需要补质量标记的行（逐条写理由）
EXTRA_FLAGS = {
    ("长隆", "安检入口"): (["p3_pseudo_poi_kept"], "P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「09:00 入园 / 安检入口」"),
    ("长隆", "家庭亲子区"): (["p3_pseudo_poi_kept"], "P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「13:10 家庭亲子区 / 飞马家庭过山车」"),
    ("长隆", "巡游主街段"): (["p3_pseudo_poi_kept"], "P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「15:30 巡游主街段 / 主题街区」"),
    ("长隆", "欢乐主街区"): (["p3_pseudo_poi_kept"], "P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「进入主街，两边是各种商店和餐厅」"),
    ("武功山", "羊狮慕小火车站"): (["p3_pseudo_poi_kept"], "P3 判为伪 POI，P6 KEEP_POI_NOTE 保留；原文「…→羊狮慕小火车站→…」"),
    ("长隆", "小火车游览区"): (["multi_class_name"],
                              "「小火车」是交通词、「游览区」是片区词，按片区归类（不是 P3 伪 POI 保留项）"),
    ("长隆", "花车大巡游"): (["activity_like"], "原文「15:30 花车大巡游（花果山始发）」= 巡游活动，不是固定地点；保留节点归 attraction"),
    ("广州白云山", "白云松涛"): (["low_evidence"], "原文只作路线串联「经过『白云松涛』」；按景名归 attraction"),
    ("长隆", "长隆旅游度假区"): (["alias_mismatch"], "原文写「广州长隆度假区」，节点名加了「旅游」二字"),
    ("武功山", "萍乡车站"): (["off_park_boundary"], "位于萍乡市区、不在武功山景区范围内；作为行程起点的交通设施保留"),
    ("武功山", "三县界碑"): (["off_park_boundary"], "位于武功山—明月山穿越线边界，非武功山景区内部点位；保留"),
    ("武功山", "安源路矿工人运动纪念馆"): (["off_park_boundary"], "位于萍乡安源（独立景点），不在武功山景区内；保留为 POI 节点"),
    ("武功山", "秋收起义广场"): (["off_park_boundary"], "位于萍乡市区（江南第一大广场），不在武功山景区内；保留"),
}
#: 仅补 scope_ambiguous 的片区（规则已判 area，但范围介于点位与片区）
GEO_SCOPE_FLAG = {
    ("广州白云山", "蒲谷"): "原文「蒲谷溪流：热带雨林既视感」= 溪谷点位；「谷」按片区规则归 area",
    ("广州白云山", "梅花谷"): "原文只作景点/路线串联；「谷」按片区规则归 area",
    ("武功山", "回音谷"): "原文只作路线串联；「谷」按片区规则归 area",
}


def load_nodes() -> list[dict]:
    rows, cols = read_csv_sig(NODES_PATH)
    for col in ("node_id", "node_type", "name", "scenic_area"):
        if col not in cols:
            raise SystemExit(f"[FAIL] graph_nodes.csv 缺列：{col}")
    return rows


def classify_location(node: dict, area_names: set[str]) -> dict:
    """返回 {node_class, confidence, method, quality_flags}；纯函数、可复算。"""
    node_type, name, area = node["node_type"], node["name"], node["scenic_area"]

    if node_type == "SCENIC_AREA":
        return dict(cls="area", conf=1.00, method="node_type:SCENIC_AREA", flags=[])
    if node_type == "TRANSPORT":
        return dict(cls="transport", conf=1.00, method="node_type:TRANSPORT", flags=[])

    override = OVERRIDES.get((area, name))
    if override is not None:
        flags = list(override["flags"])
        extra = EXTRA_FLAGS.get((area, name))
        if extra:
            flags = _merge_flags(flags, extra[0])
        return dict(cls=override["cls"], conf=override["conf"],
                    method="manual_review", flags=flags)

    flags: list[str] = []
    extra = EXTRA_FLAGS.get((area, name))
    if extra:
        flags = _merge_flags(flags, extra[0])

    if FOOD_RE.search(name):
        res = dict(cls="food", conf=0.90, method="name_rule:food")
    elif SHOP_RE.search(name):
        res = dict(cls="shop", conf=0.90, method="name_rule:shop")
    elif TRANSPORT_RE.search(name) or name.endswith("站"):
        res = dict(cls="transport", conf=0.90, method="name_rule:transport")
    elif FACILITY_RE.search(name):
        res = dict(cls="facility", conf=0.90, method="name_rule:facility")
    elif name.endswith("门"):
        res = dict(cls="facility", conf=0.90, method="name_rule:gate")
    elif (name + "景区") in area_names:
        # 同一景区内同时存在「X」与「X景区」：X 是具体点位，X景区 才是片区
        res = dict(cls="attraction", conf=0.85, method="name_rule:paired_spot")
    elif AREA_RE.search(name) or name.endswith("区"):
        res = dict(cls="area", conf=0.90, method="name_rule:area")
    elif GEO_AREA_RE.search(name):
        res = dict(cls="area", conf=0.70, method="name_rule:area_geo")
        if (area, name) in GEO_SCOPE_FLAG:
            flags = _merge_flags(flags, ["scope_ambiguous"])
    elif ATTRACTION_RE.search(name):
        res = dict(cls="attraction", conf=0.85, method="name_rule:attraction")
    else:
        res = dict(cls="attraction", conf=0.70, method="fallback:attraction")
    res["flags"] = flags
    return res


def _merge_flags(base: list[str], extra: list[str]) -> list[str]:
    out = list(base)
    for f in extra:
        if f not in out:
            out.append(f)
    return out


def build_rows() -> list[dict]:
    nodes = load_nodes()
    area_names: dict[str, set[str]] = {}
    for n in nodes:
        if n["node_type"] == "POI":
            area_names.setdefault(n["scenic_area"], set()).add(n["name"])

    rows = []
    for n in nodes:
        if n["node_type"] not in LOCATION_TYPES:
            continue
        res = classify_location(n, area_names.get(n["scenic_area"], set()))
        flags = [f for f in FLAG_ORDER if f in res["flags"]]
        bad = [f for f in flags if f not in FLAG_SET]
        if bad:
            raise SystemExit(f"[FAIL] {n['node_id']} 未知 quality_flags：{bad}")
        rows.append({
            "node_id": n["node_id"],
            "node_type": n["node_type"],
            "name": n["name"],
            "scenic_area": n["scenic_area"],
            "node_class": res["cls"],
            "confidence": f"{res['conf']:.2f}",
            "method": res["method"],
            "quality_flags": ";".join(flags),
        })
    return rows


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def check_classification(rows: list[dict], errors: list[str]) -> None:
    nodes = load_nodes()
    expect_n = sum(1 for n in nodes if n["node_type"] in LOCATION_TYPES)
    if len(rows) != expect_n:
        errors.append(f"分类行数 {len(rows)} ≠ 地点节点数 {expect_n}")
    if expect_n != 152:
        errors.append(f"当前地点节点 {expect_n} ≠ 基线 152：T1.5 重跑后需同步更新 docs 与 50 抽样表")
    # 表头
    with CLASS_PATH.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh), [])
    if header != COLUMNS:
        errors.append(f"表头不符：{header}")
    # 与输入集合相等
    expect = {n["node_id"]: n for n in nodes if n["node_type"] in LOCATION_TYPES}
    got = [r["node_id"] for r in rows]
    if len(got) != len(set(got)):
        errors.append(f"node_id 有重复：{len(got) - len(set(got))} 个")
    only_a, only_b = set(expect) - set(got), set(got) - set(expect)
    if only_a:
        errors.append(f"缺行（在 graph_nodes 不在分类表）：{sorted(only_a)}")
    if only_b:
        errors.append(f"多行（在分类表不在 graph_nodes）：{sorted(only_b)}")
    # 枚举 / 空值 / 置信度
    empty = [r["node_id"] for r in rows if not r["node_class"].strip()]
    if empty:
        errors.append(f"node_class 为空：{empty[:10]}")
    bad_cls = [r["node_id"] for r in rows if r["node_class"] not in CLASSES]
    if bad_cls:
        errors.append(f"node_class 非法：{bad_cls[:10]}")
    for r in rows:
        try:
            conf = float(r["confidence"])
        except ValueError:
            errors.append(f"{r['node_id']} confidence 非数值：{r['confidence']!r}")
            continue
        if not 0.0 <= conf <= 1.0:
            errors.append(f"{r['node_id']} confidence 越界：{conf}")
    # 每类都有节点
    counts = Counter(r["node_class"] for r in rows)
    for c in CLASSES:
        if counts[c] == 0:
            errors.append(f"node_class={c} 没有任何节点")
    # 固定 node_type 的类
    for r in rows:
        if r["node_type"] == "SCENIC_AREA" and r["node_class"] != "area":
            errors.append(f"{r['node_id']} SCENIC_AREA 必须是 area，实为 {r['node_class']}")
        if r["node_type"] == "TRANSPORT" and r["node_class"] != "transport":
            errors.append(f"{r['node_id']} TRANSPORT 必须是 transport，实为 {r['node_class']}")
    # 节点名/景区与输入一致（防止手改 CSV 造成漂移）
    for r in rows:
        n = expect.get(r["node_id"])
        if n is None:
            continue
        if (r["name"], r["node_type"], r["scenic_area"]) != (n["name"], n["node_type"], n["scenic_area"]):
            errors.append(f"{r['node_id']} 名称/类型/景区与 graph_nodes.csv 不一致")
    # quality_flags 词表
    for r in rows:
        toks = [t for t in r["quality_flags"].split(";") if t]
        for t in toks:
            if t not in FLAG_SET:
                errors.append(f"{r['node_id']} quality_flags 未登记：{t}")
        if len(toks) != len(set(toks)):
            errors.append(f"{r['node_id']} quality_flags 重复：{r['quality_flags']}")
        if toks != [f for f in FLAG_ORDER if f in toks]:
            errors.append(f"{r['node_id']} quality_flags 顺序应为 {';'.join(FLAG_ORDER)} 的顺序")
    # 范围口径：非地点节点必须仍能被显式排除并计数
    excluded = [n for n in nodes if n["node_type"] in EXCLUDED_TYPES]
    if len(rows) + len(excluded) != len(nodes):
        errors.append(f"{len(rows)} + {len(excluded)} ≠ {len(nodes)}（范围口径被破坏）")
    for t in EXCLUDED_TYPES:
        actual = sum(1 for n in excluded if n["node_type"] == t)
        if actual != BASELINE[t]:
            errors.append(f"非地点节点 {t} 计数 {actual} ≠ 基线 {BASELINE[t]}")


def check_determinism(rows: list[dict], errors: list[str]) -> None:
    regen = build_rows()
    if len(regen) != len(rows):
        errors.append("规则重算行数与磁盘 CSV 不一致（CSV 可能被手改）")
        return
    for i, (a, b) in enumerate(zip(regen, rows), start=1):
        if a != b:
            errors.append(f"第 {i} 行与规则重算不一致：磁盘={b} 重算={a}")
            if len(errors) > 20:
                return


def noise_frame() -> list[str]:
    """50 抽样框：141 个 POI 节点，按 node_id 排序后 sample（固定 seed，确定性）。"""
    nodes = load_nodes()
    pois = sorted(n["node_id"] for n in nodes if n["node_type"] == "POI")
    if len(pois) < SAMPLE_N:
        raise SystemExit(f"[FAIL] POI 只剩 {len(pois)} 个，少于抽样数 {SAMPLE_N}，无法复算抽样表")
    return random.Random(SAMPLE_SEED).sample(pois, SAMPLE_N)


def check_sample(errors: list[str]) -> None:
    if not SAMPLE_PATH.exists():
        errors.append(f"缺少 50 抽样表：{SAMPLE_PATH.relative_to(ROOT)}")
        return
    rows, cols = read_csv_sig(SAMPLE_PATH)
    if list(cols) != SAMPLE_COLUMNS:
        errors.append(f"抽样表表头不符：{list(cols)}")
    if len(rows) != SAMPLE_N:
        errors.append(f"抽样表行数 {len(rows)} ≠ {SAMPLE_N}")
    # seed / 抽样框复算
    frame = noise_frame()
    got = [r["node_id"] for r in rows]
    if got != frame:
        errors.append("抽样表 node_id 序列与 random.Random(20261115).sample(141 POI, 50) 不一致")
    if [r["sample_no"] for r in rows] != [str(i) for i in range(1, SAMPLE_N + 1)]:
        errors.append("sample_no 必须是 1..50 递增")
    # 分类一致性
    cls_map = {r["node_id"]: r["node_class"] for r in build_rows()}
    for r in rows:
        if r["node_class"] != cls_map.get(r["node_id"]):
            errors.append(f"{r['node_id']} 抽样表 node_class 与分类表不一致")
        if r["is_noise"] not in ("0", "1"):
            errors.append(f"{r['node_id']} is_noise 只能是 0/1，实为 {r['is_noise']!r}")
        if r["is_noise"] == "1" and not r["noise_reason"].strip():
            errors.append(f"{r['node_id']} is_noise=1 但没有 noise_reason")
        if r["is_noise"] == "0" and r["noise_reason"].strip():
            errors.append(f"{r['node_id']} is_noise=0 却有 noise_reason（应为空）")
        if not r["evidence_sentence"].strip():
            errors.append(f"{r['node_id']} evidence_sentence 为空")
    # 噪声率
    noise = sum(1 for r in rows if r["is_noise"] == "1")
    rate = noise / SAMPLE_N if rows else 0.0
    if rate >= NOISE_RATE_LIMIT:
        errors.append(f"POI 噪声率 {noise}/{SAMPLE_N} = {rate:.0%} ≥ 10%（需上报 blocked，不得改抽样）")
    # 证据出处：evidence_sentence 必须逐字来自 entities.jsonl 的 sentence 或 clean_content
    sents, contents = _evidence_sources()
    for r in rows:
        ev = r["evidence_sentence"].strip()
        if not ev:
            continue
        if ev not in sents and not any(ev in c for c in contents):
            errors.append(f"{r['node_id']} evidence_sentence 不是 entities.jsonl/clean_content 的原文片段：{ev[:40]}")


def _evidence_sources() -> tuple[set[str], list[str]]:
    """P2 实体句集合 + 32 篇 clean_content（只读），用于校验证据出处。"""
    ent_path = ROOT / "analysis/p02_entities/outputs/entities.jsonl"
    sents = {json.loads(line)["sentence"].strip()
             for line in ent_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    contents = []
    for area in ("changlong", "baiyunshan", "wugongshan"):
        rows, _ = read_csv_sig(ROOT / f"scenic/{area}/data/processed/{area}_guides.csv")
        contents.extend(r["clean_content"] for r in rows)
    return sents, contents


def check_docs(errors: list[str]) -> None:
    if not DOCS_PATH.exists():
        errors.append(f"缺少说明文档：{DOCS_PATH.relative_to(ROOT)}")
        return
    text = DOCS_PATH.read_text(encoding="utf-8")
    for needle, why in [
        ("152 + 77 = 229", "范围口径（152 地点 + 77 非地点 = 229）"),
        ("random.Random(20261115)", "50 抽样 seed 复算口径"),
        ("classify_nodes.py --write", "T1.5 重建命令"),
        ("attraction", "6 值枚举"),
        ("facility", "6 值枚举"),
        ("area", "6 值枚举"),
        ("噪声率", "噪声率结论"),
        ("质量标记", "难样本说明"),
    ]:
        if needle not in text:
            errors.append(f"NODE_CLASSIFICATION.md 缺必需内容：{why}（未找到 {needle!r}）")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def print_summary(rows: list[dict]) -> None:
    cls = Counter(r["node_class"] for r in rows)
    print(f"rows={len(rows)}  " + "  ".join(f"{c}={cls[c]}" for c in CLASSES))
    methods = Counter(r["method"].split(":")[0] if not r["method"].startswith("node_type") else r["method"]
                      for r in rows)
    print("method:", dict(methods))
    flagged = [r for r in rows if r["quality_flags"]]
    print(f"flagged={len(flagged)}/{len(rows)}  "
          f"flags={dict(Counter(t for r in flagged for t in r['quality_flags'].split(';')))}")


def main() -> int:
    ap = argparse.ArgumentParser(description="T1.4 节点分类器（6 值 node_class）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="只校验，不写盘；不满足 DoD 非 0 退出")
    g.add_argument("--write", action="store_true", help="重写 node_classification.csv")
    args = ap.parse_args()

    rows = build_rows()

    if args.write:
        write_csv_sig(CLASS_PATH, rows, COLUMNS)
        print(f"[OK] wrote {CLASS_PATH.relative_to(ROOT)}")
        print_summary(rows)
        return 0

    errors: list[str] = []
    if not CLASS_PATH.exists():
        print(f"[FAIL] 缺少 {CLASS_PATH.relative_to(ROOT)}，先跑 --write", file=sys.stderr)
        return 1
    disk_rows, _ = read_csv_sig(CLASS_PATH)
    check_classification(disk_rows, errors)
    check_determinism(disk_rows, errors)
    check_sample(errors)
    check_docs(errors)
    print_summary(disk_rows)
    if errors:
        print(f"[FAIL] {len(errors)} 项：", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 1
    print("[OK] node_classification.csv / 50 抽样表 / docs 全部满足 DoD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
