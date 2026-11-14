import '../enums.dart';
import 'chat_message.dart';
import 'conversation.dart';

/// 会话事件：`MessageUpsert`、`ConversationUpdated` 及未来事件同属一条按 `seq` 递增的事件序列。
sealed class ChatEvent {
  const ChatEvent({required this.conversationId, required this.seq})
    : assert(conversationId != '', 'event conversationId must not be empty'),
      assert(seq > 0, 'event seq must be positive');

  final String conversationId; // 所有会话事件都必须携带
  final int seq; // 会话内唯一、按事件产生顺序递增
}

final class MessageUpsert extends ChatEvent {
  // 含参数字段访问的 assert 不能用于 const 构造
  MessageUpsert({
    required super.conversationId,
    required super.seq,
    required ChatMessage message,
  }) : message = message,
       assert(
         message.conversationId == conversationId,
         'message conversationId must match event',
       ),
       assert(message.seq == seq, 'message seq must match event'),
       assert(
         message.syncState == SyncState.synced,
         'event message must be a formal synced message',
       );

  final ChatMessage message;
}

final class ConversationUpdated extends ChatEvent {
  // 含参数字段访问的 assert 不能用于 const 构造
  ConversationUpdated({
    required super.conversationId,
    required super.seq,
    required Conversation conversation,
  }) : conversation = conversation,
       assert(
         conversation.conversationId == conversationId,
         'conversation id must match event',
       );

  final Conversation conversation;
}

/// 历史快照：`lastSeq` 表示快照已完整反映该会话中所有 `seq <= lastSeq` 的事件所产生的状态。
class ConversationSnapshot {
  // 含集合不可变复制，构造函数不能是 const
  ConversationSnapshot({
    required this.conversation,
    required List<ChatMessage> messages,
    required this.lastSeq,
  }) : messages = List<ChatMessage>.unmodifiable(messages),
       assert(lastSeq >= 0, 'lastSeq must not be negative'),
       assert(
         messages.every(
           (m) =>
               m.syncState == SyncState.synced &&
               m.seq > 0 &&
               m.seq <= lastSeq &&
               m.conversationId == conversation.conversationId,
         ),
         'snapshot only accepts formal messages of the same conversation, seq <= lastSeq',
       ),
       assert(
         messages.map((m) => m.id).toSet().length == messages.length,
         'snapshot message ids must be unique',
       ),
       assert(
         _isStrictlyAscending(messages.map((m) => m.seq).toList()),
         'snapshot messages must be sorted by seq ascending',
       );

  final Conversation conversation; // 与 messages 同一快照点
  final List<ChatMessage> messages;
  final int lastSeq;
}

/// 该对话的持续实时状态：最新 Conversation + 正式消息 + 同步状态。
class ConversationView {
  // 含集合不可变复制，构造函数不能是 const
  ConversationView({
    required this.conversation,
    required List<ChatMessage> messages,
    this.syncState = ConversationSyncState.synced,
    this.retryCount = 0,
    this.syncError,
  }) : messages = List<ChatMessage>.unmodifiable(messages),
       assert(
         messages.every(
           (m) =>
               m.syncState == SyncState.synced &&
               m.seq > 0 &&
               m.conversationId == conversation.conversationId,
         ),
         'view only accepts formal messages of the same conversation',
       ),
       assert(
         messages.map((m) => m.id).toSet().length == messages.length,
         'view message ids must be unique',
       ),
       assert(
         _isStrictlyAscending(messages.map((m) => m.seq).toList()),
         'view messages must be sorted by seq ascending',
       ),
       assert(
         retryCount >= 0 && retryCount <= 2,
         'retryCount must be within 0..2',
       ),
       assert(
         syncState == ConversationSyncState.failed || syncError == null,
         'syncError is only allowed when failed',
       ),
       assert(
         syncState != ConversationSyncState.failed || syncError != null,
         'failed sync state requires syncError',
       ),
       assert(
         syncError == null || syncError != '',
         'syncError must not be empty',
       ),
       assert(
         (syncState == ConversationSyncState.failed ||
                 syncState == ConversationSyncState.retrying) ==
             (retryCount > 0),
         'retrying/failed require retryCount > 0; synced/syncing require 0',
       );

  final Conversation conversation;
  final List<ChatMessage> messages; // 仅正式消息
  final ConversationSyncState syncState;
  final int retryCount; // 已执行的重试次数，0–2
  final String? syncError;
}

/// 页面唯一展示来源：正式状态 + 本地 pending / queued / failed + 发送错误。
class ChatView {
  // 含集合去重、排序与不可变复制，构造函数不能是 const
  ChatView({
    required this.conversation,
    required List<ChatMessage> messages,
    required List<ChatMessage> pending,
    Map<String, String> sendErrors = const <String, String>{},
    this.syncState = ConversationSyncState.synced,
    this.retryCount = 0,
    this.syncError,
  }) : messages = List<ChatMessage>.unmodifiable(messages),
       pending = List<ChatMessage>.unmodifiable(pending),
       sendErrors = Map<String, String>.unmodifiable(sendErrors),
       assert(
         messages.every(
           (m) =>
               m.syncState == SyncState.synced &&
               m.seq > 0 &&
               m.conversationId == conversation.conversationId,
         ),
         'messages must be formal messages of the same conversation',
       ),
       assert(
         messages.map((m) => m.id).toSet().length == messages.length,
         'formal message ids must be unique',
       ),
       assert(
         _isStrictlyAscending(messages.map((m) => m.seq).toList()),
         'formal messages must be sorted by seq ascending',
       ),
       assert(
         pending.every(
           (p) =>
               p.syncState != SyncState.synced &&
               p.seq < 0 &&
               p.conversationId == conversation.conversationId,
         ),
         'pending must contain local pending/queued/failed messages of the same conversation',
       ),
       assert(
         pending.map((p) => p.id).toSet().length == pending.length,
         'pending message ids must be unique',
       ),
       assert(
         _isStrictlyAscending(pending.map((p) => -p.seq).toList()),
         'pending must be sorted by negative seq descending',
       ),
       assert(
         pending.every((p) => !messages.any((m) => m.id == p.id)),
         'pending must not contain ids already present in formal messages',
       ),
       assert(
         sendErrors.keys.every(
           (id) => pending.any(
             (p) => p.id == id && p.syncState == SyncState.failed,
           ),
         ),
         'sendErrors keys must reference failed pending messages',
       ),
       assert(
         sendErrors.values.every((text) => text != ''),
         'sendErrors values must not be empty',
       ),
       assert(
         retryCount >= 0 && retryCount <= 2,
         'retryCount must be within 0..2',
       ),
       assert(
         syncState == ConversationSyncState.failed || syncError == null,
         'syncError is only allowed when failed',
       ),
       assert(
         syncState != ConversationSyncState.failed || syncError != null,
         'failed sync state requires syncError',
       ),
       assert(
         syncError == null || syncError != '',
         'syncError must not be empty',
       ),
       assert(
         (syncState == ConversationSyncState.failed ||
                 syncState == ConversationSyncState.retrying) ==
             (retryCount > 0),
         'retrying/failed require retryCount > 0; synced/syncing require 0',
       );

  final Conversation conversation;
  final List<ChatMessage> messages; // 正式消息，按 seq 升序
  final List<ChatMessage> pending; // pending/queued/failed，负数 seq，创建顺序
  final Map<String, String> sendErrors; // clientMessageId -> 失败文案
  final ConversationSyncState syncState;
  final int retryCount; // 已执行的重试次数，0–2
  final String? syncError;

  /// 页面唯一渲染顺序：正式消息 → pending/queued/failed。
  /// UI 不得自行拼接或再次排序。
  List<ChatMessage> get displayMessages => [...messages, ...pending];
}

bool _isStrictlyAscending(List<int> values) {
  for (var i = 1; i < values.length; i++) {
    if (values[i] <= values[i - 1]) return false;
  }
  return true;
}
