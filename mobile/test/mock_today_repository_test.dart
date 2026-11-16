import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/data/mock/mock_today_repository.dart';
import 'package:mobile/domain/enums.dart';

final class _FakeClock implements Clock {
  _FakeClock(this._now);

  final DateTime _now;

  @override
  DateTime now() => _now;
}

MockTodayRepository _repository() => MockTodayRepository(
  clock: _FakeClock(DateTime(2026, 11, 16, 9)),
  delay: Duration.zero,
);

void main() {
  test('loadDay 返回按 start 排序的条目与未排期任务', () async {
    final repository = _repository();
    final day = await repository.loadDay(DateTime(2026, 11, 16));

    expect(day.date, DateTime(2026, 11, 16));
    expect(day.items, isNotEmpty);
    expect(day.unscheduled, hasLength(2));
    for (var index = 1; index < day.items.length; index++) {
      expect(
        day.items[index].start!.isBefore(day.items[index - 1].start!),
        isFalse,
      );
    }
    expect(day.morningBrief?.kind, BriefKind.morning);
    expect(day.eveningBrief?.kind, BriefKind.evening);
  });

  test('complete 与 skip 更新状态', () async {
    final repository = _repository();

    final completed = await repository.complete('today-block-1');
    expect(completed.status, TodayItemStatus.done);

    final skipped = await repository.skip('today-reminder-1');
    expect(skipped.status, TodayItemStatus.skipped);
  });

  test('reschedule 更新 start 并保持排序', () async {
    final repository = _repository();

    final updated = await repository.reschedule(
      'today-task-1',
      DateTime(2026, 11, 16, 8),
    );
    expect(updated.start, DateTime(2026, 11, 16, 8));

    final day = await repository.loadDay(DateTime(2026, 11, 16));
    expect(day.items.first.id, 'today-task-1');
  });

  test('moveToToday 把未排期任务移入时间线', () async {
    final repository = _repository();

    final moved = await repository.moveToToday(
      'today-unscheduled-1',
      DateTime(2026, 11, 16, 18),
    );
    expect(moved.start, DateTime(2026, 11, 16, 18));

    final day = await repository.loadDay(DateTime(2026, 11, 16));
    expect(day.items.any((item) => item.id == 'today-unscheduled-1'), isTrue);
    expect(day.unscheduled.length, 1);
  });

  test('submitEveningReview 按完成情况更新状态', () async {
    final repository = _repository();

    await repository.submitEveningReview({'today-block-2': true});
    final day = await repository.loadDay(DateTime(2026, 11, 16));
    expect(
      day.items.firstWhere((item) => item.id == 'today-block-2').status,
      TodayItemStatus.done,
    );
  });
}
