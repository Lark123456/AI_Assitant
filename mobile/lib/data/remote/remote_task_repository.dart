import 'dart:math';

import '../../domain/models/task.dart';
import '../../domain/repositories/task_repository.dart';
import 'api_client.dart';

/// U2 任务页真实仓库：列表走 tasks API，写操作复用 Today 端点。
class RemoteTaskRepository implements TaskRepository {
  RemoteTaskRepository({required this.client, Random? random})
    : _random = random ?? Random.secure();

  final ApiClient client;
  final Random _random;
  var _sequence = 0;

  @override
  Future<List<TaskItem>> loadTasks({
    TaskFilter filter = TaskFilter.open,
  }) async {
    final raw = await client.getJson(
      '/api/mobile/tasks?status=${filter.wireValue}&limit=100',
    );
    final list = raw['tasks'];
    if (list is! List) {
      throw const FormatException('tasks 必须是数组');
    }
    return [for (final item in list) _parseTask(item)];
  }

  @override
  Future<void> complete(String taskId) => _postTodayAction(taskId, 'complete');

  @override
  Future<void> skip(String taskId) => _postTodayAction(taskId, 'skip');

  @override
  Future<void> restore(String taskId) => _postTodayAction(taskId, 'restore');

  @override
  Future<void> scheduleToday(String taskId, DateTime start) async {
    await client.postJson(
      '/api/mobile/today/tasks/${Uri.encodeComponent(taskId)}/schedule',
      {'startsAt': start.toUtc().toIso8601String()},
      idempotencyKey: _nextKey(),
    );
  }

  Future<void> _postTodayAction(String taskId, String action) async {
    await client.postJson(
      '/api/mobile/today/items/${Uri.encodeComponent(taskId)}/$action',
      const {},
      idempotencyKey: _nextKey(),
    );
  }

  String _nextKey() {
    _sequence += 1;
    final random = List<String>.generate(
      4,
      (_) => _random.nextInt(0x100000000).toRadixString(16).padLeft(8, '0'),
    ).join();
    return 't$_sequence-$random';
  }
}

TaskItem _parseTask(Object? raw) {
  if (raw is! Map<String, dynamic>) {
    throw const FormatException('task 必须是对象');
  }
  return TaskItem(
    id: _requireString(raw, 'id'),
    title: _requireString(raw, 'title'),
    description: raw['description'] as String?,
    status: _parseStatus(_requireString(raw, 'status')),
    createdAt: _parseDate(raw['createdAt']),
    updatedAt: _parseDate(raw['updatedAt']),
    upcomingBlock: _parseBlock(raw['upcomingBlock']),
  );
}

TaskBlock? _parseBlock(Object? raw) {
  if (raw == null) return null;
  if (raw is! Map<String, dynamic>) {
    throw const FormatException('upcomingBlock 必须是对象');
  }
  return TaskBlock(
    id: _requireString(raw, 'id'),
    start: _parseDate(raw['start']),
    end: _parseDate(raw['end']),
  );
}

TaskStatus _parseStatus(String raw) => switch (raw) {
  'open' => TaskStatus.open,
  'done' => TaskStatus.done,
  'skipped' => TaskStatus.skipped,
  _ => throw FormatException('未知任务状态：$raw'),
};

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
