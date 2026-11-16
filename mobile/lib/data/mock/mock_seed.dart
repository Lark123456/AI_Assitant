import '../../domain/enums.dart';
import '../../domain/models/chat_message.dart';
import '../../domain/models/today.dart';

DateTime _at(DateTime day, int hour, int minute) =>
    DateTime(day.year, day.month, day.day, hour, minute);

/// 覆盖 7 类卡片的历史消息；顺序按 createdAt 递增。
List<ChatMessage> seedMessages(DateTime now) {
  final base = _at(now, 8, 30);
  return [
    TextMessage(
      id: 'seed-user-1',
      sender: ChatSender.user,
      createdAt: base,
      text: '今天有点忙',
    ),
    TextMessage(
      id: 'seed-friday-1',
      sender: ChatSender.friday,
      createdAt: base.add(const Duration(minutes: 1)),
      text: '需要我帮你把今天的安排顺一下吗？',
    ),
    ConfirmCard(
      id: 'seed-confirm-1',
      sender: ChatSender.friday,
      createdAt: base.add(const Duration(minutes: 2)),
      title: '把「写周报」排进今天？',
      body: '预计 45 分钟，可以放在下午的空档',
      primaryLabel: '排进今天',
      secondaryLabel: '稍后再说',
    ),
    ChoiceCard(
      id: 'seed-choice-1',
      sender: ChatSender.friday,
      createdAt: base.add(const Duration(minutes: 3)),
      question: '下午的精力通常怎么样？',
      options: const ['很好', '一般', '很差'],
    ),
    MemoryConfirmCard(
      id: 'seed-memory-1',
      sender: ChatSender.friday,
      createdAt: base.add(const Duration(minutes: 4)),
      items: const [
        MemoryCandidateItem(itemId: 'memory-1', label: '偏好上午做难事'),
        MemoryCandidateItem(itemId: 'memory-2', label: '晚上喜欢读书'),
      ],
    ),
    PlanProposalCard(
      id: 'seed-plan-1',
      sender: ChatSender.jarvis,
      createdAt: base.add(const Duration(minutes: 5)),
      summary: '把本周的三件事拆成可执行的小块',
      changes: const [
        PlanChange(type: PlanChangeType.add, title: '周二、周四各留 45 分钟写周报'),
        PlanChange(type: PlanChangeType.move, title: '把评审移到精力较好的上午'),
      ],
      rationale: '你提到下午精力一般，上午更适合深度工作',
    ),
    JarvisIntroCard(
      id: 'seed-jarvis-1',
      sender: ChatSender.friday,
      createdAt: base.add(const Duration(minutes: 6)),
      summary: '如果你愿意，我可以让 Jarvis 帮你做一次系统规划，预计 20 分钟',
      previewQuestions: const ['最近主要在忙什么', '希望先解决哪一块'],
    ),
    ThinkingCard(
      id: 'seed-thinking-1',
      sender: ChatSender.friday,
      createdAt: base.add(const Duration(minutes: 7)),
      phase: ThinkingPhase.drafting,
    ),
  ];
}

List<TodayItem> seedTodayItems(DateTime now) {
  final day = _at(now, 0, 0);
  return [
    TodayItem(
      id: 'today-block-1',
      kind: TodayItemKind.block,
      title: '专注写作',
      status: TodayItemStatus.done,
      compressible: false,
      syncState: SyncState.synced,
      start: day.add(const Duration(hours: 9)),
      end: day.add(const Duration(hours: 10)),
      durationMin: 60,
      sourceTag: '日程',
    ),
    TodayItem(
      id: 'today-reminder-1',
      kind: TodayItemKind.reminder,
      title: '喝水',
      status: TodayItemStatus.planned,
      compressible: false,
      syncState: SyncState.synced,
      start: day.add(const Duration(hours: 11, minutes: 30)),
      sourceTag: '提醒',
    ),
    TodayItem(
      id: 'today-block-2',
      kind: TodayItemKind.block,
      title: '方案评审',
      status: TodayItemStatus.inProgress,
      compressible: true,
      syncState: SyncState.synced,
      start: day.add(const Duration(hours: 14)),
      end: day.add(const Duration(hours: 15)),
      durationMin: 60,
      sourceTag: '会议',
    ),
    TodayItem(
      id: 'today-task-1',
      kind: TodayItemKind.task,
      title: '回复邮件',
      status: TodayItemStatus.planned,
      compressible: true,
      syncState: SyncState.pending,
      start: day.add(const Duration(hours: 16)),
      sourceTag: '任务',
    ),
  ];
}

List<TodayItem> seedUnscheduledItems() {
  return [
    TodayItem(
      id: 'today-unscheduled-1',
      kind: TodayItemKind.task,
      title: '整理本周笔记',
      status: TodayItemStatus.planned,
      compressible: true,
      syncState: SyncState.synced,
      reason: '还没有安排时间',
    ),
    TodayItem(
      id: 'today-unscheduled-2',
      kind: TodayItemKind.task,
      title: '给家里打电话',
      status: TodayItemStatus.planned,
      compressible: true,
      syncState: SyncState.synced,
      start: null,
      reason: '晚上比较合适',
    ),
  ];
}

Brief seedMorningBrief() => Brief(
  kind: BriefKind.morning,
  text: '今天有两段专注时间，下午精力一般，把难事放在上午。',
  reasonLine: '按你最近两周的节奏',
  mergedSuggestions: const ['上午先写周报', '下午评审后留 15 分钟缓冲'],
);

Brief seedEveningBrief() => Brief(
  kind: BriefKind.evening,
  text: '今天完成了 1 个时间块，还有 2 件待排期。',
  reasonLine: '根据今天的完成情况',
  mergedSuggestions: const ['把未完成的任务顺延到明天'],
);
