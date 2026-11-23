import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/features/chat/chat_page.dart';
import 'package:mobile/features/profile/profile_page.dart';
import 'package:mobile/features/tasks/tasks_page.dart';
import 'package:mobile/features/today/today_page.dart';
import 'package:mobile/main.dart';

Finder _tab(String label) =>
    find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

Future<void> _pumpApp(WidgetTester tester) async {
  await tester.pumpWidget(const ProviderScope(child: ButlerApp()));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(() async {
    await initializeDateFormatting('zh_CN');
  });

  testWidgets('默认进入今日 Tab 并显示四个入口', (tester) async {
    await _pumpApp(tester);

    expect(find.byType(NavigationBar), findsOneWidget);
    expect(_tab(S.tabToday), findsOneWidget);
    expect(_tab(S.tabChat), findsOneWidget);
    expect(_tab(S.tabTasks), findsOneWidget);
    expect(_tab(S.tabProfile), findsOneWidget);
    expect(find.byType(TodayPage), findsOneWidget);
    expect(find.text(S.morningBrief), findsOneWidget);
  });

  testWidgets('切换 Tab 显示对应页面', (tester) async {
    await _pumpApp(tester);

    await tester.tap(_tab(S.tabChat));
    await tester.pumpAndSettle();
    expect(find.byType(ChatPage), findsOneWidget);

    await tester.tap(_tab(S.tabTasks));
    await tester.pumpAndSettle();
    expect(find.byType(TasksPage), findsOneWidget);

    await tester.tap(_tab(S.tabProfile));
    await tester.pumpAndSettle();
    expect(find.byType(ProfilePage), findsOneWidget);
  });

  testWidgets('切回今日 Tab 仍显示今日页', (tester) async {
    await _pumpApp(tester);

    await tester.tap(_tab(S.tabChat));
    await tester.pumpAndSettle();
    await tester.tap(_tab(S.tabToday));
    await tester.pumpAndSettle();

    expect(find.byType(TodayPage), findsOneWidget);
    expect(find.text(S.morningBrief), findsOneWidget);
  });
}
