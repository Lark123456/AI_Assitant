"""记忆注入渲染：预算优先级、整条取舍、来源标注（纯函数）。"""

import datetime as dt
import uuid

from app.memory.retrieve import MemoryContext, MemoryItem, render_memory_block

BASE = dt.datetime(2026, 11, 9, tzinfo=dt.UTC)


def _item(
    *,
    type_: str = "preference",
    subject: str = "咖啡",
    text: str = "喜欢美式",
    time: str | None = None,
    slot_key: str | None = None,
    source_class: str = "stated",
    similarity: float | None = 0.9,
    scope: dict | None = None,
) -> MemoryItem:
    value = {"text": text}
    if time:
        value["time"] = time
    return MemoryItem(
        id=uuid.uuid4(),
        type=type_,
        slot_key=slot_key,
        subject=subject,
        value=value,
        scope=scope,
        source_class=source_class,
        weight=0.8,
        effective=0.8,
        similarity=similarity,
        valid_to=None,
    )


def test_render_includes_slots_preferences_and_episodes() -> None:
    context = MemoryContext(
        slots=(_item(type_="slot", slot_key="wake", subject="起床时间", text="7点", time="07:00"),),
        preferences=(_item(),),
        episodes=(
            _item(
                type_="episode",
                subject="加班",
                text="加班到九点",
                scope={"kind": "on", "date": "2026-11-09"},
            ),
        ),
    )
    block = render_memory_block(context, max_chars=800, item_max_chars=120)
    assert "长期作息：" in block
    assert "起床时间：07:00" in block
    assert "稳定偏好：" in block
    assert "近期事件：" in block
    assert "11-09 加班到九点" in block


def test_render_empty_context_returns_empty_string() -> None:
    assert render_memory_block(MemoryContext(), max_chars=800, item_max_chars=120) == ""


def test_render_drops_episodes_before_slots_when_over_budget() -> None:
    slot = _item(type_="slot", slot_key="wake", subject="起床时间", text="7点", time="07:00")
    preference = _item(subject="偏好", text="喜欢美式")
    episode = _item(
        type_="episode",
        subject="加班",
        text="加班到九点",
        scope={"kind": "on", "date": "2026-11-09"},
    )
    baseline = render_memory_block(
        MemoryContext(slots=(slot,), preferences=(preference,)),
        max_chars=10_000,
        item_max_chars=120,
    )
    block = render_memory_block(
        MemoryContext(slots=(slot,), preferences=(preference,), episodes=(episode,)),
        max_chars=len(baseline),
        item_max_chars=120,
    )
    assert "起床时间：07:00" in block
    assert "偏好：喜欢美式" in block
    assert "近期事件" not in block


def test_render_skips_single_item_over_item_limit_without_truncating() -> None:
    long_text = "很长的一段偏好描述" * 40
    context = MemoryContext(
        preferences=(
            _item(subject="长偏好", text=long_text),
            _item(subject="短偏好", text="喜欢美式"),
        )
    )
    block = render_memory_block(context, max_chars=800, item_max_chars=60)
    assert "长偏好" not in block
    assert "短偏好：喜欢美式" in block
    # 不允许出现被截断的半句话
    assert long_text[:20] not in block


def test_render_labels_inferred_as_reference_only() -> None:
    context = MemoryContext(preferences=(_item(source_class="inferred"),))
    block = render_memory_block(context, max_chars=800, item_max_chars=120)
    assert "推断，仅供参考" in block


def test_render_labels_confirmed() -> None:
    context = MemoryContext(preferences=(_item(source_class="confirmed"),))
    block = render_memory_block(context, max_chars=800, item_max_chars=120)
    assert "已确认" in block
