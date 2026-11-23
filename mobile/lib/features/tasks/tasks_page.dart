import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/clock.dart';
import '../../core/format.dart';
import '../../core/schedule_time.dart';
import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/models/task.dart';
import 'task_controller.dart';

class TasksPage extends ConsumerStatefulWidget {
  const TasksPage({super.key});

  @override
  ConsumerState<TasksPage> createState() => _TasksPageState();
}

class _TasksPageState extends ConsumerState<TasksPage> {
  @override
  Widget build(BuildContext context) {
    ref.listen<String?>(taskActionErrorProvider, (previous, next) {
      if (next == null) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(next)));
      ref.read(taskActionErrorProvider.notifier).clear();
    });
    final async = ref.watch(tasksControllerProvider);
    final filter = async.value?.filter ?? TaskFilter.open;

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(S.tabTasks),
            Text(
              S.tasksSubtitle,
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      ),
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            _FilterBar(
              selected: filter,
              onChanged: (next) =>
                  ref.read(tasksControllerProvider.notifier).setFilter(next),
            ),
            Expanded(
              child: switch (async) {
                AsyncData(:final value) =>
                  value.tasks.isEmpty
                      ? const _EmptyView()
                      : RefreshIndicator(
                          onRefresh: () => ref
                              .read(tasksControllerProvider.notifier)
                              .refresh(),
                          child: ListView.builder(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: const EdgeInsets.fromLTRB(
                              AppSpacing.lg,
                              AppSpacing.sm,
                              AppSpacing.lg,
                              AppSpacing.lg,
                            ),
                            itemCount: value.tasks.length,
                            itemBuilder: (context, index) => Padding(
                              padding: const EdgeInsets.only(
                                bottom: AppSpacing.md,
                              ),
                              child: _TaskCard(task: value.tasks[index]),
                            ),
                          ),
                        ),
                AsyncError() => _ErrorView(
                  onRetry: () => ref.invalidate(tasksControllerProvider),
                ),
                _ => const Center(child: CircularProgressIndicator()),
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _FilterBar extends StatelessWidget {
  const _FilterBar({required this.selected, required this.onChanged});

  final TaskFilter selected;
  final ValueChanged<TaskFilter> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        AppSpacing.xs,
      ),
      child: Wrap(
        spacing: AppSpacing.sm,
        children: [
          for (final filter in TaskFilter.values)
            ChoiceChip(
              label: Text(_label(filter)),
              selected: selected == filter,
              onSelected: (_) => onChanged(filter),
            ),
        ],
      ),
    );
  }

  String _label(TaskFilter filter) => switch (filter) {
    TaskFilter.open => S.taskOpen,
    TaskFilter.done => S.taskFilterDone,
    TaskFilter.all => S.taskFilterAll,
  };
}

class _TaskCard extends ConsumerWidget {
  const _TaskCard({required this.task});

  final TaskItem task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final controller = ref.read(tasksControllerProvider.notifier);
    final block = task.upcomingBlock;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(task.title, style: theme.textTheme.bodyLarge),
                ),
                _StatusLabel(status: task.status),
              ],
            ),
            if (task.description != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(task.description!, style: theme.textTheme.bodySmall),
            ],
            if (block != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Icon(
                    Icons.event_available_outlined,
                    size: 16,
                    color: theme.colorScheme.primary,
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Text(
                    '${S.taskUpcoming} · '
                    '${formatClockTime(block.start)}–${formatClockTime(block.end)}',
                    style: theme.textTheme.labelSmall,
                  ),
                ],
              ),
            ],
            const SizedBox(height: AppSpacing.sm),
            if (task.status == TaskStatus.open)
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  FilledButton.tonal(
                    onPressed: () => controller.complete(task.id),
                    child: const Text(S.markDone),
                  ),
                  OutlinedButton(
                    onPressed: () => controller.skip(task.id),
                    child: const Text(S.skipItem),
                  ),
                  if (block == null)
                    TextButton(
                      onPressed: () => _schedule(context, ref),
                      child: const Text(S.planForToday),
                    ),
                ],
              )
            else
              TextButton(
                onPressed: () => controller.restore(task.id),
                child: const Text(S.undo),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _schedule(BuildContext context, WidgetRef ref) async {
    final now = ref.read(clockProvider).now();
    final start = nextScheduleStart(now, now);
    if (start == null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text(S.scheduleTooLate)));
      return;
    }
    await ref
        .read(tasksControllerProvider.notifier)
        .scheduleToday(task.id, start);
  }
}

class _StatusLabel extends StatelessWidget {
  const _StatusLabel({required this.status});

  final TaskStatus status;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = switch (status) {
      TaskStatus.open => S.taskOpen,
      TaskStatus.done => S.done,
      TaskStatus.skipped => S.skipped,
    };
    return Text(
      label,
      style: theme.textTheme.labelSmall?.copyWith(
        color: status == TaskStatus.open
            ? theme.colorScheme.primary
            : theme.colorScheme.onSurfaceVariant,
      ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.checklist_outlined,
            size: 40,
            color: theme.colorScheme.outline,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(S.tasksEmpty, style: theme.textTheme.bodySmall),
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
