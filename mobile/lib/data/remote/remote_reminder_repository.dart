import '../../domain/models/reminder.dart';
import '../../domain/repositories/reminder_repository.dart';
import 'api_client.dart';

/// U2 应用内提醒真实仓库。
class RemoteReminderRepository implements ReminderRepository {
  RemoteReminderRepository({required this.client});

  final ApiClient client;

  @override
  Future<List<DueReminder>> loadDueReminders() async {
    final raw = await client.getJson(
      '/api/mobile/reminders/due?graceMinutes=30&limit=20',
    );
    final list = raw['reminders'];
    if (list is! List) {
      throw const FormatException('reminders 必须是数组');
    }
    return [for (final item in list) _parseReminder(item)];
  }
}

DueReminder _parseReminder(Object? raw) {
  if (raw is! Map<String, dynamic>) {
    throw const FormatException('reminder 必须是对象');
  }
  return DueReminder(
    id: _requireString(raw, 'id'),
    note: raw['note'] as String? ?? '',
    fireAt: _parseDate(raw['fireAt']),
    expiresAt: raw['expiresAt'] == null ? null : _parseDate(raw['expiresAt']),
    status: raw['status'] as String? ?? '',
  );
}

DateTime _parseDate(Object? raw) {
  if (raw is! String) throw const FormatException('时间必须是字符串');
  return DateTime.parse(raw).toLocal();
}

String _requireString(Map<String, dynamic> raw, String key) {
  final value = raw[key];
  if (value is! String || value.isEmpty) {
    throw FormatException('缺少字符串字段：$key');
  }
  return value;
}
