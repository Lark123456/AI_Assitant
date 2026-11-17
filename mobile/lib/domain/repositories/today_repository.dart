import '../enums.dart';
import '../models/today.dart';

/// 今日页数据来源。
abstract interface class TodayRepository {
  Future<DayView> loadDay(DateTime date);

  Future<TodayItem> complete(String itemId);

  Future<TodayItem> skip(String itemId);

  /// 撤销完成/跳过：把条目恢复到之前的状态。
  Future<TodayItem> restore(String itemId, TodayItemStatus status);

  Future<TodayItem> reschedule(String itemId, DateTime newStart);

  Future<TodayItem> moveToToday(String itemId, DateTime start);

  Future<void> submitEveningReview(Map<String, bool> completionByItemId);
}
