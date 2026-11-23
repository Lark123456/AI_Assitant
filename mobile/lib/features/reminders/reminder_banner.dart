import 'package:flutter/material.dart';

import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/models/reminder.dart';

/// Shell 底部的应用内提醒横幅。
class ReminderBanner extends StatelessWidget {
  const ReminderBanner({
    super.key,
    required this.reminder,
    required this.onDismiss,
  });

  final DueReminder reminder;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        child: Row(
          children: [
            Icon(
              Icons.notifications_active_outlined,
              size: 20,
              color: theme.colorScheme.onPrimaryContainer,
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    S.reminderDueTitle,
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onPrimaryContainer,
                    ),
                  ),
                  Text(
                    reminder.note.isEmpty ? S.reminderDueTitle : reminder.note,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: theme.colorScheme.onPrimaryContainer,
                    ),
                  ),
                ],
              ),
            ),
            TextButton(onPressed: onDismiss, child: const Text(S.gotIt)),
          ],
        ),
      ),
    );
  }
}
