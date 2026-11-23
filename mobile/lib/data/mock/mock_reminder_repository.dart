import '../../domain/models/reminder.dart';
import '../../domain/repositories/reminder_repository.dart';

/// Mock 模式不产生应用内提醒。
class MockReminderRepository implements ReminderRepository {
  const MockReminderRepository();

  @override
  Future<List<DueReminder>> loadDueReminders() async => const [];
}
