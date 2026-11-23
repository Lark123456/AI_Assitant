import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/providers.dart';
import '../core/strings.dart';

/// 4 Tab 外壳；每个分支独立 Navigator，切换保留状态。
///
/// 当前 Tab 写入 [selectedTabProvider]，供 Chat 页暂停/恢复轮询。
class ShellScaffold extends ConsumerWidget {
  const ShellScaffold({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final currentIndex = navigationShell.currentIndex;
    if (ref.read(selectedTabProvider) != currentIndex) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ref.read(selectedTabProvider.notifier).select(currentIndex);
      });
    }
    return Scaffold(
      body: navigationShell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: currentIndex,
        onDestinationSelected: (index) {
          ref.read(selectedTabProvider.notifier).select(index);
          navigationShell.goBranch(
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
