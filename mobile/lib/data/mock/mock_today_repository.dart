import '../../core/clock.dart';
import '../../domain/enums.dart';
import '../../domain/models/today.dart';
import '../../domain/repositories/today_repository.dart';
import 'mock_seed.dart';

/// Mock Today 数据集：正常、空、加载失败。
enum MockTodayDataset { normal, empty, error }

/// 简单的内存 Today 仓库：固定数据集 + 模拟延迟。
class MockTodayRepository implements TodayRepository {
  MockTodayRepository({
    required Clock clock,
    this.delay = const Duration(milliseconds: 250),
    this.dataset = MockTodayDataset.normal,
  }) : _items = dataset == MockTodayDataset.normal
           ? seedTodayItems(clock.now())
           : [],
       _unscheduled = dataset == MockTodayDataset.normal
           ? seedUnscheduledItems()
           : [],
       _morningBrief = dataset == MockTodayDataset.normal
           ? seedMorningBrief()
           : null,
       _eveningBrief = dataset == MockTodayDataset.normal
           ? seedEveningBrief()
           : null;

  final Duration delay;
  final MockTodayDataset dataset;
  final List<TodayItem> _items;
  final List<TodayItem> _unscheduled;
  final Brief? _morningBrief;
  final Brief? _eveningBrief;

  @override
  Future<DayView> loadDay(DateTime date) async {
    await Future<void>.delayed(delay);
    if (dataset == MockTodayDataset.error) {
      throw StateError('mock today load failed');
    }
    return DayView(
      date: DateTime(date.year, date.month, date.day),
      items: _sortedItems(),
      unscheduled: List<TodayItem>.unmodifiable(_unscheduled),
      morningBrief: _morningBrief,
      eveningBrief: _eveningBrief,
    );
  }

  @override
  Future<TodayItem> complete(String itemId) async {
    await Future<void>.delayed(delay);
    return _setStatus(itemId, TodayItemStatus.done);
  }

  @override
  Future<TodayItem> skip(String itemId) async {
    await Future<void>.delayed(delay);
    return _setStatus(itemId, TodayItemStatus.skipped);
  }

  @override
  Future<TodayItem> restore(String itemId, TodayItemStatus status) async {
    await Future<void>.delayed(delay);
    final index = _items.indexWhere((item) => item.id == itemId);
    if (index < 0) {
      throw ArgumentError.value(itemId, 'itemId', 'today item not found');
    }
    final updated = _items[index].copyWith(status: status);
    _items[index] = updated;
    return updated;
  }

  @override
  Future<TodayItem> reschedule(String itemId, DateTime newStart) async {
    await Future<void>.delayed(delay);
    final index = _items.indexWhere((item) => item.id == itemId);
    if (index < 0) {
      throw ArgumentError.value(itemId, 'itemId', 'today item not found');
    }
    final updated = _items[index].copyWith(start: newStart);
    _items[index] = updated;
    _sortItems();
    return updated;
  }

  @override
  Future<TodayItem> moveToToday(String itemId, DateTime start) async {
    await Future<void>.delayed(delay);
    final index = _unscheduled.indexWhere((item) => item.id == itemId);
    if (index < 0) {
      throw ArgumentError.value(itemId, 'itemId', 'unscheduled item not found');
    }
    final moved = _unscheduled
        .removeAt(index)
        .copyWith(start: start, status: TodayItemStatus.planned);
    _items.add(moved);
    _sortItems();
    return moved;
  }

  @override
  Future<void> submitEveningReview(Map<String, bool> completionByItemId) async {
    await Future<void>.delayed(delay);
    for (final entry in completionByItemId.entries) {
      final status = entry.value
          ? TodayItemStatus.done
          : TodayItemStatus.planned;
      final index = _items.indexWhere((item) => item.id == entry.key);
      if (index >= 0) {
        _items[index] = _items[index].copyWith(status: status);
        continue;
      }
      final unscheduledIndex = _unscheduled.indexWhere(
        (item) => item.id == entry.key,
      );
      if (unscheduledIndex >= 0) {
        if (entry.value) {
          // 未排期任务完成后不再满足 DayView.unscheduled 的 planned 约束
          _unscheduled.removeAt(unscheduledIndex);
        } else {
          _unscheduled[unscheduledIndex] = _unscheduled[unscheduledIndex]
              .copyWith(status: status);
        }
      }
    }
  }

  TodayItem _setStatus(String itemId, TodayItemStatus status) {
    final index = _items.indexWhere((item) => item.id == itemId);
    if (index >= 0) {
      final updated = _items[index].copyWith(status: status);
      _items[index] = updated;
      return updated;
    }
    final unscheduledIndex = _unscheduled.indexWhere(
      (item) => item.id == itemId,
    );
    if (unscheduledIndex >= 0) {
      final updated = _unscheduled
          .removeAt(unscheduledIndex)
          .copyWith(status: status);
      // 完成/跳过后不再属于「未排期」，避免破坏 DayView 约束
      return updated;
    }
    throw ArgumentError.value(itemId, 'itemId', 'today item not found');
  }

  List<TodayItem> _sortedItems() {
    _sortItems();
    return List<TodayItem>.unmodifiable(_items);
  }

  void _sortItems() {
    _items.sort((left, right) => left.start!.compareTo(right.start!));
  }
}
