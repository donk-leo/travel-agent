"""把图谱路线整理成可读的分时行程（T2.3 v2）。

口径与边界
----------
- **时间只来自资料明确写出的钟点**：P6 图谱里 ``rel=AT_TIME`` 的边指向
  ``TIME`` 节点，这些节点由 P3 ``time_norm``（``time_source=explicit``）生成。
  没有这类钟点时写「资料未给出」，``time_range=None``、``time_source="absent"``，
  绝不用模板钟点冒充资料时间。
- **时长只有两种依据**：固定模板（上午/下午 2-3 小时、中午 1-1.5 小时）或
  「未给出」。模板一律标 ``duration_source="模板估算"`` 并写进 ``unknowns``；
  不按点数、距离或钟点差换算时长。
- **中午 11:30–13:30 固定为餐饮/休息块**：图谱有餐饮节点就显示名称并注明
  「营业时间、位置与排队未核验」；没有就写「未找到餐饮点，请以现场为准」，
  不编造餐厅名。
- **人群/体力提示只复用 feasibility 的结论**：``caps`` / ``warnings`` /
  ``uncertainties`` 是规划假设，不写成资料事实，也不声称「已为老人/儿童优化」。
- **只读**：不修改 ``proposal.node_ids`` / ``day_plan`` / ``validation``，不生成
  距离、坐标、票价、开放时间，不调用模型；纯确定性代码，同一输入两次结果相同。
- **向后兼容**：旧字段 ``days[].periods[].text``、``duration_hint``、``plan_note``、
  ``note`` 全部保留，旧页面（``web_app.py``）继续按 ``text`` 渲染。

返回结构（``build_itinerary``）
------------------------------
::

    {days: [{day, plan_note,
             periods: [{period, time_range, time_source, title, text,
                        stops: [{node_id, name}], duration_hint,
                        duration_source, meal, rest, fatigue_note,
                        unknowns}]}],
     note}
"""

import re
import sys
from pathlib import Path

# 与 evidence.py 相同的兼容处理：既支持 ``import itinerary``（src 在 sys.path），
# 也支持 ``from analysis.p07_agent.src import itinerary`` 时按需导入 tools。
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


MEAL_WORDS = ("餐厅", "餐", "美食", "咖啡", "小吃", "食堂")
NON_MEAL_WORDS = ("酒店", "别墅", "客栈", "旅舍", "纪念品", "商店")
PERIOD_ORDER = ("上午", "中午", "下午", "晚上")
PERIOD_RANK = {period: index for index, period in enumerate(PERIOD_ORDER)}
PERIOD_HINTS = {
    "上午": "2-3 小时",
    "中午": "1-1.5 小时",
    "下午": "2-3 小时",
    "晚上": None,
}
DURATION_TEMPLATE = "模板估算"
DURATION_UNKNOWN = "未给出"
TIME_UNKNOWN_TEXT = "资料未给出"
MEAL_FALLBACK_TEXT = "未找到餐饮点，请以现场为准"
MEAL_SLOT_TEXT = "11:30–13:30"
TEMPLATE_UNKNOWN_TEXT = "时长为模板估算，不是资料给出的实际游玩时长。"

#: 资料里的钟点只认 ``HH:MM`` 或 ``HH:MM-HH:MM``；``AM/NOON/PM`` 不是具体钟点。
CLOCK_RE = re.compile(
    r"^(\d{1,2}):(\d{2})(?:\s*[-–—~～]\s*(\d{1,2}):(\d{2}))?$"
)

#: ``node_id -> [{text, start, end}, ...]``；首次读图后缓存，只读不写。
_EXPLICIT_TIME_INDEX = None


def _name(name_map, node_id):
    """节点显示名：优先用路线里的 node_names，其次取节点 ID 尾段。"""
    return name_map.get(node_id) or node_id.split("|")[-1]


def _pick_lunch(names):
    """挑一个适合中午停留的节点；没有餐饮节点时返回 None。

    与旧版一致：只按名称关键词判断，且不把首尾节点当午餐点。酒店/商店
    由 ``NON_MEAL_WORDS`` 排除，避免把「长隆酒店」写成餐厅。
    """
    for index, name in enumerate(names):
        if not (0 < index < len(names) - 1):
            continue
        if any(word in name for word in NON_MEAL_WORDS):
            continue
        if any(word in name for word in MEAL_WORDS):
            return index
    return None


def _parse_clock(text):
    """把 ``HH:MM`` / ``HH:MM-HH:MM`` 解析成分钟；不是具体钟点返回 None。"""
    value = str(text or "").strip()
    match = CLOCK_RE.match(value)
    if match is None:
        return None

    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    start = hour * 60 + minute

    if match.group(3) is None:
        end = start
    else:
        end_hour, end_minute = int(match.group(3)), int(match.group(4))
        if end_hour > 23 or end_minute > 59:
            return None
        end = end_hour * 60 + end_minute
        if end < start:
            return None

    return {"text": value, "start": start, "end": end}


def _format_minutes(minutes):
    """分钟数格式化回 ``HH:MM``，只用于把已明确的钟点拼成区间。"""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _explicit_time_index():
    """读取 P6 ``AT_TIME`` 边，返回 ``node_id -> 显式钟点列表``。

    只收 ``TIME`` 节点的名称能解析成 ``HH:MM`` / ``HH:MM-HH:MM`` 的边；
    ``AM/NOON/PM`` 这类时段词不算具体钟点。图不可读时返回空字典，行程
    仍可生成，只是所有时段都标「资料未给出」。
    """
    global _EXPLICIT_TIME_INDEX
    if _EXPLICIT_TIME_INDEX is not None:
        return _EXPLICIT_TIME_INDEX

    index = {}
    try:
        from tools import load_graph

        nodes, edges = load_graph()
        time_names = {
            node.get("node_id"): node.get("name") or ""
            for node in nodes
            if node.get("node_type") == "TIME"
        }
        for edge in edges:
            if edge.get("rel") != "AT_TIME":
                continue
            node_id = edge.get("src")
            if not node_id:
                continue
            time_text = time_names.get(edge.get("dst"))
            if time_text is None:
                time_text = str(edge.get("dst") or "").split("|")[-1]
            parsed = _parse_clock(time_text)
            if parsed is None:
                continue
            index.setdefault(node_id, []).append(parsed)
        for candidates in index.values():
            candidates.sort(key=lambda item: (item["start"], item["end"], item["text"]))
    except (ImportError, OSError, KeyError, ValueError, TypeError):
        index = {}

    _EXPLICIT_TIME_INDEX = index
    return index


def _choose_day_times(node_ids, catalog):
    """按路线顺序挑选每一天要展示的显式钟点。

    P3 允许同一节点有多个时间（例如考拉园 11:50 与 16:30）。这里按路线顺序
    贪心：只选开始时间不早于上一个已选钟点的候选；找不到就当作该节点没有
    可展示的钟点，绝不为了凑时间而回退或改节点顺序。
    """
    chosen = {}
    previous_start = -1
    for node_id in node_ids:
        selected = None
        for candidate in catalog.get(node_id) or []:
            if candidate["start"] >= previous_start:
                selected = candidate
                break
        if selected is None:
            continue
        chosen[node_id] = selected
        previous_start = selected["start"]
    return chosen


def _period_for_minutes(start):
    """按显式钟点的开始时间归入上午/中午/下午/晚上。"""
    if start < 11 * 60 + 30:
        return "上午"
    if start < 13 * 60 + 30:
        return "中午"
    if start < 18 * 60:
        return "下午"
    return "晚上"


def _span_text(times):
    """把同一时段内已明确的钟点拼成展示区间。

    只有一个钟点/区间时原样返回资料文本；多个时取最早开始与最晚结束，
    例如 10:00、11:00、11:50 → ``10:00-11:50``。端点都来自资料，不补中间值。
    """
    texts = [item["text"] for item in times]
    if len(set(texts)) == 1:
        return texts[0]

    start = min(item["start"] for item in times)
    end = max(item["end"] for item in times)
    if start == end:
        return _format_minutes(start)
    return f"{_format_minutes(start)}-{_format_minutes(end)}"


def _legacy_node_groups(node_ids, names):
    """旧版分时口径：无显式钟点时把一天拆成上午/午餐/下午三组。"""
    if len(node_ids) == 1:
        return list(node_ids), [], []

    lunch_index = _pick_lunch(names)
    if lunch_index is None:
        morning_count = max(1, min(len(node_ids) - 1, round(len(node_ids) * 0.45)))
        return node_ids[:morning_count], [], node_ids[morning_count:]

    return node_ids[:lunch_index], [node_ids[lunch_index]], node_ids[lunch_index + 1:]


def _legacy_period_texts(names):
    """旧版上午/下午文案；中午文案由餐饮块统一生成。"""
    names = [name for name in names if name]
    if not names:
        return []

    if len(names) == 1:
        name = names[0]
        return [
            {"period": "上午",
             "text": f"前往{name}，办理入园/开始游览，先熟悉主要区域。"},
            {"period": "中午",
             "text": "在园区内休息区补水，避开正午高温。"},
            {"period": "下午",
             "text": f"继续体验{name}的主要项目，按体力安排返程。"},
        ]

    lunch_index = _pick_lunch(names)
    if lunch_index is None:
        morning_count = max(1, min(len(names) - 1, round(len(names) * 0.45)))
        morning = names[:morning_count]
        afternoon = names[morning_count:]
        # 中午文案只作为兜底（正常由餐饮块覆盖），不写餐厅名。
        noon_text = (
            f"在{morning[-1]}附近休息；{MEAL_FALLBACK_TEXT}；"
            "用餐请选择园区内营业的餐厅。"
        )
    else:
        lunch = names[lunch_index]
        morning = names[:lunch_index]
        afternoon = names[lunch_index + 1:]
        noon_text = f"在{lunch}用餐、休息；营业时间、位置与排队未核验。"

    texts = []
    if morning:
        texts.append({
            "period": "上午",
            "text": "游览" + "、".join(morning) + "，按园区指示顺序步行或乘接驳工具。",
        })
    else:
        texts.append({
            "period": "上午",
            "text": "从入口进入园区，先游览核心区域。",
        })
    texts.append({"period": "中午", "text": noon_text})
    if afternoon:
        texts.append({
            "period": "下午",
            "text": "继续游览" + "、".join(afternoon) + "，预留返程和休息时间。",
        })
    else:
        texts.append({
            "period": "下午",
            "text": "自由活动或返程，避开闭园前的高峰。",
        })
    return texts


def _legacy_period_for_index(index, names, lunch_index):
    """无显式钟点的节点按旧版位置启发式归入上午/中午/下午。"""
    if len(names) == 1:
        return "上午"
    if lunch_index is not None:
        if index < lunch_index:
            return "上午"
        if index == lunch_index:
            return "中午"
        return "下午"
    morning_count = max(1, min(len(names) - 1, round(len(names) * 0.45)))
    return "上午" if index < morning_count else "下午"


def _explicit_groups(node_ids, names, chosen):
    """按显式钟点分组；没有钟点的节点跟随旧版位置启发式。

    分组保持路线顺序：时段只向后推进，不为了凑上午/下午而重排节点。
    如果一天没有任何中午停留点，也会补一个空的「中午」块用于用餐/休息。
    """
    lunch_index = _pick_lunch(names)
    groups = []
    for index, node_id in enumerate(node_ids):
        if node_id in chosen:
            desired = _period_for_minutes(chosen[node_id]["start"])
        else:
            desired = _legacy_period_for_index(index, names, lunch_index)

        if not groups:
            groups.append({"period": desired, "node_ids": [node_id]})
        elif PERIOD_RANK[desired] > PERIOD_RANK[groups[-1]["period"]]:
            groups.append({"period": desired, "node_ids": [node_id]})
        else:
            # 时段不能倒退：晚到的上午节点并入当前时段，保持节点原顺序。
            groups[-1]["node_ids"].append(node_id)

    if not any(group["period"] == "中午" for group in groups):
        insert_at = 0
        for index, group in enumerate(groups):
            if PERIOD_RANK[group["period"]] < PERIOD_RANK["中午"]:
                insert_at = index + 1
        groups.insert(insert_at, {"period": "中午", "node_ids": []})
    return groups


def _feasibility_caps(feasibility):
    """从 feasibility 报告取人群上限；缺失/非法时返回 None。"""
    if not isinstance(feasibility, dict):
        return None
    caps = feasibility.get("caps")
    if not isinstance(caps, dict):
        return None
    persona = str(caps.get("persona") or "").strip()
    max_stops = caps.get("max_stops")
    if not persona or not isinstance(max_stops, int) or isinstance(max_stops, bool):
        return None
    return persona, max_stops


def _meal_block(day_ids, noon_ids, names_map, feasibility):
    """生成中午餐饮块；只依据路线里的餐饮节点，不编餐厅名。"""
    noon_food = None
    for node_id in noon_ids:
        name = _name(names_map, node_id)
        if any(word in name for word in MEAL_WORDS) and not any(
                word in name for word in NON_MEAL_WORDS):
            noon_food = name
            break

    day_food = None
    if noon_food is None:
        for node_id in day_ids:
            name = _name(names_map, node_id)
            if any(word in name for word in MEAL_WORDS) and not any(
                    word in name for word in NON_MEAL_WORDS):
                day_food = name
                break

    if noon_food:
        return {
            "inserted": True,
            "note": (
                f"在「{noon_food}」用餐、休息；"
                "营业时间、位置与排队未核验。"
            ),
        }
    if day_food:
        return {
            "inserted": False,
            "note": (
                f"路线中的餐饮节点「{day_food}」不在中午时段；"
                f"{MEAL_SLOT_TEXT} 用餐时段未找到明确餐饮点，{MEAL_FALLBACK_TEXT}。"
                "营业时间与排队未核验。"
            ),
        }

    # 兜底前先看 feasibility 是否已判定有餐饮节点（它读 P6 分类表，比名称准）。
    if isinstance(feasibility, dict):
        report_meal = feasibility.get("meal")
        if isinstance(report_meal, dict) and report_meal.get("inserted"):
            note = str(report_meal.get("note") or "").strip()
            if note:
                return {"inserted": True, "note": note}

    return {
        "inserted": False,
        "note": (
            f"{MEAL_SLOT_TEXT} 用餐与休息时段（规划时段，非资料钟点）；"
            f"{MEAL_FALLBACK_TEXT}。营业时间与排队未核验。"
        ),
    }


def _fatigue_note(feasibility, day_stop_count, period, group_count, is_first,
                  group_has_rest=False):
    """人群/体力提示：只复用 feasibility 的 caps，不写成资料事实。"""
    caps = _feasibility_caps(feasibility)
    if caps is None:
        return None
    persona, max_stops = caps

    parts = []
    if is_first:
        parts.append(
            f"人群假设：{persona}；单日停留点上限 {max_stops} 个"
            "（PRODUCT_SPEC §7.4 建议默认，非资料结论；"
            "图谱无适龄、身高、体力标签，未做硬性过滤）。"
        )
    if is_first and day_stop_count > max_stops:
        parts.append(
            f"本日 {day_stop_count} 个停留点，超过建议上限 {max_stops} 个；"
            "未自动裁剪，请减少停留点或增加天数。"
        )
    if period != "中午" and group_count >= 3 and not group_has_rest:
        parts.append(
            f"本段连续 {group_count} 个停留点没有休息安排，"
            "建议插入 15–20 分钟休息。"
        )
    return " ".join(parts) or None


def _period_unknowns(period, time_source, missing_time, duration_hint,
                     meal_inserted, fatigue_note):
    """每个时段必须带未知/假设清单（至少一条，供页面如实展示）。"""
    unknowns = []
    if time_source == "absent":
        unknowns.append("资料未给出具体时间，未用模板钟点代替。")
    elif missing_time:
        unknowns.append("部分停留点资料未给出具体时间。")

    if duration_hint:
        unknowns.append(TEMPLATE_UNKNOWN_TEXT)
    else:
        unknowns.append("资料未给出本时段时长，未做估算。")

    if period == "中午":
        if meal_inserted:
            unknowns.append("餐饮营业时间、位置与排队情况未核验。")
        else:
            unknowns.append("中午用餐点未找到，餐厅名称与营业时间未知。")

    if fatigue_note:
        unknowns.append("人群上限与体力提示来自可行性闸的规划假设，不是资料结论。")

    unknowns.append("开放时间、步行距离、票价与排队情况未核验。")
    return unknowns


def _explicit_text(period, time_range, group_names, missing_time):
    """显式时段文案：只写资料钟点，缺时间的停留点明说。"""
    if period == "中午":
        # 中午文案由餐饮块生成，调用方会覆盖。
        return ""
    if group_names:
        if time_range:
            text = (
                f"按资料时间 {time_range} 游览" + "、".join(group_names)
                + "；顺序按图谱 NEXT 连接。"
            )
        else:
            text = (
                "游览" + "、".join(group_names)
                + "，按园区指示顺序步行或乘接驳工具；资料未给出具体时间。"
            )
        if missing_time and time_range:
            text += " 部分停留点资料未给出具体时间。"
        return text
    return "自由活动或返程，避开闭园前的高峰；资料未给出具体时间。"


def _make_period(period, group_ids, names_map, chosen, day_ids,
                 feasibility, day_stop_count, is_first, legacy_text=None):
    """构造一个时段的完整 v2 结构。"""
    group_names = [_name(names_map, node_id) for node_id in group_ids]
    times = [chosen[node_id] for node_id in group_ids if node_id in chosen]
    time_range = _span_text(times) if times else None
    time_source = "explicit" if time_range else "absent"
    missing_time = any(node_id not in chosen for node_id in group_ids)

    meal = None
    rest = None
    if period == "中午":
        meal = _meal_block(day_ids, group_ids, names_map, feasibility)
        rest = {
            "inserted": True,
            "note": (
                "中午安排 15–20 分钟休息、补水；"
                "休息点、座位与营业情况未核验。"
            ),
        }

    if period == "中午":
        text = meal["note"]
        if time_range:
            text = f"资料时间 {time_range}。" + text
        else:
            text = f"{TIME_UNKNOWN_TEXT}具体时间。" + text
    elif legacy_text is not None:
        text = legacy_text
        if time_source == "absent":
            text = f"{text}{TIME_UNKNOWN_TEXT}具体时间。"
    else:
        text = _explicit_text(period, time_range, group_names, missing_time)

    if period == "中午":
        title = "用餐与休息"
    elif group_names:
        shown = group_names[:4]
        title = "游览" + "、".join(shown) + ("等" if len(group_names) > 4 else "")
    else:
        title = "自由活动或返程"

    duration_hint = PERIOD_HINTS.get(period)
    duration_source = DURATION_TEMPLATE if duration_hint else DURATION_UNKNOWN
    group_has_rest = any(
        any(word in name for word in MEAL_WORDS + ("休息",))
        for name in group_names
    )
    fatigue_note = _fatigue_note(
        feasibility, day_stop_count, period, len(group_ids), is_first,
        group_has_rest=group_has_rest,
    )
    unknowns = _period_unknowns(
        period, time_source, missing_time, duration_hint,
        bool(meal and meal.get("inserted")), fatigue_note,
    )

    return {
        "period": period,
        "time_range": time_range,
        "time_source": time_source,
        "title": title,
        "text": text,
        "stops": [
            {"node_id": node_id, "name": _name(names_map, node_id)}
            for node_id in group_ids
        ],
        "duration_hint": duration_hint,
        "duration_source": duration_source,
        "meal": meal,
        "rest": rest,
        "fatigue_note": fatigue_note,
        "unknowns": unknowns,
    }


def _build_day_periods(day_ids, names_map, chosen, feasibility):
    """生成一天的时段列表：有显式钟点走显式分组，否则保留旧版三段式。"""
    names = [_name(names_map, node_id) for node_id in day_ids]
    if not chosen:
        morning, noon, afternoon = _legacy_node_groups(day_ids, names)
        legacy = _legacy_period_texts(names)
        groups = [
            ("上午", morning, legacy[0]["text"] if legacy else ""),
            ("中午", noon, legacy[1]["text"] if len(legacy) > 1 else ""),
            ("下午", afternoon, legacy[2]["text"] if len(legacy) > 2 else ""),
        ]
        return [
            _make_period(
                period, group_ids, names_map, chosen, day_ids, feasibility,
                len(day_ids), index == 0, legacy_text=legacy_text,
            )
            for index, (period, group_ids, legacy_text) in enumerate(groups)
        ]

    return [
        _make_period(
            group["period"], group["node_ids"], names_map, chosen, day_ids,
            feasibility, len(day_ids), index == 0,
        )
        for index, group in enumerate(_explicit_groups(day_ids, names, chosen))
    ]


def _plan_note(proposal, day_ids, chosen, feasibility):
    """每日计划说明：分天兜底、时间来源与超限提示。"""
    parts = []
    if proposal.get("day_plan_fallback"):
        parts.append("按节点数均分，不是真实每日体力安排")
    if chosen:
        parts.append("本日时间只采用资料明确写出的钟点；未写出的停留点不补时间。")
    else:
        parts.append("资料未给出具体时间，未用模板钟点代替。")

    caps = _feasibility_caps(feasibility)
    if caps is not None:
        _, max_stops = caps
        if len(day_ids) > max_stops:
            parts.append(
                f"本日 {len(day_ids)} 个停留点超过建议上限 {max_stops} 个，未自动裁剪。"
            )
    return " ".join(parts)


def build_itinerary(route, suggestions=None, scenic_area="", sub_area=None,
                    profiles=None, preferences=None, constraints=None,
                    feasibility=None):
    """从路线结果生成 v2 分时行程；没有节点时返回 None。

    参数
    ----
    route : dict
        ``plan_route()`` 的返回值；只读 ``proposal.node_ids / node_names /
        day_plan / day_plan_fallback / route_truncated`` 与 ``scope``。
    feasibility : dict | None
        ``feasibility.apply_feasibility()`` 的报告；用于人群上限与可行性提示。
        为 None 时不编造体力结论，只在 ``note`` 说明未接入。

    返回结构见模块文档。旧字段 ``text`` / ``duration_hint`` / ``plan_note`` /
    ``note`` 保留；所有新增字段都是纯确定性计算，不调用模型。
    """
    if not route:
        return None
    proposal = route.get("proposal") or {}
    node_ids = list(proposal.get("node_ids") or [])
    if not node_ids:
        return None

    names = proposal.get("node_names") or {}
    scope = route.get("scope") or {}
    notes = []

    # 子园区没有独立 NEXT 连接时，路线可能来自整个景区；只保留该园区
    # 名称能对上的节点，避免把野生动物世界写进“水上乐园一日游”。
    if sub_area and scope.get("requested") and not scope.get("applied"):
        scoped = [node_id for node_id in node_ids if sub_area in _name(names, node_id)]
        if scoped:
            node_ids = scoped
            notes.append(
                f"「{sub_area}」在图谱中没有独立的连续路线，"
                "本行程只使用该园区范围内的地点，不虚构园内路线。"
            )
        else:
            notes.append(
                f"「{sub_area}」在图谱中没有独立路线连接，"
                "请把下面的地点当作园区级建议，具体园内顺序以现场为准。"
            )

    day_plan = proposal.get("day_plan") or []
    if not day_plan:
        day_plan = [{"day": 1, "node_ids": node_ids}]

    catalog = _explicit_time_index()
    days = []
    for item in day_plan:
        day_node_ids = [
            node_id for node_id in (item.get("node_ids") or [])
            if node_id in node_ids
        ]
        if not day_node_ids:
            continue
        chosen = _choose_day_times(day_node_ids, catalog)
        days.append({
            "day": item.get("day") or len(days) + 1,
            "plan_note": _plan_note(proposal, day_node_ids, chosen, feasibility),
            "periods": _build_day_periods(
                day_node_ids, names, chosen, feasibility
            ),
        })

    if not days:
        return None

    if proposal.get("route_truncated"):
        notes.append("路线只保留了能够逐段核验的前半段，后半段需要重新规划或改用官方路线。")
    if proposal.get("day_plan_fallback"):
        notes.append("多日行程的天数按节点数均分，仅用于展示；每日体力、住宿和开放时间需要重新核对。")
    if sub_area and scope.get("requested") and scope.get("applied"):
        notes.append(f"路线已限制在「{sub_area}」范围内。")

    suggestions = suggestions or []
    tips = []
    for item in suggestions[:3]:
        condition = item.get("condition") if isinstance(item, dict) else None
        if not isinstance(condition, dict):
            continue
        text = condition.get("suggestion_text")
        if text:
            tips.append(text)
    if tips:
        notes.append("可参考的园区建议：" + "；".join(tips) + "。")

    if profiles:
        notes.append(
            "同行人：" + "、".join(str(item) for item in profiles)
            + "。图谱没有适龄、身高或体力标签，本行程未做硬性过滤，"
              "请按现场项目要求取舍。"
        )
    if preferences:
        notes.append(
            "你提到的偏好：" + "、".join(str(item) for item in preferences)
            + "。路线顺序主要按图谱 NEXT 连接生成，未保证每项偏好都已满足。"
        )
    if constraints:
        notes.append(
            "你提到的限制：" + "、".join(str(item) for item in constraints)
            + "。分时安排不能替代真实距离、坡度和开放时间核验。"
        )

    # v2：把时间、时长、餐饮与人群提示的口径写清楚，避免被当成资料事实。
    notes.append(
        "时间只显示资料明确写出的钟点；资料未给出的时段写「资料未给出」，"
        "不用模板时间冒充。"
    )
    notes.append(
        "时长区间为固定模板，已标「模板估算」，不是资料给出的实际游玩时长。"
    )
    notes.append(
        "餐饮只依据路线中的餐饮节点；未找到时写「未找到餐饮点，请以现场为准」，"
        "不编造餐厅名。"
    )
    if feasibility is None:
        notes.append("未接入可行性报告，本行程未做人群与体力判断。")
    else:
        warnings = [
            str(item.get("text") or "").strip()
            for item in (feasibility.get("warnings") or [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if warnings:
            notes.append("可行性提示：" + " ".join(warnings[:2]))
        notes.append("人群上限来自可行性闸的规划假设；时长模板同为规划假设，不是资料结论。")

    notes.append("本行程未核验：步行距离 / 开放时间 / 排队 / 票价 / 餐饮营业 / 适龄与体力。")
    notes.append("开放时间、步行距离、餐饮营业情况和适龄性请以园区现场为准。")
    return {"days": days, "note": " ".join(notes)}
