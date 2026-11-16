import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/data/mock/mock_chat_repository.dart';
import 'package:mobile/data/mock/mock_network_status_source.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/card_action.dart';
import 'package:mobile/domain/models/chat_message.dart';

final class _FakeClock implements Clock {
  _FakeClock(this._now);

  final DateTime _now;

  @override
  DateTime now() => _now;
}

MockChatRepository _repository({
  MockNetworkStatusSource? network,
  List<ChatMessage>? seed,
}) => MockChatRepository(
  clock: _FakeClock(DateTime(2026, 11, 16, 9)),
  network: network ?? MockNetworkStatusSource(),
  seed: seed ?? const [],
  sendDelay: Duration.zero,
  replyDelay: Duration.zero,
  streamInterval: Duration.zero,
  streamChunk: 3,
);

void main() {
  group('watchMessages', () {
    test('每次订阅先收到当前快照', () async {
      final repository = _repository();
      addTearDown(repository.dispose);

      final first = await repository.watchMessages().first;
      expect(first, isEmpty);
    });
  });

  group('sendText', () {
    test('在线时用户消息转已同步，并出现流式回复', () async {
      final repository = _repository();
      addTearDown(repository.dispose);

      await repository.sendText('今天有点累');
      final messages = await repository.watchMessages().first;

      final user = messages.whereType<TextMessage>().firstWhere(
        (message) => message.sender == ChatSender.user,
      );
      expect(user.syncState, SyncState.synced);
      expect(user.text, '今天有点累');

      final reply = messages.whereType<TextMessage>().lastWhere(
        (message) => message.sender == ChatSender.friday,
      );
      expect(reply.streaming, isFalse);
      expect(reply.text, isNotEmpty);
    });

    test('空白文本不产生消息', () async {
      final repository = _repository();
      addTearDown(repository.dispose);

      await repository.sendText('   ');
      expect(await repository.watchMessages().first, isEmpty);
    });

    test('离线时保持 queued 且不产生回复', () async {
      final network = MockNetworkStatusSource(initial: NetworkStatus.offline);
      final repository = _repository(network: network);
      addTearDown(repository.dispose);

      await repository.sendText('先记一下');
      final messages = await repository.watchMessages().first;

      expect(messages.length, 1);
      expect((messages.single as TextMessage).syncState, SyncState.queued);
    });

    test('恢复在线后 queued 转已同步并补发回复', () async {
      final network = MockNetworkStatusSource(initial: NetworkStatus.offline);
      final repository = _repository(network: network);
      addTearDown(repository.dispose);

      await repository.sendText('离线消息');
      network.setStatus(NetworkStatus.online);

      TextMessage? user;
      for (var attempt = 0; attempt < 100; attempt++) {
        final messages = await repository.watchMessages().first;
        user = messages
            .whereType<TextMessage>()
            .where((message) => message.sender == ChatSender.user)
            .single;
        if (user.syncState == SyncState.synced) break;
        await Future<void>.delayed(const Duration(milliseconds: 5));
      }
      expect(user?.syncState, SyncState.synced);

      final messages = await repository.watchMessages().first;
      expect(
        messages.whereType<TextMessage>().where(
          (message) => message.sender == ChatSender.friday,
        ),
        isNotEmpty,
      );
    });
  });

  group('respondToCard', () {
    test('ConfirmCard 确认后写入 actedAt', () async {
      final card = ConfirmCard(
        id: 'confirm-1',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 16, 9),
        title: '确认',
        body: '内容',
        primaryLabel: '好的',
        secondaryLabel: '不用',
      );
      final repository = _repository(seed: [card]);
      addTearDown(repository.dispose);

      await repository.respondToCard(
        messageId: 'confirm-1',
        action: const ConfirmAction(confirmed: true),
      );
      final updated =
          (await repository.watchMessages().first).single as ConfirmCard;

      expect(updated.state, ConfirmCardState.confirmed);
      expect(updated.actedAt, isNotNull);
    });

    test('ChoiceCard 选择与跳过', () async {
      final card = ChoiceCard(
        id: 'choice-1',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 16, 9),
        question: '选一个',
        options: const ['A', 'B'],
      );
      final repository = _repository(seed: [card]);
      addTearDown(repository.dispose);

      await repository.respondToCard(
        messageId: 'choice-1',
        action: const ChoiceAction(option: 'B'),
      );
      expect(
        ((await repository.watchMessages().first).single as ChoiceCard).answer,
        'B',
      );

      await repository.respondToCard(
        messageId: 'choice-1',
        action: const ChoiceAction(skipped: true),
      );
      expect(
        ((await repository.watchMessages().first).single as ChoiceCard).answer,
        isNull,
      );
    });

    test('JarvisIntroCard 接受后依次追加诊断卡、ThinkingCard、PlanProposalCard', () async {
      final card = JarvisIntroCard(
        id: 'intro-1',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 16, 9),
        summary: '预计 20 分钟',
        previewQuestions: const ['最近在忙什么'],
      );
      final repository = _repository(seed: [card]);
      addTearDown(repository.dispose);

      await repository.respondToCard(
        messageId: 'intro-1',
        action: const ConfirmAction(confirmed: true),
      );
      final messages = await repository.watchMessages().first;

      expect(
        (messages.first as JarvisIntroCard).state,
        JarvisIntroState.accepted,
      );
      expect(messages.whereType<ChoiceCard>(), hasLength(1));
      expect(messages.whereType<ThinkingCard>(), hasLength(1));
      expect(messages.whereType<PlanProposalCard>(), hasLength(1));
    });
  });
}
