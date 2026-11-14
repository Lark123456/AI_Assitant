import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/format.dart';
import 'package:mobile/core/strings.dart';

final class _FakeClock implements Clock {
  _FakeClock(this._now);

  final DateTime _now;

  @override
  DateTime now() => _now;
}

void main() {
  setUpAll(() async {
    await initializeDateFormatting('zh_CN');
  });

  test('clockProvider 默认使用 SystemClock', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(clockProvider), isA<SystemClock>());
  });

  test('FakeClock 返回注入时间', () {
    final clock = _FakeClock(DateTime(2026, 11, 15, 9, 30));

    expect(clock.now(), DateTime(2026, 11, 15, 9, 30));
  });

  test('greetingFor 按小时切换问候语', () {
    expect(greetingFor(DateTime(2026, 11, 15, 5)), S.greetingMorning);
    expect(greetingFor(DateTime(2026, 11, 15, 11, 59)), S.greetingMorning);
    expect(greetingFor(DateTime(2026, 11, 15, 12)), S.greetingNoon);
    expect(greetingFor(DateTime(2026, 11, 15, 14)), S.greetingAfternoon);
    expect(greetingFor(DateTime(2026, 11, 15, 18)), S.greetingEvening);
    expect(greetingFor(DateTime(2026, 11, 15, 23)), S.greetingDawn);
    expect(greetingFor(DateTime(2026, 11, 15, 3)), S.greetingDawn);
  });

  test('formatDuration 输出中文时长', () {
    expect(formatDuration(0), '0 分钟');
    expect(formatDuration(25), '25 分钟');
    expect(formatDuration(60), '1 小时');
    expect(formatDuration(90), '1 小时 30 分钟');
    expect(formatDuration(120), '2 小时');
  });

  test('日期格式为 zh_CN', () {
    final date = DateTime(2026, 11, 15, 14, 5);

    expect(formatMonthDay(date), '11月15日');
    expect(formatWeekday(date), '周日');
    expect(formatDayTitle(date), '11月15日 周日');
    expect(formatClockTime(date), '14:05');
  });
}
