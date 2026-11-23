import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/data/mock/mock_task_repository.dart';
import 'package:mobile/domain/models/task.dart';
import 'package:mobile/domain/repositories/task_repository.dart';
import 'package:mobile/features/tasks/tasks_page.dart';

final _now = DateTime(2026, 11, 16, 9);

final class _FakeClock implements Clock {
  @override
  DateTime now() => _now;
}

final class _ThrowingRepository implements TaskRepository {
  @override
  Future<List<TaskItem>> loadTasks({
    TaskFilter filter = TaskFilter.open,
  }) async {
    throw StateError('boom');
  }

  @override
  Future<void> complete(String taskId) async {}

  @override
  Future<void> skip(String taskId) async {}

  @override
  Future<void> restore(String taskId) async {}

  @override
  Future<void> scheduleToday(String taskId, DateTime start) async {}
}

Widget _app({TaskRepository? repository}) {
  final clock = _FakeClock();
  return ProviderScope(
    overrides: [
      clockProvider.overrideWithValue(clock),
      taskRepositoryProvider.overrideWithValue(
        repository ?? MockTaskRepository(clock: clock, delay: Duration.zero),
      ),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const TasksPage()),
  );
}

Finder _filterChip(String label) => find.widgetWithText(ChoiceChip, label);

void main() {
  testWidgets('默认展示未完成任务', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    expect(find.text('写周报'), findsOneWidget);
    expect(find.text('整理笔记'), findsOneWidget);
    expect(find.text('回复邮件'), findsNothing);
    expect(find.textContaining(S.taskUpcoming), findsOneWidget);
  });

  testWidgets('切换过滤展示已完成与全部任务', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.tap(_filterChip(S.taskFilterDone));
    await tester.pumpAndSettle();
    expect(find.text('回复邮件'), findsOneWidget);
    expect(find.text('写周报'), findsNothing);

    await tester.tap(_filterChip(S.taskFilterAll));
    await tester.pumpAndSettle();
    expect(find.text('写周报'), findsOneWidget);
    expect(find.text('取消的会议'), findsOneWidget);
  });

  testWidgets('完成任务后从未完成列表移除', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, S.markDone).first);
    await tester.pumpAndSettle();

    expect(find.text('写周报'), findsNothing);
    expect(find.text('整理笔记'), findsOneWidget);
  });

  testWidgets('排进今天后展示下一个安排', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.tap(find.text(S.planForToday));
    await tester.pumpAndSettle();

    expect(find.textContaining(S.taskUpcoming), findsNWidgets(2));
  });

  testWidgets('加载失败显示错误与重试', (tester) async {
    await tester.pumpWidget(_app(repository: _ThrowingRepository()));
    await tester.pumpAndSettle();

    expect(find.text(S.loadingFailed), findsOneWidget);
    expect(find.text(S.retry), findsOneWidget);
  });
}
