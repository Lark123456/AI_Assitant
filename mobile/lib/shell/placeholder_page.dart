import 'package:flutter/material.dart';

import '../core/strings.dart';
import '../core/theme/tokens.dart';

/// 导航外壳内的占位页；后续批次由真实页面替换。
class PlaceholderPage extends StatelessWidget {
  const PlaceholderPage({
    super.key,
    required this.title,
    this.body = S.placeholderBody,
  });

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final palette = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.construction_outlined, size: 40, color: palette.outline),
            const SizedBox(height: AppSpacing.md),
            Text(body, style: TextStyle(color: palette.onSurfaceVariant)),
          ],
        ),
      ),
    );
  }
}
