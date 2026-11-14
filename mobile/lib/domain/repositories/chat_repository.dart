import '../models/card_action.dart';
import '../models/chat_event.dart';
import '../models/conversation.dart';
import '../models/invite.dart';

/// Chat 数据来源：事件订阅 + 快照 + 发送/卡片应答/邀请。
abstract interface class ChatRepository {
  Future<Conversation> loadMainConversation();

  Future<List<Conversation>> loadTopicConversations();

  Future<Conversation> getConversation(String conversationId);

  /// 先订阅，保证不漏事件；随后再取快照。
  Stream<ChatEvent> watchConversation(String conversationId);

  Future<ConversationSnapshot> loadConversationSnapshot(String conversationId);

  /// 手动重试同步：不取消订阅、重置退避计数并重新走一次重同步流程。
  Future<void> retrySync(String conversationId);

  /// `clientMessageId` 由 Controller 生成；确认事件必须复用同一 id。
  Future<void> sendText({
    required String conversationId,
    required String clientMessageId,
    required String text,
  });

  /// 仅用于 Confirm / Choice / Memory / PlanProposal。
  Future<void> respondToCard({
    required String conversationId,
    required String messageId,
    required CardAction action,
  });

  Future<InviteAcceptResult> acceptInvite(String inviteId);

  Future<InviteDeclineResult> declineInvite(String inviteId);
}
