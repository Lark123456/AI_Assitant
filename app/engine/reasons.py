"""reason_code 注册表：主动消息的原因一律使用「命名空间.名称」形式。

新增原因必须先在此登记；delivery 写入 reason_code 时统一从这里取。
"""

REASON_CODES: dict[str, str] = {
    "commitment.reminder": "用户设定的一次性提醒到期",
    "commitment.block_start": "计划块即将开始",
    "commitment.overdue_check": "任务逾期检查",
    "brief.morning": "晨间简报",
    "brief.evening": "晚间简报",
    "suggestion.overdue_blocks": "过去 24 小时内有多个计划块逾期未完成",
    "suggestion.stale_tasks": "有任务长期没有更新",
}

# 仲裁理由码：每条被抑制/延后/合并的消息都必须用这里的码解释
GATE_REASON_CODES: dict[str, str] = {
    "quiet_hours": "处于免打扰时段",
    "budget_exhausted": "当日该类消息预算已用完",
    "cooldown": "同一去重键在冷却期内已处理过",
    "snoozed": "用户暂停了非承诺类消息",
    "expired": "候选已过期",
    "precondition_failed": "前提条件不再成立",
    "nothing_to_say": "没有可发送的内容",
    "hard_cap": "超出当日消息总量上限",
    "kill_switch": "主动消息总开关已关闭",
    "merged_into_brief": "已并入简报",
    "class_disabled": "该类别消息已关闭",
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


def is_registered_gate_reason(code: str) -> bool:
    """仲裁理由码必须先在 GATE_REASON_CODES 登记。"""
    return code in GATE_REASON_CODES
