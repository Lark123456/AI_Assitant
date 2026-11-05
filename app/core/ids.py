"""ID 生成：UUID v7（时间有序主键）、trace_id、幂等键。

UUID v7 的时间戳仅用于排序与唯一性，不属于业务时间语义，
因此此处直接读取系统时间，不受 Clock 注入约束。
"""

import os
import time
import uuid

_RAND = os.urandom  # 明确来源，便于审阅


def new_uuid7(ts_ms: int | None = None) -> uuid.UUID:
    """生成 UUID v7；ts_ms 缺省取当前系统毫秒时间戳。

    标准布局（RFC 9562）：高 48 位毫秒时间戳，随后 4 位版本（0b0111）、
    12 位随机、2 位变体（0b10）、62 位随机。
    """
    if ts_ms is None:
        ts_ms = time.time_ns() // 1_000_000
    if not 0 <= ts_ms < 2**48:
        raise ValueError("timestamp_ms out of range for uuid7")
    rand_a = int.from_bytes(_RAND(2), "big") & 0x0FFF
    rand_b = int.from_bytes(_RAND(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    value = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def new_id() -> str:
    """业务主键字符串形式。"""
    return str(new_uuid7())


def new_trace_id() -> str:
    """链路追踪 ID。"""
    return str(new_uuid7())


def new_idempotency_key() -> str:
    """幂等键（随机即可，无需时间有序）。"""
    return uuid.uuid4().hex
