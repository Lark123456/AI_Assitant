import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_chat_repository.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/chat_message.dart';

class _FixedClock implements Clock {
  _FixedClock(this._now);

  final DateTime _now;

  @override
  DateTime now() => _now;
}

class _FakeApiClient implements ApiClient {
  _FakeApiClient({required this.onGet, required this.onPost});

  final Future<Map<String, dynamic>> Function(String path) onGet;
  final Future<Map<String, dynamic>> Function(
    String path,
    Map<String, dynamic> body,
    String idempotencyKey,
  )
  onPost;

  final List<String> getPaths = [];
  final List<String> postKeys = [];
  final List<Map<String, dynamic>> postBodies = [];

  @override
  Future<Map<String, dynamic>> getJson(String path) {
    getPaths.add(path);
    return onGet(path);
  }

  @override
  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  }) {
    postKeys.add(idempotencyKey);
    postBodies.add(body);
    return onPost(path, body, idempotencyKey);
  }
}

Map<String, dynamic> _message({
  required String id,
  String role = 'user',
  String text = '你好',
  String status = 'done',
  String? clientMessageId,
  String? replyToId,
  String createdAt = '2026-11-23T09:00:00+08:00',
}) => {
  'id': id,
  'role': role,
  'text': text,
  'status': status,
  'clientMessageId': clientMessageId,
  'replyToId': replyToId,
  'createdAt': createdAt,
};

Map<String, dynamic> _page(
  List<Map<String, dynamic>> messages, {
  String? nextCursor,
}) => {
  'messages': messages,
  'nextCursor': nextCursor,
  'previousCursor': messages.isEmpty ? null : messages.first['id'],
  'hasMore': false,
};

RemoteChatRepository _repository(ApiClient client) => RemoteChatRepository(
  client: client,
  clock: _FixedClock(DateTime(2026, 11, 23, 9)),
);

void main() {
  test('首屏请求最新 50 条并保持服务端升序与状态映射', () async {
    final client = _FakeApiClient(
      onGet: (path) async => _page([
        _message(id: 'e1', text: '第一句'),
        _message(
          id: 'e2',
          role: 'friday',
          text: '回复',
          status: 'available',
          replyToId: 'e1',
          createdAt: '2026-11-23T09:00:01+08:00',
        ),
      ], nextCursor: 'e2'),
      onPost: (path, body, key) async => {},
    );
    final repository = _repository(client);
    addTearDown(repository.dispose);

    final messages = await repository.watchMessages().first;

    expect(client.getPaths.single, '/api/mobile/chat/messages?limit=50');
    expect(messages.map((message) => (message as TextMessage).text), [
      '第一句',
      '回复',
    ]);
    expect(messages.map((message) => (message as TextMessage).syncState), [
      SyncState.synced,
      SyncState.synced,
    ]);
    expect((messages[1] as TextMessage).replyToId, 'e1');
  });

  test('发送后保持 pending，状态补偿转 synced 并带回回复', () async {
    var initial = true;
    final client = _FakeApiClient(
      onGet: (path) async {
        if (path.startsWith('/api/mobile/chat/messages/')) {
          return _message(id: 's1', text: '你好', status: 'done');
        }
        if (path == '/api/mobile/chat/messages?limit=50' && initial) {
          initial = false;
          return _page([], nextCursor: null);
        }
        return _page([
          _message(
            id: 'r1',
            role: 'friday',
            text: '收到',
            status: 'available',
            replyToId: 's1',
            createdAt: '2026-11-23T09:00:01+08:00',
          ),
        ], nextCursor: 'r1');
      },
      onPost: (path, body, key) async => {
        'id': 's1',
        'clientMessageId': key,
        'status': 'processing',
      },
    );
    final repository = _repository(client);
    addTearDown(repository.dispose);
    await repository.watchMessages().first;

    await repository.sendText('你好');
    var snapshot = await repository.watchMessages().first;
    final user = snapshot.whereType<TextMessage>().single;
    expect(user.syncState, SyncState.pending);
    expect(user.serverId, 's1');
    expect(user.clientMessageId, client.postKeys.single);

    await repository.setActive(true);
    snapshot = await repository.watchMessages().first;
    final messages = snapshot.whereType<TextMessage>().toList();
    expect(messages.first.syncState, SyncState.synced);
    expect(messages.last.text, '收到');
    expect(client.getPaths, contains('/api/mobile/chat/messages/s1'));
    await repository.setActive(false);
  });

  test('processing 的入站消息通过单条状态补偿发现 failed', () async {
    var statusCalls = 0;
    final client = _FakeApiClient(
      onGet: (path) async {
        if (path.startsWith('/api/mobile/chat/messages/')) {
          statusCalls += 1;
          return _message(
            id: 's1',
            text: '你好',
            status: 'failed',
            clientMessageId: 'c1',
          );
        }
        if (path.contains('after=')) return _page([]);
        return _page([
          _message(
            id: 's1',
            text: '你好',
            status: 'processing',
            clientMessageId: 'c1',
          ),
        ], nextCursor: 's1');
      },
      onPost: (path, body, key) async => {},
    );
    final repository = _repository(client);
    addTearDown(repository.dispose);
    await repository.watchMessages().first;

    await repository.setActive(true);
    final messages = await repository.watchMessages().first;
    expect((messages.single as TextMessage).syncState, SyncState.failed);
    expect(statusCalls, 1);

    // 已移出待补偿集合，不再重复查询
    await repository.setActive(true);
    expect(statusCalls, 1);
    await repository.setActive(false);
  });

  test('发送失败标记 failed，重试复用 clientMessageId', () async {
    var attempts = 0;
    final client = _FakeApiClient(
      onGet: (path) async => _page([], nextCursor: null),
      onPost: (path, body, key) async {
        attempts += 1;
        if (attempts == 1) throw const ApiException('network');
        return {'id': 's9', 'status': 'processing'};
      },
    );
    final repository = _repository(client);
    addTearDown(repository.dispose);
    await repository.watchMessages().first;

    await expectLater(
      repository.sendText('再来一次'),
      throwsA(isA<ApiException>()),
    );
    var messages = await repository.watchMessages().first;
    final failed = messages.single as TextMessage;
    expect(failed.syncState, SyncState.failed);
    expect(failed.serverId, isNull);
    expect(failed.clientMessageId, isNotNull);

    await repository.sendText('再来一次', clientMessageId: failed.clientMessageId);
    messages = await repository.watchMessages().first;
    final retried = messages.single as TextMessage;
    expect(retried.syncState, SyncState.pending);
    expect(retried.serverId, 's9');
    expect(client.postKeys.last, failed.clientMessageId);
  });

  test('after 游标增量合并且按服务端 id 去重', () async {
    final client = _FakeApiClient(
      onGet: (path) async {
        if (path.contains('after=')) {
          return _page([
            _message(id: 'm1', text: '你好'),
            _message(
              id: 'r1',
              role: 'friday',
              text: '回复',
              status: 'available',
              replyToId: 'm1',
              createdAt: '2026-11-23T09:00:01+08:00',
            ),
          ], nextCursor: 'r1');
        }
        return _page([_message(id: 'm1', text: '你好')], nextCursor: 'm1');
      },
      onPost: (path, body, key) async => {},
    );
    final repository = _repository(client);
    addTearDown(repository.dispose);
    await repository.watchMessages().first;

    await repository.setActive(true);
    final messages = (await repository.watchMessages().first)
        .whereType<TextMessage>()
        .toList();

    expect(messages.length, 2);
    expect(messages.map((message) => message.text), ['你好', '回复']);
    expect(client.getPaths.any((path) => path.contains('after=m1')), isTrue);
    await repository.setActive(false);
  });

  test('轮询失败发出同步错误，恢复后清空', () async {
    var calls = 0;
    var failing = true;
    final client = _FakeApiClient(
      onGet: (path) async {
        calls += 1;
        if (calls == 1) return _page([], nextCursor: null);
        if (failing) throw const ApiException('boom');
        return _page([], nextCursor: null);
      },
      onPost: (path, body, key) async => {},
    );
    final repository = _repository(client);
    addTearDown(repository.dispose);
    final errors = <String?>[];
    final subscription = repository.watchSyncError().listen(errors.add);
    addTearDown(subscription.cancel);

    await repository.setActive(true);
    await Future<void>.delayed(Duration.zero);
    expect(errors.last, S.chatSyncFailed);

    failing = false;
    await repository.setActive(true);
    await Future<void>.delayed(Duration.zero);
    expect(errors.last, isNull);
    await repository.setActive(false);
  });

  test('setActive(false) 停止定时轮询', () async {
    var calls = 0;
    final client = _FakeApiClient(
      onGet: (path) async {
        calls += 1;
        return _page([], nextCursor: null);
      },
      onPost: (path, body, key) async => {},
    );
    final repository = RemoteChatRepository(
      client: client,
      clock: _FixedClock(DateTime(2026, 11, 23, 9)),
      pollInterval: const Duration(milliseconds: 20),
    );
    addTearDown(repository.dispose);

    await repository.setActive(true);
    await Future<void>.delayed(const Duration(milliseconds: 70));
    await repository.setActive(false);
    final callsAfterStop = calls;
    await Future<void>.delayed(const Duration(milliseconds: 70));

    expect(calls, callsAfterStop);
  });
}
