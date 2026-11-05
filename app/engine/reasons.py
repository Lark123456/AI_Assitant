"""reason_code 注册表：主动消息的原因一律使用「命名空间.名称」形式。

新增原因必须先在此登记；delivery 写入 reason_code 时统一从这里取。
"""

REASON_CODES: dict[str, str] = {
    "commitment.reminder": "用户设定的一次性提醒到期",
    "commitment.block_start": "计划块即将开始",
    "commitment.overdue_check": "任务逾期检查",
    "brief.morning": "晨间简报",
    "brief.evening": "晚间简报",
}

TRIGGER_KIND_TO_REASON: dict[str, str] = {
    "reminder": "commitment.reminder",
    "brief_morning": "brief.morning",
    "brief_evening": "brief.evening",
    "block_start": "commitment.block_start",
    "overdue_check": "commitment.overdue_check",
}


def reason_for_trigger(kind: str) -> str:
    """trigger kind -> 注册表中的 reason_code；未登记的 kind 视为编码错误。"""
    try:
        return TRIGGER_KIND_TO_REASON[kind]
    except KeyError:
        raise ValueError(f"unregistered trigger kind: {kind}") from None
