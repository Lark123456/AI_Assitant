/// U1 领域枚举，对应 docs/mobile-u1-plan.md 第三章。
///
/// 命名约定：
/// - `ChatSender` 只表示消息发送者，包含 user
/// - `SyncState` 表示消息/条目的同步状态；`NetworkStatus` 表示整体网络状态，二者不可混用
library;

enum ChatSender { user, friday, jarvis }

enum SyncState { synced, pending, queued, failed }

enum NetworkStatus { online, offline, syncing, error }

enum TodayItemKind { block, reminder, task }

/// overdue 不进入持久状态；由 `TodayItem.isOverdueAt(now)` 派生。
enum TodayItemStatus { planned, inProgress, done, skipped }

enum BriefKind { morning, evening }

enum ConfirmCardState { pending, confirmed, revoked }

enum PlanDecision { accept, adjust, veto }

enum PlanProposalState { pending, accepted, adjusted, vetoed }

enum PlanChangeType { add, remove, move }

enum MemoryCandidateState { pending, confirmed, rejected }

enum ThinkingPhase { thinking, organizing, drafting, executing }

enum JarvisIntroState { open, accepted, declined }
