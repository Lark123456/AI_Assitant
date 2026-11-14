import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/errors.dart';
import 'package:mobile/domain/models/chat_event.dart';
import 'package:mobile/domain/models/chat_message.dart';
import 'package:mobile/domain/models/conversation.dart';

Conversation _conversation() => Conversation(
  conversationId: 'c-1',
  type: ConversationType.main,
  agent: ConversationAgent.friday,
  status: ConversationStatus.active,
  createdAt: DateTime(2026, 11, 15, 8),
  lastActivityAt: DateTime(2026, 11, 15, 9),
);

TextMessage _formal({String id = 'm-1', int seq = 1, String text = '正式'}) =>
    TextMessage(
      id: id,
      conversationId: 'c-1',
      sender: ChatSender.user,
      createdAt: DateTime(2026, 11, 15, 9),
      seq: seq,
      text: text,
    );

TextMessage _local({
  String id = 'l-1',
  int seq = -1,
  SyncState syncState = SyncState.pending,
  String text = '本地',
}) => TextMessage(
  id: id,
  conversationId: 'c-1',
  sender: ChatSender.user,
  createdAt: DateTime(2026, 11, 15, 9),
  seq: seq,
  text: text,
  syncState: syncState,
);

void main() {
  group('ChatMessage 本地/正式边界', () {
    test('空 id 与空 conversationId 触发断言', () {
      expect(() => _formal(id: ''), throwsA(isA<AssertionError>()));
      expect(
        () => TextMessage(
          id: 'm-1',
          conversationId: '',
          sender: ChatSender.user,
          createdAt: DateTime(2026, 11, 15, 9),
          seq: 1,
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('seq 不得为 0；synced 必须正 seq，本地必须负 seq', () {
      expect(() => _formal(seq: 0), throwsA(isA<AssertionError>()));
      expect(() => _formal(seq: -1), throwsA(isA<AssertionError>()));
      expect(
        () => _local(seq: 1, syncState: SyncState.pending),
        throwsA(isA<AssertionError>()),
      );
    });

    test('本地消息不得直接标记为 synced', () {
      final local = _local();

      expect(
        () => local.copyWith(syncState: SyncState.synced),
        throwsA(isA<StateTransitionException>()),
      );
    });

    test('本地消息可更新文本与排队状态', () {
      final local = _local(syncState: SyncState.queued);

      expect(
        local.copyWith(syncState: SyncState.pending).syncState,
        SyncState.pending,
      );
      expect(local.copyWith().syncState, SyncState.queued);
      expect(local.copyWith(text: '新内容').text, '新内容');
      expect(local.copyWith(streaming: true).streaming, isTrue);
    });
  });

  group('ChatView 合并展示', () {
    test('合法视图按正式消息 → pending 展示', () {
      final queued = _local(id: 'l-2', seq: -2, syncState: SyncState.queued);
      final view = ChatView(
        conversation: _conversation(),
        messages: [
          _formal(id: 'm-1', seq: 1),
          _formal(id: 'm-2', seq: 2),
        ],
        pending: [
          _local(id: 'l-1', seq: -1),
          queued,
        ],
      );

      expect(view.displayMessages.map((m) => m.id), [
        'm-1',
        'm-2',
        'l-1',
        'l-2',
      ]);
      expect(view.displayMessages.length, 4);
      expect(
        () => view.messages.add(_formal(id: 'm-3', seq: 3)),
        throwsA(isA<UnsupportedError>()),
      );
    });

    test('发送错误只指向 failed 的 pending 消息', () {
      final failed = _local(id: 'l-3', seq: -3, syncState: SyncState.failed);
      final view = ChatView(
        conversation: _conversation(),
        messages: [_formal()],
        pending: [failed],
        sendErrors: const {'l-3': '网络异常'},
      );

      expect(view.sendErrors['l-3'], '网络异常');
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: [_formal()],
          pending: [_local(id: 'l-1', seq: -1)],
          sendErrors: const {'l-1': '网络异常'},
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: [_formal()],
          pending: [failed],
          sendErrors: const {'l-3': ''},
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('pending 必须是同会话负 seq 且按创建顺序', () {
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: [_formal()],
          pending: [_local(seq: 1)],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: [_formal()],
          pending: [
            _local(id: 'l-1', seq: -2),
            _local(id: 'l-2', seq: -1),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: [_formal()],
          pending: [
            TextMessage(
              id: 'l-1',
              conversationId: 'c-2',
              sender: ChatSender.user,
              createdAt: DateTime(2026, 11, 15, 9),
              seq: -1,
              syncState: SyncState.queued,
            ),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('pending 与正式消息 id 不得重复，pending 内 id 唯一', () {
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: [_formal(id: 'm-1', seq: 1)],
          pending: [_local(id: 'm-1', seq: -1)],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: const [],
          pending: [
            _local(id: 'l-1', seq: -1),
            _local(id: 'l-1', seq: -2),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('集合字段不可变，外部修改不影响模型', () {
      final formalSource = <ChatMessage>[_formal(id: 'm-1', seq: 1)];
      final pendingSource = <ChatMessage>[_local()];
      final errorsSource = <String, String>{'l-3': '网络异常'};
      final failed = _local(id: 'l-3', seq: -2, syncState: SyncState.failed);
      pendingSource.add(failed);
      final view = ChatView(
        conversation: _conversation(),
        messages: formalSource,
        pending: pendingSource,
        sendErrors: {'l-3': '网络异常'},
      );

      formalSource.clear();
      pendingSource.clear();
      errorsSource.clear();

      expect(view.messages.length, 1);
      expect(view.pending.length, 2);
      expect(view.sendErrors['l-3'], '网络异常');
      expect(() => view.pending.clear(), throwsA(isA<UnsupportedError>()));
      expect(
        () => view.sendErrors['x'] = 'y',
        throwsA(isA<UnsupportedError>()),
      );
    });

    test('同步状态与 retryCount/syncError 联动', () {
      expect(
        () => ChatView(
          conversation: _conversation(),
          messages: const [],
          pending: const [],
          syncState: ConversationSyncState.failed,
          retryCount: 1,
        ),
        throwsA(isA<AssertionError>()),
      );
      final view = ChatView(
        conversation: _conversation(),
        messages: const [],
        pending: const [],
        syncState: ConversationSyncState.failed,
        retryCount: 2,
        syncError: '同步异常',
      );

      expect(view.syncState, ConversationSyncState.failed);
      expect(view.retryCount, 2);
    });
  });
}
