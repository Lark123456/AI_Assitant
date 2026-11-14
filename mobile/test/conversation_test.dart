import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/conversation.dart';

Conversation _topic({
  String? projectId = 'p-1',
  String? projectTitle = '项目一',
  String? topic = '学习计划',
  String? goal = '完成课程',
  String? scopeSummary = '每周复盘',
  String? parentConversationId,
  String? originInviteId,
}) => Conversation(
  conversationId: 'c-topic',
  type: ConversationType.topic,
  agent: ConversationAgent.jarvis,
  status: ConversationStatus.active,
  createdAt: DateTime(2026, 11, 15, 8),
  lastActivityAt: DateTime(2026, 11, 15, 9),
  projectId: projectId,
  projectTitle: projectTitle,
  topic: topic,
  goal: goal,
  scopeSummary: scopeSummary,
  parentConversationId: parentConversationId,
  originInviteId: originInviteId,
);

void main() {
  group('Conversation 主对话不变量', () {
    test('合法主对话构造', () {
      final main = Conversation(
        conversationId: 'c-main',
        type: ConversationType.main,
        agent: ConversationAgent.friday,
        status: ConversationStatus.active,
        createdAt: DateTime(2026, 11, 15, 8),
        lastActivityAt: DateTime(2026, 11, 15, 9),
      );

      expect(main.isMain, isTrue);
      expect(main.agent, ConversationAgent.friday);
      expect(main.projectId, isNull);
    });

    test('主对话不得绑定 projectId', () {
      expect(
        () => Conversation(
          conversationId: 'c-main',
          type: ConversationType.main,
          agent: ConversationAgent.friday,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 8),
          lastActivityAt: DateTime(2026, 11, 15, 9),
          projectId: 'p-1',
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('主对话不得带专题字段', () {
      expect(
        () => Conversation(
          conversationId: 'c-main',
          type: ConversationType.main,
          agent: ConversationAgent.friday,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 8),
          lastActivityAt: DateTime(2026, 11, 15, 9),
          topic: '越界',
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => Conversation(
          conversationId: 'c-main',
          type: ConversationType.main,
          agent: ConversationAgent.friday,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 8),
          lastActivityAt: DateTime(2026, 11, 15, 9),
          parentConversationId: 'c-parent',
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('主对话必须归 Friday', () {
      expect(
        () => Conversation(
          conversationId: 'c-main',
          type: ConversationType.main,
          agent: ConversationAgent.jarvis,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 8),
          lastActivityAt: DateTime(2026, 11, 15, 9),
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('Conversation 专题对话不变量', () {
    test('合法专题构造', () {
      final topic = _topic();

      expect(topic.isMain, isFalse);
      expect(topic.agent, ConversationAgent.jarvis);
      expect(topic.projectId, 'p-1');
    });

    test('专题必须有 projectId', () {
      expect(() => _topic(projectId: null), throwsA(isA<AssertionError>()));
      expect(
        () => _topic(projectId: null, projectTitle: null),
        throwsA(isA<AssertionError>()),
      );
    });

    test('专题必须归 Jarvis', () {
      expect(
        () => Conversation(
          conversationId: 'c-topic',
          type: ConversationType.topic,
          agent: ConversationAgent.friday,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 8),
          lastActivityAt: DateTime(2026, 11, 15, 9),
          projectId: 'p-1',
          topic: '学习计划',
          goal: '完成课程',
          scopeSummary: '每周复盘',
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('专题必须有 topic/goal/scopeSummary', () {
      expect(() => _topic(topic: null), throwsA(isA<AssertionError>()));
      expect(() => _topic(goal: null), throwsA(isA<AssertionError>()));
      expect(() => _topic(scopeSummary: null), throwsA(isA<AssertionError>()));
    });

    test('projectTitle 非空时必须有 projectId', () {
      expect(
        () => Conversation(
          conversationId: 'c-main',
          type: ConversationType.main,
          agent: ConversationAgent.friday,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 8),
          lastActivityAt: DateTime(2026, 11, 15, 9),
          projectTitle: '孤立的标题',
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('Conversation 通用不变量', () {
    test('conversationId 不得为空', () {
      expect(
        () => Conversation(
          conversationId: '',
          type: ConversationType.main,
          agent: ConversationAgent.friday,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 8),
          lastActivityAt: DateTime(2026, 11, 15, 9),
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('lastActivityAt 不得早于 createdAt', () {
      expect(
        () => Conversation(
          conversationId: 'c-main',
          type: ConversationType.main,
          agent: ConversationAgent.friday,
          status: ConversationStatus.active,
          createdAt: DateTime(2026, 11, 15, 9),
          lastActivityAt: DateTime(2026, 11, 15, 8),
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('专题允许带 parent 与 originInvite', () {
      final topic = _topic(
        parentConversationId: 'c-main',
        originInviteId: 'i-1',
      );

      expect(topic.parentConversationId, 'c-main');
      expect(topic.originInviteId, 'i-1');
    });
  });
}
