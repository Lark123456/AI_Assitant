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
      }
      _emitIfChanged();
    } catch (_) {
      _updateLocal(messageId, syncState: SyncState.failed);
      _emitIfChanged();
      rethrow;
    }
  }

  /// 远程模式暂不支持卡片应答（服务端只返回文字消息）。
  @override
  Future<void> respondToCard({
    required String messageId,
    required CardAction action,
  }) async {
    throw UnsupportedError('远程聊天暂不支持卡片应答');
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

  void _merge(List<TextMessage> incoming) {
    for (final remote in incoming) {
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

  List<TextMessage> _parseMessages(Map<String, dynamic> raw) {
    final list = raw['messages'];
    if (list is! List) {
      throw const ApiException('messages 必须是数组');
    }
    return [for (final item in list) _parseMessage(item)];
  }

  TextMessage _parseMessage(Object? raw) {
    if (raw is! Map<String, dynamic>) {
      throw const ApiException('消息必须是对象');
    }
    final id = raw['id'];
    final role = raw['role'];
    final text = raw['text'];
    final createdAt = raw['createdAt'];
    if (id is! String ||
        id.isEmpty ||
        role is! String ||
        text is! String ||
        createdAt is! String) {
      throw const ApiException('消息字段不完整');
    }
    final sender = switch (role) {
      'user' => ChatSender.user,
      'friday' => ChatSender.friday,
      _ => throw ApiException('未知 role：$role'),
    };
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

  void _replaceById(String id, TextMessage next) {
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
    _pollTimer?.cancel();
    _pollTimer = null;
    _controller.close();
    _syncErrors.close();
  }
}

String? _stringOrNull(Object? value) =>
    value is String && value.isNotEmpty ? value : null;
