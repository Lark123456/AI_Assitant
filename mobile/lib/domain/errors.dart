/// 领域层异常，对应 docs/mobile-u1-plan.md。
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
