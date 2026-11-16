import '../enums.dart';
import '../errors.dart';
import 'unset.dart';

/// 今日条目：block（日程块）、reminder（提醒）、task（任务）。
class TodayItem {
  // 含 DateTime 比较，构造函数不能是 const
  TodayItem({
    required this.id,
    required this.kind,
    required this.title,
    required this.status,
    required this.compressible,
    required this.syncState,
    this.start,
    this.end,
    this.durationMin,
    this.sourceTag,
    this.reason,
  }) : assert(id != '', 'id must not be empty'),
       assert(title != '', 'title must not be empty'),
       assert(
         kind != TodayItemKind.block || (start != null && end != null),
         'block requires start and end',
       ),
       assert(
         kind != TodayItemKind.block || end!.isAfter(start!),
         'block end must be after start',
       ),
       assert(
         kind != TodayItemKind.block ||
             (durationMin != null && durationMin > 0),
         'block requires a positive durationMin',
       ),
       assert(
         kind != TodayItemKind.reminder || start != null,
         'reminder requires start',
       ),
       assert(
         kind == TodayItemKind.block || (end == null && durationMin == null),
         'end/durationMin are only allowed for block items',
       );

  final String id;
  final TodayItemKind kind;
  final String title;
  final TodayItemStatus status;
  final bool compressible;
  final SyncState syncState;
  final DateTime? start;
  final DateTime? end;
  final int? durationMin;
  final String? sourceTag;
  final String? reason;

  /// overdue 是派生状态，不写入 status，也不参与持久化。
  /// block 以 end 为准；reminder 有 10 分钟宽限；task 以 start 为准。
  bool isOverdueAt(DateTime now) {
    if (status == TodayItemStatus.done || status == TodayItemStatus.skipped) {
      return false;
    }
    return switch (kind) {
      TodayItemKind.block => end != null && now.isAfter(end!),
      TodayItemKind.reminder =>
        start != null && now.isAfter(start!.add(const Duration(minutes: 10))),
      TodayItemKind.task => start != null && now.isAfter(start!),
    };
  }

  /// 仅 `task` 可通过 `copyWith(start: null)` 移出时间线。
  TodayItem copyWith({
    TodayItemStatus? status,
    SyncState? syncState,
    Object? start = unset,
  }) {
    final nextStart = identical(start, unset) ? this.start : start as DateTime?;
    if (nextStart == null && kind != TodayItemKind.task) {
      throw StateTransitionException(
        model: 'TodayItem',
        from: this.start?.toIso8601String() ?? 'null',
        to: 'null',
        reason: 'only task items can clear start',
      );
    }
    if (kind == TodayItemKind.block && !end!.isAfter(nextStart!)) {
      throw StateTransitionException(
        model: 'TodayItem',
        from: this.start?.toIso8601String() ?? 'null',
        to: nextStart.toIso8601String(),
        reason: 'block end must be after start',
      );
    }
    assert(
      nextStart != null || kind == TodayItemKind.task,
      'only task items can clear start',
    );
    assert(
      kind != TodayItemKind.block || end!.isAfter(nextStart!),
      'block end must be after start',
    );
    return TodayItem(
      id: id,
      kind: kind,
      title: title,
      status: status ?? this.status,
      compressible: compressible,
      syncState: syncState ?? this.syncState,
      start: nextStart,
      end: end,
      durationMin: durationMin,
      sourceTag: sourceTag,
      reason: reason,
    );
  }
}

class Brief {
  // 含集合不可变复制，构造函数不能是 const
  Brief({
    required this.kind,
    required this.text,
    required this.reasonLine,
    List<String> mergedSuggestions = const <String>[],
  }) : mergedSuggestions = List<String>.unmodifiable(mergedSuggestions),
       assert(text != '', 'brief text must not be empty'),
       assert(reasonLine != '', 'brief reasonLine must not be empty'),
       assert(
         mergedSuggestions.every((s) => s != ''),
         'mergedSuggestions must not contain empty strings',
       );

  final BriefKind kind;
  final String text;
  final String reasonLine;
  final List<String> mergedSuggestions;
}

class DayView {
  // 含集合不可变复制，构造函数不能是 const
  DayView({
    required this.date,
    required List<TodayItem> items,
    required List<TodayItem> unscheduled,
    this.morningBrief,
    this.eveningBrief,
  }) : items = List<TodayItem>.unmodifiable(items),
       unscheduled = List<TodayItem>.unmodifiable(unscheduled),
       assert(!date.isUtc, 'DayView.date must be a local DateTime'),
       assert(
         date.hour == 0 &&
             date.minute == 0 &&
             date.second == 0 &&
             date.millisecond == 0 &&
             date.microsecond == 0,
         'DayView.date must be normalized to local midnight',
       ),
       assert(
         items.every((e) => e.start != null) &&
             unscheduled.every(
               (e) => e.start == null && e.kind == TodayItemKind.task,
             ),
         'items require start; unscheduled must be tasks without start',
       ),
       assert(
         unscheduled.every((e) => e.status == TodayItemStatus.planned),
         'unscheduled items must stay planned',
       ),
       assert(
         [...items, ...unscheduled].map((e) => e.id).toSet().length ==
             items.length + unscheduled.length,
         'TodayItem ids must be unique within a DayView',
       ),
       assert(
         _isSortedByStart(items),
         'DayView.items must be sorted by start ascending',
       ),
       assert(
         morningBrief == null || morningBrief.kind == BriefKind.morning,
         'morningBrief must be a morning brief',
       ),
       assert(
         eveningBrief == null || eveningBrief.kind == BriefKind.evening,
         'eveningBrief must be an evening brief',
       );

  final DateTime date;
  final List<TodayItem> items;
  final List<TodayItem> unscheduled;
  final Brief? morningBrief;
  final Brief? eveningBrief;
}

bool _isSortedByStart(List<TodayItem> items) {
  for (var i = 1; i < items.length; i++) {
    if (items[i].start!.isBefore(items[i - 1].start!)) return false;
  }
  return true;
}
