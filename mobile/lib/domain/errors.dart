/// 领域层异常，对应 docs/mobile-u1-technical-plan.md 4.1、4.2.1 与 4.20。
library;

/// 业务状态转换失败；debug/release 都必须抛出。
///
/// 由 Presenter 转为用户提示，不崩溃。
class StateTransitionException implements Exception {
  const StateTransitionException({
    required this.model,
    required this.from,
    required this.to,
    required this.reason,
  });

  final String model;
  final String from;
  final String to;
  final String reason;

  @override
  String toString() =>
      'StateTransitionException($model: $from -> $to, $reason)';
}

/// 事件协议校验失败：整条事件被拒绝并按 4.20 进入安全恢复。
class ChatProtocolException implements Exception {
  const ChatProtocolException({
    required this.conversationId,
    required this.field,
    this.seq,
    required this.reason,
  });

  final String conversationId;
  final String field;

  /// 仅在事件携带 seq 时提供；快照级错误为 null。
  final int? seq;
  final String reason;

  @override
  String toString() =>
      'ChatProtocolException($conversationId, seq=$seq, '
      'field=$field, $reason)';
}

/// 快照校验失败：整份快照被拒绝，进入重同步；重试耗尽转 failed。
class SnapshotValidationException implements Exception {
  const SnapshotValidationException({
    required this.conversationId,
    required this.field,
    required this.reason,
  });

  final String conversationId;
  final String field;
  final String reason;

  @override
  String toString() =>
      'SnapshotValidationException($conversationId, field=$field, $reason)';
}

/// 首次加载失败：channel 无法取得快照，向上层暴露同步异常状态。
class SyncInitialLoadException implements Exception {
  const SyncInitialLoadException({
    required this.conversationId,
    required this.reason,
  });

  final String conversationId;
  final String reason;

  @override
  String toString() => 'SyncInitialLoadException($conversationId, $reason)';
}
