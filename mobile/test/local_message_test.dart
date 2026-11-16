import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/chat_message.dart';

TextMessage _text({
  String id = 'm-1',
  String text = '你好',
  SyncState syncState = SyncState.synced,
  bool streaming = false,
}) => TextMessage(
  id: id,
  sender: ChatSender.user,
  createdAt: DateTime(2026, 11, 15, 9),
  text: text,
  syncState: syncState,
  streaming: streaming,
);

void main() {
  group('ChatMessage 基础约束', () {
    test('空 id 触发断言', () {
      expect(() => _text(id: ''), throwsA(isA<AssertionError>()));
    });

    test('消息默认已同步', () {
      expect(_text().syncState, SyncState.synced);
    });

    test('TextMessage 可更新文本、流式与同步状态', () {
      final source = _text(
        text: '你',
        streaming: true,
        syncState: SyncState.pending,
      );

      expect(source.copyWith(text: '你好').text, '你好');
      expect(source.copyWith(streaming: false).streaming, isFalse);
      expect(
        source.copyWith(syncState: SyncState.synced).syncState,
        SyncState.synced,
      );
      expect(source.copyWith().text, '你');
    });
  });

  group('JarvisIntroCard 约束', () {
    test('合法卡片保留不可变预览问题', () {
      final source = <String>['最近在忙什么', '希望先解决哪一块'];
      final card = JarvisIntroCard(
        id: 'm-2',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 15, 9),
        summary: '预计需要 20 分钟',
        previewQuestions: source,
      );

      source.add('越界');
      expect(card.previewQuestions.length, 2);
      expect(card.state, JarvisIntroState.open);
      expect(
        () => card.previewQuestions.add('越界'),
        throwsA(isA<UnsupportedError>()),
      );
    });

    test('summary 非空、预览问题 1–3 个且非空唯一', () {
      JarvisIntroCard build({
        String summary = '预计需要 20 分钟',
        List<String> questions = const ['最近在忙什么'],
      }) => JarvisIntroCard(
        id: 'm-2',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 15, 9),
        summary: summary,
        previewQuestions: questions,
      );

      expect(() => build(summary: ''), throwsA(isA<AssertionError>()));
      expect(() => build(questions: const []), throwsA(isA<AssertionError>()));
      expect(
        () => build(questions: const ['a', 'b', 'c', 'd']),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => build(questions: const ['a', '']),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => build(questions: const ['a', 'a']),
        throwsA(isA<AssertionError>()),
      );
    });
  });
}
