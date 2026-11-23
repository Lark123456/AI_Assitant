import '../models/reminder.dart';

/// 应用内提醒数据来源：前台轮询到点提醒。
abstract interface class ReminderRepository {
  Future<List<DueReminder>> loadDueReminders();
}
