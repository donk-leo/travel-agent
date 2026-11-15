"""T2.2 / T2.2b 可行性闸：判断人群点数上限、按上限裁剪停留点、用餐与时长预算。

契约与边界
----------
- 判定口径：``PRODUCT_SPEC.md`` §7.4（默认 ≤8 个停留点/天；同行人含 <6 岁儿童
  或 ≥70 岁老人时 ≤6 个/天；Q4「建议默认」采纳）、§7.2（时长只能来自资料原文、
  固定模板或明确的未知，单日不得给「合计 X 小时」）、§7.3（图谱没有餐饮节点时
  不得编餐厅名）、§5.6（连接核验与行程可行分开，本模块不新增状态词）。
- 指标口径：``03_EVAL_SPEC.md`` §3 ``stop_cap_ok`` = ``node_count <= max_stops``，
  因此 ``stop_count`` / ``day_counts`` 一律按路线节点数计（与 runner 的
  ``node_count`` 一致），不按交通/设施类节点折算。
- 只读：不修改 ``proposal.node_ids``、不增删连接、不改 ``day_plan``；裁剪方案只
  放在返回值的 ``crop`` 里，由 ``agent._apply_feasibility_gate`` 决定是否写回。
- 裁剪（T2.2b）：只在单日点数超过人群上限时触发，**只删点、不改顺序、不新增点**，
  每天从尾部删、每天至少留 1 个点；裁剪后必须用 ``tools.validate_route`` 对
  同一批 candidates 重做逐段核验，每段仍有同源 NEXT 才算可交付（``applied``）。
  不能核验（缺连接 / 跨来源文档 / 多日没有合法分天方案）就**不交付裁剪方案**，
  只把原计划降 ``partial`` 并写清哪一段失去证据。
- 不产出距离、坐标、票价、开放时间；资料不足时写「未核验 / 未知」，不写成事实。
- ``warnings[0]`` 恒为导致 ``status_override="partial"`` 的那条原因
  （``agent.py`` 直接复用它作为 reason，不需要再解析文案）。

返回结构（``apply_feasibility``）
---------------------------------
``{status_override, warnings, uncertainties, caps, meal, duration,
stop_count, day_counts, crop}``。``crop`` 为
``{applied, node_ids, removed, day_counts_before, day_counts_after, note}``：
未裁剪时 ``applied=False``、``node_ids=None``、``removed=[]``；裁剪生效时
``stop_count`` / ``day_counts`` / ``meal`` / ``duration`` 描述**裁剪后要交付的
计划**，原计划点数见 ``crop.day_counts_before``。
"""

import csv
import re
from pathlib import Path

from tools import validate_route


#: P6 节点分类表（只读）：用于餐饮判断，不修改、不落盘、不写回图谱。
CLASSIFICATION_CSV = (
    Path(__file__).resolve().parents[3]
    / "analysis" / "p06_graph" / "outputs" / "node_classification.csv"
)

#: 用餐时段（资料没有营业时间，只能标注这是需要确认的时段）。
MEAL_SLOT = "11:30–13:30"

#: PRODUCT_SPEC §7.4 的点数上限（成人 / 含老人或 0–6 岁儿童）。
MAX_STOPS_ADULT = 8
MAX_STOPS_FAMILY = 6

#: 时长模板（与 itinerary.PERIOD_HINTS 同一套「模板估算」口径，不是资料原文时长）。
MINUTES_PER_STOP = 60
MINUTES_PER_DAY_OVERHEAD = 30
MINUTES_MEAL = 45
DAY_BUDGET_MINUTES = 8 * 60

#: 复用 ``status.REASON_CODES`` 既有码，不新增码（见 status.py 码表）。
WARNING_CODE = "constraint_conflict"

SENIOR_WORDS = (
    "老人", "长辈", "父母", "爸妈", "爷爷", "奶奶", "外公", "外婆", "老年", "银发",
)
CHILD_WORDS = (
    "孩子", "儿童", "小朋友", "宝宝", "幼儿", "亲子", "带娃", "遛娃",
    "婴儿", "幼童", "学龄前",
)
MEAL_WORDS = ("餐厅", "美食", "咖啡", "小吃", "食堂", "餐")
NON_MEAL_WORDS = ("酒店", "别墅", "客栈", "旅舍", "纪念品", "商店")

AGE_RE = re.compile(r"(\d{1,3})\s*(?:周)?岁")
AGE_RANGE_RE = re.compile(r"(\d{1,2})\s*[-–—~～至到]\s*(\d{1,2})\s*(?:周)?岁")
SENIOR_AGE = 70
CHILD_MAX_AGE = 6


def _clean_list(values):
    """把意图里的列表整理成去空白的字符串列表；非列表按空处理。"""
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _coerce_days(value):
    """正整数天数；缺失或非法返回 None。"""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days >= 1 else None


def _persona_from(profiles, constraints):
    """按同行人关键词与年龄推断上限人群，返回 ``(persona 文案, max_stops)``。

    只做确定性关键词/年龄匹配，不做推断式判断；图谱没有适龄与体力标签，
    因此识别不到时按成人上限，并在 uncertainties 里说明这是假设。
    """
    text = " ".join(_clean_list(profiles) + _clean_list(constraints))
    senior = any(word in text for word in SENIOR_WORDS)
    child = any(word in text for word in CHILD_WORDS)

    for low, high in AGE_RANGE_RE.findall(text):
        if int(high) <= CHILD_MAX_AGE:
            child = True
        if int(low) >= SENIOR_AGE:
            senior = True
    for value in AGE_RE.findall(text):
        age = int(value)
        if age <= CHILD_MAX_AGE:
            child = True
        if age >= SENIOR_AGE:
            senior = True

    if senior and child:
        return "老人 + 0–6 岁儿童", MAX_STOPS_FAMILY
    if senior:
        return "老人", MAX_STOPS_FAMILY
    if child:
        return "0–6 岁儿童", MAX_STOPS_FAMILY
    return "成人", MAX_STOPS_ADULT


def _name(node_names, node_id):
    """节点显示名：优先用路线里的 node_names，其次取节点 ID 尾段。"""
    name = (node_names or {}).get(node_id)
    if name:
        return str(name)
    return str(node_id).split("|")[-1] or str(node_id)


def _valid_day_plan(node_ids, day_plan, days):
    """校验路线自带的分天方案；合法时返回每天节点 ID 列表，否则 None。

    与 ``route_planner._normalize_day_plan`` 同一口径：每天非空、顺序拼起来
    恰好等于 ``node_ids``、天数与请求一致。这里只用于计数，不改路线。
    """
    if not isinstance(day_plan, list) or not day_plan:
        return None
    if days is not None and len(day_plan) != days:
        return None
    groups = []
    flattened = []
    for item in day_plan:
        if not isinstance(item, dict):
            return None
        day = item.get("day")
        ids = item.get("node_ids")
        if (not isinstance(day, int) or isinstance(day, bool)
                or not isinstance(ids, list) or not ids
                or not all(isinstance(node_id, str) for node_id in ids)):
            return None
        groups.append(ids)
        flattened.extend(ids)
    if flattened != node_ids:
        return None
    return groups


def _day_counts(node_ids, day_plan, days):
    """返回 ``(每天节点数, 是否按节点数均分兜底)``。

    多日且没有合法 day_plan 时按节点数均分，只用于判断单日上限；
    这个分组只是计数假设，不代表真实每日体力安排。
    """
    groups = _valid_day_plan(node_ids, day_plan, days)
    if groups is not None:
        return [len(group) for group in groups], False
    if not node_ids:
        return [], False
    if not days or days <= 1:
        return [len(node_ids)], False
    group_count = min(days, len(node_ids))
    base, extra = divmod(len(node_ids), group_count)
    counts = [base + (1 if index < extra else 0) for index in range(group_count)]
    counts.extend([0] * (days - group_count))
    return counts, True


def _day_plan_groups(node_ids, proposal, days):
    """按天分组，供裁剪使用；无法确定每天有哪些点时返回 ``None``。

    单日路线总可以按整条路线处理；多日只在 ``day_plan`` 恰好覆盖 ``node_ids``
    时才按天裁剪（``_valid_day_plan`` 的口径），否则仍用均分兜底计数、不裁剪。
    """
    groups = _valid_day_plan(node_ids, proposal.get("day_plan"), days)
    if groups is not None:
        return groups
    if not days or days <= 1:
        return [node_ids]
    return None


def _crop_groups(groups, max_stops, node_names):
    """每天从尾部删点；返回 ``(裁剪后 node_ids, 每天保留的列表, 被裁点列表)``。

    只删不改序：每天保留原顺序的前缀，因此同一天内相邻段仍是原来的 NEXT；
    跨天衔接若被删出新的相邻对，由 ``crop_validation`` 重新核验。
    """
    kept_groups = []
    removed = []
    keep = max(1, max_stops)
    for day_index, group in enumerate(groups, 1):
        if len(group) <= max_stops:
            kept_groups.append(list(group))
            continue
        kept_groups.append(list(group[:keep]))
        for node_id in group[keep:]:
            removed.append({
                "node_id": node_id,
                "name": _name(node_names, node_id),
                "day": day_index,
            })
    cropped = [node_id for group in kept_groups for node_id in group]
    return cropped, kept_groups, removed


def _segment_text(node_names, from_id, to_id):
    return f"「{_name(node_names, from_id)} → {_name(node_names, to_id)}」"


def crop_validation(route, node_ids, candidates=None):
    """对裁剪后的节点序列重做逐段核验；返回 ``(validation, basis)``。

    - ``candidates`` 可用（真实路线走这条）：直接调用 ``tools.validate_route``，
      ``basis="validate_route"``，与未裁剪时用的是同一批候选连接；
    - 不可用时：只接受「裁剪后每个相邻对都来自原路线的相邻对」的裁剪。这种裁剪
      不产生新分段，每条保留分段的来源证据与原来完全一致，因此按原
      ``validation.segments`` 取对应子集推断，``basis="verified_subsequence"``；
    - 其余情况（原路线未核验通过、多日跨天产生新段、证据条数对不上）返回
      ``(None, 人话原因)``，调用方不得把计划判为已核验。
    """
    node_ids = [node_id for node_id in (node_ids or []) if isinstance(node_id, str)]
    if len(node_ids) < 2:
        return None, "裁剪后不足 2 个停留点，无法逐段核验"

    if candidates is not None:
        return validate_route(node_ids, candidates), "validate_route"

    validation = {}
    if isinstance(route, dict) and isinstance(route.get("validation"), dict):
        validation = route["validation"]
    proposal = route.get("proposal") if isinstance(route, dict) else None
    original = []
    if isinstance(proposal, dict):
        original = [nid for nid in (proposal.get("node_ids") or [])
                    if isinstance(nid, str)]
    if validation.get("fully_verified") is not True:
        return None, ("没有可用的图谱候选连接，且原路线的逐段核验未完全通过，"
                      "无法证明裁剪后每段仍有同源 NEXT")

    pairs = list(zip(original, original[1:]))
    position = {}
    for index, pair in enumerate(pairs):
        position.setdefault(pair, index)
    cropped_pairs = list(zip(node_ids, node_ids[1:]))
    if any(pair not in position for pair in cropped_pairs):
        return None, ("没有可用的图谱候选连接，且裁剪会在跨天衔接处产生新的路段，"
                      "无法证明这一段有同源 NEXT")

    segments = [segment for segment in (validation.get("segments") or [])
                if isinstance(segment, dict)]
    if not segments:
        # 有些调用方只给结论、不给逐段明细；裁剪不新增分段，沿用原结论。
        kept_segments = []
    elif len(segments) == len(pairs):
        kept_segments = [segments[position[pair]] for pair in cropped_pairs]
    else:
        return None, ("原路线的分段证据条数与节点数对不上，"
                      "无法按子序列证明裁剪后仍逐段可核验")

    return {
        "valid": True,
        "fully_verified": True,
        "segments": kept_segments,
        "missing_connections": [],
        "cross_doc_transitions": 0,
        "message": "检查完成（裁剪后各段沿用原路线的同源 NEXT 证据）",
    }, "verified_subsequence"


def _crop_failure_reason(validation, basis, node_names):
    """把重核验结果翻译成「哪一段失去证据」的人话原因。"""
    if validation is None:
        return str(basis or "裁剪后无法核验")
    missing = validation.get("missing_connections") or []
    if missing:
        segment = missing[0]
        return (f"{_segment_text(node_names, segment.get('from_node_id'), segment.get('to_node_id'))}"
                "缺少同源 NEXT 证据")
    cross_doc = validation.get("cross_doc_transitions") or 0
    if cross_doc:
        return f"有 {cross_doc} 处跨来源文档跳转，无法证明属于同一条连续路线"
    return "裁剪后的路线未通过逐段核验"


def _day_count_text(counts, max_stops=None):
    """把每天点数写成「第 1 天 12 个」；给定上限时只列超限的天。"""
    return "、".join(
        f"第 {index} 天 {count} 个"
        for index, count in enumerate(counts, 1)
        if max_stops is None or count > max_stops
    )


def _crop_note(persona, max_stops, before_counts, after_counts, removed):
    """裁剪说明：裁了几个点、为什么裁、被裁点如何处理。"""
    day_text = "、".join(
        f"第 {index} 天 {before} → {after}"
        for index, (before, after) in enumerate(zip(before_counts, after_counts), 1)
        if before != after
    )
    names = "、".join(item["name"] for item in removed)
    return (
        f"按「{persona}」单日上限 {max_stops} 个裁剪：{day_text}；"
        f"共裁掉 {len(removed)} 个停留点（{names}），被裁点不进入本次交付计划；"
        "只从每天尾部删点、不改剩余顺序，裁剪后逐段重核验仍为同源 NEXT。"
    )


def _crop_uncertainty(persona, max_stops, before_counts, after_counts, removed):
    """裁剪后的假设说明：上限是规划假设，被裁点已明示。"""
    names = "、".join(item["name"] for item in removed)
    return (
        f"原计划{_day_count_text(before_counts, max_stops)}，"
        f"超过「{persona}」单日上限 {max_stops} 个；"
        f"已按上限从每天尾部裁剪到{_day_count_text(after_counts)}（被裁：{names}），"
        "被裁点不进入本次交付计划；"
        "上限按 PRODUCT_SPEC §7.4 建议默认（Q4 待签字）执行。"
    )


def _cap_warning_text(persona, max_stops, cap_hits, crop_failure=None):
    """超限警告；裁剪失败时补上「哪一段失去证据、所以不交付裁剪方案」。"""
    day_number, count = cap_hits[0]
    extra = (f"；另有 {len(cap_hits) - 1} 天也超过上限"
             if len(cap_hits) > 1 else "")
    tail = (
        f"按上限裁剪后{crop_failure}，未交付裁剪方案；请减少停留点或增加天数。"
        if crop_failure else
        "图谱没有距离、排队与开放时间数据，未自动裁剪，请减少停留点或增加天数。"
    )
    return (
        f"单日停留点上限为 {max_stops} 个（{persona}），第 {day_number} 天排了 "
        f"{count} 个，超过 {count - max_stops} 个{extra}；{tail}"
    )


def _load_node_classes(path=None):
    """读取 P6 节点分类表；文件缺失或不可读时返回 None（退回名称关键词）。"""
    path = Path(path) if path is not None else CLASSIFICATION_CSV
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return {
                row["node_id"]: row["node_class"]
                for row in csv.DictReader(handle)
                if row.get("node_id")
            }
    except (OSError, KeyError, csv.Error):
        return None


def _meal_nodes(node_ids, node_names):
    """找出路线里的餐饮节点，返回 ``(名称列表, 判断依据)``。

    优先用 P6 分类表（``node_class == "food"``，酒店/商店不会被当成餐厅）；
    分类表不可用时退回名称关键词，并标注判断依据可能误判。
    """
    classes = _load_node_classes()
    if classes is not None:
        names = [
            _name(node_names, node_id)
            for node_id in node_ids if classes.get(node_id) == "food"
        ]
        return names, "classification"
    names = []
    for node_id in node_ids:
        name = _name(node_names, node_id)
        if (any(word in name for word in MEAL_WORDS)
                and not any(word in name for word in NON_MEAL_WORDS)):
            names.append(name)
    return names, "name_keywords"


def _empty_report(persona, max_stops):
    """没有可评估节点时的空报告；不产生任何上限或时长结论。"""
    return {
        "status_override": None,
        "warnings": [],
        "uncertainties": ["没有可评估的路线节点，未做点数上限、用餐与时长判断。"],
        "caps": {"max_stops": max_stops, "persona": persona},
        "meal": {
            "inserted": False,
            "slot": MEAL_SLOT,
            "note": "没有路线节点，未做用餐判断。",
        },
        "duration": {"total_min": 0, "over_budget": False, "assumptions": []},
        "stop_count": 0,
        "day_counts": [],
        "crop": {
            "applied": False,
            "node_ids": None,
            "removed": [],
            "day_counts_before": [],
            "day_counts_after": [],
            "note": "没有可裁剪的路线节点，未做裁剪。",
        },
    }


def apply_feasibility(route, profiles=None, constraints=None, days=None,
                      candidates=None):
    """评估一条已生成路线，返回可行性判断与裁剪方案（只读，不修改路线）。

    参数
    ----
    route : dict | None
        ``plan_route()`` 的返回值；只用 ``proposal.node_ids / node_names /
        day_plan / duration_days`` 与 ``validation`` / ``candidates``。
    profiles / constraints : list[str] | None
        意图解析出的同行人与限制；用于推断人群点数上限。
    days : int | str | None
        请求天数；缺失时退回 ``proposal.duration_days``，再退回 1 天。
    candidates : list[dict] | None
        图谱候选连接（``get_route_candidates`` 的口径）。裁剪后用它重做逐段
        核验；为 ``None`` 时退回 ``route["candidates"]``，两者都没有则只接受
        「不产生新分段」的裁剪（见 ``crop_validation``）。

    返回
    ----
    dict
        - ``status_override``：``None`` 或 ``"partial"``（单日点数超上限且**无法**
          交付裁剪方案时才降级；本项目不产生 ``error`` / ``verified``，状态判定
          仍归 agent 与 status.py）；
        - ``warnings``：``[{code, text}]``，code 取自 ``status.REASON_CODES``；
          ``warnings[0]`` 是导致 partial 的那条；
        - ``uncertainties``：假设与缺失（人群推断、均分兜底、裁剪、餐饮未知、时长模板）；
        - ``caps``：``{max_stops, persona}``；
        - ``meal``：``{inserted, slot, note}``；``inserted=False`` 表示图谱没有
          餐饮节点或未覆盖午间时段，此时只写「未知」，不编餐厅名；
        - ``duration``：``{total_min, over_budget, assumptions}``；``total_min``
          是模板预算合计（多日相加），不是实测耗时，页面不得写成「合计 X 小时」；
        - ``stop_count``：交付计划的节点数（裁剪生效时是裁剪后的数量，
          ``stop_cap_ok`` 口径）；
        - ``day_counts``：交付计划每天节点数，按 day_plan 或节点数均分得出；
        - ``crop``：裁剪方案，见模块文档；``applied=False`` 时 ``node_ids`` 为 ``None``。
    """
    proposal = {}
    if isinstance(route, dict) and isinstance(route.get("proposal"), dict):
        proposal = route["proposal"]
    node_ids = [
        node_id for node_id in (proposal.get("node_ids") or [])
        if isinstance(node_id, str)
    ]
    node_names = proposal.get("node_names") if isinstance(proposal.get("node_names"), dict) else {}
    profiles = _clean_list(profiles)
    constraints = _clean_list(constraints)
    persona, max_stops = _persona_from(profiles, constraints)
    caps = {"max_stops": max_stops, "persona": persona}

    if not node_ids:
        return _empty_report(persona, max_stops)

    effective_days = _coerce_days(days) or _coerce_days(proposal.get("duration_days"))
    day_counts, split_assumed = _day_counts(
        node_ids, proposal.get("day_plan"), effective_days)

    warnings = []
    uncertainties = []

    # 1) 单日点数上限：超过就尝试按上限裁剪停留点（T2.2b）。
    cap_hits = [
        (index + 1, count)
        for index, count in enumerate(day_counts) if count > max_stops
    ]
    crop = {
        "applied": False,
        "node_ids": None,
        "removed": [],
        "day_counts_before": list(day_counts),
        "day_counts_after": list(day_counts),
        "note": "未超过人群单日停留点上限，未裁剪。",
    }
    delivered_ids = node_ids
    delivered_counts = day_counts

    if cap_hits:
        if candidates is None and isinstance(route, dict):
            candidates = route.get("candidates")
        groups = _day_plan_groups(node_ids, proposal, effective_days)
        crop_failure = ""
        if groups is None:
            crop["note"] = ("多日行程没有可用的分天方案，无法按天裁剪；"
                            "原计划仍超过人群单日上限。")
        else:
            cropped_ids, kept_groups, removed = _crop_groups(
                groups, max_stops, node_names)
            validation, basis = crop_validation(route, cropped_ids, candidates)
            if validation is not None and validation.get("fully_verified") is True:
                crop.update({
                    "applied": True,
                    "node_ids": cropped_ids,
                    "removed": removed,
                    "day_counts_after": [len(group) for group in kept_groups],
                    "note": _crop_note(persona, max_stops, day_counts,
                                       [len(group) for group in kept_groups], removed),
                })
                delivered_ids = cropped_ids
                delivered_counts = crop["day_counts_after"]
                uncertainties.append(_crop_uncertainty(
                    persona, max_stops, day_counts, delivered_counts, removed))
            else:
                crop_failure = _crop_failure_reason(validation, basis, node_names)
                crop["note"] = (
                    f"按「{persona}」单日上限 {max_stops} 个尝试裁剪后无法保证逐段"
                    f"同源 NEXT：{crop_failure}；未交付裁剪方案，原计划仍超过上限。"
                )
        if not crop["applied"]:
            warnings.append({"code": WARNING_CODE, "text": _cap_warning_text(
                persona, max_stops, cap_hits, crop_failure or None)})
            over_days_text = "、".join(
                f"第 {day} 天 {count} 个" for day, count in cap_hits)
            if crop_failure:
                uncertainties.append(
                    f"{over_days_text}，超过「{persona}」单日上限 {max_stops} 个；"
                    f"{crop_failure}，未交付裁剪方案，请减少停留点或增加天数；"
                    "上限按 PRODUCT_SPEC §7.4 建议默认（Q4 待签字）执行。"
                )
            else:
                uncertainties.append(
                    f"{over_days_text}，超过「{persona}」单日上限 {max_stops} 个；"
                    "上限按 PRODUCT_SPEC §7.4 建议默认（Q4 待签字）执行，"
                    "是否删减或改天数需用户确认。"
                )

    # 2) 人群上限本身是推断值，必须标成假设（图谱没有适龄/体力标签）。
    if persona == "成人":
        uncertainties.append(
            f"未识别到老人或 0–6 岁儿童，按成人单日上限 {max_stops} 个判断；"
            "图谱没有体力标签，上限只是规划假设。"
        )
    else:
        uncertainties.append(
            f"同行人识别为「{persona}」，按单日上限 {max_stops} 个判断；"
            "图谱没有适龄、体力或身高标签，未做硬性过滤。"
        )

    # 3) 用餐：只依据图谱餐饮节点，不编餐厅名；没有就写未知。
    window_covered = any(count >= 2 for count in delivered_counts)
    food_names, meal_source = _meal_nodes(delivered_ids, node_names)
    if window_covered and food_names:
        meal = {
            "inserted": True,
            "slot": MEAL_SLOT,
            "note": (
                f"路线中有图谱标注的餐饮节点「{food_names[0]}」，可用于 {MEAL_SLOT} 用餐、"
                "休息；营业时间、位置与排队未核验，未保证该时段营业。"
            ),
        }
        uncertainties.append(
            f"餐饮节点「{food_names[0]}」的营业时间与排队情况未核验。"
        )
    elif window_covered:
        meal = {
            "inserted": False,
            "slot": MEAL_SLOT,
            "note": (
                f"{MEAL_SLOT} 用餐时段已覆盖，但路线中没有图谱标注的餐饮节点；"
                "餐厅名称、位置与营业时间未知，请在园区内选择营业餐厅。"
            ),
        }
        uncertainties.append(
            f"{MEAL_SLOT} 用餐点图谱未给出（没有餐饮节点），"
            "餐厅名称、位置和营业时间需现场确认。"
        )
    else:
        meal = {
            "inserted": False,
            "slot": MEAL_SLOT,
            "note": (
                f"行程每天只有 1 个停留点，未覆盖 {MEAL_SLOT} 用餐时段，未做餐饮判断。"
            ),
        }
        uncertainties.append(
            f"行程未覆盖 {MEAL_SLOT} 用餐时段，未做餐饮判断。"
        )
    if meal_source == "name_keywords":
        uncertainties.append(
            "餐饮分类表不可用，餐饮判断只按名称关键词，可能漏判或误判。"
        )

    # 4) 时长：固定模板上限预算，只作可行性判断，不当事实或「合计 X 小时」展示。
    assumptions = [
        f"每停留点按 {MINUTES_PER_STOP} 分钟模板估算，属规划假设，不是资料给出的游玩时长。",
        f"每天另计 {MINUTES_PER_DAY_OVERHEAD} 分钟入园/安检/园区接驳模板开销；"
        "不含排队、交通与休息时间。",
    ]
    if meal["inserted"]:
        assumptions.append(
            f"餐饮节点按 {MINUTES_MEAL} 分钟用餐模板计入；营业时间与位置未核验。"
        )
    assumptions.append(
        "总时长只用于可行性判断；按 PRODUCT_SPEC §7.2，不得把单日总时长写成"
        "「合计 X 小时」展示。"
    )
    assumptions.append(
        f"{DAY_BUDGET_MINUTES // 60} 小时是可行性闸的预算阈值"
        f"（{DAY_BUDGET_MINUTES} 分钟），不是资料给出的开放时长。"
    )

    total_min = 0
    over_days = []
    uncertainties.append(
        f"行程总时长按固定模板估算（每点 {MINUTES_PER_STOP} 分钟 + 每天 "
        f"{MINUTES_PER_DAY_OVERHEAD} 分钟入园开销），属规划假设，不是资料给出的时长。"
    )
    for index, count in enumerate(delivered_counts):
        if count <= 0:
            continue
        minutes = count * MINUTES_PER_STOP + MINUTES_PER_DAY_OVERHEAD
        if meal["inserted"] and count >= 2:
            minutes += MINUTES_MEAL
        total_min += minutes
        if minutes > DAY_BUDGET_MINUTES:
            over_days.append((index + 1, minutes))
    if over_days:
        day_number, minutes = over_days[0]
        warnings.append({"code": WARNING_CODE, "text": (
            f"按固定模板估算，第 {day_number} 天约 {minutes} 分钟，超过 8 小时预算；"
            "估算不含排队、交通与休息，不能证明一天走得完。"
        )})
        uncertainties.append(
            "总时长按固定模板估算超过 8 小时预算；模板假设不含排队与交通，"
            "不代表实际耗时，不能当作「合计 X 小时」展示。"
        )

    # 5) 多日没有合法 day_plan 时，计数用的是均分兜底，必须说明。
    if split_assumed:
        uncertainties.append(
            "多日没有可用的分天方案，每日点数按节点数均分计数；这只用于判断上限，"
            "不代表真实每日体力按排。"
        )

    return {
        "status_override": "partial" if (cap_hits and not crop["applied"]) else None,
        "warnings": warnings,
        "uncertainties": uncertainties,
        "caps": caps,
        "meal": meal,
        "duration": {
            "total_min": total_min,
            "over_budget": bool(over_days),
            "assumptions": assumptions,
        },
        "stop_count": len(delivered_ids),
        "day_counts": delivered_counts,
        "crop": crop,
    }
