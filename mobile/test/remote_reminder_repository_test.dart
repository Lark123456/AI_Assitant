import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_reminder_repository.dart';

class _FakeApiClient implements ApiClient {
  _FakeApiClient(this.payload);

  final Map<String, dynamic> payload;
  String? lastPath;

  @override
  Future<Map<String, dynamic>> getJson(String path) async {
    lastPath = path;
    return payload;
  }

  @override
  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  }) async => const {};
}

void main() {
  test('loadDueReminders 请求正确路径并解析字段', () async {
    final client = _FakeApiClient({
      'reminders': [
        {
          'id': 'r1',
          'note': '交报告',
          'fireAt': '2026-01-01T15:00:00+08:00',
          'expiresAt': '2026-01-02T15:00:00+08:00',
          'status': 'pending',
        },
      ],
    });
    final repository = RemoteReminderRepository(client: client);

    final reminders = await repository.loadDueReminders();

    expect(
      client.lastPath,
      '/api/mobile/reminders/due?graceMinutes=30&limit=20',
    );
    expect(reminders.single.id, 'r1');
    expect(reminders.single.note, '交报告');
    expect(reminders.single.fireAt, DateTime(2026, 1, 1, 15));
    expect(reminders.single.expiresAt, DateTime(2026, 1, 2, 15));
    expect(reminders.single.status, 'pending');
  });

  test('非法响应抛出 FormatException', () async {
    final repository = RemoteReminderRepository(
      client: _FakeApiClient({'reminders': 'nope'}),
    );

    expect(repository.loadDueReminders(), throwsA(isA<FormatException>()));
  });
}
