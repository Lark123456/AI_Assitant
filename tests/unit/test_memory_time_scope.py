"""时间与 scope 的确定性归一化。"""

import datetime as dt

from app.core.clock import UTC
from app.memory.schemas import ScopeSpec
from app.memory.scope import normalize_scope
from app.memory.timeparse import (
    disambiguate_slot_time,
    episode_roles,
    parse_time_text,
    resolve_episode_time,
)


def test_parse_time_text() -> None:
    assert parse_time_text("7点") == "07:00"
    assert parse_time_text("七点") == "07:00"
    assert parse_time_text("早上7点") == "07:00"
    assert parse_time_text("晚上9点") == "21:00"
    assert parse_time_text("下午3点半") == "15:30"
    assert parse_time_text("7:30") == "07:30"
    assert parse_time_text("中午12点") == "12:00"
    assert parse_time_text("晚上12点") == "00:00"
    assert parse_time_text("十一点") == "11:00"
    assert parse_time_text("昨晚十一点") == "23:00"
    assert parse_time_text("昨夜十二点") == "00:00"
    assert parse_time_text("今早六点") == "06:00"
    assert parse_time_text("今晚十点") == "22:00"
    assert parse_time_text("随便") is None


def test_disambiguate_slot_time_windows() -> None:
    # 无时段词时按槽位窗口纠正 12 小时制
    assert disambiguate_slot_time("work_end", "05:30") == "17:30"
    assert disambiguate_slot_time("sleep", "12:00") == "00:00"
    assert disambiguate_slot_time("lunch", "01:00") == "13:00"
    assert disambiguate_slot_time("sleep", "10:00") == "22:00"
    assert disambiguate_slot_time("work_end", "06:00") == "18:00"
    # 已在窗口内，保持不变
    assert disambiguate_slot_time("wake", "07:00") == "07:00"
    assert disambiguate_slot_time("work_start", "09:00") == "09:00"
    assert disambiguate_slot_time("lunch", "12:00") == "12:00"
    # 不自动翻转的槽位
    assert disambiguate_slot_time("commute", "09:00") == "09:00"
    assert disambiguate_slot_time("energy_peak", "03:00") == "03:00"
    assert disambiguate_slot_time("fixed_event", "08:00") == "08:00"
    # 两种读法都不合理：保留原话
    assert disambiguate_slot_time("wake", "12:00") == "12:00"
    # 已是 24 小时制，不需要再翻转
    assert disambiguate_slot_time("work_end", "21:00") == "21:00"


def test_normalize_scope_relative_dates() -> None:
    event_time = dt.datetime(2026, 11, 6, 0, 0, tzinfo=UTC)  # 本地 11-06 08:00（周五）
    tz = "Asia/Shanghai"
    day_start = dt.time(4, 0)

    assert normalize_scope(ScopeSpec(kind="persistent"), event_time, tz, day_start) == {
        "kind": "persistent"
    }
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="今天"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-06"}
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="明天"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-07"}
    assert normalize_scope(
        ScopeSpec(kind="until", date_text="月底"), event_time, tz, day_start
    ) == {"kind": "until", "date": "2026-11-30"}
    # 周五的“下周三” = 11-11
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="下周三"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-11"}
    assert normalize_scope(
        ScopeSpec(kind="recurring", rule="每周一"), event_time, tz, day_start
    ) == {"kind": "recurring", "rule": "每周一"}
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="不知道"), event_time, tz, day_start
    ) is None


def test_normalize_scope_night_and_morning_words() -> None:
    event_time = dt.datetime(2026, 11, 6, 0, 0, tzinfo=UTC)  # 本地 11-06 08:00
    tz = "Asia/Shanghai"
    day_start = dt.time(4, 0)

    assert normalize_scope(
        ScopeSpec(kind="on", date_text="昨晚"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-05"}
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="昨夜"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-05"}
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="今早"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-06"}
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="今晚"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-06"}


def test_episode_roles_prefers_multi_word_patterns() -> None:
    assert episode_roles("今天睡到9点才起") == {"wake"}
    assert episode_roles("昨天睡到11点才醒") == {"wake"}
    assert episode_roles("昨晚十一点才睡") == {"sleep"}
    assert episode_roles("今天加班到九点") == {"work_end"}
    assert episode_roles("昨天五点就下班了") == {"work_end"}
    assert episode_roles("今天十点到公司") == {"work_start"}
    assert episode_roles("今天十二点吃午饭") == {"lunch"}
    # 多字模式与另一角色同时出现：角色不唯一
    assert episode_roles("今天睡到9点才起，然后去上班") == {"wake", "work_start"}


def test_resolve_episode_time_by_role_window() -> None:
    assert resolve_episode_time("今天加班到九点", "九点") == "21:00"
    assert resolve_episode_time("昨天加班到十点", "十点") == "22:00"
    assert resolve_episode_time("今天睡到9点才起", "9点") == "09:00"
    assert resolve_episode_time("昨天睡到11点才起", "11点") == "11:00"
    assert resolve_episode_time("昨天五点就下班了", "五点") == "17:00"
    # 明确时段词直接采用
    assert resolve_episode_time("昨晚十一点才睡", "十一点") == "23:00"
    assert resolve_episode_time("今早六点就起了", "六点") == "06:00"
    assert resolve_episode_time("昨天中午一点才吃上饭", "一点") == "13:00"
    # 24 小时制直接采用
    assert resolve_episode_time("今天加班到九点", "21:00") == "21:00"


def test_resolve_episode_time_omits_when_uncertain() -> None:
    # 映射不到角色
    assert resolve_episode_time("今天感觉不错", "九点") is None
    # 两种读法都不在窗口内
    assert resolve_episode_time("今天起了个早", "十二点") is None
    # 同一句命中两个角色且不属于同一多字模式
    assert resolve_episode_time("今天睡到9点才起，然后去上班", "9点") is None
    # 没有时间表达
    assert resolve_episode_time("今天加班到九点", None) is None
    assert resolve_episode_time("今天加班到九点", "很晚") is None
