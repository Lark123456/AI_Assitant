"""事件文本与证据回查：空白归一化、tool_result 的结构化事实还原。"""

import re
from typing import Any

from app.memory.schemas import TOOL_EVIDENCE_TOOLS


def normalize_ws(text: str) -> str:
    """忽略空白差异：去掉全部空白字符后比较。"""
    return re.sub(r"\s+", "", text or "")


def quote_matches(quote: str, text: str) -> bool:
    normalized_quote = normalize_ws(quote)
    return bool(normalized_quote) and normalized_quote in normalize_ws(text)


def render_tool_fact(tool: str, arguments: dict, result_data: dict | None) -> str | None:
    """把成功工具调用的已验证参数还原为确定性文本（禁止使用 payload.message）。"""
    if tool not in TOOL_EVIDENCE_TOOLS:
        return None
    data = result_data or {}
    if tool == "schedule_block":
        title = arguments.get("title") or data.get("title") or "（未命名）"
        ends = arguments.get("ends_at")
        if ends is None and arguments.get("duration_min") is not None:
            ends = f"时长 {arguments['duration_min']} 分钟"
        return (
            f"工具 schedule_block 已成功执行；标题：{title}；"
            f"开始：{arguments.get('starts_at', '')}；结束：{ends or ''}"
        )
    if tool == "update_block_status":
        return (
            "工具 update_block_status 已成功执行；"
            f"块：{arguments.get('block_id', data.get('block_id', ''))}；"
            f"状态：{arguments.get('status', data.get('status', ''))}"
        )
    if tool == "reschedule_block":
        return (
            "工具 reschedule_block 已成功执行；"
            f"块：{arguments.get('block_id', '')}；"
            f"开始：{arguments.get('starts_at', '')}；结束：{arguments.get('ends_at', '')}"
        )
    if tool == "set_notif_prefs":
        parts = [
            f"{key}={value}"
            for key, value in sorted(arguments.items())
            if value is not None
        ]
        return "工具 set_notif_prefs 已成功执行；" + "；".join(parts)
    return None


def parse_tool_name_from_result_key(key: str | None) -> str | None:
    """tool-result:{inbound_event_id}:{tool}:{call_index} → tool。"""
    if not key or not key.startswith("tool-result:"):
        return None
    parts = key.split(":")
    return parts[2] if len(parts) >= 4 else None


def result_key_to_call_key(key: str) -> str:
    return key.replace("tool-result:", "tool-call:", 1)


def first_line(text: Any) -> str:
    return str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
