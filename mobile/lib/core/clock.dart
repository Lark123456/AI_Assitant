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

final clockProvider = Provider<Clock>((ref) => const SystemClock());
