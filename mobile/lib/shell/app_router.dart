import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/strings.dart';
import '../features/chat/chat_page.dart';
import '../features/today/today_page.dart';
import 'placeholder_page.dart';
import 'shell_scaffold.dart';

/// 路由与 4 Tab 外壳；页面内容在后续批次替换占位页。
final appRouterProvider = Provider<GoRouter>((ref) {
  final router = createAppRouter();
  ref.onDispose(router.dispose);
  return router;
});

GoRouter createAppRouter() => GoRouter(
  initialLocation: '/today',
  routes: [
    StatefulShellRoute.indexedStack(
      builder: (context, state, navigationShell) =>
          ShellScaffold(navigationShell: navigationShell),
      branches: [
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/today',
              builder: (context, state) => const TodayPage(),
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/chat',
              builder: (context, state) => const ChatPage(),
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/tasks',
              builder: (context, state) => const PlaceholderPage(
                title: S.tabTasks,
                body: S.tasksNextStage,
              ),
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/profile',
              builder: (context, state) => const PlaceholderPage(
                title: S.tabProfile,
                body: S.profileNextStage,
              ),
            ),
          ],
        ),
      ],
    ),
  ],
);
