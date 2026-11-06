"""仲裁器：纯函数，不做任何 IO。

外层负责组装 UserStateSnapshot（预取偏好、当日计数、冷却键、trigger 状态），
本模块只根据入参给出 send / defer / merge / drop 与逐步理由，便于单元测试与回放。
"""

import datetime as dt
from dataclasses import dataclass, field

from app.core.timeutil import in_quiet_hours, local_time_of, quiet_hours_end

POLICY_VERSION = "stage2-v0"
DEFER_LIMIT = 3
NON_COMMITMENT_DAILY_CAP = 12
COMMITMENT_DAILY_CAP = 50


@dataclass(frozen=True)
class CandidateView:
    """仲裁所需的候选视图（不直接依赖数据库行）。"""

    class_: str  # commitment | brief | suggestion
    reason_code: str
    explicit: bool = False
    dedupe_key: str | None = None
    expires_at: dt.datetime | None = None
    precondition_ok: bool = True
    defer_count: int = 0


@dataclass(frozen=True)
class UserStateSnapshot:
    """一次仲裁所需的用户状态快照，全部由外层预取。"""

    now: dt.datetime
    tz: str
    day_start: dt.time
    quiet_start: dt.time = dt.time(23, 0)
    quiet_end: dt.time = dt.time(7, 0)
    daily_budget: int = 4
    class_enabled: dict[str, bool] = field(default_factory=dict)
    snooze_until: dt.datetime | None = None
    briefs_enabled: bool = True
    # 当日已发送数量：按 reason_code（brief 每类每天 1 条）与按 class（硬上限）
    sent_today_by_reason: dict[str, int] = field(default_factory=dict)
    sent_today_by_class: dict[str, int] = field(default_factory=dict)
    # 当日已并入简报的建议数量
    suggestion_budget_used: int = 0
    # 同 dedupe_key 最近一次决策时刻（用于 24h 冷却）
    last_decision_at: dict[str, dt.datetime] = field(default_factory=dict)
    kill_switch: bool = False


@dataclass(frozen=True)
class Decision:
    decision: str  # send | defer | merge | drop
    gate_reasons: dict
    budget_snapshot: dict
    defer_until: dt.datetime | None = None
    policy_version: str = POLICY_VERSION


def evaluate(candidate: CandidateView, snapshot: UserStateSnapshot) -> Decision:
    """按固定顺序评估八条规则；每一步的输入与结论都写入 gate_reasons。"""
    steps: list[dict] = []
    is_commitment = candidate.class_ == "commitment"

    def record(rule: str, passed: bool, **detail: object) -> None:
        steps.append({"rule": rule, "passed": passed, **detail})

    def finish(decision: str, *, defer_until: dt.datetime | None = None) -> Decision:
        return Decision(
            decision=decision,
            gate_reasons={
                "steps": steps,
                "final": decision,
                "candidate": {
                    "class": candidate.class_,
                    "reason_code": candidate.reason_code,
                    "explicit": candidate.explicit,
                    "dedupe_key": candidate.dedupe_key,
                },
            },
            budget_snapshot={
                "daily_budget": snapshot.daily_budget,
                "suggestion_used": snapshot.suggestion_budget_used,
                "sent_today_by_class": dict(snapshot.sent_today_by_class),
                "sent_today_by_reason": dict(snapshot.sent_today_by_reason),
                "non_commitment_cap": NON_COMMITMENT_DAILY_CAP,
                "commitment_cap": COMMITMENT_DAILY_CAP,
            },
            defer_until=defer_until,
        )

    # 1. kill switch：非 commitment 一律丢弃
    if snapshot.kill_switch and not is_commitment:
        record("kill_switch", False, detail="非承诺类消息被总开关关闭")
        return finish("drop")
    record("kill_switch", True)

    # 2. 类别开关与 snooze（commitment 不受影响）
    if not is_commitment:
        if candidate.class_ == "brief" and not snapshot.briefs_enabled:
            record("class_disabled", False, detail="简报已关闭")
            return finish("drop")
        if not snapshot.class_enabled.get(candidate.class_, True):
            record("class_disabled", False, detail=f"类别 {candidate.class_} 已关闭")
            return finish("drop")
        if snapshot.snooze_until is not None and snapshot.snooze_until > snapshot.now:
            record("snoozed", False, detail=snapshot.snooze_until.isoformat())
            return finish("drop")
    record("class_switch", True)

    # 3. 过期与前提重校验
    if candidate.expires_at is not None and candidate.expires_at < snapshot.now:
        record("expired", False, detail=candidate.expires_at.isoformat())
        return finish("drop")
    if not candidate.precondition_ok:
        record("precondition_failed", False)
        return finish("drop")
    record("freshness", True)

    # 4. 去重与冷却：同 dedupe_key 24 小时内只处理一次
    if candidate.dedupe_key is not None:
        last = snapshot.last_decision_at.get(candidate.dedupe_key)
        if last is not None and (snapshot.now - last) < dt.timedelta(hours=24):
            record("cooldown", False, detail={"last": last.isoformat()})
            return finish("drop")
    record("cooldown", True)

    # 5. 免打扰
    local_now = local_time_of(snapshot.now, snapshot.tz)
    if in_quiet_hours(local_now, snapshot.quiet_start, snapshot.quiet_end):
        if is_commitment and candidate.explicit:
            record("quiet_hours", True, detail="explicit 承诺类豁免")
        else:
            until = quiet_hours_end(
                snapshot.now, snapshot.tz, snapshot.quiet_start, snapshot.quiet_end
            )
            if candidate.expires_at is not None and candidate.expires_at < until:
                record("quiet_hours", False, detail="免打扰结束前已过期")
                return finish("drop")
            if candidate.defer_count >= DEFER_LIMIT:
                record("quiet_hours", False, detail="延后次数已用尽")
                return finish("drop")
            record("quiet_hours", False, detail={"defer_until": until.isoformat()})
            return finish("defer", defer_until=until)
    record("quiet_hours", True)

    # 6. 预算：brief 每类每天 1 条；suggestion 每天最多 daily_budget 条可并入
    if candidate.class_ == "brief":
        if candidate.reason_code not in ("brief.morning", "brief.evening"):
            record("budget", False, detail="brief 缺少具体的晨/晚类型")
            return finish("drop")
        used = snapshot.sent_today_by_reason.get(candidate.reason_code, 0)
        if used >= 1:
            record("budget", False, detail={"used": used, "limit": 1})
            return finish("drop")
    elif candidate.class_ == "suggestion":
        if snapshot.suggestion_budget_used >= snapshot.daily_budget:
            record("budget", False, detail={"used": snapshot.suggestion_budget_used})
            return finish("drop")
    record("budget", True)

    # 7. suggestion 默认并入简报，不单独发送
    if candidate.class_ == "suggestion":
        record("suggestion_merge", True, detail="并入下一次简报")
        return finish("merge")

    # 8. 硬上限：只防通知风暴
    cap = COMMITMENT_DAILY_CAP if is_commitment else NON_COMMITMENT_DAILY_CAP
    used = snapshot.sent_today_by_class.get(candidate.class_, 0)
    if used >= cap:
        record("hard_cap", False, detail={"used": used, "cap": cap})
        return finish("drop")
    record("hard_cap", True, detail={"used": used, "cap": cap})

    return finish("send")
