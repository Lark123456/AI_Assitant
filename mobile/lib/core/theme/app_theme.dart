import 'package:flutter/material.dart';

import 'tokens.dart';

/// 由设计令牌构建浅色与深色主题；页面不得自行写死颜色。
abstract final class AppTheme {
  static ThemeData light() => _build(AppPalette.light, Brightness.light);

  static ThemeData dark() => _build(AppPalette.dark, Brightness.dark);

  static ThemeData _build(AppPalette palette, Brightness brightness) {
    final scheme =
        ColorScheme.fromSeed(
          seedColor: palette.primary,
          brightness: brightness,
        ).copyWith(
          primary: palette.primary,
          onPrimary: palette.onPrimary,
          primaryContainer: palette.primaryContainer,
          onPrimaryContainer: palette.onPrimaryContainer,
          surface: palette.surface,
          onSurface: palette.text,
          outline: palette.outline,
          error: palette.warning,
          onError: palette.onPrimary,
        );

    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: palette.bg,
      canvasColor: palette.bg,
    );

    final textTheme = base.textTheme.copyWith(
      headlineMedium: TextStyle(
        fontSize: AppTextSize.title,
        fontWeight: FontWeight.w700,
        color: palette.text,
        height: 1.2,
      ),
      bodyMedium: TextStyle(
        fontSize: AppTextSize.body,
        color: palette.text,
        height: 1.45,
      ),
      bodySmall: TextStyle(
        fontSize: AppTextSize.small,
        color: palette.textMuted,
        height: 1.4,
      ),
      labelSmall: TextStyle(
        fontSize: AppTextSize.label,
        color: palette.textMuted,
        height: 1.3,
      ),
    );

    return base.copyWith(
      textTheme: textTheme,
      appBarTheme: AppBarThemeData(
        backgroundColor: palette.bg,
        foregroundColor: palette.text,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          fontSize: AppTextSize.body,
          fontWeight: FontWeight.w600,
          color: palette.text,
        ),
      ),
      cardTheme: CardThemeData(
        color: palette.surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.card),
          side: BorderSide(color: palette.outline),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: palette.primary,
          foregroundColor: palette.onPrimary,
          minimumSize: const Size(AppSizes.minTouch, AppSizes.minTouch),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.button),
          ),
          textStyle: TextStyle(
            fontSize: AppTextSize.body,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: palette.primary,
          minimumSize: const Size(AppSizes.minTouch, AppSizes.minTouch),
          side: BorderSide(color: palette.outline),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.button),
          ),
        ),
      ),
      dividerTheme: DividerThemeData(color: palette.outline, thickness: 1),
    );
  }
}
