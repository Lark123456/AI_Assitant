import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 唯一时间来源；业务代码不得直接使用 DateTime.now()。
abstract interface class Clock {
  DateTime now();
}

final class SystemClock implements Clock {
  const SystemClock();

  @override
  DateTime now() => DateTime.now();
}

final class FixedClock implements Clock {
  const FixedClock(this._now);

  final DateTime _now;

  @override
  DateTime now() => _now;
}

/// 调试用模拟时间；null 表示使用系统时间。
class SimulatedTimeController extends Notifier<DateTime?> {
  @override
  DateTime? build() => null;

  void set(DateTime? value) => state = value;

  void clear() => state = null;
}

final simulatedTimeProvider =
    NotifierProvider<SimulatedTimeController, DateTime?>(
      SimulatedTimeController.new,
    );

final clockProvider = Provider<Clock>((ref) {
  final simulated = ref.watch(simulatedTimeProvider);
  return simulated == null ? const SystemClock() : FixedClock(simulated);
});
