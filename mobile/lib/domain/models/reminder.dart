/// 应用内提醒：到点的 reminder。
class DueReminder {
  const DueReminder({
    required this.id,
    required this.note,
    required this.fireAt,
    required this.status,
    this.expiresAt,
  }) : assert(id != '', 'reminder id must not be empty');

  final String id;
  final String note;
  final DateTime fireAt;
  final DateTime? expiresAt;

  /// pending | claimed | fired；仅用于展示与排查。
  final String status;
}
