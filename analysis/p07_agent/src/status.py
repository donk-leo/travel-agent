"""状态语义：``run_agent()`` 返回值只允许出现四个状态词。

契约出处
--------
``docs/optimization/PRODUCT_SPEC.md`` §5「状态语义」：

- §5.1 唯一的四个状态词：``verified`` / ``partial`` / ``clarify`` / ``error``；
- §5.2 固定免责句（逐字，``verified`` 与 ``partial`` 必显）；
- §5.4 与旧状态值的迁移关系（迁移前状态词语义收窄、旧 ``reply`` 归入 ``clarify``、
  ``working`` 不作为终态）；
- §5.5 判定禁止项（不得因“看起来顺”升级，状态只由后端判定）；
- §5.6 “连接核验”与“行程可行”分开。

签字记录：HappinessJo 于 2026-11-15 按「建议默认」签字确认四值契约，
见 ``travel-agent-run/optimization/state/G0_GATE.md`` §9（6.1-2「状态语义」）。

职责边界
--------
本模块只做**状态值归一**与**返回结构构造**（``reasons`` / ``what_verified``），
不参与「路线能否判 ``verified``」的业务判定。该判定仍由
``agent._route_problems()`` 按逐段 NEXT 证据、单一来源、未截断/未均分兜底给出；
本模块不从文案或路线“看起来顺”推断状态。
"""

STATUS_VERIFIED = "verified"
STATUS_PARTIAL = "partial"
STATUS_CLARIFY = "clarify"
STATUS_ERROR = "error"

#: 契约允许的四个终态（顺序即 PRODUCT_SPEC.md §5.1 表格顺序）。
STATUS_VALUES = (STATUS_VERIFIED, STATUS_PARTIAL, STATUS_CLARIFY, STATUS_ERROR)
STATUS_SET = frozenset(STATUS_VALUES)

#: §5.2 固定免责句（逐字，不得改写）。
DISCLAIMER = "核验通过只证明连接有据，不证明一天走得完。"

#: clarify 没有行程，明确“未生成路线、未做连接核验”。
CLARIFY_NOTE = "未生成路线，未做连接核验。"

#: error 不交付任何可当作行程的内容，也不把中间结果包装成核验结论。
ERROR_NOTE = "本次处理失败：未交付行程，也未把中间结果作为连接核验结论。"

#: reasons[].code 的契约码表；新增原因必须先扩这里，避免前端收到未知码。
REASON_CODES = frozenset({
    "missing_connection",
    "cross_doc",
    "route_truncated",
    "day_plan_fallback",
    "single_destination",
    "scope_not_applied",
    "unsupported_area",
    "missing_slot",
    "constraint_conflict",
    "model_error",
    "empty_match",
})

# 迁移（PRODUCT_SPEC.md §5.4）：旧值 complete 语义收窄为 verified，旧值 reply 归入 clarify。
LEGACY_STATUS_ALIASES = {"complete": STATUS_VERIFIED, "reply": STATUS_CLARIFY}  # 迁移：旧值→四值


def normalize_status(value):
    """把任意来源的状态值收敛为四值之一（PRODUCT_SPEC.md §5.1 / §5.4）。

    - 四个契约值原样返回；
    - 迁移前状态词按 §5.4 迁移：旧成功态 → ``verified``，旧问候态 → ``clarify``；
    - ``None`` / 缺失 / 其他未定义值（含 ``working``、``success``、``failed``）→ ``error``。
    """
    if isinstance(value, str):
        if value in STATUS_SET:
            return value
        if value in LEGACY_STATUS_ALIASES:
            return LEGACY_STATUS_ALIASES[value]
    return STATUS_ERROR


def is_contract_violation(value):
    """判断状态值是否违反四值契约（§5.4 最后一行）。

    只有 ``None`` / 缺失 / 未定义值算违例；§5.4 明确列出的旧值映射
    （迁移前状态词）属于迁移，不算违例。
    """
    if isinstance(value, str) and (value in STATUS_SET or value in LEGACY_STATUS_ALIASES):
        return False
    return True


def make_reason(code, text):
    """构造一条 ``{"code": 机器码, "text": 人话}`` 原因（§5.1 的“原因清单”）。"""
    if code not in REASON_CODES:
        raise ValueError(f"未定义的原因码：{code!r}")
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("原因文案不能为空。")
    return {"code": code, "text": clean}


def build_reasons(items):
    """把 ``(code, text)`` 序列构造为 ``reasons`` 列表；空序列返回 ``[]``。"""
    return [make_reason(code, text) for code, text in items]


def _doc_ids(segment):
    """取分段来源文档 ID 列表；字符串按单个 ID 处理，避免被逐字符拆开。"""
    value = segment.get("source_doc_ids") or []
    if isinstance(value, str):
        return [value]
    return list(value)


def build_what_verified(status, route=None):
    """回答“这次到底核验了什么”（PRODUCT_SPEC.md §5.6）。

    - ``scope="segment_connectivity"``：本次确实做了连接核验，数字来自
      ``route["validation"]``（``segments`` 的条数与 ``source_doc_ids``），不编造；
    - ``scope="none"``：没有可核验的路线分段（``clarify`` / ``error`` / 纯地点查询），
      此时 ``segments_checked=0``、``source_doc_ids=[]``；
    - ``verified`` 与 ``partial`` 的 ``note`` 逐字包含 §5.2 固定免责句。
    """
    status = normalize_status(status)
    route = route if isinstance(route, dict) else {}
    validation = route.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    segments = validation.get("segments") or []
    segments = [item for item in segments if isinstance(item, dict)]
    has_validation = (
        validation.get("valid") is True
        or validation.get("fully_verified") is True
        or bool(segments)
        or bool(validation.get("missing_connections"))
    )

    if status in (STATUS_VERIFIED, STATUS_PARTIAL) and has_validation:
        scope = "segment_connectivity"
        segments_checked = len(segments)
        source_doc_ids = sorted({
            str(doc_id)
            for segment in segments
            for doc_id in _doc_ids(segment)
            if doc_id
        })
    else:
        scope = "none"
        segments_checked = 0
        source_doc_ids = []

    if status == STATUS_CLARIFY:
        note = CLARIFY_NOTE
    elif status == STATUS_ERROR:
        note = ERROR_NOTE
    elif not route:
        note = DISCLAIMER + "本次为图谱地点查询，未生成路线。"
    elif scope != "segment_connectivity":
        note = DISCLAIMER + "本次没有可核验的路线分段。"
    else:
        note = DISCLAIMER

    return {
        "scope": scope,
        "segments_checked": segments_checked,
        "source_doc_ids": source_doc_ids,
        "note": note,
    }
