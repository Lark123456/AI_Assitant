import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/clock.dart';
import '../../core/debug.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/enums.dart';

class DebugPanelPage extends ConsumerWidget {
  const DebugPanelPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final debug = ref.watch(debugControllerProvider);
    final simulated = ref.watch(simulatedTimeProvider);
    final network =
        ref.watch(networkStatusProvider).value ?? NetworkStatus.online;

    return Scaffold(
      appBar: AppBar(title: const Text(S.debugPanel)),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          _Section(
            title: S.debugTime,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  simulated == null
                      ? S.debugTimeSystem
                      : '${formatDayTitle(simulated)} '
                            '${formatClockTime(simulated)}',
                  style: theme.textTheme.bodyMedium,
                ),
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.sm,
                  children: [
                    OutlinedButton(
                      onPressed: () => _shift(ref, const Duration(hours: 1)),
                      child: const Text(S.debugPlusHour),
                    ),
                    OutlinedButton(
                      onPressed: () => _shift(ref, const Duration(days: 1)),
                      child: const Text(S.debugPlusDay),
                    ),
                    TextButton(
                      onPressed: () =>
                          ref.read(simulatedTimeProvider.notifier).clear(),
                      child: const Text(S.debugReset),
                    ),
                  ],
                ),
              ],
            ),
          ),
          _Section(
            title: S.debugNetwork,
            child: _ChoiceRow<NetworkStatus>(
              values: NetworkStatus.values,
              selected: network,
              label: (value) => value.name,
              onSelected: (value) =>
                  ref.read(mockNetworkStatusSourceProvider).setStatus(value),
            ),
          ),
          _Section(
            title: S.debugDataset,
            child: _ChoiceRow<DebugDataset>(
              values: DebugDataset.values,
              selected: debug.dataset,
              label: (value) => value.name,
              onSelected: (value) =>
                  ref.read(debugControllerProvider.notifier).setDataset(value),
            ),
          ),
          _Section(
            title: S.debugTheme,
            child: _ChoiceRow<DebugThemeMode>(
              values: DebugThemeMode.values,
              selected: debug.themeMode,
              label: (value) => value.name,
              onSelected: (value) => ref
                  .read(debugControllerProvider.notifier)
                  .setThemeMode(value),
            ),
          ),
          _Section(
            title: S.debugTextScale,
            child: _ChoiceRow<double>(
              values: const [1.0, 1.25, 1.5],
              selected: debug.textScale,
              label: (value) => '${value}x',
              onSelected: (value) => ref
                  .read(debugControllerProvider.notifier)
                  .setTextScale(value),
            ),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text(S.debugFailSend),
            value: debug.failNextSend,
            onChanged: (value) => ref
                .read(debugControllerProvider.notifier)
                .setFailNextSend(value),
          ),
          const SizedBox(height: AppSpacing.md),
          FilledButton.icon(
            onPressed: () {
              ref.read(debugActionsProvider).injectJarvisIntro();
              ScaffoldMessenger.of(context)
                  .showSnackBar(const SnackBar(content: Text(S.debugInjected)));
            },
            icon: const Icon(Icons.person_add_alt),
            label: const Text(S.debugInjectJarvis),
          ),
        ],
      ),
    );
  }

  void _shift(WidgetRef ref, Duration duration) {
    final base = ref.read(clockProvider).now();
    ref.read(simulatedTimeProvider.notifier).set(base.add(duration));
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          child,
        ],
      ),
    );
  }
}

class _ChoiceRow<T> extends StatelessWidget {
  const _ChoiceRow({
    required this.values,
    required this.selected,
    required this.label,
    required this.onSelected,
  });

  final List<T> values;
  final T selected;
  final String Function(T value) label;
  final ValueChanged<T> onSelected;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: AppSpacing.sm,
      runSpacing: AppSpacing.sm,
      children: [
        for (final value in values)
          ChoiceChip(
            label: Text(label(value)),
            selected: value == selected,
            onSelected: (_) => onSelected(value),
          ),
      ],
    );
  }
}
