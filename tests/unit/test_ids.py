"""手写 UUID v7 的正确性（纯单元，无 DB）。"""

import time
import uuid

import pytest

from app.core.ids import new_id, new_trace_id, new_uuid7


def _extract_ts_ms(u: uuid.UUID) -> int:
    """按 RFC 9562 布局取高 48 位毫秒时间戳。"""
    return u.int >> 80


def test_uuid7_version_and_variant_bits():
    ts = 1_700_000_000_000
    u = new_uuid7(ts)
    assert u.version == 7
    # RFC 4122 变体位：byte 8 高两位为 10
    assert (u.bytes[8] >> 6) == 0b10
    assert _extract_ts_ms(u) == ts


def test_uuid7_is_time_ordered():
    u1 = new_uuid7(1_700_000_000_000)
    u2 = new_uuid7(1_700_000_000_001)
    u3 = new_uuid7(1_700_000_000_002)
    assert u1 < u2 < u3


def test_uuid7_same_millisecond_unique():
    ts = 1_700_000_000_000
    values = {new_uuid7(ts) for _ in range(1000)}
    assert len(values) == 1000


def test_uuid7_rejects_invalid_timestamp():
    with pytest.raises(ValueError):
        new_uuid7(-1)
    with pytest.raises(ValueError):
        new_uuid7(1 << 48)  # 超出 48 位


def test_new_uuid7_close_to_wall_clock():
    before_ms = int(time.time() * 1000)
    u = new_uuid7()
    after_ms = int(time.time() * 1000)
    assert before_ms <= _extract_ts_ms(u) <= after_ms
    assert u.version == 7


def test_new_id_and_trace_id_formats():
    i = new_id()
    t = new_trace_id()
    # new_id 是 UUID 字符串；new_trace_id 是 UUID 字符串
    assert str(uuid.UUID(i)) == i
    assert str(uuid.UUID(t)) == t
    assert t != new_trace_id()
