"""reason_code 注册表（纯单元，无 DB）。"""

import re

import pytest

from app.engine.reasons import REASON_CODES, TRIGGER_KIND_TO_REASON, reason_for_trigger

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def test_all_codes_use_namespace_form():
    for code in REASON_CODES:
        assert CODE_PATTERN.match(code), f"reason_code 必须是 命名空间.名称 形式：{code}"
        assert REASON_CODES[code], f"{code} 缺少描述"


def test_every_trigger_kind_maps_to_registered_reason():
    for kind, code in TRIGGER_KIND_TO_REASON.items():
        assert code in REASON_CODES, f"trigger kind {kind} 的 reason_code {code} 未在注册表登记"


def test_reason_for_trigger_known_and_unknown():
    assert reason_for_trigger("reminder") == "commitment.reminder"
    assert reason_for_trigger("brief_morning") == "brief.morning"
    with pytest.raises(ValueError):
        reason_for_trigger("nonexistent_kind")
