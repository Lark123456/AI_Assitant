import '../../domain/enums.dart';
import '../../domain/models/today.dart';
import '../../domain/repositories/today_repository.dart';
import 'api_client.dart';

/// U2 第一批：Today 只读仓库；写操作暂时明确失败。
class RemoteTodayRepository implements TodayRepository {
  RemoteTodayRepository({required this.client});

  final ApiClient client;

  @override
  bool get readOnly => true;

  @override
  Future<DayView> loadDay(DateTime date) async {
    final raw = await client.getJson(
      '/api/mobile/today?date=${_dateParam(date)}',
    );
    return _parseDayView(raw);
  }

  @override
  Future<TodayItem> complete(String itemId) =>
      throw UnsupportedError('Today 只读模式暂不支持完成');

  @override
  Future<TodayItem> skip(String itemId) =>
      throw UnsupportedError('Today 只读模式暂不支持跳过');

  @override
  Future<TodayItem> restore(String itemId, TodayItemStatus status) =>
      throw UnsupportedError('Today 只读模式暂不支持撤销');

  @override
  Future<TodayItem> reschedule(String itemId, DateTime newStart) =>
      throw UnsupportedError('Today 只读模式暂不支持改期');

  @override
  Future<TodayItem> moveToToday(String itemId, DateTime start) =>
      throw UnsupportedError('Today 只读模式暂不支持排期');

  @override
  Future<void> submitEveningReview(Map<String, bool> completionByItemId) =>
      throw UnsupportedError('Today 只读模式暂不支持复盘提交');
}

String _dateParam(DateTime date) {
  final month = date.month.toString().padLeft(2, '0');
  final day = date.day.toString().padLeft(2, '0');
  return '${date.year.toString().padLeft(4, '0')}-$month-$day';
}

DayView _parseDayView(Map<String, dynamic> raw) {
  final date = _parseLocalDate(_requireString(raw, 'date'));
  final items = _parseItems(raw['items'], defaultStatus: null);
  final unscheduled = _parseItems(raw['unscheduled'], defaultStatus: null);
  items.sort((left, right) => left.start!.compareTo(right.start!));
  return DayView(
    date: date,
    items: items,
    unscheduled: unscheduled,
    morningBrief: _parseBrief(raw['morningBrief'], BriefKind.morning),
    eveningBrief: _parseBrief(raw['eveningBrief'], BriefKind.evening),
  );
}

List<TodayItem> _parseItems(
  Object? raw, {
  required TodayItemStatus? defaultStatus,
}) {
  if (raw == null) return const [];
  if (raw is! List) throw const FormatException('items 必须是数组');
  return [
    for (final item in raw) _parseItem(item, defaultStatus: defaultStatus),
  ];
}

TodayItem _parseItem(Object? raw, {required TodayItemStatus? defaultStatus}) {
  if (raw is! Map<String, dynamic>) {
    throw const FormatException('item 必须是对象');
  }
  final kind = _parseKind(_requireString(raw, 'kind'));
  final status = raw['status'] == null
      ? (defaultStatus ?? TodayItemStatus.planned)
      : _parseStatus(_requireString(raw, 'status'));
  final start = _parseOptionalDate(raw['start']);
  final end = _parseOptionalDate(raw['end']);
  final duration = raw['durationMin'] as int?;
  return TodayItem(
    id: _requireString(raw, 'id'),
    kind: kind,
    title: _requireString(raw, 'title'),
    status: status,
    compressible: raw['compressible'] as bool? ?? false,
    syncState: _parseSyncState(raw['syncState']),
    start: start,
    end: end,
    durationMin: duration,
    sourceTag: raw['sourceTag'] as String?,
    reason: raw['reason'] as String?,
  );
}

Brief? _parseBrief(Object? raw, BriefKind kind) {
  if (raw == null) return null;
  if (raw is! Map<String, dynamic>) {
    throw const FormatException('brief 必须是对象');
  }
  final suggestions = raw['mergedSuggestions'];
  return Brief(
    kind: kind,
    text: _requireString(raw, 'text'),
    reasonLine: _requireString(raw, 'reasonLine'),
    mergedSuggestions: suggestions is List
        ? suggestions.map((item) => item.toString()).toList()
        : const [],
  );
}

String _requireString(Map<String, dynamic> raw, String key) {
  final value = raw[key];
  if (value is! String || value.isEmpty) {
    throw FormatException('缺少字符串字段：$key');
  }
  return value;
}

DateTime _parseLocalDate(String raw) {
  final parts = raw.split('-');
  if (parts.length != 3) throw FormatException('日期格式不正确：$raw');
  return DateTime(
    int.parse(parts[0]),
    int.parse(parts[1]),
    int.parse(parts[2]),
  );
}

DateTime? _parseOptionalDate(Object? raw) {
  if (raw == null) return null;
  if (raw is! String) throw const FormatException('时间必须是字符串');
  return DateTime.parse(raw).toLocal();
}

TodayItemKind _parseKind(String raw) => switch (raw) {
  'block' => TodayItemKind.block,
  'reminder' => TodayItemKind.reminder,
  'task' => TodayItemKind.task,
  _ => throw FormatException('未知 kind：$raw'),
};

TodayItemStatus _parseStatus(String raw) => switch (raw) {
  'planned' => TodayItemStatus.planned,
  'in_progress' || 'inProgress' => TodayItemStatus.inProgress,
  'done' => TodayItemStatus.done,
  'skipped' => TodayItemStatus.skipped,
  _ => throw FormatException('未知 status：$raw'),
};

SyncState _parseSyncState(Object? raw) {
  if (raw == null) return SyncState.synced;
  return switch (raw) {
    'synced' => SyncState.synced,
    'pending' => SyncState.pending,
    'queued' => SyncState.queued,
    'failed' => SyncState.failed,
    _ => throw FormatException('未知 syncState：$raw'),
  };
}
