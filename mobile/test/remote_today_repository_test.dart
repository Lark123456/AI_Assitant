import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_today_repository.dart';
import 'package:mobile/domain/enums.dart';

class _FakeApiClient implements ApiClient {
  _FakeApiClient(this.payload, {this.postResponse});

  final Map<String, dynamic> payload;
  final Map<String, dynamic>? postResponse;
  String? lastPath;
  String? lastPostPath;
  Map<String, dynamic>? lastPostBody;
  String? lastIdempotencyKey;
  var postCount = 0;

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
  }) async {
    lastPostPath = path;
    lastPostBody = body;
    lastIdempotencyKey = idempotencyKey;
    postCount += 1;
    return postResponse ?? payload;
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

Map<String, dynamic> _doneBlock() => {
  'id': 'block-1',
  'kind': 'block',
  'title': '专注写作',
  'status': 'done',
  'compressible': true,
  'syncState': 'synced',
  'start': '2026-11-16T09:00:00+08:00',
  'end': '2026-11-16T10:00:00+08:00',
  'durationMin': 60,
  'sourceTag': '日程',
  'reason': null,
};

Map<String, dynamic> _blockAt(String start, String end, {int? durationMin}) => {
  ..._doneBlock(),
  'status': 'planned',
  'start': start,
  'end': end,
  'durationMin': durationMin ?? _doneBlock()['durationMin'],
};

void main() {
  test('解析真实 Today 响应并请求正确日期', () async {
    final client = _FakeApiClient(_payload());
    final repository = RemoteTodayRepository(client: client);

    final day = await repository.loadDay(DateTime(2026, 11, 16));

    expect(client.lastPath, '/api/mobile/today?date=2026-11-16');
    expect(repository.readOnly, isFalse);
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

  test('完成与跳过调用对应接口并携带幂等键', () async {
    final client = _FakeApiClient(_payload(), postResponse: _doneBlock());
    final repository = RemoteTodayRepository(client: client);

    final completed = await repository.complete('block-1');
    final firstKey = client.lastIdempotencyKey;
    await repository.skip('block-1');

    expect(client.lastPostPath, '/api/mobile/today/items/block-1/skip');
    expect(client.lastPostBody, isEmpty);
    expect(firstKey, isNotEmpty);
    expect(client.lastIdempotencyKey, isNotEmpty);
    expect(client.lastIdempotencyKey, isNot(firstKey));
    expect(completed.status, TodayItemStatus.done);
    expect(client.postCount, 2);
  });

  test('改期发送 UTC ISO 时间', () async {
    final client = _FakeApiClient(
      _payload(),
      postResponse: _blockAt(
        '2026-11-16T09:30:00+08:00',
        '2026-11-16T10:00:00+08:00',
        durationMin: 30,
      ),
    );
    final repository = RemoteTodayRepository(client: client);

    final updated = await repository.reschedule(
      'block-1',
      DateTime.utc(2026, 11, 16, 1, 30),
    );

    expect(client.lastPostPath, '/api/mobile/today/items/block-1/reschedule');
    expect(client.lastPostBody, {'startsAt': '2026-11-16T01:30:00.000Z'});
    expect(updated.status, TodayItemStatus.planned);
    expect(updated.durationMin, 30);
  });

  test('未排期任务排进今天调用 schedule 接口', () async {
    final client = _FakeApiClient(
      _payload(),
      postResponse: _blockAt(
        '2026-11-16T18:00:00+08:00',
        '2026-11-16T19:00:00+08:00',
      ),
    );
    final repository = RemoteTodayRepository(client: client);

    final moved = await repository.moveToToday(
      'task-1',
      DateTime.utc(2026, 11, 16, 10),
    );

    expect(client.lastPostPath, '/api/mobile/today/tasks/task-1/schedule');
    expect(client.lastPostBody, {'startsAt': '2026-11-16T10:00:00.000Z'});
    expect(moved.kind, TodayItemKind.block);
  });

  test('晚间复盘提交完成状态列表', () async {
    final client = _FakeApiClient(_payload(), postResponse: const {});
    final repository = RemoteTodayRepository(client: client);

    await repository.submitEveningReview({'block-1': true, 'task-1': false});

    expect(client.lastPostPath, '/api/mobile/today/review');
    expect(client.lastPostBody, {
      'results': [
        {'itemId': 'block-1', 'done': true},
        {'itemId': 'task-1', 'done': false},
      ],
    });
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
