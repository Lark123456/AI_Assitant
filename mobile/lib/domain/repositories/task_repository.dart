import '../models/task.dart';

/// 任务页数据来源：列表 + 状态操作；写操作复用 Today 接口。
abstract interface class TaskRepository {
  Future<List<TaskItem>> loadTasks({TaskFilter filter = TaskFilter.open});

  Future<void> complete(String taskId);

  Future<void> skip(String taskId);

  Future<void> restore(String taskId);

  Future<void> scheduleToday(String taskId, DateTime start);
}
