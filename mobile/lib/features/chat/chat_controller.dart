import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../domain/models/card_action.dart';
import '../../domain/models/chat_message.dart';

class ChatState {
  const ChatState({required this.messages, this.sendError});

  final List<ChatMessage> messages;
  final String? sendError;
}

/// 对话页唯一状态来源：消息流、发送错误与卡片应答。
class ChatController extends AsyncNotifier<ChatState> {
  StreamSubscription<List<ChatMessage>>? _subscription;

  @override
  Future<ChatState> build() async {
    final repository = ref.watch(chatRepositoryProvider);
    final completer = Completer<ChatState>();
    _subscription = repository.watchMessages().listen(
      (messages) {
        final next = ChatState(
          messages: messages,
          sendError: state.value?.sendError,
        );
        if (!completer.isCompleted) completer.complete(next);
        state = AsyncData(next);
      },
      onError: (Object error, StackTrace stack) {
        if (!completer.isCompleted) completer.completeError(error, stack);
        state = AsyncError(error, stack);
      },
    );
    ref.onDispose(() => _subscription?.cancel());
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

  Future<void> retry(TextMessage message) async {
    try {
      await ref.read(chatRepositoryProvider).sendText(message.text);
      _clearError();
    } catch (_) {
      _setError(S.sendFailed);
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
    state = AsyncData(ChatState(messages: current.messages, sendError: error));
  }

  void _clearError() {
    final current = state.value;
    if (current == null || current.sendError == null) return;
    state = AsyncData(ChatState(messages: current.messages));
  }
}

final chatControllerProvider = AsyncNotifierProvider<ChatController, ChatState>(
  ChatController.new,
);
