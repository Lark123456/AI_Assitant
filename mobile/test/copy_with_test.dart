import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/errors.dart';
import 'package:mobile/domain/models/chat_message.dart';
import 'package:mobile/domain/models/conversation.dart';
import 'package:mobile/domain/models/today.dart';

Conversation _mainConversation() => Conversation(
  conversationId: 'c-main',
  type: ConversationType.main,
  agent: ConversationAgent.friday,
  status: ConversationStatus.active,
  createdAt: DateTime(2026, 11, 15, 8),
  lastActivityAt: DateTime(2026, 11, 15, 9),
);

Conversation _topicConversation({
  String? projectId = 'p-1',
  String? projectTitle = '项目一',
}) => Conversation(
  conversationId: 'c-topic',
  type: ConversationType.topic,
  agent: ConversationAgent.jarvis,
  status: ConversationStatus.active,
  createdAt: DateTime(2026, 11, 15, 8),
  lastActivityAt: DateTime(2026, 11, 15, 9),
  projectId: projectId,
  projectTitle: projectTitle,
  topic: '学习计划',
  goal: '完成课程',
  scopeSummary: '每周复盘',
);

ConfirmCard _confirmCard() => ConfirmCard(
  id: 'm-1',
  conversationId: 'c-1',
  sender: ChatSender.friday,
  createdAt: DateTime(2026, 11, 15, 9),
  seq: 1,
  title: '确认日程',
  body: '是否加入今天',
  primaryLabel: '加入',
  secondaryLabel: '取消',
);

ChoiceCard _choiceCard({String? answer}) => ChoiceCard(
  id: 'm-2',
  conversationId: 'c-1',
  sender: ChatSender.friday,
  createdAt: DateTime(2026, 11, 15, 9),
  seq: 2,
  question: '选哪个时段',
  options: const ['上午', '下午'],
  answer: answer,
);

PlanProposalCard _planCard({
  PlanProposalState state = PlanProposalState.pending,
}) => PlanProposalCard(
  id: 'm-3',
  conversationId: 'c-1',
  sender: ChatSender.jarvis,
  createdAt: DateTime(2026, 11, 15, 9),
  seq: 3,
  summary: '调整本周计划',
  changes: const [PlanChange(type: PlanChangeType.move, title: '移动作业')],
  rationale: '本周有考试',
  state: state,
);

AgentInviteCard _inviteCard({
  AgentInviteStatus status = AgentInviteStatus.pending,
  String? createdConversationId,
  bool accepting = false,
}) => AgentInviteCard(
  id: 'm-4',
  conversationId: 'c-1',
  sender: ChatSender.friday,
  createdAt: DateTime(2026, 11, 15, 9),
  seq: 4,
  inviteId: 'i-1',
  initiatorAgent: ConversationAgent.friday,
  targetAgent: ConversationAgent.jarvis,
  topic: '简历优化',
  goal: '改到可投递',
  scopeSummary: '结构与措辞',
  expectedOutcome: '一版简历',
  status: status,
  createdConversationId: createdConversationId,
  accepting: accepting,
);

TodayItem _blockItem() => TodayItem(
  id: 't-1',
  kind: TodayItemKind.block,
  title: '专注写作',
  status: TodayItemStatus.planned,
  compressible: false,
  syncState: SyncState.synced,
  start: DateTime(2026, 11, 15, 9),
  end: DateTime(2026, 11, 15, 10),
  durationMin: 60,
);

TodayItem _reminderItem() => TodayItem(
  id: 't-2',
  kind: TodayItemKind.reminder,
  title: '喝水',
  status: TodayItemStatus.planned,
  compressible: false,
  syncState: SyncState.synced,
  start: DateTime(2026, 11, 15, 9),
);

TodayItem _taskItem({DateTime? start}) => TodayItem(
  id: 't-3',
  kind: TodayItemKind.task,
  title: '回复邮件',
  status: TodayItemStatus.planned,
  compressible: true,
  syncState: SyncState.synced,
  start: start,
);

void main() {
  group('Conversation.copyWith 哨兵语义', () {
    test('不传参数保持原值', () {
      final source = _topicConversation();
      final copy = source.copyWith();

      expect(copy.status, source.status);
      expect(copy.projectId, 'p-1');
      expect(copy.projectTitle, '项目一');
      expect(copy.lastActivityAt, source.lastActivityAt);
    });

    test('不传 projectTitle 保持；显式 null 清空', () {
      final source = _topicConversation();

      expect(
        source.copyWith(status: ConversationStatus.archived).projectTitle,
        '项目一',
      );
      expect(source.copyWith(projectTitle: null).projectTitle, isNull);
    });

    test('更新 lastActivityAt 与 status', () {
      final source = _mainConversation();
      final next = DateTime(2026, 11, 15, 12);
      final copy = source.copyWith(
        status: ConversationStatus.archived,
        lastActivityAt: next,
      );

      expect(copy.status, ConversationStatus.archived);
      expect(copy.lastActivityAt, next);
    });

    test('专题对话显式清空 projectId 触发断言', () {
      final source = _topicConversation();

      expect(
        () => source.copyWith(projectId: null),
        throwsA(isA<AssertionError>()),
      );
    });

    test('主对话设置 projectId 触发断言', () {
      final source = _mainConversation();

      expect(
        () => source.copyWith(projectId: 'p-9'),
        throwsA(isA<AssertionError>()),
      );
    });

    test('lastActivityAt 早于 createdAt 触发断言', () {
      final source = _mainConversation();

      expect(
        () => source.copyWith(lastActivityAt: DateTime(2026, 11, 15, 7)),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('ConfirmCard.copyWith 状态转换', () {
    test('pending 不传参数保持 actedAt 为空', () {
      final source = _confirmCard();
      final copy = source.copyWith();

      expect(copy.state, ConfirmCardState.pending);
      expect(copy.actedAt, isNull);
    });

    test('pending 确认缺少 actedAt 抛运行时异常', () {
      final source = _confirmCard();

      expect(
        () => source.copyWith(state: ConfirmCardState.confirmed),
        throwsA(isA<StateTransitionException>()),
      );
    });

    test('pending 只设置 actedAt 抛运行时异常', () {
      final source = _confirmCard();

      expect(
        () => source.copyWith(actedAt: DateTime(2026, 11, 15, 9, 5)),
        throwsA(isA<StateTransitionException>()),
      );
    });

    test('pending 确认并携带 actedAt 成功', () {
      final actedAt = DateTime(2026, 11, 15, 9, 5);
      final copy = _confirmCard().copyWith(
        state: ConfirmCardState.confirmed,
        actedAt: actedAt,
      );

      expect(copy.state, ConfirmCardState.confirmed);
      expect(copy.actedAt, actedAt);
    });

    test('终态不可变更，也不会静默清空 actedAt', () {
      final actedAt = DateTime(2026, 11, 15, 9, 5);
      final source = _confirmCard().copyWith(
        state: ConfirmCardState.confirmed,
        actedAt: actedAt,
      );

      expect(
        () => source.copyWith(state: ConfirmCardState.revoked),
        throwsA(isA<StateTransitionException>()),
      );
      expect(
        () => source.copyWith(state: ConfirmCardState.pending, actedAt: null),
        throwsA(isA<StateTransitionException>()),
      );
      expect(source.copyWith().actedAt, actedAt);
    });
  });

  group('ChoiceCard.copyWith 答案', () {
    test('未回答时保持空；合法答案可写入', () {
      final source = _choiceCard();

      expect(source.copyWith().answer, isNull);
      expect(source.copyWith(answer: '下午').answer, '下午');
    });

    test('答案不属于选项抛运行时异常', () {
      final source = _choiceCard();

      expect(
        () => source.copyWith(answer: '晚上'),
        throwsA(isA<StateTransitionException>()),
      );
    });

    test('已回答后只允许清空撤销', () {
      final source = _choiceCard(answer: '上午');

      expect(
        () => source.copyWith(answer: '下午'),
        throwsA(isA<StateTransitionException>()),
      );
      expect(source.copyWith(answer: null).answer, isNull);
      expect(source.copyWith().answer, '上午');
    });
  });

  group('MemoryConfirmCard.copyWith items', () {
    test('更新 items 保持不可变视图', () {
      final source = MemoryConfirmCard(
        id: 'm-5',
        conversationId: 'c-1',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 15, 9),
        seq: 5,
        items: const [MemoryCandidateItem(itemId: 'a', label: '偏好')],
      );

      final copy = source.copyWith(
        items: const [
          MemoryCandidateItem(
            itemId: 'a',
            label: '偏好',
            state: MemoryCandidateState.confirmed,
          ),
        ],
      );

      expect(copy.items.single.state, MemoryCandidateState.confirmed);
    });

    test('空列表与重复 itemId 触发断言', () {
      final source = MemoryConfirmCard(
        id: 'm-5',
        conversationId: 'c-1',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 15, 9),
        seq: 5,
        items: const [MemoryCandidateItem(itemId: 'a', label: '偏好')],
      );

      expect(
        () => source.copyWith(items: const []),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => source.copyWith(
          items: const [
            MemoryCandidateItem(itemId: 'a', label: '偏好'),
            MemoryCandidateItem(itemId: 'a', label: '重复'),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('PlanProposalCard.copyWith 终态', () {
    test('pending 可进入终态', () {
      final source = _planCard();

      expect(
        source.copyWith(state: PlanProposalState.accepted).state,
        PlanProposalState.accepted,
      );
    });

    test('终态回退或互转抛运行时异常', () {
      final source = _planCard(state: PlanProposalState.accepted);

      expect(
        () => source.copyWith(state: PlanProposalState.pending),
        throwsA(isA<StateTransitionException>()),
      );
      expect(
        () => source.copyWith(state: PlanProposalState.vetoed),
        throwsA(isA<StateTransitionException>()),
      );
      expect(source.copyWith().state, PlanProposalState.accepted);
    });
  });

  group('AgentInviteCard.copyWith 状态与 createdConversationId', () {
    test('pending 不传 createdConversationId 保持为空', () {
      final source = _inviteCard();

      expect(source.copyWith().createdConversationId, isNull);
      expect(source.copyWith(accepting: true).accepting, isTrue);
    });

    test('accepted 必须携带 createdConversationId', () {
      final source = _inviteCard();

      expect(
        () => source.copyWith(status: AgentInviteStatus.accepted),
        throwsA(isA<StateTransitionException>()),
      );
      expect(
        source
            .copyWith(
              status: AgentInviteStatus.accepted,
              createdConversationId: 'c-new',
            )
            .createdConversationId,
        'c-new',
      );
    });

    test('非 accepted 携带 createdConversationId 抛运行时异常', () {
      final source = _inviteCard();

      expect(
        () => source.copyWith(createdConversationId: 'c-new'),
        throwsA(isA<StateTransitionException>()),
      );
      expect(
        () => source.copyWith(createdConversationId: ''),
        throwsA(isA<StateTransitionException>()),
      );
    });

    test('accepted 不可回退，且不可保持 accepting', () {
      final source = _inviteCard(
        status: AgentInviteStatus.accepted,
        createdConversationId: 'c-new',
      );

      expect(
        () => source.copyWith(status: AgentInviteStatus.pending),
        throwsA(isA<StateTransitionException>()),
      );
      expect(
        () => source.copyWith(accepting: true),
        throwsA(isA<StateTransitionException>()),
      );
      expect(source.copyWith().status, AgentInviteStatus.accepted);
    });
  });

  group('TodayItem.copyWith start', () {
    test('task 可清空 start 移出时间线', () {
      final source = _taskItem(start: DateTime(2026, 11, 15, 9));

      expect(source.copyWith(start: null).start, isNull);
      expect(source.copyWith().start, DateTime(2026, 11, 15, 9));
      expect(
        source.copyWith(status: TodayItemStatus.done).status,
        TodayItemStatus.done,
      );
    });

    test('block / reminder 清空 start 抛运行时异常', () {
      expect(
        () => _blockItem().copyWith(start: null),
        throwsA(isA<StateTransitionException>()),
      );
      expect(
        () => _reminderItem().copyWith(start: null),
        throwsA(isA<StateTransitionException>()),
      );
    });

    test('block 的 start 不得晚于 end', () {
      final source = _blockItem();

      expect(
        () => source.copyWith(start: DateTime(2026, 11, 15, 10)),
        throwsA(isA<StateTransitionException>()),
      );
    });
  });
}
