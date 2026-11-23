import '../models/card_action.dart';
import '../models/chat_message.dart';

/// Chat 数据来源：一条消息流 + 发送 + 卡片应答。
///
/// U1 只有 Friday 主对话；没有事件序号、快照、基线与摘要。
/// 流式回复通过同一个 `watchMessages()` 流实现：文本消息带 `streaming` 标志，
/// 文字随每次发射逐步增长。
abstract interface class ChatRepository {
  Stream<List<ChatMessage>> watchMessages();

  /// 发送文字。[clientMessageId] 用于本地重试时复用服务端幂等键；
  /// 由仓库自动生成新 id 的路径传 null。
  Future<void> sendText(String text, {String? clientMessageId});

  /// 会话可见性与前后台切换；激活时立即刷新一次并开始轮询，Mock no-op。
  Future<void> setActive(bool active);

  /// 轮询/同步错误（null 表示恢复正常）；Mock 不发射。
  Stream<String?> watchSyncError();

  /// Confirm / Choice / Memory / PlanProposal 使用各自的 CardAction；
  /// JarvisIntroCard 用 `ConfirmAction(confirmed: true/false)` 表示接受/拒绝。
  Future<void> respondToCard({
    required String messageId,
    required CardAction action,
  });
}
