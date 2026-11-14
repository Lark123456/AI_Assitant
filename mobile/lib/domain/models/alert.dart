import '../enums.dart';

/// 紧急提醒的动作项。
class AlertAction {
  const AlertAction({
    required this.actionId,
    required this.label,
    this.destructive = false,
  }) : assert(actionId != '', 'actionId must not be empty'),
       assert(label != '', 'label must not be empty');

  final String actionId;
  final String label;
  final bool destructive;
}

/// 紧急提醒本身，不记录用户所在页面。
class PriorityAlert {
  // 含集合非空、元素判断与不可变复制，构造函数不能是 const
  PriorityAlert({
    required this.alertId,
    required this.priority,
    required this.reason,
    required List<AlertAction> actions,
    required this.status,
    required this.createdAt,
    this.deadline,
    this.handledActionId,
  }) : actions = List<AlertAction>.unmodifiable(actions),
       assert(alertId != '', 'alertId must not be empty'),
       assert(reason != '', 'reason must not be empty'),
       assert(actions.isNotEmpty, 'alert requires at least one action'),
       assert(
         actions.map((a) => a.actionId).toSet().length == actions.length,
         'alert action ids must be unique',
       ),
       assert(
         status != AlertStatus.handled ||
             (handledActionId != null &&
                 actions.any((a) => a.actionId == handledActionId)),
         'handled alert requires a handledActionId from actions',
       ),
       assert(
         status == AlertStatus.handled || handledActionId == null,
         'handledActionId is only allowed when handled',
       );

  final String alertId;
  final AlertPriority priority;
  final String reason;
  final DateTime? deadline;
  final List<AlertAction> actions;
  final AlertStatus status;
  final DateTime createdAt;
  final String? handledActionId; // handled 时记录实际执行的动作
}

/// 弹窗出现前由 Shell 采集，关闭/处理后用于恢复。
class AlertResumeContext {
  const AlertResumeContext({
    required this.previousRoute,
    required this.capturedAt,
    this.conversationId,
    this.messageId,
    this.scrollOffset,
    this.draftText,
  }) : assert(previousRoute != '', 'previousRoute must not be empty'),
       assert(
         conversationId != null ||
             (messageId == null && scrollOffset == null && draftText == null),
         'messageId/scrollOffset/draftText require conversationId',
       ),
       assert(
         scrollOffset == null || scrollOffset >= 0,
         'scrollOffset must not be negative',
       );

  final String previousRoute; // 如 /chat/c-123?messageId=m-9
  final String? conversationId; // 当前对话（Today 页面时为空）
  final String? messageId; // 深链定位的消息
  final double? scrollOffset;
  final String? draftText;
  final DateTime capturedAt;
}
