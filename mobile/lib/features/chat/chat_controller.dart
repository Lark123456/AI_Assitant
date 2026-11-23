import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../domain/models/card_action.dart';
import '../../domain/models/chat_message.dart';

class ChatState {
  const ChatState({required this.messages, this.sendError, this.syncError});

  final List<ChatMessage> messages;

  /// 发送失败（用户可用重试按钮再发）。
  final String? sendError;

  /// 轮询/同步失败；恢复后由仓库清空。
  final String? syncError;
}

/// 对话页唯一状态来源：消息流、发送错误、同步错误与卡片应答。
class ChatController extends AsyncNotifier<ChatState> {
  StreamSubscription<List<ChatMessage>>? _subscription;
  StreamSubscription<String?>? _syncErrorSubscription;

  @override
  Future<ChatState> build() async {
    final repository = ref.watch(chatRepositoryProvider);
    final completer = Completer<ChatState>();
    _subscription = repository.watchMessages().listen(
      (messages) {
        final current = state.value;
        final next = ChatState(
          messages: messages,
          sendError: current?.sendError,
          syncError: current?.syncError,
        );
        if (!completer.isCompleted) completer.complete(next);
        state = AsyncData(next);
      },
      onError: (Object error, StackTrace stack) {
        if (!completer.isCompleted) completer.completeError(error, stack);
        state = AsyncError(error, stack);
      },
    );
    _syncErrorSubscription = repository.watchSyncError().listen((error) {
      final current = state.value;
      if (current == null) return;
      state = AsyncData(
        ChatState(
          messages: current.messages,
          sendError: current.sendError,
          syncError: error,
        ),
      );
    });
    ref.onDispose(() {
      _subscription?.cancel();
      _syncErrorSubscription?.cancel();
    });
    return completer.future;
  }

  Future<void> sendText(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    try {
      await ref.read(chatRepositoryProvider).sendText(trimmed);
      _clearError();
    } catch (_) {
      _setError(S.sendFailed);
    }
  }

  /// 本地网络失败复用原 clientMessageId；服务端已确认失败的消息换新 id，
  /// 否则会命中 failed 终态事件而无法重新处理。
  Future<void> retry(TextMessage message) async {
    final clientMessageId = message.serverId == null
        ? message.clientMessageId
        : null;
    try {
      await ref
          .read(chatRepositoryProvider)
          .sendText(message.text, clientMessageId: clientMessageId);
      _clearError();
    } catch (_) {
      _setError(S.sendFailed);
    }
  }

  Future<void> setPollingActive(bool active) async {
    try {
      await ref.read(chatRepositoryProvider).setActive(active);
    } catch (_) {
      // 初始历史加载失败由消息流错误视图展示；轮询错误由 syncError 展示。
      // 这里吞掉是为了避免 unawaited 的 setActive 产生未处理异步异常。
    }
  }

  Future<void> respondToCard(String messageId, CardAction action) async {
    await ref
        .read(chatRepositoryProvider)
        .respondToCard(messageId: messageId, action: action);
  }

  void _setError(String error) {
    final current = state.value;
    if (current == null) return;
    state = AsyncData(
      ChatState(
        messages: current.messages,
        sendError: error,
        syncError: current.syncError,
      ),
    );
  }

  void _clearError() {
    final current = state.value;
    if (current == null || current.sendError == null) return;
    state = AsyncData(
      ChatState(messages: current.messages, syncError: current.syncError),
    );
  }
}

final chatControllerProvider = AsyncNotifierProvider<ChatController, ChatState>(
  ChatController.new,
);
