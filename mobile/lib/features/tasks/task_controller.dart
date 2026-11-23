import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../domain/models/task.dart';
import '../../domain/repositories/task_repository.dart';

/// 任务操作失败时在页面展示一次提示；null 表示无待展示错误。
class TaskActionError extends Notifier<String?> {
  @override
  String? build() => null;

  void show(String message) => state = message;

  void clear() => state = null;
}

final taskActionErrorProvider = NotifierProvider<TaskActionError, String?>(
  TaskActionError.new,
);

class TasksState {
  const TasksState({required this.filter, required this.tasks});

  final TaskFilter filter;
  final List<TaskItem> tasks;
}

/// 任务页唯一状态来源：过滤、列表与状态操作。
class TasksController extends AsyncNotifier<TasksState> {
  @override
  Future<TasksState> build() async {
    final repository = ref.watch(taskRepositoryProvider);
    final tasks = await repository.loadTasks();
    return TasksState(filter: TaskFilter.open, tasks: tasks);
  }

  Future<void> setFilter(TaskFilter filter) async {
    final current = state.value;
    if (current != null && current.filter == filter) return;
    state = const AsyncLoading();
    state = await AsyncValue.guard(() => _load(filter));
  }

  /// 下拉刷新或操作后重载；失败时保留旧数据并提示。
  Future<void> refresh() async {
    final filter = state.value?.filter ?? TaskFilter.open;
    try {
      state = AsyncData(await _load(filter));
    } catch (_) {
      ref.read(taskActionErrorProvider.notifier).show(S.refreshFailed);
    }
  }

  Future<void> complete(String taskId) =>
      _apply((repository) => repository.complete(taskId));

  Future<void> skip(String taskId) =>
      _apply((repository) => repository.skip(taskId));

  Future<void> restore(String taskId) =>
      _apply((repository) => repository.restore(taskId));

  Future<void> scheduleToday(String taskId, DateTime start) =>
      _apply((repository) => repository.scheduleToday(taskId, start));

  Future<void> _apply(
    Future<void> Function(TaskRepository repository) action,
  ) async {
    try {
      await action(ref.read(taskRepositoryProvider));
      await refresh();
    } catch (_) {
      ref.read(taskActionErrorProvider.notifier).show(S.actionFailed);
    }
  }

  Future<TasksState> _load(TaskFilter filter) async {
    final tasks = await ref
        .read(taskRepositoryProvider)
        .loadTasks(filter: filter);
    return TasksState(filter: filter, tasks: tasks);
  }
}

final tasksControllerProvider =
    AsyncNotifierProvider<TasksController, TasksState>(TasksController.new);
