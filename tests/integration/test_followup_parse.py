"""追问解析：借助对话历史 + list_schedule，「第一个做完了」落到第一个块的 update_block_status。"""

import datetime as dt
import json
from collections.abc import Callable

from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.core.clock import UTC, FakeClock
from app.db.models import ChannelIdentity, EventLog, PlannedBlock, User
from app.llm.schemas import LLMResult, ToolCall, Usage
from app.tools.base import ToolContext
from app.tools.registry import execute_tool


def _usage() -> Usage:
    return Usage(input=10, cached=0, output=10, reasoning=0)


def _tool_result(messages: list[dict]) -> dict:
    for message in reversed(messages):
        if message.get("role") == "tool":
            return dict(json.loads(str(message["content"])))
    raise AssertionError("没有工具结果")


async def _seed_block(session, clock, settings, user, event_id, title, starts_at, ends_at, idx):
    ctx = ToolContext(
        session=session,
        clock=clock,
        settings=settings,
        user=user,
        trace_id="followup",
        channel="console",
        source_event_id=event_id,
    )
    result = await execute_tool(
        ctx,
        "schedule_block",
        {"title": title, "starts_at": starts_at, "ends_at": ends_at},
        call_index=idx,
    )
    assert result.status == "ok"
    return str(result.data["block_id"])


def followup_script() -> tuple[Callable[[list[dict]], LLMResult], dict]:
    """两轮对话脚本：先列日程，再按「第一个」更新块状态。"""
    state: dict = {"phase": 0, "history_seen": False, "block_id": None}

    def responder(messages: list[dict]) -> LLMResult:
        if state["phase"] == 0:
            state["phase"] = 1
            return LLMResult(
                content=None,
                tool_calls=[ToolCall(id="s1", name="list_schedule", arguments={"date": "2026-01-01"})],
                usage=_usage(),
            )
        if state["phase"] == 1:
            state["phase"] = 2
            return LLMResult(
                content="今天有 3 个时间块：1) 09:10 写报告；2) 11:00 复盘；3) 14:00 整理笔记。",
                usage=_usage(),
            )
        if state["phase"] == 2:
            # 第二轮：对话历史里必须能看到上一轮回复，否则「第一个」无从指代
            state["history_seen"] = any(
                "今天有 3 个时间块" in str(m.get("content") or "") for m in messages
            )
            state["phase"] = 3
            return LLMResult(
                content=None,
                tool_calls=[ToolCall(id="s2", name="list_schedule", arguments={"date": "2026-01-01"})],
                usage=_usage(),
            )
        if state["phase"] == 3:
            blocks = _tool_result(messages)["data"]["blocks"]
            state["block_id"] = blocks[0]["block_id"]
            state["phase"] = 4
            return LLMResult(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="s3",
                        name="update_block_status",
                        arguments={"block_id": blocks[0]["block_id"], "status": "done"},
                    )
                ],
                usage=_usage(),
            )
        state["phase"] = 5
        return LLMResult(content="好的，已把写报告标记为完成。", usage=_usage())

    return responder, state


async def test_followup_first_one_done(db, settings, make_pipeline):
    clock = FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    responder, state = followup_script()
    pipeline, console = make_pipeline(responder)

    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        session.add(ChannelIdentity(user_id=user.id, channel="console", external_id="u1", rev=1))
        event = EventLog(
            user_id=user.id,
            channel="console",
            direction="inbound",
            type="message",
            payload={"text": "seed"},
            trace_id="followup",
            occurred_at=clock.now(),
            recorded_at=clock.now(),
        )
        session.add(event)
        await session.flush()
        await _seed_block(
            session, clock, settings, user, event.id, "写报告",
            "2026-01-01T09:10:00+08:00", "2026-01-01T10:00:00+08:00", 1,
        )
        await _seed_block(
            session, clock, settings, user, event.id, "复盘",
            "2026-01-01T11:00:00+08:00", "2026-01-01T12:00:00+08:00", 2,
        )
        await _seed_block(
            session, clock, settings, user, event.id, "整理笔记",
            "2026-01-01T14:00:00+08:00", "2026-01-01T15:00:00+08:00", 3,
        )
        await session.commit()

    await pipeline.handle(
        InboundEvent(
            channel="console", external_user_id="u1", kind="message",
            text="今天我有哪些安排？", idempotency_key="evt-1",
        )
    )
    await pipeline.handle(
        InboundEvent(
            channel="console", external_user_id="u1", kind="message",
            text="第一个做完了", idempotency_key="evt-2",
        )
    )

    replies = [m["body"]["text"] for m in console.messages_for("u1")]
    assert any("今天有 3 个时间块" in text for text in replies)
    assert any("已把写报告标记为完成" in text for text in replies)
    assert not any("出了点故障" in text for text in replies)

    # 历史注入生效：第二轮确实看到了上一轮回复
    assert state["history_seen"] is True
    # 「第一个」解析到 09:10 的写报告块
    async with db() as session:
        blocks = (
            await session.execute(select(PlannedBlock).order_by(PlannedBlock.starts_at))
        ).scalars().all()
    assert str(blocks[0].id) == state["block_id"]
    assert blocks[0].status == "done"
    assert blocks[0].actual_ended_at is not None
    assert [b.status for b in blocks[1:]] == ["planned", "planned"]
