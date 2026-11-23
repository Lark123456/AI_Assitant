import '../../core/clock.dart';
import '../../domain/models/task.dart';
import '../../domain/repositories/task_repository.dart';

/// Mock 任务仓库：固定种子 + 内存状态变更。
class MockTaskRepository implements TaskRepository {
  MockTaskRepository({
    required Clock clock,
    this.delay = const Duration(milliseconds: 150),
  }) : _tasks = _seed(clock.now());

  final Duration delay;
  final List<TaskItem> _tasks;

  @override
  Future<List<TaskItem>> loadTasks({
    TaskFilter filter = TaskFilter.open,
  }) async {
    await Future<void>.delayed(delay);
    final statuses = switch (filter) {
      TaskFilter.open => {TaskStatus.open},
      TaskFilter.done => {TaskStatus.done},
      TaskFilter.all => {TaskStatus.open, TaskStatus.done, TaskStatus.skipped},
    };
    final rows = _tasks.where((task) => statuses.contains(task.status)).toList()
      ..sort((left, right) {
        final byTime = right.updatedAt.compareTo(left.updatedAt);
        return byTime != 0 ? byTime : right.id.compareTo(left.id);
      });
    return List<TaskItem>.unmodifiable(rows);
  }

  @override
  Future<void> complete(String taskId) => _setStatus(taskId, TaskStatus.done);

  @override
  Future<void> skip(String taskId) => _setStatus(taskId, TaskStatus.skipped);

  @override
  Future<void> restore(String taskId) => _setStatus(taskId, TaskStatus.open);

  @override
  Future<void> scheduleToday(String taskId, DateTime start) async {
    await Future<void>.delayed(delay);
    final index = _indexOf(taskId);
    final task = _tasks[index];
    if (task.status != TaskStatus.open) {
      throw StateError('只有未完成任务可以排期');
    }
    _tasks[index] = task.copyWith(
      upcomingBlock: TaskBlock(
        id: 'block-$taskId',
        start: start,
        end: start.add(const Duration(hours: 1)),
      ),
    );
  }

  Future<void> _setStatus(String taskId, TaskStatus status) async {
    await Future<void>.delayed(delay);
    final index = _indexOf(taskId);
    _tasks[index] = _tasks[index].copyWith(status: status);
  }

  int _indexOf(String taskId) {
    final index = _tasks.indexWhere((task) => task.id == taskId);
    if (index < 0) {
      throw ArgumentError.value(taskId, 'taskId', 'task not found');
    }
    return index;
  }

  static List<TaskItem> _seed(DateTime now) {
    final today = DateTime(now.year, now.month, now.day);
    return [
      TaskItem(
        id: 'task-1',
        title: '写周报',
        description: '周五前交',
        status: TaskStatus.open,
        createdAt: now.subtract(const Duration(days: 1)),
        updatedAt: now.subtract(const Duration(minutes: 5)),
      ),
      TaskItem(
        id: 'task-2',
        title: '整理笔记',
        status: TaskStatus.open,
        createdAt: now.subtract(const Duration(days: 2)),
        updatedAt: now.subtract(const Duration(minutes: 10)),
        upcomingBlock: TaskBlock(
          id: 'block-task-2',
          start: DateTime(today.year, today.month, today.day, 14),
          end: DateTime(today.year, today.month, today.day, 15),
        ),
      ),
      TaskItem(
        id: 'task-3',
        title: '回复邮件',
        status: TaskStatus.done,
        createdAt: now.subtract(const Duration(days: 3)),
        updatedAt: now.subtract(const Duration(hours: 1)),
      ),
      TaskItem(
        id: 'task-4',
        title: '取消的会议',
        status: TaskStatus.skipped,
        createdAt: now.subtract(const Duration(days: 4)),
        updatedAt: now.subtract(const Duration(hours: 2)),
      ),
    ];
  }
}
