import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/data/mock/mock_chat_repository.dart';
import 'package:mobile/data/mock/mock_network_status_source.dart';
import 'package:mobile/data/mock/mock_today_repository.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/chat_message.dart';
import 'package:mobile/features/chat/chat_page.dart';
import 'package:mobile/features/debug/debug_panel_page.dart';
import 'package:mobile/features/today/today_page.dart';

final _now = DateTime(2026, 11, 16, 9);
final _generateScreenshots = Platform.environment['SCREENSHOTS'] == '1';

final class _FakeClock implements Clock {
  @override
  DateTime now() => _now;
}

List<ChatMessage> _chatSeed() => [
  TextMessage(
    id: 'shot-user-1',
    sender: ChatSender.user,
    createdAt: _now,
    text: '今天有点忙',
  ),
  TextMessage(
    id: 'shot-nudge-1',
    sender: ChatSender.friday,
    createdAt: _now.add(const Duration(minutes: 1)),
    text: '下午有一个空档，要不要先把评审排进去？',
    reason: '你昨天提到今天要交评审意见',
  ),
];

ThemeData _withChineseFont(ThemeData theme) {
  final textTheme = theme.textTheme.apply(fontFamily: 'SimHei');
  final filledStyle = theme.filledButtonTheme.style;
  final filledTextStyle = filledStyle?.textStyle?.resolve(const {});
  return theme.copyWith(
    textTheme: textTheme,
    primaryTextTheme: theme.primaryTextTheme.apply(fontFamily: 'SimHei'),
    appBarTheme: theme.appBarTheme.copyWith(
      titleTextStyle: theme.appBarTheme.titleTextStyle?.copyWith(
        fontFamily: 'SimHei',
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: filledStyle?.copyWith(
        textStyle: WidgetStatePropertyAll(
          filledTextStyle?.copyWith(fontFamily: 'SimHei'),
        ),
      ),
    ),
  );
}

Widget _host({
  required Key key,
  required Widget page,
  required ThemeData theme,
  required ProviderScope Function(Widget child) scope,
}) {
  return scope(
    RepaintBoundary(
      key: key,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: _withChineseFont(theme),
        home: page,
      ),
    ),
  );
}

Future<void> _capture(WidgetTester tester, Key key, String fileName) async {
  await tester.pumpAndSettle();
  await expectLater(
    find.byKey(key),
    matchesGoldenFile('../screenshots/$fileName'),
  );
}

void main() {
  setUpAll(() async {
    await initializeDateFormatting('zh_CN');
    // 测试环境默认字体没有中文字形；用系统黑体覆盖默认 Roboto，
    // 仅影响截图测试，不改变应用依赖。
    final fontFile = File(r'C:\Windows\Fonts\simhei.ttf');
    if (fontFile.existsSync()) {
      final bytes = fontFile.readAsBytesSync();
      for (final family in ['Roboto', 'Ahem', 'FlutterTest', 'SimHei']) {
        final loader = FontLoader(family)
          ..addFont(Future.value(ByteData.view(bytes.buffer)));
        await loader.load();
      }
    }
    final iconFile = File(
      r'D:\flutter\bin\cache\artifacts\material_fonts\materialicons-regular.otf',
    );
    if (iconFile.existsSync()) {
      final bytes = iconFile.readAsBytesSync();
      final loader = FontLoader('MaterialIcons')
        ..addFont(Future.value(ByteData.view(bytes.buffer)));
      await loader.load();
    }
  });

  testWidgets('今日页浅色与深色截图', (tester) async {
    // 截图测试依赖本机中文字体与 MaterialIcons，默认跳过；用 SCREENSHOTS=1 运行。
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    for (final (name, theme) in [
      ('today_light.png', AppTheme.light()),
      ('today_dark.png', AppTheme.dark()),
    ]) {
      final clock = _FakeClock();
      final key = ValueKey(name);
      await tester.pumpWidget(
        _host(
          key: key,
          page: const TodayPage(),
          theme: theme,
          scope: (child) => ProviderScope(
            overrides: [
              clockProvider.overrideWithValue(clock),
              todayRepositoryProvider.overrideWithValue(
                MockTodayRepository(clock: clock, delay: Duration.zero),
              ),
              mockNetworkStatusSourceProvider.overrideWithValue(
                MockNetworkStatusSource(),
              ),
            ],
            child: child,
          ),
        ),
      );
      await _capture(tester, key, name);
    }
  }, skip: !_generateScreenshots);

  testWidgets('对话页浅色与深色截图', (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    for (final (name, theme) in [
      ('chat_light.png', AppTheme.light()),
      ('chat_dark.png', AppTheme.dark()),
    ]) {
      final key = ValueKey(name);
      await tester.pumpWidget(
        _host(
          key: key,
          page: const ChatPage(),
          theme: theme,
          scope: (child) => ProviderScope(
            overrides: [
              clockProvider.overrideWithValue(_FakeClock()),
              mockNetworkStatusSourceProvider.overrideWithValue(
                MockNetworkStatusSource(),
              ),
              chatRepositoryProvider.overrideWith((ref) {
                final repository = MockChatRepository(
                  clock: _FakeClock(),
                  network: MockNetworkStatusSource(),
                  seed: _chatSeed(),
                  sendDelay: Duration.zero,
                  replyDelay: Duration.zero,
                  streamInterval: Duration.zero,
                );
                ref.onDispose(repository.dispose);
                return repository;
              }),
            ],
            child: child,
          ),
        ),
      );
      await _capture(tester, key, name);
    }
  }, skip: !_generateScreenshots);

  testWidgets('调试面板浅色与深色截图', (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 1100));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    for (final (name, theme) in [
      ('debug_light.png', AppTheme.light()),
      ('debug_dark.png', AppTheme.dark()),
    ]) {
      final key = ValueKey(name);
      await tester.pumpWidget(
        _host(
          key: key,
          page: const DebugPanelPage(),
          theme: theme,
          scope: (child) => ProviderScope(
            overrides: [
              clockProvider.overrideWithValue(_FakeClock()),
              mockNetworkStatusSourceProvider.overrideWithValue(
                MockNetworkStatusSource(),
              ),
            ],
            child: child,
          ),
        ),
      );
      await _capture(tester, key, name);
    }
  }, skip: !_generateScreenshots);
}
