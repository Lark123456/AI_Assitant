import 'package:intl/intl.dart';

import 'strings.dart';

final DateFormat _monthDay = DateFormat('M月d日', 'zh_CN');
final DateFormat _weekday = DateFormat('E', 'zh_CN');
final DateFormat _clockTime = DateFormat('HH:mm');

/// 按小时返回问候语：5–11 早上、12–13 中午、14–17 下午、18–22 晚上，其余夜深。
String greetingFor(DateTime now) {
  final hour = now.hour;
  if (hour >= 5 && hour < 12) return S.greetingMorning;
  if (hour >= 12 && hour < 14) return S.greetingNoon;
  if (hour >= 14 && hour < 18) return S.greetingAfternoon;
  if (hour >= 18 && hour < 23) return S.greetingEvening;
  return S.greetingDawn;
}

/// 分钟转为「X 小时 Y 分钟」；整点不带 0 分钟。
String formatDuration(int minutes) {
  assert(minutes >= 0, 'minutes must not be negative');
  if (minutes < 60) return '$minutes 分钟';
  final hours = minutes ~/ 60;
  final rest = minutes % 60;
  if (rest == 0) return '$hours 小时';
  return '$hours 小时 $rest 分钟';
}

String formatMonthDay(DateTime date) => _monthDay.format(date);

String formatWeekday(DateTime date) => _weekday.format(date);

String formatDayTitle(DateTime date) =>
    '${formatMonthDay(date)} ${formatWeekday(date)}';

String formatClockTime(DateTime date) => _clockTime.format(date);
