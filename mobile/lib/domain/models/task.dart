/// 任务页模型：与后端 `/api/mobile/tasks` 对齐。
enum TaskStatus { open, done, skipped }

enum TaskFilter { open, done, all }

extension TaskFilterWire on TaskFilter {
  String get wireValue => switch (this) {
    TaskFilter.open => 'open',
    TaskFilter.done => 'done',
    TaskFilter.all => 'all',
  };
}

class TaskBlock {
  const TaskBlock({required this.id, required this.start, required this.end})
    : assert(id != '', 'block id must not be empty');

  final String id;
  final DateTime start;
  final DateTime end;
}

class TaskItem {
  const TaskItem({
    required this.id,
    required this.title,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    this.description,
    this.upcomingBlock,
  }) : assert(id != '', 'task id must not be empty'),
       assert(title != '', 'task title must not be empty');

  final String id;
  final String title;
  final String? description;
  final TaskStatus status;
  final DateTime createdAt;
  final DateTime updatedAt;
  final TaskBlock? upcomingBlock;

  TaskItem copyWith({TaskStatus? status, TaskBlock? upcomingBlock}) {
    return TaskItem(
      id: id,
      title: title,
      description: description,
      status: status ?? this.status,
      createdAt: createdAt,
      updatedAt: updatedAt,
      upcomingBlock: upcomingBlock ?? this.upcomingBlock,
    );
  }
}
