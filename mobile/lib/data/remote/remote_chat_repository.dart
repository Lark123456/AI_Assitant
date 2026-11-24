import 'dart:async';
import 'dart:math';

import '../../core/clock.dart';
import '../../core/strings.dart';
import '../../domain/enums.dart';
import '../../domain/models/card_action.dart';
import '../../domain/models/chat_message.dart';
import '../../domain/repositories/chat_repository.dart';
import 'api_client.dart';

/// 手机聊天真实仓库。
///
/// 数据来源只有 event_log 派生的 chat API：
/// - 首屏取最新 N 条（后端已按时间升序返回）；
/// - 轮询用 after 游标取增量，不整表覆盖；
/// - 已存在的入站消息从 processing 变 done/failed 不产生新事件，
///   因此额外用单条状态接口补偿（见 [setActive] 的立即刷新）。
///
/// 本地乐观消息按 clientMessageId 与服务端回显合并；服务端消息按事件 id 去重。
class RemoteChatRepository implements ChatRepository {
  RemoteChatRepository({
    required this.client,
    required this.clock,
    this.pollInterval = const Duration(seconds: 2),
    this.pageSize = 50,
  });

  final ApiClient client;
  final Clock clock;
  final Duration pollInterval;
  final int pageSize;

  final _controller = StreamController<List<ChatMessage>>.broadcast();
  final _syncErrors = StreamController<String?>.broadcast();
  final List<ChatMessage> _messages = [];
  final Set<String> _pendingInboundIds = {};
  final Map<String, StreamSubscription<SseEvent>> _streamSubs = {};

  Timer? _pollTimer;
  var _active = false;
  var _inFlight = false;
  var _loaded = false;
  Future<void>? _loading;
  String? _cursor;
  String? _syncError;
  String? _lastSignature;
  Duration _backoff = Duration.zero;
  DateTime? _nextPollAt;
  var _sequence = 0;
  final _random = Random.secure();

  static const _maxBackoff = Duration(seconds: 30);

  @override
  Stream<List<ChatMessage>> watchMessages() async* {
    await _ensureLoaded();
    yield _snapshot();
    yield* _controller.stream;
  }

  @override
  Stream<String?> watchSyncError() => _syncErrors.stream;

  @override
  Future<void> setActive(bool active) async {
    _active = active;
    if (!active) {
      _pollTimer?.cancel();
      _pollTimer = null;
      _cancelStreams();
      return;
    }
    await _ensureLoaded();
    await _pollOnce(force: true);
    _pollTimer ??= Timer.periodic(pollInterval, (_) => unawaited(_pollOnce()));
  }

  @override
  Future<void> sendText(String text, {String? clientMessageId}) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;

    final messageId = clientMessageId ?? _newClientMessageId();
    final existing = _findByClientMessageId(messageId);
    final local = existing == null
        ? TextMessage(
            id: 'local-$messageId',
            sender: ChatSender.user,
            createdAt: clock.now(),
            text: trimmed,
            syncState: SyncState.pending,
            clientMessageId: messageId,
          )
        : existing.copyWith(text: trimmed, syncState: SyncState.pending);
    if (existing == null) {
      _messages.add(local);
    } else {
      _replaceById(local.id, local);
    }
    _emitIfChanged();

    try {
      final raw = await client.postJson('/api/mobile/chat/messages', {
        'clientMessageId': messageId,
        'text': trimmed,
      }, idempotencyKey: messageId);
      final serverId = raw['id'];
      final status = raw['status'];
      final statusText = status is String ? status : 'processing';
      _updateLocal(
        messageId,
        serverId: serverId is String ? serverId : null,
        syncState: _inboundSyncState(statusText),
      );
      if (serverId is String && statusText == 'processing') {
        _pendingInboundIds.add(serverId);
        _startStream(serverId);
      }
      _emitIfChanged();
    } catch (_) {
      _updateLocal(messageId, syncState: SyncState.failed);
      _emitIfChanged();
      rethrow;
    }
  }

  /// 记忆确认卡片：确认/拒绝走真实后端；其它卡片仍不支持远程应答。
  @override
  Future<void> respondToCard({
    required String messageId,
    required CardAction action,
  }) async {
    final index = _messages.indexWhere((message) => message.id == messageId);
    if (index < 0 || _messages[index] is! MemoryConfirmCard) {
      throw UnsupportedError('远程仅支持记忆确认卡片');
    }
    final card = _messages[index] as MemoryConfirmCard;
    final Map<String, dynamic> body;
    switch (action) {
      case MemoryAction(:final itemId, :final confirmed):
        body = {'action': confirmed ? 'confirm' : 'reject', 'itemId': itemId};
      case ConfirmAllMemoryAction():
        body = {'action': 'confirm'};
      default:
        throw UnsupportedError('该卡片动作暂不支持远程应答');
    }
    final raw = await client.postJson(
      '/api/mobile/chat/messages/${Uri.encodeComponent(messageId)}/card-actions',
      body,
      idempotencyKey: _newClientMessageId(),
    );
    final rawItems = raw['items'];
    if (rawItems is! List || rawItems.isEmpty) {
      throw const ApiException('卡片响应缺少 items');
    }
    final labels = {for (final item in card.items) item.itemId: item.label};
    final items = <MemoryCandidateItem>[];
    for (final item in rawItems) {
      if (item is! Map<String, dynamic>) {
        throw const ApiException('卡片 item 格式错误');
      }
      final itemId = item['itemId'];
      if (itemId is! String || itemId.isEmpty) {
        throw const ApiException('卡片 item 缺少 itemId');
      }
      items.add(
        MemoryCandidateItem(
          itemId: itemId,
          label: (item['label'] as String?) ?? labels[itemId] ?? itemId,
          state: _memoryState(item['state']),
        ),
      );
    }
    _replaceById(messageId, card.copyWith(items: items));
    _emitIfChanged();
  }

  Future<void> _ensureLoaded() {
    if (_loaded) return Future<void>.value();
    return _loading ??= _loadInitial().whenComplete(() {
      _loading = null;
    });
  }

  Future<void> _loadInitial() async {
    final raw = await client.getJson(
      '/api/mobile/chat/messages?limit=$pageSize',
    );
    _merge(_parseMessages(raw));
    _cursor = _stringOrNull(raw['nextCursor']);
    _loaded = true;
    _setSyncError(null);
    _emitIfChanged();
  }

  Future<void> _pollOnce({bool force = false}) async {
    if (_inFlight || !_active) return;
    final nextPollAt = _nextPollAt;
    if (!force && nextPollAt != null && clock.now().isBefore(nextPollAt)) {
      return;
    }
    _inFlight = true;
    try {
      final path = _cursor == null
          ? '/api/mobile/chat/messages?limit=$pageSize'
          : '/api/mobile/chat/messages'
                '?after=${Uri.encodeQueryComponent(_cursor!)}&limit=$pageSize';
      final raw = await client.getJson(path);
      _merge(_parseMessages(raw));
      final next = _stringOrNull(raw['nextCursor']);
      if (next != null) _cursor = next;
      await _refreshPendingStatuses();
      _backoff = Duration.zero;
      _nextPollAt = null;
      _setSyncError(null);
      _emitIfChanged();
    } catch (_) {
      _backoff = _backoff == Duration.zero
          ? pollInterval
          : (_backoff * 2 > _maxBackoff ? _maxBackoff : _backoff * 2);
      _nextPollAt = clock.now().add(_backoff);
      _setSyncError(S.chatSyncFailed);
    } finally {
      _inFlight = false;
    }
  }

  /// after 只带回新事件；processing→done/failed 必须逐条查询补齐。
  Future<void> _refreshPendingStatuses() async {
    if (_pendingInboundIds.isEmpty) return;
    for (final eventId in _pendingInboundIds.take(20).toList()) {
      final raw = await client.getJson(
        '/api/mobile/chat/messages/${Uri.encodeComponent(eventId)}',
      );
      final status = raw['status'];
      final syncState = _inboundSyncState(status is String ? status : 'failed');
      _applyServerStatus(eventId, syncState);
      if (syncState != SyncState.pending) {
        _pendingInboundIds.remove(eventId);
      }
    }
  }

  void _merge(List<ChatMessage> incoming) {
    for (final remote in incoming) {
      if (remote is! TextMessage) {
        // 卡片等非文本消息按事件 id 覆盖，确保状态更新能推送。
        final index = _messages.indexWhere(
          (message) => message.id == remote.id,
        );
        if (index >= 0) {
          _messages[index] = remote;
        } else {
          _messages.add(remote);
        }
        continue;
      }
      if (remote.sender == ChatSender.friday && remote.replyToId != null) {
        // 服务端最终回复到达后移除同一条入站的流式占位气泡。
        _removeById('stream-${remote.replyToId}');
      }
      var index = -1;
      final clientId = remote.clientMessageId;
      if (remote.sender == ChatSender.user && clientId != null) {
        index = _indexOfClientMessageId(clientId);
      }
      if (index < 0 && remote.serverId != null) {
        index = _messages.indexWhere(
          (message) =>
              message is TextMessage && message.serverId == remote.serverId,
        );
      }
      if (index >= 0) {
        final local = _messages[index] as TextMessage;
        _messages[index] = _mergeInto(local, remote);
      } else {
        _messages.add(remote);
      }
      if (remote.sender == ChatSender.user && remote.serverId != null) {
        if (remote.syncState == SyncState.pending) {
          _pendingInboundIds.add(remote.serverId!);
        } else {
          _pendingInboundIds.remove(remote.serverId);
        }
      }
    }
    _messages.sort(_compare);
  }

  TextMessage _mergeInto(TextMessage local, TextMessage remote) {
    return TextMessage(
      id: local.id,
      sender: remote.sender,
      createdAt: local.createdAt,
      text: remote.text,
      syncState: remote.syncState,
      serverId: remote.serverId ?? local.serverId,
      clientMessageId: remote.clientMessageId ?? local.clientMessageId,
      replyToId: remote.replyToId,
    );
  }

  List<ChatMessage> _parseMessages(Map<String, dynamic> raw) {
    final list = raw['messages'];
    if (list is! List) {
      throw const ApiException('messages 必须是数组');
    }
    final messages = <ChatMessage>[];
    for (final item in list) {
      final parsed = _parseMessage(item);
      if (parsed != null) messages.add(parsed);
    }
    return messages;
  }

  ChatMessage? _parseMessage(Object? raw) {
    if (raw is! Map<String, dynamic>) {
      throw const ApiException('消息必须是对象');
    }
    final id = raw['id'];
    final role = raw['role'];
    final createdAt = raw['createdAt'];
    if (id is! String ||
        id.isEmpty ||
        role is! String ||
        createdAt is! String) {
      throw const ApiException('消息字段不完整');
    }
    final sender = switch (role) {
      'user' => ChatSender.user,
      'friday' => ChatSender.friday,
      _ => throw ApiException('未知 role：$role'),
    };
    final kind = raw['kind'];

    if (kind == 'memory_confirm') {
      final rawItems = raw['items'];
      if (rawItems is! List || rawItems.isEmpty) {
        throw const ApiException('记忆卡片 items 不能为空');
      }
      final items = <MemoryCandidateItem>[];
      for (final item in rawItems) {
        if (item is! Map<String, dynamic>) {
          throw const ApiException('记忆卡片 item 格式错误');
        }
        final itemId = item['itemId'];
        final label = item['label'];
        if (itemId is! String ||
            itemId.isEmpty ||
            label is! String ||
            label.isEmpty) {
          throw const ApiException('记忆卡片 item 字段不完整');
        }
        items.add(
          MemoryCandidateItem(
            itemId: itemId,
            label: label,
            state: _memoryState(item['state']),
          ),
        );
      }
      return MemoryConfirmCard(
        id: id,
        sender: sender,
        createdAt: DateTime.parse(createdAt).toLocal(),
        syncState: SyncState.synced,
        items: items,
      );
    }

    final text = raw['text'];
    if (text is! String) {
      // 未知且无文本的卡片类型：跳过，避免整页解析失败。
      if (kind != null && kind != 'text') return null;
      throw const ApiException('消息字段不完整');
    }
    final status = raw['status'];
    return TextMessage(
      id: id,
      sender: sender,
      createdAt: DateTime.parse(createdAt).toLocal(),
      text: text,
      syncState: sender == ChatSender.user
          ? _inboundSyncState(status is String ? status : 'failed')
          : SyncState.synced,
      serverId: id,
      clientMessageId: _stringOrNull(raw['clientMessageId']),
      replyToId: _stringOrNull(raw['replyToId']),
    );
  }

  MemoryCandidateState _memoryState(Object? raw) => switch (raw) {
    'confirmed' => MemoryCandidateState.confirmed,
    'rejected' => MemoryCandidateState.rejected,
    _ => MemoryCandidateState.pending,
  };

  void _startStream(String inboundId) {
    final sse = client is SseClient ? client as SseClient : null;
    if (sse == null) return;
    _cancelStream(inboundId);
    // 订阅保存在 _streamSubs，由 _cancelStream/dispose 统一取消。
    // ignore: cancel_subscriptions
    final subscription = sse
        .getSse(
          '/api/mobile/chat/messages/${Uri.encodeComponent(inboundId)}/stream',
        )
        .listen(
          (event) {
            switch (event.event) {
              case 'delta':
                _upsertStreamSnapshot(inboundId, event.data['text']);
              case 'done':
                _finalizeStream(inboundId, event.data);
              case 'error':
                _abandonStream(inboundId);
            }
          },
          onError: (Object error, StackTrace stack) =>
              _abandonStream(inboundId),
          cancelOnError: true,
        );
    _streamSubs[inboundId] = subscription;
  }

  void _upsertStreamSnapshot(String inboundId, Object? rawText) {
    if (rawText is! String) return;
    final streamId = 'stream-$inboundId';
    final index = _messages.indexWhere((message) => message.id == streamId);
    final existing = index >= 0 ? _messages[index] as TextMessage : null;
    final message = TextMessage(
      id: streamId,
      sender: ChatSender.friday,
      createdAt: existing?.createdAt ?? clock.now(),
      text: rawText,
      streaming: true,
      syncState: SyncState.pending,
      replyToId: inboundId,
    );
    if (index >= 0) {
      _messages[index] = message;
    } else {
      _messages.add(message);
    }
    _emitIfChanged();
  }

  void _finalizeStream(String inboundId, Map<String, dynamic> data) {
    _cancelStream(inboundId);
    _pendingInboundIds.remove(inboundId);
    final messageId = data['messageId'];
    final text = data['text'];
    if (messageId is String && messageId.isNotEmpty) {
      final message = TextMessage(
        id: messageId,
        sender: ChatSender.friday,
        createdAt: _parseStreamTime(data['createdAt']),
        text: text is String ? text : '',
        syncState: SyncState.synced,
        serverId: messageId,
        replyToId: inboundId,
      );
      final index = _messages.indexWhere(
        (existing) => existing is TextMessage && existing.serverId == messageId,
      );
      if (index >= 0) {
        _messages[index] = message;
      } else {
        _messages.add(message);
      }
      _messages.sort(_compare);
    }
    _emitIfChanged();
  }

  void _abandonStream(String inboundId) {
    _cancelStream(inboundId);
    _emitIfChanged();
  }

  void _cancelStream(String inboundId) {
    final subscription = _streamSubs.remove(inboundId);
    if (subscription != null) unawaited(subscription.cancel());
    _removeById('stream-$inboundId');
  }

  void _cancelStreams() {
    for (final inboundId in _streamSubs.keys.toList()) {
      _cancelStream(inboundId);
    }
    _streamSubs.clear();
    _emitIfChanged();
  }

  bool _removeById(String id) {
    final before = _messages.length;
    _messages.removeWhere((message) => message.id == id);
    return _messages.length != before;
  }

  DateTime _parseStreamTime(Object? raw) {
    if (raw is String) {
      final parsed = DateTime.tryParse(raw);
      if (parsed != null) return parsed.toLocal();
    }
    return clock.now();
  }

  void _applyServerStatus(String serverId, SyncState syncState) {
    final index = _messages.indexWhere(
      (message) => message is TextMessage && message.serverId == serverId,
    );
    if (index < 0) return;
    final local = _messages[index] as TextMessage;
    _messages[index] = local.copyWith(syncState: syncState);
  }

  void _updateLocal(
    String clientMessageId, {
    String? serverId,
    SyncState? syncState,
  }) {
    final index = _indexOfClientMessageId(clientMessageId);
    if (index < 0) return;
    final local = _messages[index] as TextMessage;
    _messages[index] = local.copyWith(serverId: serverId, syncState: syncState);
  }

  void _replaceById(String id, ChatMessage next) {
    final index = _messages.indexWhere((message) => message.id == id);
    if (index >= 0) _messages[index] = next;
  }

  int _indexOfClientMessageId(String clientMessageId) {
    return _messages.indexWhere(
      (message) =>
          message is TextMessage && message.clientMessageId == clientMessageId,
    );
  }

  TextMessage? _findByClientMessageId(String clientMessageId) {
    final index = _indexOfClientMessageId(clientMessageId);
    return index < 0 ? null : _messages[index] as TextMessage;
  }

  SyncState _inboundSyncState(String status) => switch (status) {
    'processing' => SyncState.pending,
    'done' => SyncState.synced,
    'failed' => SyncState.failed,
    _ => SyncState.failed,
  };

  String _newClientMessageId() {
    _sequence += 1;
    final suffix = _random
        .nextInt(0x100000000)
        .toRadixString(16)
        .padLeft(8, '0');
    return 'c-${clock.now().millisecondsSinceEpoch}-$_sequence-$suffix';
  }

  void _emitIfChanged() {
    final messages = _snapshot();
    final signature = messages.map(_signatureOf).join('|');
    if (signature == _lastSignature) return;
    _lastSignature = signature;
    _controller.add(messages);
  }

  String _signatureOf(ChatMessage message) => switch (message) {
    TextMessage(:final id, :final text, :final syncState, :final serverId) =>
      '$id:$text:${syncState.name}:$serverId',
    MemoryConfirmCard(:final id, :final items) =>
      '$id:${items.map((item) => '${item.itemId}:${item.state.name}').join(',')}',
    _ => message.id,
  };

  List<ChatMessage> _snapshot() {
    final sorted = [..._messages]..sort(_compare);
    return List<ChatMessage>.unmodifiable(sorted);
  }

  int _compare(ChatMessage left, ChatMessage right) {
    final byTime = left.createdAt.compareTo(right.createdAt);
    return byTime != 0 ? byTime : left.id.compareTo(right.id);
  }

  void _setSyncError(String? error) {
    if (_syncError == error) return;
    _syncError = error;
    _syncErrors.add(error);
  }

  void dispose() {
    _cancelStreams();
    _pollTimer?.cancel();
    _pollTimer = null;
    _controller.close();
    _syncErrors.close();
  }
}

String? _stringOrNull(Object? value) =>
    value is String && value.isNotEmpty ? value : null;
