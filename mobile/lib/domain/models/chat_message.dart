import '../enums.dart';
import '../errors.dart';
import 'unset.dart';

/// 聊天消息基类；U1 只有一条 Friday 主对话，因此不含会话字段与事件序号。
///
/// 排序规则：`createdAt` 升序；相同时按 `id` 字典序，保证稳定。
sealed class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.sender,
    required this.createdAt,
    this.reason,
    this.syncState = SyncState.synced,
  }) : assert(id != '', 'message id must not be empty');

  final String id; // 全局唯一
  final ChatSender sender;
  final DateTime createdAt;
  final String? reason; // 主动消息的理由
  final SyncState syncState;
}

final class TextMessage extends ChatMessage {
  const TextMessage({
    required super.id,
    required super.sender,
    required super.createdAt,
    super.reason,
    super.syncState,
    this.text = '',
    this.streaming = false,
  });

  final String text;
  final bool streaming;

  TextMessage copyWith({String? text, bool? streaming, SyncState? syncState}) {
    return TextMessage(
      id: id,
      sender: sender,
      createdAt: createdAt,
      reason: reason,
      syncState: syncState ?? this.syncState,
      text: text ?? this.text,
      streaming: streaming ?? this.streaming,
    );
  }
}

final class ConfirmCard extends ChatMessage {
  const ConfirmCard({
    required super.id,
    required super.sender,
    required super.createdAt,
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
      sender: sender,
      createdAt: createdAt,
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
    required super.sender,
    required super.createdAt,
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
      sender: sender,
      createdAt: createdAt,
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
    required super.sender,
    required super.createdAt,
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
      sender: sender,
      createdAt: createdAt,
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
    required super.sender,
    required super.createdAt,
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
      sender: sender,
      createdAt: createdAt,
      reason: reason,
      syncState: syncState,
      summary: summary,
      changes: changes,
      rationale: rationale,
      state: nextState,
    );
  }
}

/// Jarvis 引荐卡片：不创建会话，接受后由假数据仓库在同一消息流追加后续消息。
final class JarvisIntroCard extends ChatMessage {
  // 含集合非空、唯一性与不可变复制，构造函数不能是 const
  JarvisIntroCard({
    required super.id,
    required super.sender,
    required super.createdAt,
    super.reason,
    super.syncState,
    required this.summary,
    required List<String> previewQuestions,
    this.state = JarvisIntroState.open,
  }) : previewQuestions = List<String>.unmodifiable(previewQuestions),
       assert(summary != '', 'summary must not be empty'),
       assert(
         previewQuestions.isNotEmpty && previewQuestions.length <= 3,
         'jarvis intro requires 1-3 preview questions',
       ),
       assert(
         previewQuestions.every((q) => q != ''),
         'preview questions must not be empty',
       ),
       assert(
         previewQuestions.toSet().length == previewQuestions.length,
         'preview questions must be unique',
       );

  final String summary; // 粗估说明
  final List<String> previewQuestions; // 最多 3 个
  final JarvisIntroState state;

  /// 终态（accepted / declined）不可回到 open，也不可互转。
  JarvisIntroCard copyWith({JarvisIntroState? state}) {
    final nextState = state ?? this.state;
    if (this.state != JarvisIntroState.open && nextState != this.state) {
      throw StateTransitionException(
        model: 'JarvisIntroCard',
        from: this.state.name,
        to: nextState.name,
        reason: 'terminal jarvis intro cannot change state',
      );
    }
    assert(
      !(this.state != JarvisIntroState.open &&
          nextState == JarvisIntroState.open),
      'terminal jarvis intro cannot return to open',
    );
    return JarvisIntroCard(
      id: id,
      sender: sender,
      createdAt: createdAt,
      reason: reason,
      syncState: syncState,
      summary: summary,
      previewQuestions: previewQuestions,
      state: nextState,
    );
  }
}

final class ThinkingCard extends ChatMessage {
  const ThinkingCard({
    required super.id,
    required super.sender,
    required super.createdAt,
    super.reason,
    super.syncState,
    this.phase = ThinkingPhase.thinking,
  });

  final ThinkingPhase phase;

  ThinkingCard copyWith({ThinkingPhase? phase}) {
    return ThinkingCard(
      id: id,
      sender: sender,
      createdAt: createdAt,
      reason: reason,
      syncState: syncState,
      phase: phase ?? this.phase,
    );
  }
}
