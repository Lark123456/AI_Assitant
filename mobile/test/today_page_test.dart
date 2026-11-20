import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/data/mock/mock_network_status_source.dart';
import 'package:mobile/data/mock/mock_today_repository.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_today_repository.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/today.dart';
import 'package:mobile/domain/repositories/today_repository.dart';
import 'package:mobile/features/today/today_page.dart';

final _now = DateTime(2026, 11, 16, 9);

class _FakeApiClient implements ApiClient {
  _FakeApiClient(this.payload, {this.postResponse});

  final Map<String, dynamic> payload;
  final Map<String, dynamic>? postResponse;
  String? lastPostPath;

  @override
  Future<Map<String, dynamic>> getJson(String path) async => payload;

  @override
  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  }) async {
    lastPostPath = path;
    return postResponse ?? payload;
  }
}

Map<String, dynamic> _remotePayload() => {
  'date': '2026-11-16',
  'items': [
    {
      'id': 'block-1',
      'kind': 'block',
      'title': '专注写作',
      'status': 'planned',
      'compressible': true,
      'syncState': 'synced',
      'start': '2026-11-16T09:00:00+08:00',
      'end': '2026-11-16T10:00:00+08:00',
      'durationMin': 60,
      'sourceTag': '日程',
      'reason': null,
    },
  ],
  'unscheduled': [],
  'morningBrief': null,
  'eveningBrief': null,
};

Future<void> _pumpAction(WidgetTester tester) async {
  for (var round = 0; round < 2; round++) {
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
  }
}

final class _FakeClock implements Clock {
  @override
  DateTime now() => _now;
}

class _FailingRefreshRepository extends MockTodayRepository {
  _FailingRefreshRepository({required super.clock})
    : super(delay: Duration.zero);

  var loads = 0;

  @override
  Future<DayView> loadDay(DateTime date) async {
    loads += 1;
    if (loads > 1) throw StateError('refresh failed');
    return super.loadDay(date);
  }
}

Widget _app({
  MockTodayDataset dataset = MockTodayDataset.normal,
  NetworkStatus network = NetworkStatus.online,
  double textScale = 1.0,
  MockNetworkStatusSource? source,
  TodayRepository? repository,
}) {
  final clock = _FakeClock();
  return ProviderScope(
    overrides: [
      clockProvider.overrideWithValue(clock),
      todayRepositoryProvider.overrideWithValue(
        repository ??
            MockTodayRepository(
              clock: clock,
              delay: Duration.zero,
              dataset: dataset,
            ),
      ),
      mockNetworkStatusSourceProvider.overrideWithValue(
        source ?? MockNetworkStatusSource(initial: network),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
      home: const TodayPage(),
    ),
  );
}

void main() {
  setUpAll(() async {
    await initializeDateFormatting('zh_CN');
  });

  testWidgets('正常数据集显示简报、时间线与未排期', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    expect(find.text(S.morningBrief), findsOneWidget);
    expect(find.text('专注写作'), findsOneWidget);
    expect(find.text('喝水'), findsOneWidget);
    expect(find.text(S.unscheduled), findsOneWidget);
    expect(find.text('1/4'), findsOneWidget);
    await tester.scrollUntilVisible(find.text(S.eveningReview), 200);
    expect(find.text(S.eveningReview), findsOneWidget);
  });

  testWidgets('点击完成按钮更新进度', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.check_circle_outline).first);
    await tester.pumpAndSettle();

    expect(find.text('2/4'), findsOneWidget);
  });

  testWidgets('空数据集显示空状态', (tester) async {
    await tester.pumpWidget(_app(dataset: MockTodayDataset.empty));
    await tester.pumpAndSettle();

    expect(find.text(S.todayEmpty), findsOneWidget);
  });

  testWidgets('加载失败显示错误与重试', (tester) async {
    await tester.pumpWidget(_app(dataset: MockTodayDataset.error));
    await tester.pumpAndSettle();

    expect(find.text(S.loadingFailed), findsOneWidget);
    expect(find.text(S.retry), findsOneWidget);
  });

  testWidgets('离线时显示离线提示', (tester) async {
    await tester.pumpWidget(_app(network: NetworkStatus.offline));
    await tester.pumpAndSettle();

    expect(find.text(S.offline), findsOneWidget);
  });

  testWidgets('1.5 倍文字缩放不溢出', (tester) async {
    await tester.pumpWidget(_app(textScale: 1.5));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  testWidgets('左滑完成并可撤销', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();
    expect(find.text('1/4'), findsOneWidget);

    await tester.drag(
      find.byKey(const ValueKey('today-reminder-1')),
      const Offset(-500, 0),
    );
    await _pumpAction(tester);

    expect(find.text('2/4'), findsOneWidget);
    expect(find.text(S.undo), findsOneWidget);

    await tester.tap(find.text(S.undo));
    await _pumpAction(tester);
    expect(find.text('1/4'), findsOneWidget);
  });

  testWidgets('右滑跳过并可撤销', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.drag(
      find.byKey(const ValueKey('today-reminder-1')),
      const Offset(500, 0),
    );
    await _pumpAction(tester);

    expect(find.text(S.skipped), findsWidgets);
    await tester.tap(find.text(S.undo));
    await _pumpAction(tester);
    expect(find.text(S.skipped), findsNothing);
  });

  testWidgets('已完成条目不再响应滑动', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.check_circle_outline).first);
    await _pumpAction(tester);
    expect(find.text('2/4'), findsOneWidget);

    final dismissible = tester.widget<Dismissible>(
      find.byKey(const ValueKey('today-reminder-1')),
    );
    expect(dismissible.direction, DismissDirection.none);
  });

  testWidgets('长按打开操作面板并查看详情', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.longPress(find.text('喝水'));
    await tester.pumpAndSettle();

    expect(find.text(S.adjustTime), findsOneWidget);
    expect(find.text(S.skipItem), findsOneWidget);
    expect(find.text(S.viewDetails), findsOneWidget);
    expect(find.text(S.whyScheduled), findsOneWidget);

    await tester.tap(find.text(S.viewDetails));
    await tester.pumpAndSettle();
    expect(find.text(S.detailsTitle), findsOneWidget);
    expect(find.text(S.detailType), findsOneWidget);
  });

  testWidgets('为什么这样排显示原因', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.longPress(find.text('喝水'));
    await tester.pumpAndSettle();
    await tester.tap(find.text(S.whyScheduled));
    await tester.pumpAndSettle();

    expect(find.text(S.whyScheduledFallback), findsOneWidget);
  });

  testWidgets('晨间简报调整打开底部面板', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.tap(find.text(S.morningBrief));
    await tester.pumpAndSettle();
    await tester.tap(find.text(S.adjust));
    await tester.pumpAndSettle();

    expect(find.text(S.briefAdjustTitle), findsOneWidget);
    expect(find.text(S.briefAdjustLater), findsOneWidget);
    expect(find.text(S.briefAdjustShorter), findsOneWidget);
    expect(find.text(S.briefAdjustOther), findsOneWidget);
  });

  testWidgets('调整时间打开时间选择器', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.longPress(find.text('方案评审'));
    await tester.pumpAndSettle();
    await tester.tap(find.text(S.adjustTime));
    await tester.pumpAndSettle();

    expect(find.byType(TimePickerDialog), findsOneWidget);
    Navigator.of(tester.element(find.byType(TimePickerDialog))).pop();
    await tester.pumpAndSettle();
    expect(find.byType(TimePickerDialog), findsNothing);
  });

  test('时间块改期必须早于结束时间且至少 5 分钟', () {
    final item = TodayItem(
      id: 'block-1',
      kind: TodayItemKind.block,
      title: '块',
      status: TodayItemStatus.planned,
      compressible: false,
      syncState: SyncState.synced,
      start: DateTime(2026, 11, 16, 9),
      end: DateTime(2026, 11, 16, 10),
      durationMin: 60,
    );

    expect(
      resolveAdjustedStart(item, const TimeOfDay(hour: 9, minute: 30)),
      isNotNull,
    );
    expect(
      resolveAdjustedStart(item, const TimeOfDay(hour: 9, minute: 55)),
      isNotNull,
    );
    expect(
      resolveAdjustedStart(item, const TimeOfDay(hour: 9, minute: 56)),
      isNull,
    );
    expect(
      resolveAdjustedStart(item, const TimeOfDay(hour: 10, minute: 0)),
      isNull,
    );
  });

  test('排期时间避开过去并选择可用时段', () {
    final day = DateTime(2026, 11, 16);

    expect(
      nextScheduleStart(DateTime(2026, 11, 16, 9), day),
      DateTime(2026, 11, 16, 18),
    );
    expect(
      nextScheduleStart(DateTime(2026, 11, 16, 17, 58), day),
      DateTime(2026, 11, 16, 18, 30),
    );
    expect(
      nextScheduleStart(DateTime(2026, 11, 16, 19, 10), day),
      DateTime(2026, 11, 16, 19, 30),
    );
    expect(
      nextScheduleStart(DateTime(2026, 11, 16, 22, 50), day),
      DateTime(2026, 11, 16, 23),
    );
    expect(nextScheduleStart(DateTime(2026, 11, 16, 23), day), isNull);
    expect(nextScheduleStart(DateTime(2026, 11, 16, 23, 40), day), isNull);
    expect(nextScheduleStart(DateTime(2026, 11, 16, 23, 58), day), isNull);
    expect(
      nextScheduleStart(DateTime(2026, 11, 16, 9), DateTime(2026, 11, 17)),
      DateTime(2026, 11, 17, 18),
    );
    expect(
      nextScheduleStart(DateTime(2026, 11, 16, 9), DateTime(2026, 11, 15)),
      isNull,
    );
  });

  testWidgets('下拉刷新切换同步状态', (tester) async {
    final source = MockNetworkStatusSource();
    await tester.pumpWidget(_app(source: source));
    await tester.pumpAndSettle();

    await tester.drag(find.byType(ListView), const Offset(0, 400));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text(S.syncing), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(find.text(S.syncing), findsNothing);
  });

  testWidgets('刷新失败保留原数据并提示', (tester) async {
    final clock = _FakeClock();
    final repository = _FailingRefreshRepository(clock: clock);
    await tester.pumpWidget(_app(repository: repository));
    await tester.pumpAndSettle();
    expect(find.text('专注写作'), findsOneWidget);

    await tester.drag(find.byType(ListView), const Offset(0, 400));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();

    expect(find.text(S.refreshFailed), findsOneWidget);
    expect(find.text('专注写作'), findsOneWidget);
  });

  testWidgets('按住语音按钮显示录音面板与假波形', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    final gesture = await tester.startGesture(
      tester.getCenter(find.byIcon(Icons.mic)),
    );
    await tester.pump();

    expect(find.text(S.voiceListening), findsOneWidget);
    expect(find.text(S.voiceRelease), findsOneWidget);

    await gesture.up();
    await tester.pumpAndSettle();
    expect(find.text(S.voiceListening), findsNothing);
  });

  testWidgets('远程模式允许完成并调用真实接口', (tester) async {
    final client = _FakeApiClient(
      _remotePayload(),
      postResponse: {
        'id': 'block-1',
        'kind': 'block',
        'title': '专注写作',
        'status': 'done',
        'compressible': true,
        'syncState': 'synced',
        'start': '2026-11-16T09:00:00+08:00',
        'end': '2026-11-16T10:00:00+08:00',
        'durationMin': 60,
        'sourceTag': '日程',
        'reason': null,
      },
    );
    final repository = RemoteTodayRepository(client: client);
    await tester.pumpWidget(_app(repository: repository));
    await tester.pumpAndSettle();

    expect(find.text(S.readOnlyMode), findsNothing);
    final button = tester.widget<IconButton>(
      find.widgetWithIcon(IconButton, Icons.check_circle_outline).first,
    );
    expect(button.onPressed, isNotNull);

    await tester.tap(find.byIcon(Icons.check_circle_outline).first);
    await _pumpAction(tester);

    expect(client.lastPostPath, '/api/mobile/today/items/block-1/complete');
    expect(find.text(S.done), findsOneWidget);
  });

  testWidgets('远程模式排进今天后移除未排期条目', (tester) async {
    final payload = _remotePayload();
    payload['unscheduled'] = [
      {
        'id': 'task-1',
        'kind': 'task',
        'title': '整理笔记',
        'status': 'planned',
        'compressible': true,
        'syncState': 'synced',
        'start': null,
        'end': null,
        'durationMin': null,
        'sourceTag': '任务',
        'reason': '还没安排时间',
      },
    ];
    final client = _FakeApiClient(
      payload,
      postResponse: {
        'id': 'block-new',
        'kind': 'block',
        'title': '整理笔记',
        'status': 'planned',
        'compressible': true,
        'syncState': 'synced',
        'start': '2026-11-16T18:00:00+08:00',
        'end': '2026-11-16T19:00:00+08:00',
        'durationMin': 60,
        'sourceTag': '日程',
        'reason': null,
      },
    );
    final repository = RemoteTodayRepository(client: client);
    await tester.pumpWidget(_app(repository: repository));
    await tester.pumpAndSettle();

    await tester.tap(find.text(S.planForToday));
    await _pumpAction(tester);

    expect(client.lastPostPath, '/api/mobile/today/tasks/task-1/schedule');
    expect(find.text(S.unscheduled), findsNothing);
    expect(find.text('整理笔记'), findsOneWidget);
  });

  testWidgets('1.5 倍文字缩放下操作面板与录音面板不溢出', (tester) async {
    await tester.pumpWidget(_app(textScale: 1.5));
    await tester.pumpAndSettle();

    await tester.longPress(find.text('喝水'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    Navigator.of(tester.element(find.text(S.adjustTime))).pop();
    await tester.pumpAndSettle();

    await tester.tap(find.text(S.morningBrief));
    await tester.pumpAndSettle();
    await tester.tap(find.text(S.adjust));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    Navigator.of(tester.element(find.text(S.briefAdjustTitle))).pop();
    await tester.pumpAndSettle();

    final gesture = await tester.startGesture(
      tester.getCenter(find.byIcon(Icons.mic)),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
    await gesture.up();
    await tester.pumpAndSettle();
  });
}
