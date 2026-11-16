import 'dart:async';
import 'dart:math' as math;

import '../../core/clock.dart';
import '../../domain/enums.dart';
import '../../domain/models/card_action.dart';
import '../../domain/models/chat_message.dart';
import '../../domain/repositories/chat_repository.dart';
import 'mock_network_status_source.dart';
import 'mock_seed.dart';

/// 简单的内存 Chat 仓库：一个消息流、模拟延迟、离线排队、流式回复。
///
/// 不设计传输协议；所有状态变化都通过同一个 `watchMessages()` 流发射。
class MockChatRepository implements ChatRepository {
  MockChatRepository({
    required Clock clock,
    required this.network,
    List<ChatMessage>? seed,
    this.sendDelay = const Duration(milliseconds: 300),
    this.replyDelay = const Duration(milliseconds: 600),
    this.streamInterval = const Duration(milliseconds: 80),
    this.streamChunk = 2,
    this.failNextSend = false,
  }) : _clock = clock,
       _messages = List<ChatMessage>.of(seed ?? seedMessages(clock.now())) {
    _networkSub = network.watch().listen(_onNetworkChanged);
  }

  final Clock _clock;
  final MockNetworkStatusSource network;
  final Duration sendDelay;
  final Duration replyDelay;
  final Duration streamInterval;
  final int streamChunk;

  final _controller = StreamController<List<ChatMessage>>.broadcast();
  final List<ChatMessage> _messages;
  StreamSubscription<NetworkStatus>? _networkSub;
  var _counter = 0;
  var _flushing = false;
  var failNextSend = false;

  @override
  Stream<List<ChatMessage>> watchMessages() async* {
    yield List<ChatMessage>.unmodifiable(_sorted());
    yield* _controller.stream;
  }

  @override
  Future<void> sendText(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;

    final failed = _lastFailed(trimmed);
    if (failed != null) {
      _replace(failed.id, failed.copyWith(syncState: SyncState.pending));
      await _confirmAndReply(failed.id);
      return;
    }

    final queued = network.current == NetworkStatus.offline;
    final id = _nextId();
    _messages.add(
      TextMessage(
        id: id,
        sender: ChatSender.user,
        createdAt: _clock.now(),
        text: trimmed,
        syncState: queued ? SyncState.queued : SyncState.pending,
      ),
    );
    _emit();
    if (queued) return;
    if (failNextSend) {
      failNextSend = false;
      final message = _find(id);
      if (message is TextMessage) {
        _replace(id, message.copyWith(syncState: SyncState.failed));
      }
      throw StateError('mock send failed');
    }
    await _confirmAndReply(id);
  }

  @override
  Future<void> respondToCard({
    required String messageId,
    required CardAction action,
  }) async {
    final index = _messages.indexWhere((message) => message.id == messageId);
    if (index < 0) return;
    final message = _messages[index];

    if (message is ConfirmCard && action is ConfirmAction) {
      _replace(
        messageId,
        message.copyWith(
          state: action.confirmed
              ? ConfirmCardState.confirmed
              : ConfirmCardState.revoked,
          actedAt: _clock.now(),
        ),
      );
      return;
    }
    if (message is ChoiceCard && action is ChoiceAction) {
      _replace(
        messageId,
        message.copyWith(answer: action.skipped ? null : action.option),
      );
      return;
    }
    if (message is MemoryConfirmCard && action is MemoryAction) {
      _replace(
        messageId,
        message.copyWith(
          items: [
            for (final item in message.items)
              item.itemId == action.itemId
                  ? item.copyWith(
                      state: action.confirmed
                          ? MemoryCandidateState.confirmed
                          : MemoryCandidateState.rejected,
                    )
                  : item,
          ],
        ),
      );
      return;
    }
    if (message is MemoryConfirmCard && action is ConfirmAllMemoryAction) {
      _replace(
        messageId,
        message.copyWith(
          items: [
            for (final item in message.items)
              item.copyWith(state: MemoryCandidateState.confirmed),
          ],
        ),
      );
      return;
    }
    if (message is PlanProposalCard && action is PlanProposalAction) {
      _replace(
        messageId,
        message.copyWith(
          state: switch (action.decision) {
            PlanDecision.accept => PlanProposalState.accepted,
            PlanDecision.adjust => PlanProposalState.adjusted,
            PlanDecision.veto => PlanProposalState.vetoed,
          },
        ),
      );
      return;
    }
    if (message is JarvisIntroCard && action is ConfirmAction) {
      _replace(
        messageId,
        message.copyWith(
          state: action.confirmed
              ? JarvisIntroState.accepted
              : JarvisIntroState.declined,
        ),
      );
      if (action.confirmed) {
        await _appendJarvisFollowUp();
      }
    }
  }

  Future<void> _confirmAndReply(String id) async {
    await Future<void>.delayed(sendDelay);
    final message = _find(id);
    if (message is TextMessage) {
      _replace(id, message.copyWith(syncState: SyncState.synced));
    }
    await Future<void>.delayed(replyDelay);
    if (network.current == NetworkStatus.offline) return;
    await _streamReply();
  }

  Future<void> _streamReply() async {
    final replyId = _nextId();
    final full = _replyText();
    _messages.add(
      TextMessage(
        id: replyId,
        sender: ChatSender.friday,
        createdAt: _clock.now(),
        text: '',
        streaming: true,
      ),
    );
    _emit();

    var shown = 0;
    while (shown < full.length) {
      await Future<void>.delayed(streamInterval);
      shown = math.min(full.length, shown + streamChunk);
      final current = _find(replyId);
      if (current is TextMessage) {
        _replace(replyId, current.copyWith(text: full.substring(0, shown)));
      }
    }
    final current = _find(replyId);
    if (current is TextMessage) {
      _replace(
        replyId,
        current.copyWith(streaming: false, syncState: SyncState.synced),
      );
    }
  }

  Future<void> _appendJarvisFollowUp() async {
    await Future<void>.delayed(replyDelay);
    _messages.add(
      ChoiceCard(
        id: _nextId(),
        sender: ChatSender.jarvis,
        createdAt: _clock.now(),
        question: '先从哪一块开始？',
        options: const ['时间安排', '精力状态', '优先级'],
      ),
    );
    _emit();

    await Future<void>.delayed(replyDelay);
    _messages.add(
      ThinkingCard(
        id: _nextId(),
        sender: ChatSender.jarvis,
        createdAt: _clock.now(),
        phase: ThinkingPhase.organizing,
      ),
    );
    _emit();

    await Future<void>.delayed(replyDelay);
    _messages.add(
      PlanProposalCard(
        id: _nextId(),
        sender: ChatSender.jarvis,
        createdAt: _clock.now(),
        summary: '先把本周最难的一件事固定在上午',
        changes: const [
          PlanChange(type: PlanChangeType.add, title: '上午留 45 分钟深度工作'),
        ],
        rationale: '你之前提到下午精力一般',
      ),
    );
    _emit();
  }

  void _onNetworkChanged(NetworkStatus status) {
    if (status != NetworkStatus.online || _flushing) return;
    final queued = _messages.whereType<TextMessage>().where(
      (message) =>
          message.sender == ChatSender.user &&
          message.syncState == SyncState.queued,
    );
    if (queued.isEmpty) return;
    _flushing = true;
    Future<void>(() async {
      try {
        for (final message in queued.toList()) {
          _replace(message.id, message.copyWith(syncState: SyncState.pending));
          _emit();
          await _confirmAndReply(message.id);
        }
      } finally {
        _flushing = false;
      }
    });
  }

  void injectJarvisIntro() {
    _messages.add(
      JarvisIntroCard(
        id: _nextId(),
        sender: ChatSender.friday,
        createdAt: _clock.now(),
        summary: '如果你愿意，我可以让 Jarvis 帮你做一次系统规划',
        previewQuestions: const ['最近主要在忙什么', '希望先解决哪一块'],
      ),
    );
    _emit();
  }

  String _replyText() {
    final lastUserText = _lastUserText();
    if (lastUserText != null && lastUserText.contains('累')) {
      return '听起来今天消耗不小。要不要把下午的安排压缩一点，先留一段空档？';
    }
    return '收到。我先按你现在的节奏排，需要调整随时说。';
  }

  TextMessage? _lastFailed(String text) {
    TextMessage? found;
    for (final message in _messages) {
      if (message is TextMessage &&
          message.sender == ChatSender.user &&
          message.syncState == SyncState.failed &&
          message.text == text) {
        found = message;
      }
    }
    return found;
  }

  String? _lastUserText() {
    String? text;
    for (final message in _messages) {
      if (message is TextMessage && message.sender == ChatSender.user) {
        text = message.text;
      }
    }
    return text;
  }

  /// 统一前缀 + 单调序号，保证同时间戳下按插入顺序稳定排序。
  String _nextId() {
    final number = _counter++;
    return 'm-${number.toString().padLeft(6, '0')}';
  }

  ChatMessage? _find(String id) {
    for (final message in _messages) {
      if (message.id == id) return message;
    }
    return null;
  }

  void _replace(String id, ChatMessage next) {
    final index = _messages.indexWhere((message) => message.id == id);
    if (index >= 0) _messages[index] = next;
    _emit();
  }

  List<ChatMessage> _sorted() {
    final sorted = [..._messages]
      ..sort((left, right) {
        final byTime = left.createdAt.compareTo(right.createdAt);
        return byTime != 0 ? byTime : left.id.compareTo(right.id);
      });
    return sorted;
  }

  void _emit() {
    _controller.add(List<ChatMessage>.unmodifiable(_sorted()));
  }

  void dispose() {
    _networkSub?.cancel();
    _controller.close();
  }
}
