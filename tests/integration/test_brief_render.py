"""简报渲染：晨/晚模板、无内容不发送、开场语回退与限界。"""

import datetime as dt

from app.db.models import (
    NudgeCandidate,
    NudgeDecision,
    PlannedBlock,
    TriggerInstance,
    User,
    WorkItem,
)
from app.engine.brief import render_brief
from app.engine.materializer import get_or_create_prefs
from app.llm.schemas import LLMResult


async def _seed(db, clock) -> tuple[User, PlannedBlock, WorkItem]:
    async with db() as session:
        user = User(display_name="render", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        item = WorkItem(
            user_id=user.id, type="item", status="active", title="写报告",
            created_at=clock.now(), updated_at=clock.now(),
        )
        session.add(item)
        await session.flush()
        block = PlannedBlock(
            user_id=user.id, work_item_id=item.id,
            starts_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=dt.UTC),  # 09:00 本地
            ends_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=dt.UTC),
            status="planned", assigned_by="friday", rev=1,
        )
        session.add(block)
        await session.commit()
        return user, block, item


async def _add_merged_suggestion(db, user: User) -> None:
    async with db() as session:
        candidate = NudgeCandidate(
            user_id=user.id, class_="suggestion", reason_code="suggestion.stale_tasks",
            reason_text="这些任务很久没动了：整理笔记", value_score=0.5,
            expires_at=dt.datetime(2026, 1, 2, 20, 0, tzinfo=dt.UTC),
            dedupe_key="suggestion.stale_tasks:2026-01-01",
        )
        session.add(candidate)
        await session.flush()
        session.add(
            NudgeDecision(
                candidate_id=candidate.id, decision="merge", gate_reasons={},
                policy_version="test", budget_snapshot={}, decided_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            )
        )
        await session.commit()


async def test_morning_brief_contains_schedule_and_reminder(db, fake_clock, settings) -> None:
    user, _, _ = await _seed(db, fake_clock)
    async with db() as session:
        prefs = await get_or_create_prefs(session, user.id, fake_clock)
        trigger = TriggerInstance(
            user_id=user.id, kind="reminder", key="r:1",
            fire_at=dt.datetime(2026, 1, 1, 7, 0, tzinfo=dt.UTC),
            tz="Asia/Shanghai", payload={"note": "交报告"}, status="pending",
            created_at=fake_clock.now(),
        )
        session.add(trigger)
        await session.commit()
        content = await render_brief(
            session, user=user, prefs=prefs, kind="brief_morning", clock=fake_clock,
            settings=settings, gateway=None, trace_id="t",
        )
    assert content is not None
    assert "今日安排" in content.text
    assert "写报告" in content.text
    assert "09:00" in content.text
    assert "今日提醒：交报告" in content.text
    assert "08:30" in content.text
    assert content.block_ids


async def test_evening_brief_marks_unfinished(db, fake_clock, settings) -> None:
    user, _, _ = await _seed(db, fake_clock)
    await _add_merged_suggestion(db, user)
    async with db() as session:
        prefs = await get_or_create_prefs(session, user.id, fake_clock)
        content = await render_brief(
            session, user=user, prefs=prefs, kind="brief_evening", clock=fake_clock,
            settings=settings, gateway=None, trace_id="t",
        )
    assert content is not None
    assert "[未完成]" in content.text
    assert "建议：" in content.text
    assert "第一个做完了" in content.text
    assert content.merged_ids


async def test_empty_brief_returns_none(db, fake_clock, settings) -> None:
    async with db() as session:
        user = User(display_name="empty", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.commit()
        prefs = await get_or_create_prefs(session, user.id, fake_clock)
        content = await render_brief(
            session, user=user, prefs=prefs, kind="brief_morning", clock=fake_clock,
            settings=settings, gateway=None, trace_id="t",
        )
    assert content is None


async def test_opening_failure_falls_back_to_template(db, fake_clock, settings, make_gateway) -> None:
    user, _, _ = await _seed(db, fake_clock)

    def broken(messages: list[dict]) -> LLMResult:
        raise RuntimeError("compose down")

    gateway = make_gateway(broken)
    async with db() as session:
        prefs = await get_or_create_prefs(session, user.id, fake_clock)
        content = await render_brief(
            session, user=user, prefs=prefs, kind="brief_morning", clock=fake_clock,
            settings=settings, gateway=gateway, trace_id="t",
        )
    assert content is not None
    assert content.text.startswith("早上好。")


async def test_opening_takes_first_line_only(db, fake_clock, settings, make_gateway) -> None:
    user, _, _ = await _seed(db, fake_clock)

    def chatty(messages: list[dict]) -> LLMResult:
        return LLMResult(content="今天也加油。\n- 假清单：不该出现", model_id="fake")

    gateway = make_gateway(chatty)
    async with db() as session:
        prefs = await get_or_create_prefs(session, user.id, fake_clock)
        content = await render_brief(
            session, user=user, prefs=prefs, kind="brief_morning", clock=fake_clock,
            settings=settings, gateway=gateway, trace_id="t",
        )
    assert content is not None
    first_line = content.text.splitlines()[0]
    assert first_line == "今天也加油。"
    assert "假清单" not in first_line


async def test_evening_uses_configured_time_in_footer(db, fake_clock, settings) -> None:
    user, _, _ = await _seed(db, fake_clock)
    async with db() as session:
        prefs = await get_or_create_prefs(session, user.id, fake_clock)
        prefs.evening_brief_time = dt.time(22, 0)
        await session.commit()
        content = await render_brief(
            session, user=user, prefs=prefs, kind="brief_evening", clock=fake_clock,
            settings=settings, gateway=None, trace_id="t",
        )
    assert content is not None
    assert "22:00" in content.text
