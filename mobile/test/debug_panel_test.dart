import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/debug.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/chat_message.dart';
import 'package:mobile/features/debug/debug_panel_page.dart';
import 'package:mobile/main.dart';

void main() {
  setUpAll(() async {
    await initializeDateFormatting('zh_CN');
  });

  testWidgets('长按今日页标题打开调试面板', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: ButlerApp()));
    await tester.pumpAndSettle();

    final title = find.descendant(
      of: find.byType(AppBar),
      matching: find.text(S.tabToday),
    );
    await tester.longPress(title);
    await tester.pumpAndSettle();

    expect(find.byType(DebugPanelPage), findsOneWidget);
  });

  testWidgets('模拟时间与网络切换生效', (tester) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const DebugPanelPage(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text(S.debugPlusHour));
    await tester.pumpAndSettle();
    expect(container.read(simulatedTimeProvider), isNotNull);

    await tester.tap(find.text(NetworkStatus.offline.name));
    await tester.pumpAndSettle();
    expect(
      container.read(mockNetworkStatusSourceProvider).current,
      NetworkStatus.offline,
    );
  });

  testWidgets('数据集、主题与文字缩放切换生效', (tester) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const DebugPanelPage(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text(DebugDataset.empty.name));
    await tester.pumpAndSettle();
    expect(container.read(debugControllerProvider).dataset, DebugDataset.empty);

    await tester.tap(find.text(DebugThemeMode.dark.name));
    await tester.pumpAndSettle();
    expect(
      container.read(debugControllerProvider).themeMode,
      DebugThemeMode.dark,
    );

    await tester.tap(find.text('1.5x'));
    await tester.pumpAndSettle();
    expect(container.read(debugControllerProvider).textScale, 1.5);
  });

  testWidgets('发送失败开关与插入 Jarvis 引荐', (tester) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const DebugPanelPage(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(container.read(debugControllerProvider).failNextSend, isTrue);

    final repository = container.read(chatRepositoryProvider);
    await tester.scrollUntilVisible(find.text(S.debugInjectJarvis), 200);
    await tester.tap(find.text(S.debugInjectJarvis));
    await tester.pumpAndSettle();

    final messages = await repository.watchMessages().first;
    expect(messages.whereType<JarvisIntroCard>(), isNotEmpty);
  });
}
