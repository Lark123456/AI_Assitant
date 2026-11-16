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
import 'package:mobile/domain/enums.dart';
import 'package:mobile/features/today/today_page.dart';

final _now = DateTime(2026, 11, 16, 9);

final class _FakeClock implements Clock {
  @override
  DateTime now() => _now;
}

Widget _app({
  MockTodayDataset dataset = MockTodayDataset.normal,
  NetworkStatus network = NetworkStatus.online,
  double textScale = 1.0,
}) {
  final clock = _FakeClock();
  return ProviderScope(
    overrides: [
      clockProvider.overrideWithValue(clock),
      todayRepositoryProvider.overrideWithValue(
        MockTodayRepository(
          clock: clock,
          delay: Duration.zero,
          dataset: dataset,
        ),
      ),
      mockNetworkStatusSourceProvider.overrideWithValue(
        MockNetworkStatusSource(initial: network),
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
}
