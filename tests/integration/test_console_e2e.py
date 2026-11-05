"""Console 渠道端到端（需要 Postgres）：
1. 相对时间「明天 9 点提醒我交报告」→ 建任务 + 设提醒 → 快进 → worker 领取投递，trace_id 可还原全链路。
2. 同一事件重复投递不产生重复任务。
"""

import datetime as dt
import re

from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.db.models import Delivery, EventLog, LLMCall, TriggerInstance, WorkItem
from app.engine.gate import PassthroughGate
from app.engine.triggers import claim_due_triggers
from app.llm.schemas import LLMResult, ToolCall, Usage
from app.worker.runner import process_claimed_trigger


def make_inbound(text: str, *, key: str, user: str = "u1") -> InboundEvent:
    return InboundEvent(
        channel="console", external_user_id=user, kind="message", text=text, idempotency_key=key
    )


def reminder_script(clock):
    """假 LLM：从系统提示解析当前时间，换算「明天 9 点」并发起工具调用。"""
    state = {"phase": 0}

    def responder(messages: list[dict]) -> LLMResult:
        if state["phase"] == 0:
            system = messages[0]["content"]
            m = re.search(r"当前时间：(.+?)（用户时区：(.+?)）", system)
            assert m, "系统提示必须注入当前时间与用户时区"
            now_local = dt.datetime.fromisoformat(m.group(1))
            tomorrow_9 = (now_local + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            state["phase"] = 1
            return LLMResult(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="create_task", arguments={"title": "交报告"}),
                    ToolCall(id="c2", name="set_reminder", arguments={
                        "fire_at": tomorrow_9.isoformat(),
                        "note": "记得交报告",
                        "task_id": None,
                    }),
                ],
                usage=Usage(input=10, cached=0, output=20, reasoning=0),
            )
        state["phase"] = 2
        return LLMResult(
            content="已创建任务并设置明天 9 点的提醒。",
            usage=Usage(input=30, cached=10, output=5, reasoning=0),
        )

    return responder


async def _run_due_triggers(db, fake_clock, adapters):
    """worker 主路径：领取（立即提交）→ 逐条处理。"""
    async with db() as session:
        claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    for trigger in claimed:
        await process_claimed_trigger(
            db, trigger_id=trigger.id, adapters=adapters, clock=fake_clock, gate=PassthroughGate()
        )
    return claimed


async def test_reminder_roundtrip(db, fake_clock, make_pipeline):
    pipeline, console = make_pipeline(reminder_script(fake_clock))

    # 1. 用户消息进入管道（Console 渠道）
    await pipeline.handle(make_inbound("明天 9 点提醒我交报告", key="evt-1"))

    # 2. 任务与提醒均已落库；fire_at = 北京时间次日 09:00
    async with db() as session:
        items = (await session.execute(select(WorkItem))).scalars().all()
        assert len(items) == 1
        assert items[0].title == "交报告"
        assert items[0].status == "active"
        triggers = (await session.execute(select(TriggerInstance))).scalars().all()
        assert len(triggers) == 1
        fire_at = triggers[0].fire_at
        assert fire_at == dt.datetime(2026, 1, 2, 1, 0, tzinfo=dt.UTC)  # 09:00+08:00
        assert triggers[0].status == "pending"
        assert triggers[0].attempts == 0

    # 3. Friday 的回复已通过 Console 渠道发出；首答附带你所用时区说明
    messages = console.messages_for("u1")
    assert any("已创建任务" in m["body"]["text"] for m in messages)
    assert any("当前使用时区 Asia/Shanghai" in m["body"]["text"] for m in messages)

    # 4. 快进到触发时刻，worker 领取并投递
    fake_clock.advance_to(fire_at)
    claimed = await _run_due_triggers(db, fake_clock, {"console": console})
    assert len(claimed) == 1
    async with db() as session:
        claimed_row = (
            await session.execute(select(TriggerInstance))
        ).scalar_one()
        assert claimed_row.attempts == 1
        assert claimed_row.claimed_at == fake_clock.now()

    # 5. 提醒送达 Console，链路状态正确
    nudges = [m for m in console.messages_for("u1") if m["type"] == "nudge"]
    assert len(nudges) == 1
    assert nudges[0]["body"]["text"] == "记得交报告"
    async with db() as session:
        trigger = (await session.execute(select(TriggerInstance))).scalar_one()
        assert trigger.status == "fired"
        delivery = (await session.execute(select(Delivery))).scalar_one()
        assert delivery.sent_at is not None
        assert delivery.provider_msg_id == nudges[0]["provider_msg_id"]

    # 6. trace_id 在 event_log 与 llm_call 中还原完整链路
    async with db() as session:
        inbound = (
            await session.execute(select(EventLog).where(EventLog.type == "message"))
        ).scalars().all()
        trace_id = inbound[0].trace_id
        events = (
            await session.execute(select(EventLog).where(EventLog.trace_id == trace_id))
        ).scalars().all()
        types = [e.type for e in events]
        assert "message" in types            # inbound + outbound
        assert "tool_call" in types          # create_task / set_reminder
        assert "tool_result" in types
        assert "delivery" in types           # 提醒投递
        llm_calls = (
            await session.execute(select(LLMCall).where(LLMCall.trace_id == trace_id))
        ).scalars().all()
        assert len(llm_calls) == 2           # 两轮模型调用
        assert {c.alias for c in llm_calls} == {"friday_fast"}
        assert {c.model_id for c in llm_calls} == {"fake-model"}
        assert sorted(c.input_tokens or 0 for c in llm_calls) == [10, 30]


async def test_duplicate_delivery_creates_no_duplicate_task(db, fake_clock, make_pipeline):
    pipeline, console = make_pipeline(reminder_script(fake_clock))

    await pipeline.handle(make_inbound("明天 9 点提醒我交报告", key="evt-1"))
    reply_count = len(console.messages_for("u1"))

    # 同一事件重复投递：渠道层重发同一 idempotency_key
    await pipeline.handle(make_inbound("明天 9 点提醒我交报告", key="evt-1"))

    async with db() as session:
        items = (await session.execute(select(WorkItem))).scalars().all()
        triggers = (await session.execute(select(TriggerInstance))).scalars().all()
        inbound_events = (
            await session.execute(select(EventLog).where(EventLog.direction == "inbound"))
        ).scalars().all()
    assert len(items) == 1
    assert len(triggers) == 1
    assert len(inbound_events) == 1          # 去重后只有一条入站事件
    assert len(console.messages_for("u1")) == reply_count  # 没有第二次回复
