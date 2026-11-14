import 'package:flutter/material.dart';

/// 设计令牌：颜色、间距、圆角、字号与动效数值只在这里定义。
/// 对应 docs/mobile-u1-technical-plan.md 第 5 章。
@immutable
class AppPalette {
  const AppPalette({
    required this.bg,
    required this.surface,
    required this.outline,
    required this.text,
    required this.textMuted,
    required this.primary,
    required this.onPrimary,
    required this.primaryContainer,
    required this.onPrimaryContainer,
    required this.jarvis,
    required this.jarvisContainer,
    required this.warning,
  });

  final Color bg;
  final Color surface;
  final Color outline;
  final Color text;
  final Color textMuted;
  final Color primary;
  final Color onPrimary;
  final Color primaryContainer;
  final Color onPrimaryContainer;
  final Color jarvis;
  final Color jarvisContainer;
  final Color warning;

  /// 浅色令牌（5.1 给定值）。jarvisContainer 为按 Jarvis 色推导的浅底。
  static const AppPalette light = AppPalette(
    bg: Color(0xFFFAF8F4),
    surface: Color(0xFFFFFFFF),
    outline: Color(0xFFE4DED3),
    text: Color(0xFF1F2328),
    textMuted: Color(0xFF5B6168),
    primary: Color(0xFF2F6F62),
    onPrimary: Color(0xFFFFFFFF),
    primaryContainer: Color(0xFFE1EFEA),
    onPrimaryContainer: Color(0xFF245A4F),
    jarvis: Color(0xFF2B3A55),
    jarvisContainer: Color(0xFFEDF0F6),
    warning: Color(0xFFB4540A),
  );

  /// 深色令牌（5.2 推导值）。
  static const AppPalette dark = AppPalette(
    bg: Color(0xFF12100E),
    surface: Color(0xFF1B1917),
    outline: Color(0xFF33302A),
    text: Color(0xFFECE8E1),
    textMuted: Color(0xFFAAA49B),
    primary: Color(0xFF7FBFAF),
    onPrimary: Color(0xFF12100E),
    primaryContainer: Color(0xFF1E3A34),
    onPrimaryContainer: Color(0xFFD6EDE6),
    jarvis: Color(0xFF9FB0CE),
    jarvisContainer: Color(0xFF1C2637),
    warning: Color(0xFFE08A3C),
  );
}

abstract final class AppSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 20;
  static const double xxl = 24;
}

abstract final class AppRadius {
  static const double card = 14;
  static const double cardLarge = 16;
  static const double button = 12;
  static const double capsule = 999;
}

abstract final class AppTextSize {
  static const double title = 28;
  static const double body = 15;
  static const double small = 12;
  static const double label = 11;
}

abstract final class AppSizes {
  static const double minTouch = 44;
}

abstract final class AppMotion {
  static const Duration fast = Duration(milliseconds: 120);
  static const Duration normal = Duration(milliseconds: 220);
  static const Duration perCharacter = Duration(milliseconds: 25);
}
