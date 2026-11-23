import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../domain/models/reminder.dart';

/// Shell 级应用内提醒：前台每 30 秒轮询，同一 trigger 本会话只提示一次。
class ReminderAlertController extends Notifier<DueReminder?> {
  Timer? _timer;
  final Set<String> _seen = {};
  var _active = false;

  @override
  DueReminder? build() {
    ref.onDispose(_stopTimer);
    return null;
  }

  /// App 前台时启动并立即刷新；进入后台/销毁时停止。
  Future<void> setActive(bool active) async {
    _active = active;
    if (!active) {
      _stopTimer();
      return;
    }
    await refresh();
    _timer ??= Timer.periodic(
      const Duration(seconds: 30),
      (_) => unawaited(refresh()),
    );
  }

  Future<void> refresh() async {
    // 已有横幅时不覆盖，等用户关闭后再提示下一条。
    if (!_active || state != null) return;
    try {
      final reminders = await ref
          .read(reminderRepositoryProvider)
          .loadDueReminders();
      for (final reminder in reminders) {
        if (_seen.contains(reminder.id)) continue;
        state = reminder;
        return;
      }
    } catch (_) {
      // 提醒轮询失败静默处理，下一轮重试；不打断当前页面。
    }
  }

  /// 仅本地隐藏；不写后端 ack。
  void dismiss() {
    final current = state;
    if (current != null) _seen.add(current.id);
    state = null;
  }

  void _stopTimer() {
    _timer?.cancel();
    _timer = null;
  }
}

final reminderAlertProvider =
    NotifierProvider<ReminderAlertController, DueReminder?>(
      ReminderAlertController.new,
    );
