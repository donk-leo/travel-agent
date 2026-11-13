"""把图谱路线整理成可读的分时行程。

实验要求回答能用自然语言描述“上午/中午/下午”的安排，而不是只给一串
节点箭头。这里不调用模型：节点顺序来自已经核验过的路线，分时只做展示，
避免再引入不可追溯的编造内容。开放时间、步行距离、餐厅营业情况等仍写入
提示，提醒用户以现场为准。
"""


MEAL_WORDS = ("餐厅", "餐", "美食", "咖啡", "小吃", "食堂")
PERIOD_HINTS = {
    "上午": "建议预留 2–3 小时",
    "中午": "约 1–1.5 小时",
    "下午": "建议预留 2–3 小时",
}


def _name(name_map, node_id):
    return name_map.get(node_id) or node_id.split("|")[-1]


def _pick_lunch(names):
    """挑一个适合中午停留的节点；没有餐饮节点时返回 None。"""
    for index, name in enumerate(names):
        if 0 < index < len(names) - 1 and any(word in name for word in MEAL_WORDS):
            return index
    return None


def _periods_for_day(names):
    """把一天的节点拆成上午/中午/下午；节点太少时也给出完整时段。"""
    names = [name for name in names if name]
    if not names:
        return []

    if len(names) == 1:
        name = names[0]
        return [
            {"period": "上午", "duration_hint": PERIOD_HINTS["上午"],
             "text": f"前往{name}，办理入园/开始游览，先熟悉主要区域。"},
            {"period": "中午", "duration_hint": PERIOD_HINTS["中午"],
             "text": "在园区内餐厅或休息区用餐、补水，避开正午高温。"},
            {"period": "下午", "duration_hint": PERIOD_HINTS["下午"],
             "text": f"继续体验{name}的主要项目，按体力安排返程。"},
        ]

    lunch_index = _pick_lunch(names)
    if lunch_index is None:
        morning_count = max(1, min(len(names) - 1, round(len(names) * 0.45)))
        morning = names[:morning_count]
        afternoon = names[morning_count:]
        lunch_text = (
            f"在{morning[-1]}附近休息；用餐请选择园区内营业的餐厅，"
            "具体位置和营业时间以现场为准。"
        )
    else:
        morning = names[:lunch_index]
        lunch = names[lunch_index]
        afternoon = names[lunch_index + 1:]
        lunch_text = f"在{lunch}用餐、休息；具体营业时间以现场为准。"

    periods = []
    if morning:
        periods.append({
            "period": "上午",
            "duration_hint": PERIOD_HINTS["上午"],
            "text": "游览" + "、".join(morning) + "，按园区指示顺序步行或乘接驳工具。",
        })
    else:
        periods.append({
            "period": "上午",
            "duration_hint": PERIOD_HINTS["上午"],
            "text": "从入口进入园区，先游览核心区域。",
        })
    periods.append({
        "period": "中午",
        "duration_hint": PERIOD_HINTS["中午"],
        "text": lunch_text,
    })
    if afternoon:
        periods.append({
            "period": "下午",
            "duration_hint": PERIOD_HINTS["下午"],
            "text": "继续游览" + "、".join(afternoon) + "，预留返程和休息时间。",
        })
    else:
        periods.append({
            "period": "下午",
            "duration_hint": PERIOD_HINTS["下午"],
            "text": "自由活动或返程，避开闭园前的高峰。",
        })
    return periods


def build_itinerary(route, suggestions=None, scenic_area="", sub_area=None,
                    profiles=None, preferences=None, constraints=None):
    """从路线结果生成分时行程；没有节点时返回 None。"""
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

    days = []
    for item in day_plan:
        day_node_ids = [node_id for node_id in (item.get("node_ids") or []) if node_id in node_ids]
        if not day_node_ids:
            continue
        day_names = [_name(names, node_id) for node_id in day_node_ids]
        days.append({
            "day": item.get("day") or len(days) + 1,
            "periods": _periods_for_day(day_names),
            "plan_note": "按节点数均分，不是真实每日体力安排"
                         if proposal.get("day_plan_fallback") else "",
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

    notes.append("开放时间、步行距离、餐饮营业情况和适龄性请以园区现场为准。")
    return {"days": days, "note": " ".join(notes)}
