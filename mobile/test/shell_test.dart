import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/main.dart';

Finder _tab(String label) =>
    find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

Future<void> _pumpApp(WidgetTester tester) async {
  await tester.pumpWidget(const ProviderScope(child: ButlerApp()));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('默认进入今日 Tab 并显示四个入口', (tester) async {
    await _pumpApp(tester);

    expect(find.byType(NavigationBar), findsOneWidget);
    expect(_tab(S.tabToday), findsOneWidget);
    expect(_tab(S.tabChat), findsOneWidget);
    expect(_tab(S.tabTasks), findsOneWidget);
    expect(_tab(S.tabProfile), findsOneWidget);
    expect(find.text(S.placeholderBody), findsOneWidget);
  });

  testWidgets('切换 Tab 显示对应占位页', (tester) async {
    await _pumpApp(tester);

    await tester.tap(_tab(S.tabChat));
    await tester.pumpAndSettle();
    expect(find.text(S.placeholderBody), findsOneWidget);

    await tester.tap(_tab(S.tabTasks));
    await tester.pumpAndSettle();
    expect(find.text(S.tasksNextStage), findsOneWidget);

    await tester.tap(_tab(S.tabProfile));
    await tester.pumpAndSettle();
    expect(find.text(S.profileNextStage), findsOneWidget);
  });

  testWidgets('切回今日 Tab 仍显示今日占位页', (tester) async {
    await _pumpApp(tester);

    await tester.tap(_tab(S.tabChat));
    await tester.pumpAndSettle();
    await tester.tap(_tab(S.tabToday));
    await tester.pumpAndSettle();

    expect(find.text(S.placeholderBody), findsOneWidget);
  });
}
