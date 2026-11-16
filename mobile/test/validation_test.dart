import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/domain/enums.dart';
import 'package:mobile/domain/models/card_action.dart';
import 'package:mobile/domain/models/chat_message.dart';
import 'package:mobile/domain/models/today.dart';

ChoiceCard _choiceCard({List<String>? options, String? answer}) => ChoiceCard(
  id: 'm-1',
  sender: ChatSender.friday,
  createdAt: DateTime(2026, 11, 15, 9),
  question: '选哪个时段',
  options: options ?? <String>['上午', '下午'],
  answer: answer,
);

TodayItem _todayItem({
  String id = 't-1',
  TodayItemKind kind = TodayItemKind.task,
  String title = '任务',
  TodayItemStatus status = TodayItemStatus.planned,
  DateTime? start,
  DateTime? end,
  int? durationMin,
}) => TodayItem(
  id: id,
  kind: kind,
  title: title,
  status: status,
  compressible: false,
  syncState: SyncState.synced,
  start: start,
  end: end,
  durationMin: durationMin,
);

void main() {
  group('CardAction 与选项约束', () {
    test('ChoiceAction 的 skipped 与 option 联动', () {
      expect(const ChoiceAction(option: '上午').option, '上午');
      expect(const ChoiceAction(skipped: true).option, isNull);

      expect(() => ChoiceAction(), throwsA(isA<AssertionError>()));
      expect(
        () => ChoiceAction(option: '上午', skipped: true),
        throwsA(isA<AssertionError>()),
      );
      expect(() => ChoiceAction(option: ''), throwsA(isA<AssertionError>()));
    });

    test('ChoiceCard 选项数量必须为 2–4', () {
      expect(
        () => _choiceCard(options: const ['只有一项']),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => _choiceCard(options: const ['1', '2', '3', '4', '5']),
        throwsA(isA<AssertionError>()),
      );
    });

    test('ChoiceCard 选项非空且不重复', () {
      expect(
        () => _choiceCard(options: const ['上午', '']),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => _choiceCard(options: const ['上午', '上午']),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => _choiceCard(options: const ['上午', '下午'], answer: '晚上'),
        throwsA(isA<AssertionError>()),
      );
    });

    test('ChoiceCard options 为不可变视图', () {
      final source = <String>['上午', '下午'];
      final card = _choiceCard(options: source);

      source.add('晚上');
      expect(card.options, ['上午', '下午']);
      expect(() => card.options.add('晚上'), throwsA(isA<UnsupportedError>()));
    });
  });

  group('MemoryConfirmCard 与 PlanProposalCard 集合约束', () {
    test('items 非空且 itemId 唯一', () {
      expect(
        () => MemoryConfirmCard(
          id: 'm-2',
          sender: ChatSender.friday,
          createdAt: DateTime(2026, 11, 15, 9),
          items: const [],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => MemoryConfirmCard(
          id: 'm-2',
          sender: ChatSender.friday,
          createdAt: DateTime(2026, 11, 15, 9),
          items: const [
            MemoryCandidateItem(itemId: 'a', label: '偏好'),
            MemoryCandidateItem(itemId: 'a', label: '重复'),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );

      final card = MemoryConfirmCard(
        id: 'm-2',
        sender: ChatSender.friday,
        createdAt: DateTime(2026, 11, 15, 9),
        items: const [MemoryCandidateItem(itemId: 'a', label: '偏好')],
      );
      expect(() => card.items.clear(), throwsA(isA<UnsupportedError>()));
      expect(card.allHandled, isFalse);
    });

    test('PlanProposalCard changes 非空且为不可变视图', () {
      final source = [
        const PlanChange(type: PlanChangeType.add, title: '新增复习'),
      ];
      final card = PlanProposalCard(
        id: 'm-3',
        sender: ChatSender.jarvis,
        createdAt: DateTime(2026, 11, 15, 9),
        summary: '调整本周',
        changes: source,
        rationale: '本周有考试',
      );

      source.clear();
      expect(card.changes.length, 1);
      expect(() => card.changes.clear(), throwsA(isA<UnsupportedError>()));
      expect(
        () => PlanProposalCard(
          id: 'm-3',
          sender: ChatSender.jarvis,
          createdAt: DateTime(2026, 11, 15, 9),
          summary: '调整本周',
          changes: const [],
          rationale: '本周有考试',
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('TodayItem 类型与时间约束', () {
    test('block 必须有 start/end 且 end 晚于 start', () {
      expect(
        () => _todayItem(
          kind: TodayItemKind.block,
          start: DateTime(2026, 11, 15, 10),
          end: DateTime(2026, 11, 15, 10),
          durationMin: 60,
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => _todayItem(kind: TodayItemKind.block, durationMin: 60),
        throwsA(isA<AssertionError>()),
      );
    });

    test('block 必须有正时长', () {
      expect(
        () => _todayItem(
          kind: TodayItemKind.block,
          start: DateTime(2026, 11, 15, 9),
          end: DateTime(2026, 11, 15, 10),
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => _todayItem(
          kind: TodayItemKind.block,
          start: DateTime(2026, 11, 15, 9),
          end: DateTime(2026, 11, 15, 10),
          durationMin: 0,
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('reminder 必须有 start，且只有 block 可带 end/duration', () {
      expect(
        () => _todayItem(kind: TodayItemKind.reminder),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => _todayItem(
          start: DateTime(2026, 11, 15, 10),
          end: DateTime(2026, 11, 15, 11),
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => _todayItem(start: DateTime(2026, 11, 15, 10), durationMin: 30),
        throwsA(isA<AssertionError>()),
      );
    });

    test('isOverdueAt 按类型派生', () {
      final block = _todayItem(
        kind: TodayItemKind.block,
        start: DateTime(2026, 11, 15, 9),
        end: DateTime(2026, 11, 15, 10),
        durationMin: 60,
      );
      final reminder = _todayItem(
        kind: TodayItemKind.reminder,
        start: DateTime(2026, 11, 15, 9),
      );
      final task = _todayItem(start: DateTime(2026, 11, 15, 9));
      final unscheduled = _todayItem();

      expect(block.isOverdueAt(DateTime(2026, 11, 15, 9, 30)), isFalse);
      expect(block.isOverdueAt(DateTime(2026, 11, 15, 10, 1)), isTrue);
      expect(reminder.isOverdueAt(DateTime(2026, 11, 15, 9, 5)), isFalse);
      expect(reminder.isOverdueAt(DateTime(2026, 11, 15, 9, 11)), isTrue);
      expect(task.isOverdueAt(DateTime(2026, 11, 15, 9, 1)), isTrue);
      expect(unscheduled.isOverdueAt(DateTime(2026, 11, 15, 12)), isFalse);
      expect(
        task
            .copyWith(status: TodayItemStatus.done)
            .isOverdueAt(DateTime(2026, 11, 15, 12)),
        isFalse,
      );
    });
  });

  group('Brief 与 DayView', () {
    test('Brief 文本非空，suggestions 不含空串且不可变', () {
      expect(
        () => Brief(kind: BriefKind.morning, text: '', reasonLine: '原因'),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => Brief(kind: BriefKind.morning, text: '早安', reasonLine: ''),
        throwsA(isA<AssertionError>()),
      );

      final source = ['先做重要的事'];
      final brief = Brief(
        kind: BriefKind.morning,
        text: '早安',
        reasonLine: '今天有 2 个日程',
        mergedSuggestions: source,
      );
      source.add('');
      expect(brief.mergedSuggestions, ['先做重要的事']);
      expect(
        () => brief.mergedSuggestions.add('新建议'),
        throwsA(isA<UnsupportedError>()),
      );
    });

    test('DayView 要求本地零点与归类正确的条目', () {
      final item = _todayItem(
        kind: TodayItemKind.block,
        start: DateTime(2026, 11, 15, 9),
        end: DateTime(2026, 11, 15, 10),
        durationMin: 60,
      );
      final unscheduled = _todayItem(id: 't-2');
      final day = DayView(
        date: DateTime(2026, 11, 15),
        items: [item],
        unscheduled: [unscheduled],
      );

      expect(day.items.length, 1);
      expect(day.unscheduled.length, 1);
      expect(() => day.items.clear(), throwsA(isA<UnsupportedError>()));

      expect(
        () => DayView(
          date: DateTime.utc(2026, 11, 15),
          items: const [],
          unscheduled: const [],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => DayView(
          date: DateTime(2026, 11, 15, 8),
          items: const [],
          unscheduled: const [],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => DayView(
          date: DateTime(2026, 11, 15),
          items: [_todayItem(id: 't-3')],
          unscheduled: const [],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => DayView(
          date: DateTime(2026, 11, 15),
          items: const [],
          unscheduled: [
            _todayItem(id: 't-4', start: DateTime(2026, 11, 15, 9)),
          ],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => DayView(
          date: DateTime(2026, 11, 15),
          items: const [],
          unscheduled: [_todayItem(id: 't-5', status: TodayItemStatus.done)],
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('DayView 条目按 start 升序且 id 不重复', () {
      final later = _todayItem(
        id: 't-2',
        kind: TodayItemKind.block,
        start: DateTime(2026, 11, 15, 11),
        end: DateTime(2026, 11, 15, 12),
        durationMin: 60,
      );
      final earlier = _todayItem(
        id: 't-1',
        kind: TodayItemKind.block,
        start: DateTime(2026, 11, 15, 9),
        end: DateTime(2026, 11, 15, 10),
        durationMin: 60,
      );

      expect(
        () => DayView(
          date: DateTime(2026, 11, 15),
          items: [later, earlier],
          unscheduled: const [],
        ),
        throwsA(isA<AssertionError>()),
      );
      expect(
        () => DayView(
          date: DateTime(2026, 11, 15),
          items: [earlier],
          unscheduled: [_todayItem(id: 't-1')],
        ),
        throwsA(isA<AssertionError>()),
      );
    });

    test('简报类型必须与字段匹配', () {
      expect(
        () => DayView(
          date: DateTime(2026, 11, 15),
          items: const [],
          unscheduled: const [],
          morningBrief: Brief(
            kind: BriefKind.evening,
            text: '晚安',
            reasonLine: '今日完成',
          ),
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });
}
