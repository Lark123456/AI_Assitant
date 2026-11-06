"""阶段 1 修订 2：工具执行包在 savepoint（begin_nested）中，异常不污染外层事务。"""

from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import EventLog, User, WorkItem
from app.tools.base import ToolContext, ToolDef, ToolResult
from app.tools.registry import TOOLS, execute_tool


class _BoomArgs(BaseModel):
    title: str


async def _boom_run(ctx: ToolContext, args: dict) -> ToolResult:
    """先写一半业务数据再抛异常：验证 savepoint 能干净回滚。"""
    ctx.session.add(
        WorkItem(
            user_id=ctx.user.id,
            type="item",
            status="active",
            title=args["title"] + "-partial",
            source_event_id=ctx.source_event_id,
            created_at=ctx.clock.now(),
            updated_at=ctx.clock.now(),
        )
    )
    await ctx.session.flush()
    raise RuntimeError("tool exploded")


BOOM_TOOL = ToolDef(
    name="explode", description="测试用：写一半就炸", args_model=_BoomArgs, run=_boom_run, write=True
)


async def _make_ctx(db, fake_clock, settings) -> ToolContext:
    async with db() as session:
        user = User(display_name="u", timezone="Asia/Shanghai", created_at=fake_clock.now())
        session.add(user)
        await session.flush()  # 生成 user.id 后再建事件
        event = EventLog(
            user_id=user.id,
            channel="console",
            direction="inbound",
            type="message",
            payload={"text": "hi"},
            trace_id="tr-savepoint",
            occurred_at=fake_clock.now(),
            recorded_at=fake_clock.now(),
        )
        session.add(event)
        await session.commit()
        user_id, event_id = user.id, event.id

    async with db() as session:
        user = await session.get(User, user_id)
        return ToolContext(
            session=session,
            clock=fake_clock,
            settings=settings,
            user=user,
            trace_id="tr-savepoint",
            channel="console",
            source_event_id=event_id,
        )


async def test_tool_exception_rolls_back_savepoint_only(db, fake_clock, settings):
    """写工具中途炸掉：savepoint 回滚半途写入，外层事务仍可继续并提交。"""
    TOOLS["explode"] = BOOM_TOOL
    ctx = await _make_ctx(db, fake_clock, settings)
    try:
        result = await execute_tool(ctx, "explode", {"title": "买牛奶"}, call_index=0)

        assert result.status == "error"
        assert "RuntimeError" in result.message

        # savepoint 已回滚：半途写入的业务数据不在
        partial = (
            await ctx.session.execute(
                select(WorkItem).where(WorkItem.title == "买牛奶-partial")
            )
        ).scalars().all()
        assert partial == []

        # 外层事务未被污染：继续写入 + 提交成功
        ctx.session.add(
            WorkItem(
                user_id=ctx.user.id,
                type="item",
                status="active",
                title="正式任务",
                source_event_id=ctx.source_event_id,
                created_at=fake_clock.now(),
                updated_at=fake_clock.now(),
            )
        )
        await ctx.session.commit()

        # tool_call 与 error tool_result 事件都留痕
        events = (
            await ctx.session.execute(
                select(EventLog).where(EventLog.type.in_(("tool_call", "tool_result")))
            )
        ).scalars().all()
        types = sorted(e.type for e in events)
        assert types == ["tool_call", "tool_result"]

        # 幂等重放：同一入站事件+调用序号返回上次的 error 结果，不再执行工具
        replay = await execute_tool(ctx, "explode", {"title": "买牛奶"}, call_index=0)
        assert replay.status == "error"
        assert "RuntimeError" in replay.message
    finally:
        del TOOLS["explode"]
        await ctx.session.close()  # 必须显式关：泄漏的开放事务会挡住下一个测试的 TRUNCATE

    async with db() as session:
        items = (await session.execute(select(WorkItem))).scalars().all()
    assert [i.title for i in items] == ["正式任务"]
