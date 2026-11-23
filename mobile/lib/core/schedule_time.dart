/// 通用排期时间计算：Today 与任务页共用的“排进今天”默认时刻。
DateTime? nextScheduleStart(DateTime now, DateTime day) {
  final target = DateTime(day.year, day.month, day.day);
  final today = DateTime(now.year, now.month, now.day);
  if (target.isBefore(today)) return null;
  if (target.isAfter(today)) {
    return DateTime(day.year, day.month, day.day, 18);
  }

  final evening = DateTime(now.year, now.month, now.day, 18);
  final earliest = now.add(const Duration(minutes: 5));
  final earliestDay = DateTime(earliest.year, earliest.month, earliest.day);
  if (!earliestDay.isAtSameMomentAs(today)) return null;
  if (evening.isAfter(earliest)) return evening;

  final totalMinutes = earliest.hour * 60 + earliest.minute;
  final roundedMinutes = ((totalMinutes + 29) ~/ 30) * 30;
  // 最晚允许 23:00 开始，避免默认 60 分钟的块跨过午夜。
  if (roundedMinutes > 23 * 60) return null;
  return earliestDay.add(Duration(minutes: roundedMinutes));
}
