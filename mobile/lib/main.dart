import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'core/strings.dart';
import 'core/theme/app_theme.dart';
import 'shell/app_router.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('zh_CN');
  runApp(const ProviderScope(child: ButlerApp()));
}

class ButlerApp extends ConsumerWidget {
  const ButlerApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp.router(
      title: S.appName,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      routerConfig: ref.watch(appRouterProvider),
    );
  }
}
