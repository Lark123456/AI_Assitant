import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/clock.dart';
import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../domain/enums.dart';
import '../../domain/models/today.dart';
import '../../domain/repositories/today_repository.dart';

/// 写操作失败时在页面展示一次提示；null 表示无待展示错误。
class TodayActionError extends Notifier<String?> {
  @override
  String? build() => null;

  void show(String message) => state = message;

  void clear() => state = null;
}

final todayActionErrorProvider = NotifierProvider<TodayActionError, String?>(
  TodayActionError.new,
);

class TodayState {
  const TodayState({required this.date, required this.day});

  final DateTime date;
  final DayView day;
}

/// 今日页唯一状态来源：日期、DayView 与动作。
class TodayController extends AsyncNotifier<TodayState> {
  late DateTime _date;

  @override
  Future<TodayState> build() async {
    final clock = ref.watch(clockProvider);
    final repository = ref.watch(todayRepositoryProvider);
    final now = clock.now();
    _date = DateTime(now.year, now.month, now.day);
    final day = await repository.loadDay(_date);
    return TodayState(date: _date, day: day);
  }

  Future<void> previousDay() => _load(_date.subtract(const Duration(days: 1)));

  Future<void> nextDay() => _load(_date.add(const Duration(days: 1)));

  Future<void> retry() => _load(_date);

  Future<void> complete(String itemId) async {
    await _apply((repository) => repository.complete(itemId));
  }

  Future<void> skip(String itemId) async {
    await _apply((repository) => repository.skip(itemId));
  }

  Future<void> restore(String itemId, TodayItemStatus status) async {
    await _apply((repository) => repository.restore(itemId, status));
  }

  /// 下拉刷新：Mock 模式保留模拟同步态；失败时保留旧数据并提示。
  Future<void> refresh() async {
    final remote = ref.read(remoteConfigProvider).enabled;
    final source = ref.read(mockNetworkStatusSourceProvider);
    final previous = source.current;
    if (!remote) {
      source.setStatus(NetworkStatus.syncing);
      await Future<void>.delayed(const Duration(milliseconds: 450));
    }
    try {
      final day = await ref.read(todayRepositoryProvider).loadDay(_date);
      state = AsyncData(TodayState(date: _date, day: day));
    } catch (_) {
      ref.read(todayActionErrorProvider.notifier).show(S.refreshFailed);
    } finally {
      if (!remote) {
        source.setStatus(
          previous == NetworkStatus.offline
              ? NetworkStatus.offline
              : NetworkStatus.online,
        );
      }
    }
  }

  Future<void> reschedule(String itemId, DateTime newStart) async {
    await _apply((repository) => repository.reschedule(itemId, newStart));
  }

  Future<void> moveToToday(String itemId, DateTime start) async {
    final current = state.value;
    if (current == null) return;
    try {
      final updated = await ref
          .read(todayRepositoryProvider)
          .moveToToday(itemId, start);
      final items = [
        ...current.day.items.where((item) => item.id != updated.id),
        if (updated.start != null) updated,
      ]..sort((left, right) => left.start!.compareTo(right.start!));
      final unscheduled = current.day.unscheduled
          .where((item) => item.id != itemId)
          .toList();
      state = AsyncData(
        TodayState(
          date: current.date,
          day: DayView(
            date: current.day.date,
            items: items,
            unscheduled: unscheduled,
            morningBrief: current.day.morningBrief,
            eveningBrief: current.day.eveningBrief,
          ),
        ),
      );
    } catch (_) {
      await _handleActionError();
    }
  }

  Future<void> submitEveningReview() async {
    final current = state.value;
    if (current == null) return;
    final completion = {
      for (final item in [...current.day.items, ...current.day.unscheduled])
        item.id: item.status == TodayItemStatus.done,
    };
    try {
      await ref.read(todayRepositoryProvider).submitEveningReview(completion);
    } catch (_) {
      await _handleActionError();
      return;
    }
    await _load(current.date);
  }

  Future<void> _load(DateTime date) async {
    final normalized = DateTime(date.year, date.month, date.day);
    _date = normalized;
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final day = await ref.read(todayRepositoryProvider).loadDay(normalized);
      return TodayState(date: normalized, day: day);
    });
  }

  Future<void> _apply(
    Future<TodayItem> Function(TodayRepository repository) action,
  ) async {
    final current = state.value;
    if (current == null) return;
    try {
      final updated = await action(ref.read(todayRepositoryProvider));
      _replaceItem(current, updated);
    } catch (_) {
      await _handleActionError();
    }
  }

  Future<void> _handleActionError() async {
    ref.read(todayActionErrorProvider.notifier).show(S.actionFailed);
    await _load(_date);
  }

  void _replaceItem(TodayState current, TodayItem updated) {
    final items = <TodayItem>[];
    var foundInItems = false;
    for (final item in current.day.items) {
      if (item.id == updated.id) {
        items.add(updated);
        foundInItems = true;
      } else {
        items.add(item);
      }
    }
    if (!foundInItems && updated.start != null) {
      items.add(updated);
    }
    items.sort((left, right) => left.start!.compareTo(right.start!));

    final unscheduled = current.day.unscheduled
        .where((item) => item.id != updated.id)
        .toList();
    if (updated.start == null &&
        updated.kind == TodayItemKind.task &&
        updated.status == TodayItemStatus.planned) {
      unscheduled.add(updated);
    }

    state = AsyncData(
      TodayState(
        date: current.date,
        day: DayView(
          date: current.day.date,
          items: items,
          unscheduled: unscheduled,
          morningBrief: current.day.morningBrief,
          eveningBrief: current.day.eveningBrief,
        ),
      ),
    );
  }
}

final todayControllerProvider =
    AsyncNotifierProvider<TodayController, TodayState>(TodayController.new);
