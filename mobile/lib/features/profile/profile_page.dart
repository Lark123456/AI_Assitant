import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_info.dart';
import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/models/profile.dart';
import '../debug/debug_panel_page.dart';
import 'profile_controller.dart';

class ProfilePage extends ConsumerWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(profileControllerProvider);
    final remote = ref.watch(remoteConfigProvider);

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(S.tabProfile),
            Text(
              S.profileSubtitle,
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      ),
      body: SafeArea(
        top: false,
        child: switch (async) {
          AsyncData(:final value) => _ProfileList(
            profile: value,
            remoteEnabled: remote.enabled,
            baseUrl: remote.baseUrl,
          ),
          AsyncError() => _ErrorView(
            onRetry: () => ref.read(profileControllerProvider.notifier).retry(),
          ),
          _ => const Center(child: CircularProgressIndicator()),
        },
      ),
    );
  }
}

class _ProfileList extends StatelessWidget {
  const _ProfileList({
    required this.profile,
    required this.remoteEnabled,
    required this.baseUrl,
  });

  final UserProfile profile;
  final bool remoteEnabled;
  final String baseUrl;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        AppSpacing.lg,
      ),
      children: [
        const _SectionHeader(text: S.profileAccount),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.person_outline),
          title: const Text(S.profileName),
          subtitle: Text(profile.displayName),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.public),
          title: const Text(S.profileTimezone),
          subtitle: Text(profile.timezone),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.schedule),
          title: const Text(S.profileDayStart),
          subtitle: Text(profile.dayStart),
        ),
        const Divider(height: AppSpacing.lg),
        const _SectionHeader(text: S.profileDataSource),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.storage_outlined),
          title: Text(remoteEnabled ? S.profileRemote : S.profileMock),
          subtitle: remoteEnabled ? Text(baseUrl) : null,
        ),
        const Divider(height: AppSpacing.lg),
        const _SectionHeader(text: S.profileAbout),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.info_outline),
          title: const Text(S.profileVersion),
          subtitle: const Text(appVersion),
        ),
        if (kDebugMode)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.bug_report_outlined),
            title: const Text(S.profileDebug),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const DebugPanelPage()),
            ),
          ),
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: Text(
        text,
        style: theme.textTheme.labelSmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
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
