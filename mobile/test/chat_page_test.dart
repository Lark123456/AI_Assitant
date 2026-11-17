import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/data/mock/mock_chat_repository.dart';
import 'package:mobile/data/mock/mock_network_status_source.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/card_action.dart';
import 'package:mobile/domain/models/chat_message.dart';
import 'package:mobile/domain/repositories/chat_repository.dart';
import 'package:mobile/features/chat/chat_page.dart';

final _now = DateTime(2026, 11, 16, 9);

final class _FakeClock implements Clock {
  @override
  DateTime now() => _now;
}

final class _FailingRepository implements ChatRepository {
  @override
  Stream<List<ChatMessage>> watchMessages() =>
      Stream<List<ChatMessage>>.error(StateError('boom'));

  @override
  Future<void> sendText(String text) async {}

  @override
  Future<void> respondToCard({
    required String messageId,
    required CardAction action,
  }) async {}
}

TextMessage _text(
  String id,
  String text, {
  ChatSender sender = ChatSender.user,
}) => TextMessage(id: id, sender: sender, createdAt: _now, text: text);

Widget _app({
  List<ChatMessage> seed = const [],
  NetworkStatus network = NetworkStatus.online,
  bool failing = false,
  double textScale = 1.0,
  MockChatRepository? repository,
}) {
  final clock = _FakeClock();
  return ProviderScope(
    overrides: [
      clockProvider.overrideWithValue(clock),
      mockNetworkStatusSourceProvider.overrideWithValue(
        MockNetworkStatusSource(initial: network),
      ),
      chatRepositoryProvider.overrideWith((ref) {
        if (failing) return _FailingRepository();
        final repo =
            repository ??
            MockChatRepository(
              clock: clock,
              network: MockNetworkStatusSource(initial: network),
              seed: seed,
              sendDelay: Duration.zero,
              replyDelay: Duration.zero,
              streamInterval: Duration.zero,
              streamChunk: 4,
            );
        ref.onDispose(repo.dispose);
        return repo;
      }),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
      home: const ChatPage(),
    ),
  );
}

void main() {
  testWidgets('显示种子消息', (tester) async {
    await tester.pumpWidget(
      _app(
        seed: [
          _text('m-1', '今天有点忙'),
          _text('m-2', '需要我帮你吗', sender: ChatSender.friday),
        ],
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('今天有点忙'), findsOneWidget);
    expect(find.text('需要我帮你吗'), findsOneWidget);
  });

  testWidgets('发送后出现用户消息与流式回复', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), '今天有点累');
    await tester.tap(find.text(S.send));
    await tester.pumpAndSettle();

    expect(find.text('今天有点累'), findsOneWidget);
    expect(find.textContaining('听起来今天消耗不小'), findsOneWidget);
  });

  testWidgets('离线发送显示等待联网', (tester) async {
    await tester.pumpWidget(_app(network: NetworkStatus.offline));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), '先记一下');
    await tester.tap(find.text(S.send));
    await tester.pumpAndSettle();

    expect(find.text(S.waitingForNetwork), findsOneWidget);
  });

  testWidgets('空消息显示空状态', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    expect(find.text(S.chatEmpty), findsOneWidget);
  });

  testWidgets('消息流错误显示错误与重试', (tester) async {
    await tester.pumpWidget(_app(failing: true));
    await tester.pumpAndSettle();

    expect(find.text(S.loadingFailed), findsOneWidget);
    expect(find.text(S.retry), findsOneWidget);
  });

  testWidgets('确认卡点击后进入终态', (tester) async {
    final card = ConfirmCard(
      id: 'confirm-1',
      sender: ChatSender.friday,
      createdAt: _now,
      title: '把「写周报」排进今天？',
      body: '预计 45 分钟',
      primaryLabel: '排进今天',
      secondaryLabel: '稍后再说',
    );
    await tester.pumpWidget(_app(seed: [card]));
    await tester.pumpAndSettle();

    await tester.tap(find.text(card.primaryLabel));
    await tester.pumpAndSettle();

    expect(find.text(S.done), findsOneWidget);
  });

  testWidgets('JarvisIntroCard 接受后追加后续消息', (tester) async {
    final card = JarvisIntroCard(
      id: 'intro-1',
      sender: ChatSender.friday,
      createdAt: _now,
      summary: '可以帮你做一次规划',
      previewQuestions: const ['最近在忙什么'],
    );
    await tester.pumpWidget(_app(seed: [card]));
    await tester.pumpAndSettle();

    await tester.tap(find.text(S.jarvisPlan));
    for (var attempt = 0; attempt < 20; attempt++) {
      await tester.pump(const Duration(milliseconds: 10));
      if (find.text('先把本周最难的一件事固定在上午').evaluate().isNotEmpty) {
        break;
      }
    }

    expect(find.text('先从哪一块开始？'), findsOneWidget);
    expect(find.text(S.organizing), findsOneWidget);
    expect(find.text('先把本周最难的一件事固定在上午'), findsOneWidget);
  });

  testWidgets('1.5 倍文字缩放不溢出', (tester) async {
    await tester.pumpWidget(
      _app(seed: [_text('m-1', '一段比较长的消息，用来检查文字缩放时不会溢出布局边界。')], textScale: 1.5),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  testWidgets('副标题显示常驻秒回', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    expect(find.text(S.chatSubtitle), findsOneWidget);
  });

  testWidgets('主动消息显示理由并可打开为什么推给我', (tester) async {
    final nudge = TextMessage(
      id: 'nudge-1',
      sender: ChatSender.friday,
      createdAt: _now,
      text: '下午有一个空档',
      reason: '你昨天提到今天要交报告',
    );
    await tester.pumpWidget(_app(seed: [nudge]));
    await tester.pumpAndSettle();

    expect(find.textContaining(nudge.reason!), findsOneWidget);

    await tester.tap(find.textContaining(S.whyPushed));
    await tester.pumpAndSettle();

    expect(find.text(S.whyPushed), findsOneWidget);
    expect(find.text(S.quieter), findsOneWidget);
    expect(find.text(S.disableCategory), findsOneWidget);

    await tester.tap(find.text(S.quieter));
    await tester.pumpAndSettle();
    expect(find.text(S.quieterNoted), findsOneWidget);
  });

  testWidgets('快捷词点击直接发送', (tester) async {
    final clock = _FakeClock();
    final repository = MockChatRepository(
      clock: clock,
      network: MockNetworkStatusSource(),
      seed: const [],
      sendDelay: Duration.zero,
      replyDelay: Duration.zero,
      streamInterval: Duration.zero,
      streamChunk: 100,
    );
    await tester.pumpWidget(_app(repository: repository));
    await tester.pumpAndSettle();

    await tester.tap(find.text(S.quickAddReminder));
    await tester.pumpAndSettle();

    final messages = await repository.watchMessages().first;
    expect(
      messages.whereType<TextMessage>().any(
        (message) =>
            message.sender == ChatSender.user &&
            message.text == S.quickAddReminder,
      ),
      isTrue,
    );
  });

  testWidgets('加号打开拍照与相册面板', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip(S.more));
    await tester.pumpAndSettle();
    expect(find.text(S.takePhoto), findsOneWidget);
    expect(find.text(S.chooseFromAlbum), findsOneWidget);

    await tester.tap(find.text(S.takePhoto));
    await tester.pumpAndSettle();
    expect(find.text(S.takePhoto), findsNothing);
    expect(find.text(S.uiOnly), findsOneWidget);
  });

  testWidgets('上翻后新消息显示跳转按钮', (tester) async {
    final clock = _FakeClock();
    final repository = MockChatRepository(
      clock: clock,
      network: MockNetworkStatusSource(),
      seed: [
        for (var index = 0; index < 30; index++)
          TextMessage(
            id: 'history-$index',
            sender: ChatSender.friday,
            createdAt: _now.add(Duration(minutes: index)),
            text: '历史消息 $index',
          ),
      ],
      sendDelay: Duration.zero,
      replyDelay: Duration.zero,
      streamInterval: Duration.zero,
      streamChunk: 100,
    );
    await tester.pumpWidget(_app(repository: repository));
    await tester.pumpAndSettle();

    await tester.drag(find.byType(ListView), const Offset(0, 600));
    await tester.pumpAndSettle();
    expect(find.text(S.newMessages), findsNothing);

    final sending = repository.sendText('新消息内容');
    for (var step = 0; step < 10; step++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    await sending;
    await tester.pumpAndSettle();
    expect(find.text(S.newMessages), findsOneWidget);

    await tester.tap(find.text(S.newMessages));
    await tester.pumpAndSettle();
    expect(find.text(S.newMessages), findsNothing);
  });

  testWidgets('1.5 倍文字缩放打开理由与加号面板不溢出', (tester) async {
    final nudge = TextMessage(
      id: 'nudge-2',
      sender: ChatSender.friday,
      createdAt: _now,
      text: '下午有一个空档',
      reason: '你昨天提到今天要交报告',
    );
    await tester.pumpWidget(_app(seed: [nudge], textScale: 1.5));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await tester.tap(find.textContaining(S.whyPushed));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    Navigator.of(tester.element(find.text(S.whyPushed))).pop();
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip(S.more));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
