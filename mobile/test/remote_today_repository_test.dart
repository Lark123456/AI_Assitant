import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_today_repository.dart';
import 'package:mobile/domain/enums.dart';

class _FakeApiClient implements ApiClient {
  _FakeApiClient(this.payload);

  final Map<String, dynamic> payload;
  String? lastPath;

  @override
  Future<Map<String, dynamic>> getJson(String path) async {
    lastPath = path;
    return payload;
  }
}

Map<String, dynamic> _payload() => {
  'date': '2026-11-16',
  'items': [
    {
      'id': 'block-1',
      'kind': 'block',
      'title': '专注写作',
      'status': 'planned',
      'compressible': true,
      'syncState': 'synced',
      'start': '2026-11-16T09:00:00+08:00',
      'end': '2026-11-16T10:00:00+08:00',
      'durationMin': 60,
      'sourceTag': '日程',
      'reason': null,
    },
    {
      'id': 'reminder-1',
      'kind': 'reminder',
      'title': '喝水',
      'status': 'done',
      'compressible': false,
      'syncState': 'synced',
      'start': '2026-11-16T11:30:00+08:00',
      'end': null,
      'durationMin': null,
      'sourceTag': '提醒',
      'reason': null,
    },
  ],
  'unscheduled': [
    {
      'id': 'task-1',
      'kind': 'task',
      'title': '整理笔记',
      'status': 'planned',
      'compressible': true,
      'syncState': 'synced',
      'start': null,
      'end': null,
      'durationMin': null,
      'sourceTag': '任务',
      'reason': '还没安排时间',
    },
  ],
  'morningBrief': null,
  'eveningBrief': null,
};

void main() {
  test('解析真实 Today 响应并请求正确日期', () async {
    final client = _FakeApiClient(_payload());
    final repository = RemoteTodayRepository(client: client);

    final day = await repository.loadDay(DateTime(2026, 11, 16));

    expect(client.lastPath, '/api/mobile/today?date=2026-11-16');
    expect(repository.readOnly, isTrue);
    expect(day.date, DateTime(2026, 11, 16));
    expect(day.items, hasLength(2));
    expect(day.items.first.kind, TodayItemKind.block);
    expect(day.items.first.status, TodayItemStatus.planned);
    expect(day.items.first.start!.toUtc(), DateTime.utc(2026, 11, 16, 1));
    expect(day.items.first.durationMin, 60);
    expect(day.items.last.kind, TodayItemKind.reminder);
    expect(day.items.last.status, TodayItemStatus.done);
    expect(day.unscheduled, hasLength(1));
    expect(day.unscheduled.single.kind, TodayItemKind.task);
    expect(day.unscheduled.single.start, isNull);
    expect(day.morningBrief, isNull);
    expect(day.eveningBrief, isNull);
  });

  test('写操作在只读仓库明确失败', () async {
    final repository = RemoteTodayRepository(
      client: _FakeApiClient(_payload()),
    );

    expect(
      () => repository.complete('block-1'),
      throwsA(isA<UnsupportedError>()),
    );
    expect(
      () => repository.reschedule('block-1', DateTime(2026, 11, 16, 8)),
      throwsA(isA<UnsupportedError>()),
    );
  });

  test('未知状态抛出格式错误', () async {
    final payload = _payload();
    (payload['items'] as List).first['status'] = 'unknown';
    final repository = RemoteTodayRepository(client: _FakeApiClient(payload));

    expect(
      () => repository.loadDay(DateTime(2026, 11, 16)),
      throwsA(isA<FormatException>()),
    );
  });
}
