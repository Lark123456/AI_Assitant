import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/providers.dart';
import '../core/strings.dart';
import '../features/reminders/reminder_banner.dart';
import '../features/reminders/reminder_controller.dart';

/// 4 Tab 外壳；每个分支独立 Navigator，切换保留状态。
///
/// 当前 Tab 写入 [selectedTabProvider]，供 Chat 页暂停/恢复轮询；
/// 应用内提醒在 Shell 级前台轮询，任意 Tab 都能看到横幅。
class ShellScaffold extends ConsumerStatefulWidget {
  const ShellScaffold({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  ConsumerState<ShellScaffold> createState() => _ShellScaffoldState();
}

class _ShellScaffoldState extends ConsumerState<ShellScaffold>
    with WidgetsBindingObserver {
  var _appActive = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncReminders());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final active = state == AppLifecycleState.resumed;
    if (active == _appActive) return;
    _appActive = active;
    _syncReminders();
  }

  void _syncReminders() {
    if (!mounted) return;
    // Mock 模式没有真实提醒，不启动轮询。
    if (!ref.read(remoteConfigProvider).enabled) return;
    unawaited(ref.read(reminderAlertProvider.notifier).setActive(_appActive));
  }

  @override
  Widget build(BuildContext context) {
    final currentIndex = widget.navigationShell.currentIndex;
    if (ref.read(selectedTabProvider) != currentIndex) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ref.read(selectedTabProvider.notifier).select(currentIndex);
      });
    }
    final reminder = ref.watch(reminderAlertProvider);
    return Scaffold(
      body: Column(
        children: [
          Expanded(child: widget.navigationShell),
          if (reminder != null)
            ReminderBanner(
              reminder: reminder,
              onDismiss: () =>
                  ref.read(reminderAlertProvider.notifier).dismiss(),
            ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: currentIndex,
        onDestinationSelected: (index) {
          ref.read(selectedTabProvider.notifier).select(index);
          widget.navigationShell.goBranch(
            index,
            initialLocation: index == currentIndex,
          );
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.today_outlined),
            selectedIcon: Icon(Icons.today),
            label: S.tabToday,
          ),
          NavigationDestination(
            icon: Icon(Icons.chat_bubble_outline),
            selectedIcon: Icon(Icons.chat_bubble),
            label: S.tabChat,
          ),
          NavigationDestination(
            icon: Icon(Icons.check_circle_outline),
            selectedIcon: Icon(Icons.check_circle),
            label: S.tabTasks,
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: S.tabProfile,
          ),
        ],
      ),
    );
  }
}
