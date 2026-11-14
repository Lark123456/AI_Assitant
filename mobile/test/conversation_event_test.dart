import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/chat_event.dart';
import 'package:mobile/domain/models/chat_message.dart';
import 'package:mobile/domain/models/conversation.dart';

Conversation _conversation({
  String id = 'c-1',
  ConversationStatus status = ConversationStatus.active,
}) => Conversation(
  conversationId: id,
  type: ConversationType.main,
  agent: ConversationAgent.friday,
  status: status,
  createdAt: DateTime(2026, 11, 15, 8),
  lastActivityAt: DateTime(2026, 11, 15, 9),
);

TextMessage _formal({
  String id = 'm-1',
  String conversationId = 'c-1',
  int seq = 1,
}) => TextMessage(
  id: id,
  conversationId: conversationId,
  sender: ChatSender.user,
  createdAt: DateTime(2026, 11, 15, 9),
  seq: seq,
  text: '你好',
);

TextMessage _local({String id = 'l-1', String conversationId = 'c-1'}) =>
    TextMessage(
      id: id,
      conversationId: conversationId,
      sender: ChatSender.user,
      createdAt: DateTime(2026, 11, 15, 9),
      seq: -1,
      text: '本地',
      syncState: SyncState.pending,
    );

void main() {
  group('ChatEvent 基础不变量', () {
    test('conversationId 不得为空，seq 必须为正', () {
      expect(
        () => ConversationUpdated(
          conversationId: '',
          seq: 1,
          conversation: _conversation(),
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ConversationUpdated(
          conversationId: 'c-1',
          seq: 0,
          conversation: _conversation(),
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('MessageUpsert 一致性', () {
    test('合法正式消息事件', () {
      final event = MessageUpsert(
        conversationId: 'c-1',
        seq: 1,
        message: _formal(),
      );

      expect(event.seq, 1);
      expect(event.message.id, 'm-1');
    });

    test('消息归属与事件不一致触发断言', () {
      expect(
        () => MessageUpsert(
          conversationId: 'c-1',
          seq: 1,
          message: _formal(conversationId: 'c-2'),
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('消息 seq 与事件不一致触发断言', () {
      expect(
        () => MessageUpsert(
          conversationId: 'c-1',
          seq: 2,
          message: _formal(seq: 1),
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('事件消息必须是已同步正式消息', () {
      expect(
        () => MessageUpsert(conversationId: 'c-1', seq: 1, message: _local()),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('ConversationUpdated 一致性', () {
    test('对话 id 与事件不一致触发断言', () {
      expect(
        () => ConversationUpdated(
          conversationId: 'c-1',
          seq: 2,
          conversation: _conversation(id: 'c-2'),
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('ConversationSnapshot', () {
    test('合法快照保留正式消息顺序', () {
      final snapshot = ConversationSnapshot(
        conversation: _conversation(),
        messages: [
          _formal(id: 'm-1', seq: 1),
          _formal(id: 'm-2', seq: 2),
        ],
        lastSeq: 2,
      );

      expect(snapshot.lastSeq, 2);
      expect(snapshot.messages.map((m) => m.id), ['m-1', 'm-2']);
      expect(
        () => snapshot.messages.add(_formal(id: 'm-3', seq: 3)),
        throwsA(isA<UnsupportedError>()),
      );
    });

    test('lastSeq 不得为负', () {
      expect(
        () => ConversationSnapshot(
          conversation: _conversation(),
          messages: const [],
          lastSeq: -1,
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('仅接受同一会话的正式消息且 seq <= lastSeq', () {
      expect(
        () => ConversationSnapshot(
          conversation: _conversation(),
          messages: [_formal(seq: 3)],
          lastSeq: 2,
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ConversationSnapshot(
          conversation: _conversation(),
          messages: [_formal(conversationId: 'c-2')],
          lastSeq: 1,
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ConversationSnapshot(
          conversation: _conversation(),
          messages: [_local()],
          lastSeq: 1,
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('消息 id 唯一且按 seq 升序', () {
      expect(
        () => ConversationSnapshot(
          conversation: _conversation(),
          messages: [
            _formal(id: 'm-1', seq: 1),
            _formal(id: 'm-1', seq: 2),
          ],
          lastSeq: 2,
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ConversationSnapshot(
          conversation: _conversation(),
          messages: [
            _formal(id: 'm-2', seq: 2),
            _formal(id: 'm-1', seq: 1),
          ],
          lastSeq: 2,
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('ConversationView 同步状态组合', () {
    test('合法同步视图', () {
      final view = ConversationView(
        conversation: _conversation(),
        messages: [_formal(seq: 1)],
      );

      expect(view.syncState, ConversationSyncState.synced);
      expect(view.retryCount, 0);
      expect(view.syncError, isNull);
      expect(() => view.messages.clear(), throwsA(isA<UnsupportedError>()));
    });

    test('failed 必须携带非空 syncError，且 retryCount > 0', () {
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: const [],
          syncState: ConversationSyncState.failed,
          retryCount: 1,
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: const [],
          syncState: ConversationSyncState.failed,
          retryCount: 0,
          syncError: '同步失败',
        ),
        throwsA(isA<AssertionError>()),
      );
      final view = ConversationView(
        conversation: _conversation(),
        messages: const [],
        syncState: ConversationSyncState.failed,
        retryCount: 2,
        syncError: '同步失败',
      );
      expect(view.syncError, '同步失败');
    });

    test('非 failed 不得携带 syncError', () {
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: const [],
          syncState: ConversationSyncState.syncing,
          syncError: '异常',
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('retrying 必须有 retryCount 且无 syncError', () {
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: const [],
          syncState: ConversationSyncState.retrying,
        ),
        throwsA(isA<AssertionError>()),
      );
      final view = ConversationView(
        conversation: _conversation(),
        messages: const [],
        syncState: ConversationSyncState.retrying,
        retryCount: 1,
      );
      expect(view.retryCount, 1);
    });

    test('retryCount 不得超过 2', () {
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: const [],
          syncState: ConversationSyncState.retrying,
          retryCount: 3,
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('消息必须同会话、唯一且按 seq 升序', () {
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: [_formal(conversationId: 'c-2')],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: [
            _formal(id: 'm-1', seq: 1),
            _formal(id: 'm-1', seq: 2),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ConversationView(
          conversation: _conversation(),
          messages: [
            _formal(id: 'm-2', seq: 2),
            _formal(id: 'm-1', seq: 1),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });
}
