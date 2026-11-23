import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/domain/models/reminder.dart';
import 'package:mobile/domain/repositories/reminder_repository.dart';
import 'package:mobile/features/reminders/reminder_controller.dart';

class _FakeReminderRepository implements ReminderRepository {
  _FakeReminderRepository(this.reminders);

  final List<DueReminder> reminders;
  var calls = 0;

  @override
  Future<List<DueReminder>> loadDueReminders() async {
    calls += 1;
    return reminders;
  }
}

DueReminder _reminder(String id, String note) => DueReminder(
  id: id,
  note: note,
  fireAt: DateTime(2026, 11, 16, 9),
  status: 'pending',
);

void main() {
  test('前台立即刷新并按 trigger 去重', () async {
    final repository = _FakeReminderRepository([
      _reminder('r1', '交报告'),
      _reminder('r2', '开会'),
    ]);
    final container = ProviderContainer(
      overrides: [reminderRepositoryProvider.overrideWithValue(repository)],
    );
    addTearDown(container.dispose);
    final notifier = container.read(reminderAlertProvider.notifier);

    await notifier.setActive(true);
    expect(container.read(reminderAlertProvider)?.id, 'r1');

    notifier.dismiss();
    expect(container.read(reminderAlertProvider), isNull);

    await notifier.refresh();
    expect(container.read(reminderAlertProvider)?.id, 'r2');

    notifier.dismiss();
    await notifier.refresh();
    expect(container.read(reminderAlertProvider), isNull);

    await notifier.setActive(false);
  });

  test('后台不轮询提醒', () async {
    final repository = _FakeReminderRepository([_reminder('r1', '交报告')]);
    final container = ProviderContainer(
      overrides: [reminderRepositoryProvider.overrideWithValue(repository)],
    );
    addTearDown(container.dispose);
    final notifier = container.read(reminderAlertProvider.notifier);

    await notifier.setActive(false);
    final calls = repository.calls;
    await notifier.refresh();

    expect(repository.calls, calls);
    expect(container.read(reminderAlertProvider), isNull);
  });
}
