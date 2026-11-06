"""证据文本：结构化工具事实与空白归一化回查。"""

from app.memory.text import (
    normalize_ws,
    parse_tool_name_from_result_key,
    quote_matches,
    render_tool_fact,
    result_key_to_call_key,
)


def test_quote_matches_ignores_whitespace() -> None:
    assert quote_matches("我平时 7 点 起床", "我平时7点起床，周末会晚一点")
    assert not quote_matches("我 8 点起床", "我平时7点起床")
    assert not quote_matches("   ", "我平时7点起床")


def test_render_schedule_block_uses_structured_arguments() -> None:
    text = render_tool_fact(
        "schedule_block",
        {
            "title": "写报告",
            "starts_at": "2026-11-07T09:00:00+08:00",
            "ends_at": "2026-11-07T10:00:00+08:00",
        },
        {},
    )
    assert text is not None
    assert "写报告" in text and "2026-11-07T09:00:00+08:00" in text
    assert "已成功执行" in text


def test_render_set_notif_prefs_is_sorted_and_ignores_none() -> None:
    text = render_tool_fact(
        "set_notif_prefs", {"quiet_hours": "22:00-08:00", "daily_budget": None}, {}
    )
    assert text == "工具 set_notif_prefs 已成功执行；quiet_hours=22:00-08:00"


def test_unverified_tools_have_no_evidence_text() -> None:
    assert render_tool_fact("set_timezone", {"tz": "Asia/Tokyo"}, {}) is None


def test_tool_key_parsing() -> None:
    key = "tool-result:in-1:schedule_block:3"
    assert parse_tool_name_from_result_key(key) == "schedule_block"
    assert result_key_to_call_key(key) == "tool-call:in-1:schedule_block:3"
    assert normalize_ws(" a\tb\nc ") == "abc"
