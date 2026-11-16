import '../models/card_action.dart';
import '../models/chat_message.dart';

/// Chat 数据来源：一条消息流 + 发送 + 卡片应答。
///
/// U1 只有 Friday 主对话；没有事件序号、快照、基线与摘要。
/// 流式回复通过同一个 `watchMessages()` 流实现：文本消息带 `streaming` 标志，
/// 文字随每次发射逐步增长。
abstract interface class ChatRepository {
  Stream<List<ChatMessage>> watchMessages();

  Future<void> sendText(String text);

  /// Confirm / Choice / Memory / PlanProposal 使用各自的 CardAction；
  /// JarvisIntroCard 用 `ConfirmAction(confirmed: true/false)` 表示接受/拒绝。
  Future<void> respondToCard({
    required String messageId,
    required CardAction action,
  });
}
