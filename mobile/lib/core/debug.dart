import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 调试面板可切换的数据集。
enum DebugDataset { normal, empty, error }

enum DebugThemeMode { system, light, dark }

class DebugState {
  const DebugState({
    this.dataset = DebugDataset.normal,
    this.themeMode = DebugThemeMode.system,
    this.textScale = 1.0,
    this.failNextSend = false,
  });

  final DebugDataset dataset;
  final DebugThemeMode themeMode;
  final double textScale;
  final bool failNextSend;

  DebugState copyWith({
    DebugDataset? dataset,
    DebugThemeMode? themeMode,
    double? textScale,
    bool? failNextSend,
  }) {
    return DebugState(
      dataset: dataset ?? this.dataset,
      themeMode: themeMode ?? this.themeMode,
      textScale: textScale ?? this.textScale,
      failNextSend: failNextSend ?? this.failNextSend,
    );
  }
}

class DebugController extends Notifier<DebugState> {
  @override
  DebugState build() => const DebugState();

  void setDataset(DebugDataset value) => state = state.copyWith(dataset: value);

  void setThemeMode(DebugThemeMode value) =>
      state = state.copyWith(themeMode: value);

  void setTextScale(double value) => state = state.copyWith(textScale: value);

  void setFailNextSend(bool value) =>
      state = state.copyWith(failNextSend: value);
}

final debugControllerProvider = NotifierProvider<DebugController, DebugState>(
  DebugController.new,
);
