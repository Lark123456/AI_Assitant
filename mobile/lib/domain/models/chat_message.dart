import '../enums.dart';
import '../errors.dart';
import 'unset.dart';

/// 聊天消息基类；`seq` 由仓库分配，正式消息不得由前端生成。
///
/// 正式事件序号：与产生该消息的 `MessageUpsert.seq` 相等，用于排序/去重/缺口检测，必须 > 0。
/// 本地 pending / queued / failed 使用负数临时值（-1、-2、…），仅用于本地排序，
/// 不是正式事件序号，不参与连续性检查，也不写入 `lastSeq`。
sealed class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.conversationId,
    required this.sender,
    required this.createdAt,
    required this.seq,
    this.reason,
    this.syncState = SyncState.synced,
  }) : assert(id != '', 'message id must not be empty'),
       assert(conversationId != '', 'conversationId must not be empty'),
       assert(seq != 0, 'seq must be positive (formal) or negative (local)'),
       assert(
         syncState != SyncState.synced || seq > 0,
         'synced message requires a positive seq',
       ),
       assert(
         syncState == SyncState.synced || seq < 0,
         'pending/queued/failed message requires a negative seq',
       );

  final String id; // 全局唯一
  final String conversationId; // 必填
  final ChatSender sender;
  final DateTime createdAt;
  final int seq;
  final String? reason; // 主动消息的理由
  final SyncState syncState;
}

final class TextMessage extends ChatMessage {
  const TextMessage({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    this.text = '',
    this.streaming = false,
  });

  final String text;
  final bool streaming;

  TextMessage copyWith({String? text, bool? streaming, SyncState? syncState}) {
    final nextSyncState = syncState ?? this.syncState;
    if (nextSyncState == SyncState.synced && seq <= 0) {
      throw StateTransitionException(
        model: 'TextMessage',
        from: this.syncState.name,
        to: nextSyncState.name,
        reason: 'local message cannot become synced without a formal seq',
      );
    }
    assert(
      nextSyncState != SyncState.synced || seq > 0,
      'cannot mark a local message as synced without a formal seq',
    );
    return TextMessage(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: nextSyncState,
      text: text ?? this.text,
      streaming: streaming ?? this.streaming,
    );
  }
}

final class ConfirmCard extends ChatMessage {
  const ConfirmCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.title,
    required this.body,
    required this.primaryLabel,
    required this.secondaryLabel,
    this.state = ConfirmCardState.pending,
    this.actedAt,
  }) : assert(title != '', 'title must not be empty'),
       assert(body != '', 'body must not be empty'),
       assert(primaryLabel != '', 'primaryLabel must not be empty'),
       assert(secondaryLabel != '', 'secondaryLabel must not be empty'),
       assert(
         primaryLabel != secondaryLabel,
         'primary and secondary labels must differ',
       ),
       assert(
         (state == ConfirmCardState.pending) == (actedAt == null),
         'pending requires actedAt == null; confirmed/revoked require actedAt != null',
       );

  final String title;
  final String body;
  final String primaryLabel;
  final String secondaryLabel;
  final ConfirmCardState state;
  final DateTime? actedAt;

  ConfirmCard copyWith({ConfirmCardState? state, Object? actedAt = unset}) {
    final nextState = state ?? this.state;
    final nextActedAt = identical(actedAt, unset)
        ? this.actedAt
        : actedAt as DateTime?;
    if ((nextState == ConfirmCardState.pending) != (nextActedAt == null)) {
      throw StateTransitionException(
        model: 'ConfirmCard',
        from: this.state.name,
        to: nextState.name,
        reason: 'pending requires actedAt == null; terminal requires actedAt != null',
      );
    }
    if (this.state != ConfirmCardState.pending && nextState != this.state) {
      throw StateTransitionException(
        model: 'ConfirmCard',
        from: this.state.name,
        to: nextState.name,
        reason: 'terminal confirm card cannot change state',
      );
    }
    assert(
      (nextState == ConfirmCardState.pending) == (nextActedAt == null),
      'pending requires actedAt == null; confirmed/revoked require actedAt != null',
    );
    return ConfirmCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      title: title,
      body: body,
      primaryLabel: primaryLabel,
      secondaryLabel: secondaryLabel,
      state: nextState,
      actedAt: nextActedAt,
    );
  }
}

final class ChoiceCard extends ChatMessage {
  // 含集合元素判断与不可变复制，构造函数不能是 const
  ChoiceCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.question,
    required List<String> options,
    this.answer,
  }) : options = List<String>.unmodifiable(options),
       assert(question != '', 'question must not be empty'),
       assert(
         options.length >= 2 && options.length <= 4,
         'choice card requires 2-4 options',
       ),
       assert(
         options.every((o) => o != ''),
         'choice options must not be empty',
       ),
       assert(
         options.toSet().length == options.length,
         'choice options must be unique',
       ),
       assert(
         answer == null || options.contains(answer),
         'answer must be one of options',
       );

  final String question;
  final List<String> options; // 2–4 项
  final String? answer; // 已选项；null = 未回答

  /// 已回答后只允许清空撤销，不允许改成另一个答案。
  ChoiceCard copyWith({Object? answer = unset}) {
    final nextAnswer = identical(answer, unset)
        ? this.answer
        : answer as String?;
    if (nextAnswer != null && !options.contains(nextAnswer)) {
      throw StateTransitionException(
        model: 'ChoiceCard',
        from: this.answer ?? 'unanswered',
        to: nextAnswer,
        reason: 'answer must be one of options',
      );
    }
    if (this.answer != null &&
        nextAnswer != null &&
        nextAnswer != this.answer) {
      throw StateTransitionException(
        model: 'ChoiceCard',
        from: this.answer!,
        to: nextAnswer,
        reason: 'answered choice can only be cleared, not replaced',
      );
    }
    assert(
      nextAnswer == null || options.contains(nextAnswer),
      'answer must be one of options',
    );
    return ChoiceCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      question: question,
      options: options,
      answer: nextAnswer,
    );
  }
}

class MemoryCandidateItem {
  const MemoryCandidateItem({
    required this.itemId,
    required this.label,
    this.state = MemoryCandidateState.pending,
  }) : assert(itemId != '', 'itemId must not be empty'),
       assert(label != '', 'label must not be empty');

  final String itemId;
  final String label;
  final MemoryCandidateState state;

  MemoryCandidateItem copyWith({MemoryCandidateState? state}) {
    return MemoryCandidateItem(
      itemId: itemId,
      label: label,
      state: state ?? this.state,
    );
  }
}

final class MemoryConfirmCard extends ChatMessage {
  // 含集合非空、唯一性与不可变复制，构造函数不能是 const
  MemoryConfirmCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required List<MemoryCandidateItem> items,
  }) : items = List<MemoryCandidateItem>.unmodifiable(items),
       assert(items.isNotEmpty, 'memory card requires at least one item'),
       assert(
         items.map((e) => e.itemId).toSet().length == items.length,
         'itemId must be unique within a memory card',
       );

  final List<MemoryCandidateItem> items;

  bool get allConfirmed =>
      items.isNotEmpty &&
      items.every((e) => e.state == MemoryCandidateState.confirmed);

  bool get allHandled =>
      items.isNotEmpty &&
      items.every((e) => e.state != MemoryCandidateState.pending);

  MemoryConfirmCard copyWith({List<MemoryCandidateItem>? items}) {
    final nextItems = items ?? this.items;
    assert(nextItems.isNotEmpty, 'memory card requires at least one item');
    assert(
      nextItems.map((e) => e.itemId).toSet().length == nextItems.length,
      'itemId must be unique within a memory card',
    );
    return MemoryConfirmCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      items: nextItems,
    );
  }
}

class PlanChange {
  const PlanChange({required this.type, required this.title, this.detail})
    : assert(title != '', 'plan change title must not be empty');

  final PlanChangeType type;
  final String title;
  final String? detail;
}

final class PlanProposalCard extends ChatMessage {
  // 含集合非空与不可变复制，构造函数不能是 const
  PlanProposalCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.summary,
    required List<PlanChange> changes,
    required this.rationale,
    this.state = PlanProposalState.pending,
  }) : changes = List<PlanChange>.unmodifiable(changes),
       assert(summary != '', 'summary must not be empty'),
       assert(changes.isNotEmpty, 'plan proposal requires at least one change'),
       assert(rationale != '', 'rationale must not be empty');

  final String summary;
  final List<PlanChange> changes;
  final String rationale;
  final PlanProposalState state;

  /// 终态不可回退，终态之间不可互转。
  PlanProposalCard copyWith({PlanProposalState? state}) {
    final nextState = state ?? this.state;
    if (this.state != PlanProposalState.pending && nextState != this.state) {
      throw StateTransitionException(
        model: 'PlanProposalCard',
        from: this.state.name,
        to: nextState.name,
        reason: 'terminal plan proposal cannot change state',
      );
    }
    assert(
      !(this.state != PlanProposalState.pending &&
          nextState == PlanProposalState.pending),
      'terminal plan proposal cannot return to pending',
    );
    return PlanProposalCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      summary: summary,
      changes: changes,
      rationale: rationale,
      state: nextState,
    );
  }
}

final class AgentInviteCard extends ChatMessage {
  const AgentInviteCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.inviteId,
    required this.initiatorAgent,
    required this.targetAgent,
    required this.topic,
    required this.goal,
    required this.scopeSummary,
    required this.expectedOutcome,
    this.projectId,
    this.status = AgentInviteStatus.pending,
    this.createdConversationId,
    this.accepting = false,
  }) : assert(inviteId != '', 'inviteId must not be empty'),
       assert(
         targetAgent == ConversationAgent.jarvis,
         'U1 invite target must be jarvis',
       ),
       assert(
         topic != '' &&
             goal != '' &&
             scopeSummary != '' &&
             expectedOutcome != '',
         'invite requires topic/goal/scopeSummary/expectedOutcome',
       ),
       assert(
         status == AgentInviteStatus.pending || !accepting,
         'accepting is only allowed while pending',
       ),
       assert(
         status != AgentInviteStatus.accepted || createdConversationId != null,
         'accepted invite requires createdConversationId',
       ),
       assert(
         status == AgentInviteStatus.accepted || createdConversationId == null,
         'unaccepted invite must not have createdConversationId',
       ),
       assert(
         createdConversationId == null || createdConversationId != '',
         'createdConversationId must not be empty',
       );

  final String inviteId;
  final ConversationAgent initiatorAgent; // 不含 user
  final ConversationAgent targetAgent; // U1 固定 jarvis
  final String? projectId;
  final String topic;
  final String goal;
  final String scopeSummary;
  final String expectedOutcome;
  final AgentInviteStatus status;
  final String? createdConversationId; // 接受后回填
  final bool accepting; // UI 处理中，防重复点击

  /// `accepted` 必须携带 `createdConversationId`；非 `accepted` 必须为空。
  AgentInviteCard copyWith({
    AgentInviteStatus? status,
    Object? createdConversationId = unset,
    bool? accepting,
  }) {
    final nextStatus = status ?? this.status;
    final nextCreatedConversationId = identical(createdConversationId, unset)
        ? this.createdConversationId
        : createdConversationId as String?;
    final nextAccepting = accepting ?? this.accepting;
    if (this.status != AgentInviteStatus.pending && nextStatus != this.status) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'terminal invite cannot change status',
      );
    }
    if (nextStatus != AgentInviteStatus.pending && nextAccepting) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'accepting is only allowed while pending',
      );
    }
    if (nextStatus == AgentInviteStatus.accepted &&
        nextCreatedConversationId == null) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'accepted invite requires createdConversationId',
      );
    }
    if (nextStatus != AgentInviteStatus.accepted &&
        nextCreatedConversationId != null) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'unaccepted invite must not have createdConversationId',
      );
    }
    if (nextCreatedConversationId == '') {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'createdConversationId must not be empty',
      );
    }
    assert(
      nextStatus == AgentInviteStatus.pending || !nextAccepting,
      'accepting is only allowed while pending',
    );
    assert(
      nextStatus != AgentInviteStatus.accepted ||
          nextCreatedConversationId != null,
      'accepted invite requires createdConversationId',
    );
    assert(
      nextStatus == AgentInviteStatus.accepted ||
          nextCreatedConversationId == null,
      'unaccepted invite must not have createdConversationId',
    );
    assert(
      nextCreatedConversationId == null || nextCreatedConversationId != '',
      'createdConversationId must not be empty',
    );
    return AgentInviteCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      inviteId: inviteId,
      initiatorAgent: initiatorAgent,
      targetAgent: targetAgent,
      topic: topic,
      goal: goal,
      scopeSummary: scopeSummary,
      expectedOutcome: expectedOutcome,
      projectId: projectId,
      status: nextStatus,
      createdConversationId: nextCreatedConversationId,
      accepting: nextAccepting,
    );
  }
}

final class ThinkingCard extends ChatMessage {
  const ThinkingCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    this.phase = ThinkingPhase.thinking,
  });

  final ThinkingPhase phase;

  ThinkingCard copyWith({ThinkingPhase? phase}) {
    return ThinkingCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      phase: phase ?? this.phase,
    );
  }
}
