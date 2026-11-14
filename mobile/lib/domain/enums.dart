/// 领域枚举，对应 docs/mobile-u1-technical-plan.md 4.1。
///
/// 命名约定：
/// - `ChatSender` 只表示消息发送者，包含 user
/// - `ConversationAgent` 只表示对话负责方，不含 user
/// - `SyncState` 表示条目/消息的同步状态；`NetworkStatus` 表示整体网络状态，二者不可混用
library;

enum ConversationType { main, topic }

enum ConversationAgent { friday, jarvis }

enum ConversationStatus { active, archived }

enum ChatSender { user, friday, jarvis }

enum SyncState { synced, pending, queued, failed }

enum NetworkStatus { online, offline, syncing, error }

enum TodayItemKind { block, reminder, task }

/// overdue 不进入持久状态；由 `TodayItem.isOverdueAt(now)` 派生。
enum TodayItemStatus { planned, inProgress, done, skipped }

enum BriefKind { morning, evening }

enum ConversationSyncState { syncing, synced, retrying, failed }

enum ConfirmCardState { pending, confirmed, revoked }

enum PlanDecision { accept, adjust, veto }

enum PlanProposalState { pending, accepted, adjusted, vetoed }

enum PlanChangeType { add, remove, move }

enum MemoryCandidateState { pending, confirmed, rejected }

enum AgentInviteStatus { pending, accepted, declined, expired }

enum ThinkingPhase { thinking, organizing, drafting, executing }

enum AlertPriority { urgent }

enum AlertStatus { pending, handled, dismissed }

enum InviteRejectReason {
  declined,
  expired,
  notFound,
  notOwner,
  alreadyAccepted,
}
