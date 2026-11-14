import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/core/theme/tokens.dart';

void main() {
  test('7 组关键配对满足 WCAG 4.5:1', () {
    final pairs = <({String name, Color foreground, Color background})>[
      (
        name: '浅色正文/页面背景',
        foreground: AppPalette.light.text,
        background: AppPalette.light.bg,
      ),
      (
        name: '浅色次要文字/页面背景',
        foreground: AppPalette.light.textMuted,
        background: AppPalette.light.bg,
      ),
      (
        name: '主色按钮文字/主色背景',
        foreground: AppPalette.light.onPrimary,
        background: AppPalette.light.primary,
      ),
      (
        name: '深色正文/页面背景',
        foreground: AppPalette.dark.text,
        background: AppPalette.dark.bg,
      ),
      (
        name: '深色次要文字/页面背景',
        foreground: AppPalette.dark.textMuted,
        background: AppPalette.dark.bg,
      ),
      (
        name: '深色 Jarvis 文字/容器',
        foreground: AppPalette.dark.jarvis,
        background: AppPalette.dark.jarvisContainer,
      ),
      (
        name: '浅色主色浅底标签文字',
        foreground: AppPalette.light.onPrimaryContainer,
        background: AppPalette.light.primaryContainer,
      ),
    ];

    for (final pair in pairs) {
      final ratio = contrastRatio(pair.foreground, pair.background);
      expect(
        ratio,
        greaterThanOrEqualTo(4.5),
        reason: '${pair.name} 对比度不足：$ratio',
      );
    }

    expect(
      contrastRatio(
        AppPalette.light.onPrimaryContainer,
        AppPalette.light.primaryContainer,
      ),
      closeTo(6.69, 0.02),
    );
  });

  test('主题使用令牌颜色', () {
    final light = AppTheme.light();
    final dark = AppTheme.dark();

    expect(light.brightness, Brightness.light);
    expect(dark.brightness, Brightness.dark);
    expect(light.scaffoldBackgroundColor, AppPalette.light.bg);
    expect(dark.scaffoldBackgroundColor, AppPalette.dark.bg);
    expect(light.colorScheme.primary, AppPalette.light.primary);
    expect(dark.colorScheme.primary, AppPalette.dark.primary);
  });

  test('浅色与深色令牌与计划给定值一致', () {
    expect(AppPalette.light.bg, const Color(0xFFFAF8F4));
    expect(AppPalette.light.surface, const Color(0xFFFFFFFF));
    expect(AppPalette.light.primary, const Color(0xFF2F6F62));
    expect(AppPalette.light.primaryContainer, const Color(0xFFE1EFEA));
    expect(AppPalette.light.onPrimaryContainer, const Color(0xFF245A4F));
    expect(AppPalette.light.jarvis, const Color(0xFF2B3A55));
    expect(AppPalette.light.warning, const Color(0xFFB4540A));

    expect(AppPalette.dark.bg, const Color(0xFF12100E));
    expect(AppPalette.dark.surface, const Color(0xFF1B1917));
    expect(AppPalette.dark.primary, const Color(0xFF7FBFAF));
    expect(AppPalette.dark.primaryContainer, const Color(0xFF1E3A34));
    expect(AppPalette.dark.onPrimaryContainer, const Color(0xFFD6EDE6));
    expect(AppPalette.dark.jarvis, const Color(0xFF9FB0CE));
    expect(AppPalette.dark.jarvisContainer, const Color(0xFF1C2637));
    expect(AppPalette.dark.warning, const Color(0xFFE08A3C));
  });
}

double contrastRatio(Color a, Color b) {
  final luminanceA = relativeLuminance(a);
  final luminanceB = relativeLuminance(b);
  final lighter = math.max(luminanceA, luminanceB);
  final darker = math.min(luminanceA, luminanceB);
  return (lighter + 0.05) / (darker + 0.05);
}

double relativeLuminance(Color color) {
  double linearize(double channel) {
    if (channel <= 0.03928) return channel / 12.92;
    return math.pow((channel + 0.055) / 1.055, 2.4).toDouble();
  }

  return 0.2126 * linearize(color.r) +
      0.7152 * linearize(color.g) +
      0.0722 * linearize(color.b);
}
