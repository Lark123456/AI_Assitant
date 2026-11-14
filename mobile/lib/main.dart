import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'core/strings.dart';
import 'core/theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('zh_CN');
  runApp(const ButlerApp());
}

class ButlerApp extends StatelessWidget {
  const ButlerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: S.appName,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      home: const Scaffold(body: Center(child: Text(S.appName))),
    );
  }
}
