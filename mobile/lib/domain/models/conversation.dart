import '../enums.dart';
import 'unset.dart';

/// 对话：主对话归 Friday，专题对话归 Jarvis。
///
/// 含 DateTime 比较的 assert 不能用于 const 构造，故本类为非 const。
class Conversation {
  Conversation({
    required this.conversationId,
    required this.type,
    required this.agent,
    required this.status,
    required this.createdAt,
    required this.lastActivityAt,
    this.projectId,
    this.projectTitle,
    this.topic,
    this.goal,
    this.scopeSummary,
    this.parentConversationId,
    this.originInviteId,
  }) : assert(conversationId != '', 'conversationId must not be empty'),
       assert(
         !lastActivityAt.isBefore(createdAt),
         'lastActivityAt must not be earlier than createdAt',
       ),
       assert(
         type != ConversationType.main || projectId == null,
         'main conversation must not have projectId',
       ),
       assert(
         type != ConversationType.main ||
             (parentConversationId == null && originInviteId == null),
         'main conversation must not have parent or origin invite',
       ),
       assert(
         type != ConversationType.main ||
             (topic == null && goal == null && scopeSummary == null),
         'main conversation must not have topic/goal/scopeSummary',
       ),
       assert(
         type != ConversationType.topic || projectId != null,
         'topic conversation requires projectId',
       ),
       assert(
         projectId != null || projectTitle == null,
         'projectTitle requires projectId',
       ),
       assert(
         type != ConversationType.main || agent == ConversationAgent.friday,
         'main conversation must belong to friday',
       ),
       assert(
         type != ConversationType.topic || agent == ConversationAgent.jarvis,
         'topic conversation must belong to jarvis',
       ),
       assert(
         type != ConversationType.topic ||
             (topic != null && goal != null && scopeSummary != null),
         'topic conversation requires topic/goal/scopeSummary',
       );

  final String conversationId;
  final ConversationType type;
  final ConversationAgent agent;
  final ConversationStatus status;
  final DateTime createdAt;
  final DateTime lastActivityAt;

  final String? projectId; // 专题必填；主对话为空
  final String? projectTitle;
  final String? topic; // 专题名称
  final String? goal; // 专题目标
  final String? scopeSummary; // 讨论范围
  final String? parentConversationId;
  final String? originInviteId;

  bool get isMain => type == ConversationType.main;

  /// 仅 `topic` 可改 `projectId`（且不可清空）；`projectTitle` 可改可清空。
  Conversation copyWith({
    ConversationStatus? status,
    DateTime? lastActivityAt,
    Object? projectId = unset,
    Object? projectTitle = unset,
  }) {
    final nextProjectId = identical(projectId, unset)
        ? this.projectId
        : projectId as String?;
    final nextProjectTitle = identical(projectTitle, unset)
        ? this.projectTitle
        : projectTitle as String?;
    final nextLastActivityAt = lastActivityAt ?? this.lastActivityAt;
    assert(
      type != ConversationType.topic || nextProjectId != null,
      'cannot clear projectId of a topic conversation',
    );
    assert(
      type != ConversationType.main || nextProjectId == null,
      'main conversation projectId must stay null',
    );
    assert(
      nextProjectId != null || nextProjectTitle == null,
      'projectTitle requires projectId',
    );
    assert(
      !nextLastActivityAt.isBefore(createdAt),
      'lastActivityAt must not be earlier than createdAt',
    );
    return Conversation(
      conversationId: conversationId,
      type: type,
      agent: agent,
      status: status ?? this.status,
      createdAt: createdAt,
      lastActivityAt: nextLastActivityAt,
      projectId: nextProjectId,
      projectTitle: nextProjectTitle,
      topic: topic,
      goal: goal,
      scopeSummary: scopeSummary,
      parentConversationId: parentConversationId,
      originInviteId: originInviteId,
    );
  }
}
