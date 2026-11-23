import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_task_repository.dart';
import 'package:mobile/domain/models/task.dart';

class _FakeApiClient implements ApiClient {
  _FakeApiClient({required this.getResponse});

  final Map<String, dynamic> Function(String path) getResponse;
  String? lastGetPath;
  String? lastPostPath;
  String? lastIdempotencyKey;
  Map<String, dynamic>? lastBody;

  @override
  Future<Map<String, dynamic>> getJson(String path) async {
    lastGetPath = path;
    return getResponse(path);
  }

  @override
  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  }) async {
    lastPostPath = path;
    lastBody = body;
    lastIdempotencyKey = idempotencyKey;
    return const {};
  }
}

Map<String, dynamic> _task({
  required String id,
  required String title,
  required String status,
  String? description,
  Map<String, dynamic>? upcomingBlock,
}) => {
  'id': id,
  'title': title,
  'description': description,
  'status': status,
  'createdAt': '2026-01-01T08:00:00+08:00',
  'updatedAt': '2026-01-01T08:10:00+08:00',
  'upcomingBlock': upcomingBlock,
};

void main() {
  test('loadTasks 请求正确路径并解析状态与计划块', () async {
    final client = _FakeApiClient(
      getResponse: (path) => {
        'tasks': [
          _task(id: 't1', title: '写报告', status: 'open', description: '季度'),
          _task(
            id: 't2',
            title: '回复邮件',
            status: 'done',
            upcomingBlock: {
              'id': 'b1',
              'start': '2026-01-01T09:00:00+08:00',
              'end': '2026-01-01T10:00:00+08:00',
              'status': 'planned',
            },
          ),
        ],
      },
    );
    final repository = RemoteTaskRepository(client: client);

    final tasks = await repository.loadTasks(filter: TaskFilter.open);

    expect(client.lastGetPath, '/api/mobile/tasks?status=open&limit=100');
    expect(tasks.map((task) => task.status), [
      TaskStatus.open,
      TaskStatus.done,
    ]);
    expect(tasks[0].title, '写报告');
    expect(tasks[0].description, '季度');
    expect(tasks[0].upcomingBlock, isNull);
    expect(tasks[1].upcomingBlock?.id, 'b1');
    expect(tasks[1].upcomingBlock?.start, DateTime(2026, 1, 1, 9));
  });

  test('写操作复用 Today 端点并生成幂等键', () async {
    final client = _FakeApiClient(getResponse: (path) => {'tasks': []});
    final repository = RemoteTaskRepository(client: client);

    await repository.complete('task-1');
    expect(client.lastPostPath, '/api/mobile/today/items/task-1/complete');
    expect(client.lastIdempotencyKey, isNotEmpty);

    await repository.skip('task-1');
    expect(client.lastPostPath, '/api/mobile/today/items/task-1/skip');

    await repository.restore('task-1');
    expect(client.lastPostPath, '/api/mobile/today/items/task-1/restore');

    final start = DateTime(2026, 1, 1, 18);
    await repository.scheduleToday('task-1', start);
    expect(client.lastPostPath, '/api/mobile/today/tasks/task-1/schedule');
    expect(client.lastBody?['startsAt'], start.toUtc().toIso8601String());
  });

  test('非法响应抛出 FormatException', () async {
    final client = _FakeApiClient(getResponse: (path) => {'tasks': 'nope'});
    final repository = RemoteTaskRepository(client: client);

    expect(repository.loadTasks(), throwsA(isA<FormatException>()));
  });
}
