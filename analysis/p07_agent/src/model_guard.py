"""模型调用加固的共用小工具（T2.6）。

职责只有三件，避免改业务判定：
- 统一的"模型调用可能抛出的异常"元组；
- 解析 Ollama ``/api/chat`` 响应里的 JSON 内容；
- 识别并遮蔽模型输出里泄露的系统提示原文。

本模块不使用第三方依赖，也不发起网络请求。
"""

import json
import urllib.error


#: 模型调用/解析失败时允许回退的异常范围（标准库异常，无新增依赖）。
MODEL_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    OSError,
    json.JSONDecodeError,
    ValueError,
    KeyError,
    TypeError,
)

#: 各 SYSTEM_PROMPT 的特征句；命中即说明模型把内部提示原文写进了输出。
PROMPT_SIGNATURES = (
    "你是旅游规划系统的需求解析器",
    "你是旅游 Agent 的决策器",
    "你是旅游路线规划助手",
    "你是旅游 Agent 的工具选择器",
    "你是旅游需求检查助手",
    "你是旅游方案的约束检查助手",
    "只返回符合给定 JSON Schema 的结果",
)

#: 检测到泄露时的确定性替代文案；不谎称"没有系统提示"，只是不展示内部提示。
LEAK_REPLACEMENT = "模型输出包含不应显示的内部说明，已隐藏。"


def contains_system_prompt_leak(text):
    """判断文本是否包含任一系统提示的特征句。"""
    if not isinstance(text, str) or not text:
        return False
    return any(signature in text for signature in PROMPT_SIGNATURES)


def redact_system_prompt_leak(text):
    """遮蔽模型输出中的系统提示原文；非字符串原样返回。"""
    if not isinstance(text, str):
        return text
    if contains_system_prompt_leak(text):
        return LEAK_REPLACEMENT
    return text


def parse_chat_content(response_json):
    """从 Ollama 响应中取出合法的 JSON 对象 content。

    结构不对（非 dict、缺 message/content、content 不是 JSON 对象）时抛
    ``ValueError``，由调用方的回退逻辑处理。
    """
    if not isinstance(response_json, dict):
        raise ValueError("模型响应不是 JSON 对象。")
    message = response_json.get("message")
    if not isinstance(message, dict):
        raise ValueError("模型响应缺少 message 对象。")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型响应内容为空。")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的 JSON 不是对象。")
    return parsed


def clean_text(value, default=""):
    """把模型字段收敛为去首尾空白的字符串，并遮蔽系统提示泄露。"""
    if not isinstance(value, str):
        return default
    return redact_system_prompt_leak(value.strip())


def clean_str_list(values):
    """校验"字符串列表"并去空、去重（保持顺序）；类型不对抛 ValueError。"""
    if not isinstance(values, list):
        raise ValueError("字段必须是字符串列表。")
    cleaned = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("列表元素必须是字符串。")
        text = clean_text(value)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned
