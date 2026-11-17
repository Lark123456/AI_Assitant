import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/clock.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/enums.dart';
import '../../domain/models/today.dart';
import '../debug/debug_panel_page.dart';
import 'today_controller.dart';

/// 把时间选择器的结果合并回条目日期；时间块要求新开始时间早于结束时间。
DateTime? resolveAdjustedStart(TodayItem item, TimeOfDay picked) {
  final start = item.start;
  if (start == null) return null;
  final next = DateTime(
    start.year,
    start.month,
    start.day,
    picked.hour,
    picked.minute,
  );
  if (item.kind == TodayItemKind.block &&
      item.end != null &&
      !item.end!.isAfter(next)) {
    return null;
  }
  return next;
}

String formatItemTime(TodayItem item) {
  final start = item.start;
  if (start == null) return '';
  if (item.kind == TodayItemKind.block && item.end != null) {
    return '${formatClockTime(start)}–${formatClockTime(item.end!)}';
  }
  return formatClockTime(start);
}

class TodayPage extends ConsumerStatefulWidget {
  const TodayPage({super.key});

  @override
  ConsumerState<TodayPage> createState() => _TodayPageState();
}

class _TodayPageState extends ConsumerState<TodayPage> {
  var _recording = false;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(todayControllerProvider);
    final networkStatus = ref.watch(networkStatusProvider).value;
    return Scaffold(
      appBar: AppBar(
        title: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onLongPress: kDebugMode
              ? () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => const DebugPanelPage(),
                  ),
                )
              : null,
          child: const Text(S.tabToday),
        ),
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
      floatingActionButton: _VoiceButton(
        onHoldStart: () => setState(() => _recording = true),
        onHoldEnd: () => setState(() => _recording = false),
      ),
      bottomSheet: _recording ? const _RecordingPanel() : null,
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

    return RefreshIndicator(
      onRefresh: () => ref.read(todayControllerProvider.notifier).refresh(),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          if (networkStatus == NetworkStatus.offline) ...[
            const _NetworkBanner(
              text: S.offline,
              icon: Icons.cloud_off_outlined,
            ),
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
              onAdjust: () => _showBriefAdjust(context),
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
      ),
    );
  }

  void _showBriefAdjust(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                title: Text(
                  S.briefAdjustTitle,
                  style: Theme.of(sheetContext).textTheme.bodyMedium,
                ),
              ),
              ListTile(
                leading: const Icon(Icons.schedule),
                title: const Text(S.briefAdjustLater),
                onTap: () => Navigator.pop(sheetContext),
              ),
              ListTile(
                leading: const Icon(Icons.compress),
                title: const Text(S.briefAdjustShorter),
                onTap: () => Navigator.pop(sheetContext),
              ),
              ListTile(
                leading: const Icon(Icons.swap_horiz),
                title: const Text(S.briefAdjustOther),
                onTap: () => Navigator.pop(sheetContext),
              ),
            ],
          ),
        ),
      ),
    );
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

enum _ItemAction { adjustTime, skip, details, why }

class _TodayItemTile extends ConsumerWidget {
  const _TodayItemTile({required this.item, required this.now});

  final TodayItem item;
  final DateTime now;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final done = item.status == TodayItemStatus.done;
    final skipped = item.status == TodayItemStatus.skipped;
    final terminal = done || skipped;
    final overdue = item.isOverdueAt(now);
    final pendingSync =
        item.syncState == SyncState.pending ||
        item.syncState == SyncState.queued;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 56,
          child: Text(formatItemTime(item), style: theme.textTheme.bodySmall),
        ),
        Expanded(
          child: Dismissible(
            key: ValueKey(item.id),
            direction: terminal
                ? DismissDirection.none
                : DismissDirection.horizontal,
            background: _SwipeBackground(
              alignment: Alignment.centerLeft,
              color: theme.colorScheme.secondaryContainer,
              icon: Icons.skip_next,
              label: S.skipItem,
            ),
            secondaryBackground: _SwipeBackground(
              alignment: Alignment.centerRight,
              color: theme.colorScheme.primaryContainer,
              icon: Icons.check,
              label: S.markDone,
            ),
            confirmDismiss: (direction) =>
                _confirmDismiss(context, ref, direction),
            child: Card(
              child: InkWell(
                borderRadius: BorderRadius.circular(AppRadius.card),
                onTap: () => _showDetails(context),
                onLongPress: () => _showActions(context, ref),
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
                          if (item.sourceTag != null)
                            _Tag(text: item.sourceTag!),
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
        ),
        IconButton(
          tooltip: done ? S.done : S.markDone,
          constraints: const BoxConstraints.tightFor(
            width: AppSizes.minTouch,
            height: AppSizes.minTouch,
          ),
          onPressed: terminal
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

  Future<bool> _confirmDismiss(
    BuildContext context,
    WidgetRef ref,
    DismissDirection direction,
  ) async {
    if (direction == DismissDirection.endToStart) {
      await ref.read(todayControllerProvider.notifier).complete(item.id);
      if (!context.mounted) return false;
      _showUndoSnackBar(context, ref, S.markedDone);
    } else if (direction == DismissDirection.startToEnd) {
      await ref.read(todayControllerProvider.notifier).skip(item.id);
      if (!context.mounted) return false;
      _showUndoSnackBar(context, ref, S.markedSkipped);
    }
    // 卡片留在时间线上，由状态标签展示完成/跳过。
    return false;
  }

  void _showUndoSnackBar(BuildContext context, WidgetRef ref, String message) {
    final previous = item.status;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(message),
          action: SnackBarAction(
            label: S.undo,
            onPressed: () async {
              await ref
                  .read(todayControllerProvider.notifier)
                  .restore(item.id, previous);
              if (context.mounted) {
                ScaffoldMessenger.of(context)
                    .showSnackBar(const SnackBar(content: Text(S.undone)));
              }
            },
          ),
        ),
      );
  }

  Future<void> _showActions(BuildContext context, WidgetRef ref) async {
    final terminal =
        item.status == TodayItemStatus.done ||
        item.status == TodayItemStatus.skipped;
    final action = await showModalBottomSheet<_ItemAction>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                title: Text(
                  item.title,
                  style: Theme.of(sheetContext).textTheme.bodyMedium,
                ),
                subtitle: Text(
                  formatItemTime(item),
                  style: Theme.of(sheetContext).textTheme.bodySmall,
                ),
              ),
              ListTile(
                enabled: !terminal,
                leading: const Icon(Icons.schedule),
                title: const Text(S.adjustTime),
                onTap: () =>
                    Navigator.pop(sheetContext, _ItemAction.adjustTime),
              ),
              ListTile(
                enabled: !terminal,
                leading: const Icon(Icons.skip_next),
                title: const Text(S.skipItem),
                onTap: () => Navigator.pop(sheetContext, _ItemAction.skip),
              ),
              ListTile(
                leading: const Icon(Icons.info_outline),
                title: const Text(S.viewDetails),
                onTap: () => Navigator.pop(sheetContext, _ItemAction.details),
              ),
              ListTile(
                leading: const Icon(Icons.help_outline),
                title: const Text(S.whyScheduled),
                onTap: () => Navigator.pop(sheetContext, _ItemAction.why),
              ),
            ],
          ),
        ),
      ),
    );
    if (!context.mounted || action == null) return;
    switch (action) {
      case _ItemAction.adjustTime:
        await _pickTime(context, ref);
        break;
      case _ItemAction.skip:
        await ref.read(todayControllerProvider.notifier).skip(item.id);
        if (context.mounted) {
          _showUndoSnackBar(context, ref, S.markedSkipped);
        }
        break;
      case _ItemAction.details:
        _showDetails(context);
        break;
      case _ItemAction.why:
        _showWhy(context);
        break;
    }
  }

  Future<void> _pickTime(BuildContext context, WidgetRef ref) async {
    final start = item.start;
    if (start == null) return;
    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(start),
    );
    if (picked == null || !context.mounted) return;
    final nextStart = resolveAdjustedStart(item, picked);
    if (nextStart == null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text(S.invalidTime)));
      return;
    }
    await ref
        .read(todayControllerProvider.notifier)
        .reschedule(item.id, nextStart);
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text(S.timeUpdated)));
    }
  }

  void _showDetails(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => _ItemDetailsSheet(item: item),
    );
  }

  void _showWhy(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => _ReasonSheet(
        title: S.whyScheduled,
        body: item.reason ?? S.whyScheduledFallback,
      ),
    );
  }
}

class _SwipeBackground extends StatelessWidget {
  const _SwipeBackground({
    required this.alignment,
    required this.color,
    required this.icon,
    required this.label,
  });

  final Alignment alignment;
  final Color color;
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: alignment,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(AppRadius.card),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 18),
          const SizedBox(width: AppSpacing.xs),
          Text(label, style: Theme.of(context).textTheme.labelSmall),
        ],
      ),
    );
  }
}

class _ItemDetailsSheet extends StatelessWidget {
  const _ItemDetailsSheet({required this.item});

  final TodayItem item;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = <(String, String)>[
      (S.detailType, _kindText(item.kind)),
      (S.detailStatus, _statusText(item.status)),
      if (item.start != null) (S.detailTime, formatItemTime(item)),
      if (item.durationMin != null)
        (S.detailDuration, formatDuration(item.durationMin!)),
      if (item.sourceTag != null) (S.detailSource, item.sourceTag!),
      (S.detailSync, _syncText(item.syncState)),
      if (item.reason != null) (S.detailReason, item.reason!),
    ];
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(S.detailsTitle, style: theme.textTheme.bodyMedium),
            const SizedBox(height: AppSpacing.sm),
            Text(item.title, style: theme.textTheme.headlineMedium),
            const SizedBox(height: AppSpacing.md),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 72,
                      child: Text(row.$1, style: theme.textTheme.bodySmall),
                    ),
                    Expanded(
                      child: Text(row.$2, style: theme.textTheme.bodyMedium),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _ReasonSheet extends StatelessWidget {
  const _ReasonSheet({required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: theme.textTheme.bodyMedium),
            const SizedBox(height: AppSpacing.sm),
            Text(body, style: theme.textTheme.bodySmall),
            const SizedBox(height: AppSpacing.md),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text(S.gotIt),
              ),
            ),
          ],
        ),
      ),
    );
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

class _VoiceButton extends StatelessWidget {
  const _VoiceButton({required this.onHoldStart, required this.onHoldEnd});

  final VoidCallback onHoldStart;
  final VoidCallback onHoldEnd;

  @override
  Widget build(BuildContext context) {
    return FloatingActionButton(
      tooltip: S.voiceHold,
      onPressed: () {},
      child: Listener(
        onPointerDown: (_) => onHoldStart(),
        onPointerUp: (_) => onHoldEnd(),
        onPointerCancel: (_) => onHoldEnd(),
        child: const Icon(Icons.mic),
      ),
    );
  }
}

class _RecordingPanel extends StatelessWidget {
  const _RecordingPanel();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surface,
      elevation: 8,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(S.voiceListening, style: theme.textTheme.bodyMedium),
              const SizedBox(height: AppSpacing.md),
              const _FakeWaveform(),
              const SizedBox(height: AppSpacing.sm),
              Text(S.voiceRelease, style: theme.textTheme.bodySmall),
            ],
          ),
        ),
      ),
    );
  }
}

class _FakeWaveform extends StatelessWidget {
  const _FakeWaveform();

  static const _heights = <double>[
    12,
    24,
    18,
    30,
    14,
    22,
    26,
    16,
    20,
    28,
    12,
    24,
  ];

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.primary;
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        for (final height in _heights)
          Container(
            width: 4,
            height: height,
            margin: const EdgeInsets.symmetric(horizontal: 2),
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
      ],
    );
  }
}

String _kindText(TodayItemKind kind) => switch (kind) {
  TodayItemKind.block => S.kindBlock,
  TodayItemKind.reminder => S.kindReminder,
  TodayItemKind.task => S.kindTask,
};

String _statusText(TodayItemStatus status) => switch (status) {
  TodayItemStatus.planned => S.planned,
  TodayItemStatus.inProgress => S.inProgress,
  TodayItemStatus.done => S.done,
  TodayItemStatus.skipped => S.skipped,
};

String _syncText(SyncState state) => switch (state) {
  SyncState.synced => S.synced,
  SyncState.pending => S.sending,
  SyncState.queued => S.waitingForNetwork,
  SyncState.failed => S.syncFailed,
};
