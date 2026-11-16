import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/data/mock/mock_chat_repository.dart';
import 'package:mobile/data/mock/mock_network_status_source.dart';
import 'package:mobile/data/mock/mock_today_repository.dart';
import 'package:mobile/features/chat/chat_page.dart';
import 'package:mobile/features/today/today_page.dart';

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

  testWidgets('深色主题渲染今日页无异常', (tester) async {
    final clock = _FakeClock(DateTime(2026, 11, 16, 9));
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          clockProvider.overrideWithValue(clock),
          mockNetworkStatusSourceProvider.overrideWithValue(
            MockNetworkStatusSource(),
          ),
          todayRepositoryProvider.overrideWithValue(
            MockTodayRepository(clock: clock, delay: Duration.zero),
          ),
        ],
        child: MaterialApp(theme: AppTheme.dark(), home: const TodayPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text(S.morningBrief), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('深色主题渲染对话页无异常', (tester) async {
    final clock = _FakeClock(DateTime(2026, 11, 16, 9));
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          clockProvider.overrideWithValue(clock),
          mockNetworkStatusSourceProvider.overrideWithValue(
            MockNetworkStatusSource(),
          ),
          chatRepositoryProvider.overrideWith((ref) {
            final repository = MockChatRepository(
              clock: clock,
              network: MockNetworkStatusSource(),
              sendDelay: Duration.zero,
              replyDelay: Duration.zero,
              streamInterval: Duration.zero,
            );
            ref.onDispose(repository.dispose);
            return repository;
          }),
        ],
        child: MaterialApp(theme: AppTheme.dark(), home: const ChatPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Friday'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
