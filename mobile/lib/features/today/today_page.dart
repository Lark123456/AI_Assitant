import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/clock.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/enums.dart';
import '../../domain/models/today.dart';
import 'today_controller.dart';

class TodayPage extends ConsumerWidget {
  const TodayPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(todayControllerProvider);
    final networkStatus = ref.watch(networkStatusProvider).value;
    return Scaffold(
      appBar: AppBar(
        title: const Text(S.tabToday),
        actions: [
          IconButton(
            tooltip: S.previousDay,
            onPressed: () =>
                ref.read(todayControllerProvider.notifier).previousDay(),
            icon: const Icon(Icons.chevron_left),
          ),
          IconButton(
            tooltip: S.nextDay,
            onPressed: () =>
                ref.read(todayControllerProvider.notifier).nextDay(),
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
      body: switch (async) {
        AsyncData(:final value) => _TodayBody(
          state: value,
          networkStatus: networkStatus,
        ),
        AsyncError() => _ErrorView(
          onRetry: () => ref.read(todayControllerProvider.notifier).retry(),
        ),
        _ => const Center(child: CircularProgressIndicator()),
      },
    );
  }
}

class _TodayBody extends ConsumerWidget {
  const _TodayBody({required this.state, required this.networkStatus});

  final TodayState state;
  final NetworkStatus? networkStatus;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final day = state.day;
    final now = ref.watch(clockProvider).now();
    final doneCount = day.items
        .where((item) => item.status == TodayItemStatus.done)
        .length;
    final isEmpty = day.items.isEmpty && day.unscheduled.isEmpty;

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        if (networkStatus == NetworkStatus.offline) ...[
          const _NetworkBanner(text: S.offline, icon: Icons.cloud_off_outlined),
          const SizedBox(height: AppSpacing.md),
        ] else if (networkStatus == NetworkStatus.syncing) ...[
          const _NetworkBanner(text: S.syncing, icon: Icons.sync),
          const SizedBox(height: AppSpacing.md),
        ],
        _TodayHeader(
          date: state.date,
          greeting: greetingFor(now),
          doneCount: doneCount,
          total: day.items.length,
        ),
        if (day.morningBrief != null) ...[
          const SizedBox(height: AppSpacing.lg),
          _BriefCard(
            brief: day.morningBrief!,
            onAdjust: () => _showAdjustHint(context),
          ),
        ],
        const SizedBox(height: AppSpacing.lg),
        if (isEmpty)
          const _EmptyView()
        else ...[
          for (final item in day.items)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: _TodayItemTile(item: item, now: now),
            ),
          if (day.unscheduled.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            Text(S.unscheduled, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: AppSpacing.sm),
            for (final item in day.unscheduled)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: _UnscheduledTile(item: item, day: state.date),
              ),
          ],
        ],
        const SizedBox(height: AppSpacing.xl),
        OutlinedButton.icon(
          onPressed: () => _confirmReview(context, ref),
          icon: const Icon(Icons.nightlight_outlined),
          label: const Text(S.eveningReview),
        ),
      ],
    );
  }

  void _showAdjustHint(BuildContext context) {
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text(S.tellFriday)));
  }

  Future<void> _confirmReview(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        content: const Text(S.reviewConfirm),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text(S.cancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text(S.submit),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await ref.read(todayControllerProvider.notifier).submitEveningReview();
    messenger.showSnackBar(const SnackBar(content: Text(S.reviewSubmitted)));
  }
}

class _TodayHeader extends StatelessWidget {
  const _TodayHeader({
    required this.date,
    required this.greeting,
    required this.doneCount,
    required this.total,
  });

  final DateTime date;
  final String greeting;
  final int doneCount;
  final int total;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(formatDayTitle(date), style: theme.textTheme.bodySmall),
        const SizedBox(height: AppSpacing.xs),
        Row(
          children: [
            Expanded(
              child: Text(greeting, style: theme.textTheme.headlineMedium),
            ),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.md,
                vertical: AppSpacing.xs,
              ),
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(AppRadius.capsule),
              ),
              child: Text(
                '$doneCount/$total',
                style: theme.textTheme.labelSmall?.copyWith(
                  color: theme.colorScheme.onPrimaryContainer,
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _BriefCard extends StatelessWidget {
  const _BriefCard({required this.brief, required this.onAdjust});

  final Brief brief;
  final VoidCallback onAdjust;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        childrenPadding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        title: Text(S.morningBrief, style: theme.textTheme.bodyMedium),
        subtitle: Text(
          brief.text,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.bodySmall,
        ),
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Text(brief.reasonLine, style: theme.textTheme.bodySmall),
          ),
          for (final suggestion in brief.mergedSuggestions)
            Align(
              alignment: Alignment.centerLeft,
              child: Padding(
                padding: const EdgeInsets.only(top: AppSpacing.xs),
                child: Text('· $suggestion', style: theme.textTheme.bodySmall),
              ),
            ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(onPressed: onAdjust, child: const Text(S.adjust)),
          ),
        ],
      ),
    );
  }
}

class _TodayItemTile extends ConsumerWidget {
  const _TodayItemTile({required this.item, required this.now});

  final TodayItem item;
  final DateTime now;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final done = item.status == TodayItemStatus.done;
    final skipped = item.status == TodayItemStatus.skipped;
    final overdue = item.isOverdueAt(now);
    final pendingSync =
        item.syncState == SyncState.pending ||
        item.syncState == SyncState.queued;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 56,
          child: Text(_timeLabel(item), style: theme.textTheme.bodySmall),
        ),
        Expanded(
          child: Card(
            child: InkWell(
              borderRadius: BorderRadius.circular(AppRadius.card),
              onLongPress: done || skipped
                  ? null
                  : () => ref
                        .read(todayControllerProvider.notifier)
                        .skip(item.id),
              child: Padding(
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.title,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        decoration: done ? TextDecoration.lineThrough : null,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Wrap(
                      spacing: AppSpacing.sm,
                      runSpacing: AppSpacing.xs,
                      children: [
                        if (item.sourceTag != null) _Tag(text: item.sourceTag!),
                        if (item.durationMin != null)
                          _Tag(text: formatDuration(item.durationMin!)),
                        if (item.status == TodayItemStatus.inProgress)
                          _Tag(text: S.inProgress),
                        if (done) _Tag(text: S.done),
                        if (skipped) _Tag(text: S.skipped),
                        if (overdue) _Tag(text: S.overdue, warning: true),
                        if (pendingSync) _Tag(text: S.waitingSync),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        IconButton(
          tooltip: done ? S.done : S.markDone,
          constraints: const BoxConstraints.tightFor(
            width: AppSizes.minTouch,
            height: AppSizes.minTouch,
          ),
          onPressed: done || skipped
              ? null
              : () => ref
                    .read(todayControllerProvider.notifier)
                    .complete(item.id),
          icon: Icon(
            done ? Icons.check_circle : Icons.check_circle_outline,
            color: done ? theme.colorScheme.primary : theme.colorScheme.outline,
          ),
        ),
      ],
    );
  }

  String _timeLabel(TodayItem item) {
    final start = item.start;
    if (start == null) return '';
    if (item.kind == TodayItemKind.block && item.end != null) {
      return '${formatClockTime(start)}–${formatClockTime(item.end!)}';
    }
    return formatClockTime(start);
  }
}

class _UnscheduledTile extends ConsumerWidget {
  const _UnscheduledTile({required this.item, required this.day});

  final TodayItem item;
  final DateTime day;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.title, style: theme.textTheme.bodyMedium),
                  if (item.reason != null) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Text(item.reason!, style: theme.textTheme.bodySmall),
                  ],
                ],
              ),
            ),
            TextButton(
              onPressed: () => ref
                  .read(todayControllerProvider.notifier)
                  .moveToToday(
                    item.id,
                    DateTime(day.year, day.month, day.day, 18),
                  ),
              child: const Text(S.planForToday),
            ),
          ],
        ),
      ),
    );
  }
}

class _NetworkBanner extends StatelessWidget {
  const _NetworkBanner({required this.text, required this.icon});

  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: theme.colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(AppRadius.button),
      ),
      child: Row(
        children: [
          Icon(icon, size: 18, color: theme.colorScheme.onErrorContainer),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              text,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onErrorContainer,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xxl),
      child: Column(
        children: [
          Icon(
            Icons.wb_sunny_outlined,
            size: 40,
            color: theme.colorScheme.outline,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(S.todayEmpty, style: theme.textTheme.bodySmall),
        ],
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: 40, color: theme.colorScheme.error),
          const SizedBox(height: AppSpacing.md),
          Text(S.loadingFailed, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.md),
          FilledButton(onPressed: onRetry, child: const Text(S.retry)),
        ],
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.text, this.warning = false});

  final String text;
  final bool warning;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = warning
        ? theme.colorScheme.error
        : theme.colorScheme.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: 2,
      ),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(AppRadius.capsule),
      ),
      child: Text(
        text,
        style: theme.textTheme.labelSmall?.copyWith(color: color),
      ),
    );
  }
}
