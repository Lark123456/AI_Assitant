import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/domain/models/reminder.dart';
import 'package:mobile/features/reminders/reminder_banner.dart';

void main() {
  testWidgets('展示提醒内容并响应知道了', (tester) async {
    var dismissed = false;
    final reminder = DueReminder(
      id: 'r1',
      note: '交报告',
      fireAt: DateTime(2026, 11, 16, 9),
      status: 'pending',
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ReminderBanner(
            reminder: reminder,
            onDismiss: () => dismissed = true,
          ),
        ),
      ),
    );

    expect(find.text(S.reminderDueTitle), findsOneWidget);
    expect(find.text('交报告'), findsOneWidget);

    await tester.tap(find.text(S.gotIt));
    expect(dismissed, isTrue);
  });
}
