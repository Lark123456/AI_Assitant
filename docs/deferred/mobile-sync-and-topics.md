# 延后：会话同步协议、多会话与 Jarvis 专题对话

> 状态：延后。待后端接口方案确定后与后端一起设计。
> 以下章节原样摘自 `docs/archive/mobile-u1-technical-plan-v2.4.4.md`，内容未修改。
> U1 执行以 `docs/mobile-u1-plan.md` 为准；本文件不参与当前批次实现。

---
### 4.2 Conversation

```dart
class Conversation {
  // 含 DateTime 比较的 assert 不能用于 const 构造，故本类为非 const
  Conversation({
    required this.conversationId,
    required this.type,
    required this.agent,
    required this.status,
    required this.createdAt,
    required this.lastActivityAt,
    this.projectId,
    this.projectTitle,
    this.topic,
    this.goal,
    this.scopeSummary,
    this.parentConversationId,
    this.originInviteId,
  })  : assert(conversationId != '', 'conversationId must not be empty'),
        assert(
          !lastActivityAt.isBefore(createdAt),
          'lastActivityAt must not be earlier than createdAt',
        ),
        assert(
          type != ConversationType.main || projectId == null,
          'main conversation must not have projectId',
        ),
        assert(
          type != ConversationType.main ||
              (parentConversationId == null && originInviteId == null),
          'main conversation must not have parent or origin invite',
        ),
        assert(
          type != ConversationType.main ||
              (topic == null && goal == null && scopeSummary == null),
          'main conversation must not have topic/goal/scopeSummary',
        ),
        assert(
          type != ConversationType.topic || projectId != null,
          'topic conversation requires projectId',
        ),
        assert(
          projectId != null || projectTitle == null,
          'projectTitle requires projectId',
        ),
        assert(
          type != ConversationType.main || agent == ConversationAgent.friday,
          'main conversation must belong to friday',
        ),
        assert(
          type != ConversationType.topic || agent == ConversationAgent.jarvis,
          'topic conversation must belong to jarvis',
        ),
        assert(
          type != ConversationType.topic ||
              (topic != null && goal != null && scopeSummary != null),
          'topic conversation requires topic/goal/scopeSummary',
        );

  final String conversationId;
  final ConversationType type;
  final ConversationAgent agent;
  final ConversationStatus status;
  final DateTime createdAt;
  final DateTime lastActivityAt;

  final String? projectId;        // 专题必填；主对话为空
  final String? projectTitle;
  final String? topic;            // 专题名称
  final String? goal;             // 专题目标
  final String? scopeSummary;     // 讨论范围
  final String? parentConversationId;
  final String? originInviteId;

  bool get isMain => type == ConversationType.main;

  Conversation copyWith({
    ConversationStatus? status,
    DateTime? lastActivityAt,
    Object? projectId = unset,
    Object? projectTitle = unset,
  }) {
    final nextProjectId =
        identical(projectId, unset) ? this.projectId : projectId as String?;
    final nextProjectTitle = identical(projectTitle, unset)
        ? this.projectTitle
        : projectTitle as String?;
    final nextLastActivityAt = lastActivityAt ?? this.lastActivityAt;
    assert(
      type != ConversationType.topic || nextProjectId != null,
      'cannot clear projectId of a topic conversation',
    );
    assert(
      type != ConversationType.main || nextProjectId == null,
      'main conversation projectId must stay null',
    );
    assert(
      nextProjectId != null || nextProjectTitle == null,
      'projectTitle requires projectId',
    );
    assert(
      !nextLastActivityAt.isBefore(createdAt),
      'lastActivityAt must not be earlier than createdAt',
    );
    return Conversation(
      conversationId: conversationId,
      type: type,
      agent: agent,
      status: status ?? this.status,
      createdAt: createdAt,
      lastActivityAt: nextLastActivityAt,
      projectId: nextProjectId,
      projectTitle: nextProjectTitle,
      topic: topic,
      goal: goal,
      scopeSummary: scopeSummary,
      parentConversationId: parentConversationId,
      originInviteId: originInviteId,
    );
  }
}
```

#### 4.2.1 copyWith 约定（可空字段的显式清空）

文件级定义一次哨兵值，所有模型共用：

```dart
const Object unset = Object();
```

通用规则：

- **不传参数** → 保持原值
- **显式传 `null`** → 清空该字段（仅限允许清空的字段）
- **显式传非空值** → 更新为新值
- **非空字段**不提供 `null` 入口，无法被清空
- 参数类型写成 `Object?`，实现内用 `identical(value, unset)` 判断，再 `as T?` 转型
- 所有允许清空的可空字段统一使用该约定；不允许出现「一部分用 sentinel、一部分用 `?? this.field`」的混用
- 不接受「传 null 等于不传」的旧写法

**可空字段清单与修改权限**（逐一核对，避免开发人员自行猜测）：

| 模型 | 可空字段 | copyWith 是否可改 | 是否可显式清空 | 约束 |
|---|---|---|---|---|
| Conversation | projectId | 仅 `topic` 可改 | 否 | `main` 恒为 null，不可设置；`topic` 必须有且不可清空 |
| Conversation | projectTitle | 是 | 是 | 与 projectId 同步；无 projectId 时应为空 |
| Conversation | topic / goal / scopeSummary | 否（构造时设置） | — | 主对话为 null；专题构造时必填 |
| Conversation | parentConversationId / originInviteId | 否（构造时设置） | — | 创建后不可变；主对话必须为 null |
| ChatMessage 基类 | reason | 否（构造时设置） | — | 主动消息创建后不可变 |
| ConfirmCard | actedAt | 是 | 是（回到未处理时） | 状态为 pending 时应为 null |
| ChoiceCard | answer | 是 | 是（撤销选择） | 清空后恢复为未回答 |
| MemoryCandidateItem | 无可空字段 | — | — | state 非空 |
| PlanChange | detail | 否（构造时设置） | — | 不可变 |
| PlanProposalCard | 无可空字段 | — | — | state 非空 |
| ThinkingCard | 无可空字段 | — | — | phase 非空 |
| AgentInviteCard | projectId | 否（构造时设置） | — | 接受后可回填，但不由 UI 随意清空 |
| AgentInviteCard | createdConversationId | 是（仅仓库回填） | 否 | accepted 时必须非空；pending/declined/expired 时必须为空 |
| TodayItem | start / end | start 可改 | 仅 `kind = task` 可清空 | block/reminder 的 start 不可清空；end 构造时设置 |
| TodayItem | durationMin / sourceTag / reason / projectId / projectTitle | 否（构造时设置） | — | 不可变 |
| Brief | 无可空字段 | — | — | — |
| DayView | morningBrief / eveningBrief | 否（构造时设置） | — | 缺失即表示当天没有该简报 |
| AlertAction | 无可空字段 | — | — | — |
| PriorityAlert | deadline | 否（构造时设置） | — | 不可变 |
| AlertResumeContext | conversationId / messageId / scrollOffset / draftText | 否（构造时设置） | — | 由 Shell 采集后不可变 |

**业务不变量总表（构造与 copyWith 均不得破坏）**：

| 模型 | 不变量 |
|---|---|
| Conversation | `main` → `agent = friday`、`projectId = null`、`topic/goal/scopeSummary/parentConversationId/originInviteId = null` |
| Conversation | `topic` → `agent = jarvis`、`projectId != null`、`topic/goal/scopeSummary` 非空；`projectTitle` 非空时必须有 `projectId` |
| Conversation | `lastActivityAt >= createdAt`；`status = archived` 后仍允许读取，不再产生新事件 |
| ChatMessage | `id`、`conversationId` 非空；`seq != 0` |
| ChatMessage | `synced` → `seq > 0`（正式消息）；`pending/queued/failed` → `seq < 0` |
| ChatMessage | 正式消息的 `seq` 必须等于其 `MessageUpsert.seq`；pending/queued/failed 不参与事件序列、不写入 `lastSeq` |
| ChatMessage | pending/queued/failed 使用同一负数临时 seq 与同一 `clientMessageId`；重试只改 `syncState`，不新建消息 |
| ConfirmCard | `pending` → `actedAt = null`；`confirmed / revoked` → `actedAt != null` |
| ConfirmCard | `title/body/primaryLabel/secondaryLabel` 非空；主次按钮文案不得相同 |
| ChoiceCard | `options.length` 在 2–4；选项非空且不重复；`answer` 为 null 或必须属于 `options` |
| ChoiceCard | 同一卡片只有一个 `answer`；清空表示撤销并回到未回答，不允许同时保留多个答案 |
| ChoiceAction | `skipped = true` → `option = null`；`skipped = false` → `option != null` 且非空；option 必须属于目标 ChoiceCard（运行时校验） |
| MemoryConfirmCard | `items` 非空；`itemId` 在卡片内唯一；`allConfirmed` 仅当全部 confirmed |
| PlanProposalCard | `changes` 非空；`summary/rationale` 非空；终态不可回退到 pending |
| AgentInviteCard | `targetAgent = jarvis`；`initiatorAgent` 为 friday 或 jarvis（不含 user） |
| AgentInviteCard | `accepted` → `createdConversationId != null`；`pending/declined/expired` → 必须为 null |
| AgentInviteCard | `topic/goal/scopeSummary/expectedOutcome` 非空；`accepting` 仅在 pending 时可为 true |
| TodayItem | `kind = block` → `start/end != null` 且 `end > start`、`durationMin > 0`；block 的 `start` 不可清空 |
| TodayItem | `kind = reminder` → `start != null`，`end/durationMin` 必须为空；reminder 的 `start` 不可清空 |
| TodayItem | `kind = task` → `start` 可为空；只有 task 允许通过 `copyWith(start: null)` 移出时间线 |
| TodayItem | `overdue` 不是状态值，按类型派生：block 在 `now > end` 时逾期；reminder 在 `now > start + 10min` 时逾期；task 在 `now > start` 时逾期；无 start 的 task 与 done/skipped 永不逾期 |
| TodayItem | `done/skipped` 与完成按钮状态一致；状态字段不得写入 overdue |
| PriorityAlert | `actions` 非空；`actionId` 非空且唯一；`label` 非空；`status = handled` 时 `handledActionId` 非空且必须属于 `actions` |
| PriorityAlert | `handledActionId` 仅在 `status = handled` 时非空；`deadline` 可空 |
| AlertResumeContext | `previousRoute` 非空；`capturedAt` 为采集时刻；字段创建后不可变 |
| AlertResumeContext | `conversationId` 为空时，`messageId/scrollOffset/draftText` 必须为空；`scrollOffset` 为空或非负 |
| ChatEvent | `conversationId` 非空、`seq > 0`；`MessageUpsert` 的消息归属/seq/syncState 与事件一致；`ConversationUpdated` 的对话 id 与事件一致 |
| ConversationSnapshot | `lastSeq >= 0`；仅正式消息、同一 conversation、`seq <= lastSeq`、id 唯一、按 seq 升序 |
| ConversationView | 消息约束同快照；`retryCount` 在 0–2；`syncError` 非空字符串；`failed` 必须有 `syncError`，非 failed 不得有；`syncing/synced` 时 retryCount = 0，`retrying/failed` 时 retryCount > 0 |
| ChatState | pending 仅 pending/queued/failed 且负数 seq、id 唯一、按负数 seq 降序；sendErrors 只指向 failed 且文案非空 |
| ChatView | 正式消息与 pending 的约束同源；两组 id 不重复；sendErrors 只指向 pending 中的 failed 且文案非空；同步状态/retryCount/syncError 关系同 ConversationView |
| Brief | `text/reasonLine` 非空；`mergedSuggestions` 不含空字符串 |
| DayView | `date` 为本地零点；`items` 均有 start 且按 start 升序；`unscheduled` 均为无 start 的 planned task；两组 id 合并不重复；brief 类型与字段匹配 |

说明：`Conversation.archived 后不再产生事件`、`done/skipped 与按钮一致` 属于 Repository / UI 行为约束，无法在单条模型构造时判定，由对应测试覆盖，不写成虚假 assert。`TodayItem.overdue` 已改为模型内派生方法，不再依赖 UI 约定。

**集合不可变约定**：

- 所有对外暴露的 `List` / `Map` 字段都必须在构造时复制为不可变视图：`List.unmodifiable(...)`、`Map.unmodifiable(...)`
- 不接受调用方传入的可变集合直接赋给字段；`copyWith` 传入的集合同样先复制再构造
- 涉及集合的构造函数不使用 `const`；默认值可写 `const []` / `const {}`，构造后仍复制
- 集合不可变不等于元素不可变：元素仍须满足自身不变量；`ChatState` / `ChatView` 的集合由 Controller 与 Provider 构造，不允许 UI 修改
- 单元测试对每个集合字段断言「写入抛 `UnsupportedError`」，并断言外部修改原集合不会影响模型

**执行方式**：

- 上述规则必须在**每个模型的构造函数**内用 `assert` 落地；提供 `copyWith` 的模型还必须在每个 `copyWith` 分支断言新值，不允许只在文档或测试里写规则
- `copyWith` 先算出新值再断言，不得先构造再依赖构造函数断言来「顺带」校验（构造函数断言仍必须保留）
- `const` 取舍：涉及集合长度/元素判断、`DateTime` 比较的构造函数不使用 `const`；字符串非空统一写 `!= ''`，使仅含字段关系断言的模型仍可 `const`。不得为了 `const` 删除断言
- 一个模型有多个 `copyWith` 分支时，每个分支都要断言；不允许只在 UI 层兜底
- 违反不变量的状态不得进入 UI；单元测试逐条覆盖，映射到 `copy_with_test` 与各模型测试
- Domain 层不引入额外校验框架；release 下 assert 被移除，外部数据必须先按 4.20 做运行时校验，业务代码不得构造非法状态

**逐模型落地位置**（与测试映射）：

| 模型 | assert 位置 | 覆盖测试 |
|---|---|---|
| Conversation | 构造函数 + `copyWith`（类型/Agent/projectId/时间） | `copy_with_test`、`conversation_test` |
| ChatMessage 基类 | 构造函数（id、conversationId、seq 与 syncState 关系） | `local_message_test`、`copy_with_test` |
| ConfirmCard | 构造函数 + `copyWith`（状态与 actedAt、按钮文案） | `copy_with_test`、`chat_controller_test` |
| ChoiceCard | 构造函数 + `copyWith`（2–4 项、选项非空且唯一、答案属于选项） | `copy_with_test` |
| ChoiceAction | 构造函数（skipped 与 option 关系） | `copy_with_test`、`validation_test` |
| MemoryConfirmCard | 构造函数 + `copyWith`（items 非空、itemId 唯一） | `copy_with_test` |
| PlanProposalCard | 构造函数（changes/summary/rationale 非空）+ `copyWith`（终态不回退） | `copy_with_test` |
| AgentInviteCard | 构造函数 + `copyWith`（targetAgent、非空文本、accepted 与 createdConversationId、accepting） | `copy_with_test`、`invite_test` |
| TodayItem | 构造函数 + `copyWith`（block/reminder 时间关系、only task 可清空 start） | `copy_with_test`、`today_controller_test` |
| PriorityAlert | 构造函数（actions 非空、actionId 唯一、handledActionId） | `copy_with_test`、`urgent_alert_test` |
| AlertResumeContext | 构造函数（字段联动） | `copy_with_test` |
| ChatEvent / MessageUpsert / ConversationUpdated | 构造函数（conversationId、seq、消息与对话归属一致性） | `conversation_event_test`、`validation_test` |
| ConversationSnapshot / ConversationView | 构造函数（lastSeq、正式消息、id 唯一、seq 升序、同步状态与 error 联动） | `message_merge_test`、`conversation_event_test` |
| Brief / DayView | 构造函数（文本非空、date 零点、items 排序、unscheduled 归类、brief 类型、id 唯一） | `copy_with_test`、`today_controller_test` |
| ChatState | 构造函数 + `copyWith`（pending 负数/唯一/降序、sendErrors 只指向 failed） | `local_message_test`、`chat_controller_test` |
| ChatView | 构造函数（正式/pending 各自约束、两组 id 不重复、sendErrors 匹配） | `local_message_test`、`chat_page_test` |

**copyWith 状态转换的 release 保障**：

- `assert` 在 release 被移除，**不能**作为业务状态转换的唯一保障；终态转换必须使用运行时 `if` 检查并抛出 `StateTransitionException`
- `copyWith` 只负责字段复制；业务转换统一走显式方法（如 `ConfirmCard.act()`、`PlanProposalCard.decide()`、`AgentInviteCard.markAccepted()`），方法内部先做运行时校验，再调用 `copyWith`
- 为保证 release 安全，终态转换相关的 `copyWith` 也必须内置运行时检查，不能只依赖调用方；禁止出现「debug 下 assert、release 下静默接受」的分支
- `StateTransitionException` 携带 `model`、`from`、`to`、`reason`；由 Presenter 转为用户提示，不崩溃
- 转换规则表：

| 模型 | 运行时禁止的转换 | release 行为 |
|---|---|---|
| ConfirmCard | `confirmed/revoked → pending`；状态变化但 `actedAt` 不匹配 | 抛 `StateTransitionException` |
| ChoiceCard | `answer` 不属于 `options`；已回答后改成另一个答案（只允许清空撤销） | 抛 `StateTransitionException` |
| PlanProposalCard | 终态 → `pending`；终态之间互相回退 | 抛 `StateTransitionException` |
| AgentInviteCard | `accepted → pending/declined/expired`；`accepted` 缺少 `createdConversationId`；非 accepted 携带 `createdConversationId` | 抛 `StateTransitionException` |
| TodayItem | block/reminder 清空 `start`；block 的 `start >= end` | 抛 `StateTransitionException` |
| ChatMessage | 负数 seq 的 pending/queued/failed 改为 `synced` | 抛 `StateTransitionException` |

- `copy_with_test` 除 assert 外，必须用「运行时异常」断言覆盖上表；这些测试不依赖 `--enable-asserts`，release 同样有效
- UI / Controller 不得直接改 `ConfirmCard/PlanProposalCard/AgentInviteCard` 的终态字段；只调用模型方法或 Controller 的卡片动作方法

对话规则：

- 每个用户有且只有一个 `type = main`、`agent = friday` 的主对话
- 用户可以拥有多个 `type = topic`、`agent = jarvis` 的专题对话
- 专题必须绑定 `projectId`；接受邀请时若邀请无项目，由后端（U1 为 Mock）创建或关联项目
- 同一项目可有多个专题；不同项目的数据与消息必须隔离
- 归属由仓库数据决定，前端不得用「最近发言者」推断

### 4.9 AgentInviteCard

```dart
final class AgentInviteCard extends ChatMessage {
  const AgentInviteCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.inviteId,
    required this.initiatorAgent,
    required this.targetAgent,
    required this.topic,
    required this.goal,
    required this.scopeSummary,
    required this.expectedOutcome,
    this.projectId,
    this.status = AgentInviteStatus.pending,
    this.createdConversationId,
    this.accepting = false,
  })  : assert(inviteId != '', 'inviteId must not be empty'),
        assert(
          targetAgent == ConversationAgent.jarvis,
          'U1 invite target must be jarvis',
        ),
        assert(
          topic != '' && goal != '' && scopeSummary != '' && expectedOutcome != '',
          'invite requires topic/goal/scopeSummary/expectedOutcome',
        ),
        assert(
          status == AgentInviteStatus.pending || !accepting,
          'accepting is only allowed while pending',
        ),
        assert(
          status != AgentInviteStatus.accepted ||
              createdConversationId != null,
          'accepted invite requires createdConversationId',
        ),
        assert(
          status == AgentInviteStatus.accepted ||
              createdConversationId == null,
          'unaccepted invite must not have createdConversationId',
        ),
        assert(
          createdConversationId == null || createdConversationId != '',
          'createdConversationId must not be empty',
        );

  final String inviteId;
  final ConversationAgent initiatorAgent;  // 不含 user
  final ConversationAgent targetAgent;     // U1 固定 jarvis
  final String? projectId;
  final String topic;
  final String goal;
  final String scopeSummary;
  final String expectedOutcome;
  final AgentInviteStatus status;
  final String? createdConversationId;     // 接受后回填
  final bool accepting;                    // UI 处理中，防重复点击

  AgentInviteCard copyWith({
    AgentInviteStatus? status,
    Object? createdConversationId = unset,
    bool? accepting,
  }) {
    final nextStatus = status ?? this.status;
    final nextCreatedConversationId = identical(createdConversationId, unset)
        ? this.createdConversationId
        : createdConversationId as String?;
    final nextAccepting = accepting ?? this.accepting;
    if (this.status != AgentInviteStatus.pending &&
        nextStatus != this.status) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'terminal invite cannot change status',
      );
    }
    if (nextStatus != AgentInviteStatus.pending && nextAccepting) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'accepting is only allowed while pending',
      );
    }
    if (nextStatus == AgentInviteStatus.accepted &&
        nextCreatedConversationId == null) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'accepted invite requires createdConversationId',
      );
    }
    if (nextStatus != AgentInviteStatus.accepted &&
        nextCreatedConversationId != null) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'unaccepted invite must not have createdConversationId',
      );
    }
    if (nextCreatedConversationId != null &&
        nextCreatedConversationId == '') {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'createdConversationId must not be empty',
      );
    }
    assert(
      nextStatus == AgentInviteStatus.pending || !nextAccepting,
      'accepting is only allowed while pending',
    );
    assert(
      nextStatus != AgentInviteStatus.accepted ||
          nextCreatedConversationId != null,
      'accepted invite requires createdConversationId',
    );
    assert(
      nextStatus == AgentInviteStatus.accepted ||
          nextCreatedConversationId == null,
      'unaccepted invite must not have createdConversationId',
    );
    assert(
      nextCreatedConversationId == null || nextCreatedConversationId != '',
      'createdConversationId must not be empty',
    );
    return AgentInviteCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      inviteId: inviteId,
      initiatorAgent: initiatorAgent,
      targetAgent: targetAgent,
      topic: topic,
      goal: goal,
      scopeSummary: scopeSummary,
      expectedOutcome: expectedOutcome,
      projectId: projectId,
      status: nextStatus,
      createdConversationId: nextCreatedConversationId,
      accepting: nextAccepting,
    );
  }
}
```

### 4.12 PriorityAlert 与 AlertResumeContext（职责分离）

```dart
class AlertAction {
  const AlertAction({
    required this.actionId,
    required this.label,
    this.destructive = false,
  })  : assert(actionId != '', 'actionId must not be empty'),
        assert(label != '', 'label must not be empty');

  final String actionId;
  final String label;
  final bool destructive;
}

class PriorityAlert {
  // 含集合非空、元素判断与不可变复制，构造函数不能是 const
  PriorityAlert({
    required this.alertId,
    required this.priority,
    required this.reason,
    required List<AlertAction> actions,
    required this.status,
    required this.createdAt,
    this.deadline,
    this.handledActionId,
  })  : actions = List<AlertAction>.unmodifiable(actions),
        assert(alertId != '', 'alertId must not be empty'),
        assert(reason != '', 'reason must not be empty'),
        assert(actions.length > 0, 'alert requires at least one action'),
        assert(
          actions.map((a) => a.actionId).toSet().length == actions.length,
          'alert action ids must be unique',
        ),
        assert(
          status != AlertStatus.handled ||
              (handledActionId != null &&
                  actions.any((a) => a.actionId == handledActionId)),
          'handled alert requires a handledActionId from actions',
        ),
        assert(
          status == AlertStatus.handled || handledActionId == null,
          'handledActionId is only allowed when handled',
        );

  final String alertId;
  final AlertPriority priority;
  final String reason;
  final DateTime? deadline;
  final List<AlertAction> actions;
  final AlertStatus status;
  final DateTime createdAt;
  final String? handledActionId;   // handled 时记录实际执行的动作
}

class AlertResumeContext {
  const AlertResumeContext({
    required this.previousRoute,
    required this.capturedAt,
    this.conversationId,
    this.messageId,
    this.scrollOffset,
    this.draftText,
  })  : assert(previousRoute != '', 'previousRoute must not be empty'),
        assert(
          conversationId != null ||
              (messageId == null && scrollOffset == null && draftText == null),
          'messageId/scrollOffset/draftText require conversationId',
        ),
        assert(
          scrollOffset == null || scrollOffset >= 0,
          'scrollOffset must not be negative',
        );

  final String previousRoute;       // 如 /chat/c-123?messageId=m-9
  final String? conversationId;     // 当前对话（Today 页面时为空）
  final String? messageId;          // 深链定位的消息
  final double? scrollOffset;
  final String? draftText;
  final DateTime capturedAt;
}
```

职责：

- `PriorityAlert` 只描述提醒本身，不记录用户在看哪个页面
- `AlertResumeContext` 由 App Shell 在弹窗出现前采集，弹窗关闭/处理后用于恢复
- 两者不互相引用；Shell 内部以 `(alert, resumeContext)` 成对持有

### 4.14 ChatEvent 与快照

```dart
sealed class ChatEvent {
  const ChatEvent({
    required this.conversationId,
    required this.seq,
  })  : assert(conversationId != '', 'event conversationId must not be empty'),
        assert(seq > 0, 'event seq must be positive');

  final String conversationId;  // 所有会话事件都必须携带
  final int seq;                // 会话内唯一、按事件产生顺序递增
}

final class MessageUpsert extends ChatEvent {
  const MessageUpsert({
    required super.conversationId,
    required super.seq,
    required this.message,
  })  : assert(
          message.conversationId == conversationId,
          'message conversationId must match event',
        ),
        assert(message.seq == seq, 'message seq must match event'),
        assert(
          message.syncState == SyncState.synced,
          'event message must be a formal synced message',
        );
  final ChatMessage message;
}

final class ConversationUpdated extends ChatEvent {
  const ConversationUpdated({
    required super.conversationId,
    required super.seq,
    required this.conversation,
  }) : assert(
          conversation.conversationId == conversationId,
          'conversation id must match event',
        );
  final Conversation conversation;
}

class ConversationSnapshot {
  // 含集合不可变复制，构造函数不能是 const
  ConversationSnapshot({
    required this.conversation,
    required List<ChatMessage> messages,
    required this.lastSeq,
  })  : messages = List<ChatMessage>.unmodifiable(messages),
        assert(lastSeq >= 0, 'lastSeq must not be negative'),
        assert(
          messages.every(
            (m) =>
                m.syncState == SyncState.synced &&
                m.seq > 0 &&
                m.seq <= lastSeq &&
                m.conversationId == conversation.conversationId,
          ),
          'snapshot only accepts formal messages of the same conversation, seq <= lastSeq',
        ),
        assert(
          messages.map((m) => m.id).toSet().length == messages.length,
          'snapshot message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(messages.map((m) => m.seq).toList()),
          'snapshot messages must be sorted by seq ascending',
        );

  final Conversation conversation;   // 与 messages 同一快照点
  final List<ChatMessage> messages;
  final int lastSeq;
  // lastSeq = 快照已完整反映该会话中所有 seq <= lastSeq 的事件所产生的状态
}

class ConversationView {
  // 含集合不可变复制，构造函数不能是 const
  ConversationView({
    required this.conversation,
    required List<ChatMessage> messages,
    this.syncState = ConversationSyncState.synced,
    this.retryCount = 0,
    this.syncError,
  })  : messages = List<ChatMessage>.unmodifiable(messages),
        assert(
          messages.every(
            (m) =>
                m.syncState == SyncState.synced &&
                m.seq > 0 &&
                m.conversationId == conversation.conversationId,
          ),
          'view only accepts formal messages of the same conversation',
        ),
        assert(
          messages.map((m) => m.id).toSet().length == messages.length,
          'view message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(messages.map((m) => m.seq).toList()),
          'view messages must be sorted by seq ascending',
        ),
        assert(
          retryCount >= 0 && retryCount <= 2,
          'retryCount must be within 0..2',
        ),
        assert(
          syncState == ConversationSyncState.failed || syncError == null,
          'syncError is only allowed when failed',
        ),
        assert(
          syncState != ConversationSyncState.failed || syncError != null,
          'failed sync state requires syncError',
        ),
        assert(
          syncError == null || syncError != '',
          'syncError must not be empty',
        ),
        assert(
          (syncState == ConversationSyncState.failed ||
                  syncState == ConversationSyncState.retrying) ==
              (retryCount > 0),
          'retrying/failed require retryCount > 0; synced/syncing require 0',
        );

  final Conversation conversation;
  final List<ChatMessage> messages;  // 仅正式消息
  final ConversationSyncState syncState;
  final int retryCount;              // 已执行的重试次数，0–2
  final String? syncError;
}

class ChatView {
  // 含集合去重、排序与不可变复制，构造函数不能是 const
  ChatView({
    required this.conversation,
    required List<ChatMessage> messages,
    required List<ChatMessage> pending,
    Map<String, String> sendErrors = const <String, String>{},
    this.syncState = ConversationSyncState.synced,
    this.retryCount = 0,
    this.syncError,
  })  : messages = List<ChatMessage>.unmodifiable(messages),
        pending = List<ChatMessage>.unmodifiable(pending),
        sendErrors = Map<String, String>.unmodifiable(sendErrors),
        assert(
          messages.every(
            (m) =>
                m.syncState == SyncState.synced &&
                m.seq > 0 &&
                m.conversationId == conversation.conversationId,
          ),
          'messages must be formal messages of the same conversation',
        ),
        assert(
          messages.map((m) => m.id).toSet().length == messages.length,
          'formal message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(messages.map((m) => m.seq).toList()),
          'formal messages must be sorted by seq ascending',
        ),
        assert(
          pending.every(
            (p) =>
                p.syncState != SyncState.synced &&
                p.seq < 0 &&
                p.conversationId == conversation.conversationId,
          ),
          'pending must contain local pending/queued/failed messages of the same conversation',
        ),
        assert(
          pending.map((p) => p.id).toSet().length == pending.length,
          'pending message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(pending.map((p) => -p.seq).toList()),
          'pending must be sorted by negative seq descending',
        ),
        assert(
          pending.every((p) => !messages.any((m) => m.id == p.id)),
          'pending must not contain ids already present in formal messages',
        ),
        assert(
          sendErrors.keys.every(
            (id) => pending.any(
              (p) => p.id == id && p.syncState == SyncState.failed,
            ),
          ),
          'sendErrors keys must reference failed pending messages',
        ),
        assert(
          sendErrors.values.every((text) => text != ''),
          'sendErrors values must not be empty',
        ),
        assert(
          retryCount >= 0 && retryCount <= 2,
          'retryCount must be within 0..2',
        ),
        assert(
          syncState == ConversationSyncState.failed || syncError == null,
          'syncError is only allowed when failed',
        ),
        assert(
          syncState != ConversationSyncState.failed || syncError != null,
          'failed sync state requires syncError',
        ),
        assert(
          syncError == null || syncError != '',
          'syncError must not be empty',
        ),
        assert(
          (syncState == ConversationSyncState.failed ||
                  syncState == ConversationSyncState.retrying) ==
              (retryCount > 0),
          'retrying/failed require retryCount > 0; synced/syncing require 0',
        );

  final Conversation conversation;
  final List<ChatMessage> messages;  // 正式消息，按 seq 升序
  final List<ChatMessage> pending;   // pending/queued/failed，负数 seq，按创建顺序排在正式消息之后
  final Map<String, String> sendErrors; // clientMessageId -> 失败文案，仅 failed 存在
  final ConversationSyncState syncState;
  final int retryCount;              // 已执行的重试次数，0–2
  final String? syncError;

  /// 页面唯一渲染顺序：正式消息 → pending/queued/failed。
  /// UI 不得自行拼接或再次排序。
  List<ChatMessage> get displayMessages => [...messages, ...pending];
}

bool _isStrictlyAscending(List<int> values) {
  for (var i = 1; i < values.length; i++) {
    if (values[i] <= values[i - 1]) return false;
  }
  return true;
}
```

**统一事件序列**：

- `MessageUpsert`、`ConversationUpdated` 以及未来新增的会话事件，全部属于**同一条**按 `seq` 递增的事件序列
- 不允许不同事件类型各自维护序号；`seq` 在单个 Conversation 内唯一
- 事件处理必须参与连续性检查；暂不支持业务处理的新事件类型，可以安全忽略其业务效果，但必须推进 `currentSeq`，不能破坏序列

**不同事件的处理方式**：

| 事件 | 处理 |
|---|---|
| `MessageUpsert` | 按 `message.id` upsert 消息 |
| `ConversationUpdated` | 用事件内的 Conversation 覆盖当前对话信息（状态、最近活动、项目标题等） |
| 未来事件类型 | 推进 `currentSeq`；如无法处理则记录并安全忽略，不改变已有状态 |

**事件一致性校验**（任何一条不满足都不得直接应用；这些是运行时校验，不得只依赖构造 assert，失败路径见 4.20）：

| 校验 | 要求 |
|---|---|
| 外层会话 | `event.conversationId` 必须等于当前监听的 `conversationId` |
| 消息归属 | `MessageUpsert.message.conversationId == event.conversationId` |
| 消息序号 | `MessageUpsert.message.seq == event.seq` |
| 对话归属 | `ConversationUpdated.conversation.conversationId == event.conversationId` |
| 消息 ID | `MessageUpsert.message.id` 非空；同一事件内保持一致 |

校验失败的处理：

- 不应用到正式状态
- 记录诊断信息（事件类型、conversationId、seq、校验失败原因）
- 进入安全恢复流程：重新获取快照；恢复失败则保留上一份有效状态并提示同步异常

**重复、过期与冲突的统一判定**：

Repository 为每个 `seq` 记录**事件摘要**（事件类型 + 关键字段，如 `messageId`、文本、对话状态；不要求暴露给上层）。摘要只对 `(baselineSeq, currentSeq]` 建立，并保留最近 200 个已应用 `seq` 的摘要；`baselineSeq` 定义见 4.17：

| 条件 | 判定 | 处理 |
|---|---|---|
| `seq <= baselineSeq` | 快照已覆盖 | 直接忽略，不比对摘要、不报冲突 |
| `baselineSeq < seq < currentSeq`，摘要相同或已淘汰 | 过期事件 | 忽略，不改变状态 |
| `baselineSeq < seq < currentSeq`，摘要不同 | 迟到冲突 | 忽略其业务效果；记录 `late_conflict` 诊断；不触发重同步（快照与后续事件已是权威） |
| `seq == currentSeq > baselineSeq`，摘要相同 | 重复事件 | 忽略 |
| `seq == currentSeq > baselineSeq`，摘要不同 | 头部冲突 | 视为协议冲突，触发重新同步 |
| `seq == currentSeq == baselineSeq` | 快照已覆盖 | 按第一行忽略，不能误判为重复或头部冲突 |
| buffer 内同一 `seq` 摘要相同 | 重复 | 合并为一条，只应用一次 |
| buffer 内同一 `seq` 摘要不同 | 缓冲冲突 | 停止应用该 seq 及后续事件，触发重新同步 |

约束：

- 冲突事件一律不得任意选一个覆盖另一个
- 重同步开始时清除全部旧摘要，并重设 `baselineSeq = currentSeq = newLastSeq`；新摘要只对之后的事件建立
- `seq <= baselineSeq` 的事件不记录摘要，避免把快照覆盖区间误当成「已应用事件」
- 若冲突重复出现，Repository 记录错误并向上层暴露同步异常状态

### 4.15 邀请结果类型

```dart
sealed class InviteAcceptResult {
  const InviteAcceptResult();
}

final class InviteAccepted extends InviteAcceptResult {
  const InviteAccepted({required this.conversation, required this.alreadyAccepted});
  final Conversation conversation;
  final bool alreadyAccepted;
}

final class InviteCannotAccept extends InviteAcceptResult {
  const InviteCannotAccept({required this.reason});
  final InviteRejectReason reason;
}

sealed class InviteDeclineResult {
  const InviteDeclineResult();
}

final class InviteDeclined extends InviteDeclineResult {
  const InviteDeclined();
}

final class InviteCannotDecline extends InviteDeclineResult {
  const InviteCannotDecline({required this.reason});
  final InviteRejectReason reason;
}
```

### 4.16 仓库接口

```dart
abstract interface class ChatRepository {
  Future<Conversation> loadMainConversation();
  Future<List<Conversation>> loadTopicConversations();
  Future<Conversation> getConversation(String conversationId);

  // 先订阅，保证不漏事件
  Stream<ChatEvent> watchConversation(String conversationId);

  // 后取快照；与事件按 4.17 的规则合并
  Future<ConversationSnapshot> loadConversationSnapshot(String conversationId);

  // 手动重试同步：重置退避计数并重新走一次 4.17 的重同步流程
  Future<void> retrySync(String conversationId);

  // clientMessageId 由 Controller 生成；确认事件必须复用同一 id
  Future<void> sendText({
    required String conversationId,
    required String clientMessageId,
    required String text,
  });

  // 仅用于 Confirm / Choice / Memory / PlanProposal；邀请卡片走 acceptInvite/declineInvite
  Future<void> respondToCard({
    required String conversationId,
    required String messageId,
    required CardAction action,
  });

  Future<InviteAcceptResult> acceptInvite(String inviteId);
  Future<InviteDeclineResult> declineInvite(String inviteId);
}

abstract interface class TodayRepository {
  Future<DayView> loadDay(DateTime date);
  Future<TodayItem> complete(String itemId);
  Future<TodayItem> skip(String itemId);
  Future<TodayItem> reschedule(String itemId, DateTime newStart);
  Future<TodayItem> moveToToday(String itemId, DateTime start);
  Future<void> submitEveningReview(Map<String, bool> completionByItemId);
}

abstract interface class NetworkStatusSource {
  Stream<NetworkStatus> watch();
}

abstract interface class AlertRepository {
  Stream<PriorityAlert> watchAlerts();
  Future<void> handleAlert({required String alertId, required String actionId});
  Future<void> dismissAlert(String alertId);
}
```

接口约束：

- `sendText` 必须携带 Controller 生成的 `clientMessageId`，且与本地 pending 的 `id` 完全一致；失败重试复用同一 id
- `sendText` 正常返回只表示请求已被接受，**不代表消息已确认**；确认只认正式消息或事件中出现的同一 `id`
- `sendText` 失败必须抛出异常，由 Controller 将该条消息置为 `failed`；Repository 不得吞异常或伪造确认
- Repository **不创建、不持有、不返回** pending；pending 由 Controller 持有，合并规则见 4.17 与 4.19
- `loadConversationSnapshot` 返回的 `conversation`、`messages`、`lastSeq` 必须来自同一快照点；不得由两个请求拼接
- `retrySync` 只用于用户手动重试：不取消、不重建订阅，重置退避计数并从第 1 次尝试重新开始；仅 `failed` 状态下清空旧事件队列后重新取快照，不得绕过运行时校验
- 调用方必须先 `watchConversation` 再取快照；Repository 负责缓存、排序、去重与缺口恢复，调用方不做这些判断
- `respondToCard` 只接受 Confirm / Choice / Memory / PlanProposal；邀请卡片一律走 `acceptInvite` / `declineInvite`
- `acceptInvite` 幂等：重复或并发调用最多创建一个 Conversation，成功结果指向同一 `conversationId`
- 前端只传 `conversationId`、`clientMessageId`、文本、卡片动作、`inviteId`
- 不传 Prompt、不选模型、不指定 Agent；路由与模型选择属于后端
- Mock 实现必须体现 4.17（事件合并、快照基线、重试退避、pending 归属、本地消息边界）、4.18（邀请幂等）、4.19（pending/queued/failed 生命周期、确认清理）与 4.21（离线发送、销毁保护）的语义，含延迟事件、重复事件、流式更新、发送失败、非法 payload 与并发接受；`retrySync` 必须可被 UI 触发

### 4.17 事件序列与快照衔接规则（关键）

**目标**：历史快照与实时事件之间不能出现消息遗漏或对话状态不同步；同一消息不能重复出现。

**订阅顺序**：先 `watchConversation`，再 `loadConversationSnapshot`。

**基线定义**：

- `baselineSeq`：最近一次快照的 `lastSeq`，表示「该 seq 及之前的状态已由快照完整覆盖」
- `currentSeq`：当前已应用的最大 seq，始终满足 `currentSeq >= baselineSeq`
- 摘要只对 `seq > baselineSeq` 的事件建立；`seq <= baselineSeq` 不建立摘要，也不做内容比对
- 初次加载与每次重同步都会重设 `baselineSeq = lastSeq`、`currentSeq = lastSeq`，并清除旧摘要

**统一事件应用规则**（初次合并、持续监听、重同步三个阶段共用）：

| 收到的事件 | 处理 |
|---|---|
| `event.seq <= baselineSeq` | 快照已覆盖：直接忽略，不比对内容、不报冲突 |
| `baselineSeq < event.seq < currentSeq` | 过期事件：忽略；若摘要存在且不同，记录 `late_conflict`，不回滚、不重同步 |
| `event.seq == currentSeq == baselineSeq` | 快照已覆盖：直接忽略，不判重复、不判头部冲突 |
| `event.seq == currentSeq > baselineSeq` | 重复或头部事件：摘要相同则忽略；摘要不同则判定头部冲突并进入重新同步 |
| `event.seq == currentSeq + 1` | 正常应用，记录摘要，`currentSeq = event.seq` |
| `event.seq > currentSeq + 1` | 发现缺口，停止应用后续事件，进入重新同步 |

约束：

- `MessageUpsert`、`ConversationUpdated` 及未来会话事件全部遵循同一规则
- 不能只在持续监听阶段检查缺口；初次 buffer 合并与重同步后的再次合并都必须逐条检查
- 快照刚建立时 `currentSeq == baselineSeq`，此时收到 `seq == currentSeq` 的事件属于快照覆盖范围，按第一行忽略，不能误判为头部冲突
- 已到 15 又收到 13：若 13 > baselineSeq 且摘要不同，记录 `late_conflict`；若 13 <= baselineSeq，直接忽略
- 同一 `seq` 的重复事件只应用一次；同 `seq` 不同内容按上表冲突分支处理，不任选其一
- 摘要只保留 `(baselineSeq, currentSeq]` 范围内最近 200 个 seq；更早的过期事件只按过期忽略，不再做内容比对

**阶段一：初次加载**

1. 建立 `watchConversation` 订阅，事件立即进入 `buffer`
2. 请求 `ConversationSnapshot(conversation, messages, lastSeq)`
3. 用快照的 `conversation` 与 `messages` 初始化正式状态：
   - `baselineSeq = lastSeq`
   - `currentSeq = lastSeq`
   - 清空旧摘要
4. 丢弃 buffer 中 `seq <= baselineSeq` 的事件（快照已覆盖，不做内容比对）
5. 将剩余事件按 `seq` 升序排序，逐条按 4.17 统一事件判定规则处理
6. 每次应用前先做 4.14 的事件一致性校验
7. 若遇到缺口：停止应用，保留未处理事件，转入重新同步
8. 若全部事件连续处理完毕，进入持续监听

**初次 buffer 缺口的例子**：

- 快照 `lastSeq = 10`
- buffer 收到 `MessageUpsert(seq=11)`、`ConversationUpdated(seq=13)`
- 处理 11 后，13 不满足 `== 12`，判定缺口
- 不得直接应用 13 后进入监听；必须重新取快照并重新合并

**阶段二：持续监听**

- 每条事件先校验一致性，再按统一事件判定规则处理
- `currentSeq` 只随成功应用的事件推进
- 收到缺口立即转入重新同步，不尝试跳过缺失事件

**阶段三：重新同步**

1. 进入「重新同步」状态，**不取消订阅**，新事件继续进入 buffer
2. 请求新快照；请求期间到达的事件同样保留
3. 新快照返回后，用其 `conversation` 与 `messages` 重建**正式状态**（Repository 不持有 pending），并重设：
   - `baselineSeq = newLastSeq`
   - `currentSeq = newLastSeq`
   - 清除旧摘要（含旧 baseline 区间）
4. Controller 保留自己持有的 pending，并在收到新 `ConversationView` 后重新合并（见下文）
5. 丢弃 buffer 中 `seq <= baselineSeq` 的事件
6. 对剩余事件重新执行统一事件判定规则
7. 若仍有缺口，重复本阶段，但受 3 次尝试上限约束；超过上限转 `failed`，不得无限循环
8. 同一时刻只允许一个同步流程修改会话状态；禁止两个监听器并行写入

**事件队列串行与 buffer 原子切换**：

- 每个 conversation 只有一条事件队列；初次 buffer、持续监听事件、重同步期间事件全部进入同一队列，按 `seq` 排序后**逐条串行**处理
- 事件应用函数必须是同步段：`seq` 判定、状态写入、`currentSeq`/摘要更新在同一个同步块内完成，中间不得 `await`；IO/通知在状态提交后另行触发
- 每次重同步递增 `syncGeneration`；快照请求携带发起时的 generation，返回时若 generation 已变化则丢弃该快照，不能覆盖更新的状态
- buffer 切换必须原子：处理快照时一次性取出当前 buffer 并替换为空 buffer；切换期间到达的新事件进入新 buffer，待当前批处理完再按序处理，不能丢失或重复
- 禁止两个 `async` 流程同时写 `baselineSeq`/`currentSeq`/摘要/消息；用单飞（in-flight）标志或互斥锁保证同一时刻只有一个同步任务
- 事件队列设置上限（U1 为 1000 条）；溢出时丢弃队列并直接进入重同步，以新快照为准，禁止无限堆积
- 重同步失败进入 `failed` 后停止消费队列；手动 `retrySync` 不重建订阅，只清空旧队列、重置退避并重新取快照
- 应用顺序固定为：一致性校验 → 序号判定 → 状态/消息写入 → 摘要更新 → 通知监听者；任一步失败不得留下半应用状态
- 测试必须覆盖：事件到达与快照返回交错、切换 buffer 瞬间插入事件、旧 generation 快照晚到、队列溢出、重同步失败后手动重试

**同步引擎实现位置**：

- 4.17 的全部规则（单队列串行、buffer 原子切换、`syncGeneration`、摘要窗口、重同步退避）集中在 `ConversationSyncEngine` 一个类中，文件为 `mobile/lib/core/sync/conversation_sync_engine.dart`
- `ChatRepository` 的实现内部持有或调用该引擎；Provider / Controller / Widget 不出现 `baselineSeq`、摘要、`syncGeneration` 等概念
- 引擎对外只暴露 `Stream<ConversationView> watch(String conversationId)`、`Future<ConversationSnapshot> loadSnapshot(String conversationId)` 与 `Future<void> retrySync(String conversationId)`；全部状态变更在引擎内部串行完成
- 将来接入真实后端协议时只替换引擎与 Repository，不动 Controller 与 UI

**重同步重试上限与退避**：

- 每次发现缺口后，重同步最多尝试 **3 次**（首次 + 2 次重试）；不得无限循环
- 退避在每次重试前执行：第 1 次重试前 300ms，第 2 次重试前 600ms；上限 1200ms；每次叠加 ±20% jitter
- 退避通过可注入的 `Sleeper` 执行（`Future<void> sleep(Duration)`）；jitter 通过可注入的 `Random` 生成；测试注入固定 seed，断言延迟落在 [0.8×base, 1.2×base] 且不超过 1200ms；禁止在 Repository 内直接硬编码 `Future.delayed`
- 第 3 次尝试仍失败：停止自动重试，保留最后一次有效 `ConversationView`，将 `syncState = failed`、`retryCount = 2`（已执行 2 次重试）、`syncError` 置为可展示文案
- 成功后 `retryCount = 0`、`syncState = synced`、清空 `syncError`；下一次新的缺口重新从 3 次额度开始
- 用户手动「重试同步」视为新周期，从第 1 次尝试重新计数；不再自动触发
- `conversationChannelProvider` 必须关闭 Riverpod 3 的 provider 自动重试（`retry: (_, __) => null`），避免与 Repository 自己的退避策略叠加
- 重试期间订阅不取消，事件继续进入 buffer；每次尝试都用新快照重设 `baselineSeq/currentSeq` 并清空旧摘要
- `late_conflict` 只记录诊断，不触发重试；只有缺口、头部冲突、缓冲冲突、快照校验失败进入重试流程

**首次加载失败处理**：

- 初次 `loadConversationSnapshot` 与重同步共用同一重试策略：最多 3 次尝试、300ms/600ms 退避、±20% jitter
- 3 次仍失败时不得构造半成品 `ConversationView`：`conversationChannelProvider` 返回 `AsyncError(SyncInitialLoadException)`，不设置 `baselineSeq/currentSeq`，不建立摘要
- UI 显示整页错误态「加载失败」+「重试」；输入条禁用，不能创建 pending
- `retrySync` 对首次加载失败同样有效：重新发起首次快照请求，成功后再进入正常同步流程
- 初次加载失败不写入同步 `failed` 横幅（没有旧消息可保留），与「已有数据后重同步失败」区分
- Mock 必须提供「首次快照连续失败 3 次 → AsyncError → 手动重试成功」的数据

**MessageUpsert 语义**：

- 以 `message.id` 为键 upsert：存在则替换，不存在则插入
- 重复收到同一 `messageId` 的事件不产生重复消息
- 流式文字增长始终更新同一条消息（同一 `id` 的 `text` 变化），不创建新消息
- `seq` 更新为事件 `seq`；`createdAt` 不变

**ConversationUpdated 语义**：

- 以事件内的 `Conversation` 整体覆盖当前值（同 `conversationId`）
- 与消息事件一样参与连续性与冲突检查
- 重复事件按 `seq` 去重，不产生重复状态变更

**排序规则**：

- 正式消息按正式 `seq` 升序展示
- 不按 `createdAt` 排序（时钟漂移会导致乱序）；`createdAt` 仅用于界面时间显示

**本地临时消息、clientMessageId 与重试**：

- 正式 `seq` 只由仓库/服务端分配；Controller 与 UI 不得分配正式 `seq`
- Controller 为每次发送生成唯一 `clientMessageId`，用它创建本地 pending 消息，并原样传给 `sendText`
- 服务端确认事件的 `message.id` 必须等于 `clientMessageId`；Repository 通过该 id 完成确认
- 本地 pending / queued / failed 使用**负数临时 seq**（从 -1 开始递减：-1、-2、-3…），仅用于本地排序：不参与连续性检查、不写入 `lastSeq`、不进入 `ConversationSnapshot`、不得作为 `ChatEvent`
- 排序：正式消息按 `seq` 升序；pending / queued / failed 按负数临时 seq **降序**（-1 在 -2 之前，即创建顺序）排在正式消息之后，不依赖 `createdAt`，避免时钟回拨
- 同一会话的多条 pending 使用各自 `clientMessageId` 与临时 seq，互不覆盖
- 网络失败重试必须复用原 `clientMessageId` 与原负数 seq；同一 `clientMessageId` 的重复发送不得创建第二条消息
- 失败消息保留原 id 与原负数 seq，只把 `syncState` 改为 `failed`；重试在线改回 `pending`、离线改回 `queued`，不新建消息

**pending / queued / failed 状态机**：

| 状态 | `syncState` | `seq` | 进入条件 | 退出条件 |
|---|---|---|---|---|
| 离线排队 | `queued` | 负数 | 离线时 Controller 创建消息 | 网络恢复转 `pending` 并补发 |
| 发送中 | `pending` | 负数 | 在线创建 pending 并上屏 | 发送成功等确认；或发送失败转 `failed` |
| 发送失败 | `failed` | 同一负数 | `sendText` 抛异常/超时 | 用户重试转 `pending/queued`；确认到达则直接清理 |
| 已确认 | `synced` | 正式正数 | 正式消息/事件/快照出现同一 `id` | 终态，不再回到本地状态 |

**pending 的创建、持有、合并与清理（统一归属 Controller）**：

- **创建**：Controller 生成 `clientMessageId` 与负数临时 seq，在线创建 `TextMessage(syncState: pending)`、离线创建 `queued`，并立即上屏
- **持有**：pending / queued / failed 只存在于 `ChatState.pending`；Repository 不创建、不存储、不返回
- **合并**：`chatViewProvider` 读取 `conversationChannelProvider` 的正式 `ConversationView` 与 `chatControllerProvider` 的 `ChatState`，过滤掉正式消息中已存在的 id 后生成 `ChatView`
- **确认清理**：`ChatController.build()` 监听 `conversationChannelProvider`，只要正式消息或重同步快照中出现 `id == clientMessageId`，就从 `ChatState.pending` 与 `sendErrors` 中删除该条；UI 不再显示 pending
- **失败**：`sendText` 抛异常时，把同一消息的 `syncState` 改为 `failed`，并在 `sendErrors[clientMessageId]` 记录文案；不删除消息、不改 id、不改负数 seq
- **重试**：复用原 `clientMessageId` 与原负数 seq，把 `syncState` 改回 `pending`，清除 `sendErrors` 对应项，再次调用 `sendText`
- **重同步**：Repository 只重建正式状态；Controller 收到新 `ConversationView` 后重新合并 pending，pending / queued / failed 都不会因快照而消失
- **去重**：合并以 `messageId` 为键；正式消息优先，`ChatView` 构造断言保证 pending 与正式消息无重复 id
- **不自动清理 failed**：failed 不会因重同步、流式更新或 `ConversationUpdated` 被删除；只有确认到达或用户重试成功才离开列表

**重同步期间保留 pending**：

- 快照只包含正式消息，Controller 不得因新快照而清空 pending
- 若快照或随后事件中已存在相同 `clientMessageId` / `messageId`，Controller 必须把该 pending 转为已确认并复用已有消息，不能再次插入
- 合并后正式消息与临时消息不得重复显示

**Mock 要求**：

- `loadConversationSnapshot` 人为延迟 300ms，期间推入一条新消息与一次 `ConversationUpdated`
- 能模拟初次 buffer 缺口、持续监听缺口、重同步期间继续到达事件、重同步后仍有缺口
- 能模拟旧事件迟到、重复事件、同 seq 冲突、conversationId 不一致、消息内外 seq 不一致
- 能模拟「发送 pending → 重同步 → pending 保留 → 服务端确认同一 id」，最终只有一条消息
- 能模拟连续快照失败：验证 3 次尝试、300ms/600ms 退避、最终 `failed` 与手动重试
- 能模拟非法事件/快照 payload：验证运行时校验拒绝、类型化异常与不部分应用
- 流式回复通过同一 `TextMessage` 的多次 `MessageUpsert` 模拟

**职责边界**：

| 层 | 负责 | 不负责 |
|---|---|---|
| Repository | 订阅、快照获取、事件缓存与一致性校验、统一序号判定与摘要、缺口恢复、按 messageId upsert、分配正式 seq（Mock 内） | 页面状态、Widget 生命周期、创建/持有 pending/queued/failed、合并 pending |
| Controller / Notifier | 生成 `clientMessageId`、创建并持有 pending/queued/failed 与 `sendErrors`、与正式 `ConversationView` 合并、卡片乐观更新与回滚、离线队列与 flush、消息失败转 `failed`、失败重试（复用原 id/seq）、草稿与滚动 | 判断事件是否遗漏、分配正式 seq、决定 Agent 归属 |
| UI / Widget | 展示 `ChatView.displayMessages`、发送中/失败标记、对话头部与专题信息；触发用户操作 | 同步合并、seq 分配、缺口恢复、Agent 路由、pending 去重 |

UI 不得在 Widget 内做事件去重、重排或补拉；这些逻辑只能存在于 Repository（或 Repository 与 Controller 之间的同步层）。

### 4.18 邀请接受与拒绝的幂等规则

**唯一操作路径**：

- `AgentInviteCard` 的接受/拒绝**只允许**调用 `acceptInvite` / `declineInvite`
- 不提供 `InviteAction`，也不能通过 `respondToCard()` 处理邀请，避免绕过幂等与 `accepting` 状态
- 若 `respondToCard()` 收到邀请卡片 id，直接拒绝并记录错误

**唯一性范围**：

- `inviteId` 全局唯一（UUID），由后端/Mock 生成
- 仓库内部记录 `inviteId → { ownerUserId, mainConversationId, status, createdConversationId }`
- 只有 `ownerUserId` 对应的用户、且在 `mainConversationId` 中出现的邀请可被操作；其他情况返回 `InviteCannotAccept(reason: notFound/notOwner)`

**规则表**：

| 场景 | 行为 |
|---|---|
| 首次接受 | 创建项目（如需）与一个 `topic` 对话，`status = accepted`，回填 `createdConversationId` |
| 重复接受（已接受） | 返回此前创建的同一个 Conversation，`alreadyAccepted = true`，不新建 |
| 接受已拒绝/已过期 | `InviteCannotAccept(reason: declined/expired)`，不创建 |
| 并发接受（双击/重试/重复事件） | 以 `inviteId` 为键串行化或等效原子处理；最多创建 1 个 Conversation，项目最多创建/关联一次 |
| 并发接受的返回值 | 所有成功返回都指向同一个 `conversationId`；后到请求 `alreadyAccepted = true` |
| 首次拒绝 | `status = declined`，不创建 Conversation |
| 重复拒绝 | 幂等返回 `InviteDeclined` |
| 拒绝已接受 | `InviteCannotDecline(reason: alreadyAccepted)`，不改变对话 |
| 接受与拒绝同时到达 | 以先到者为准，后到者返回对应 `Cannot*`，二者互斥 |

**并发实现约定（U1 用 Mock 模拟）**：

- 仓库内部以 `inviteId` 为锁键，接受流程串行执行：检查状态 → 创建/关联项目 → 创建 Conversation → 更新邀请
- 创建 Conversation 与更新邀请必须在同一个原子步骤内完成；失败则整体回滚，邀请保持 `pending`
- 网络重试若服务端已完成创建，只返回既有 Conversation，不重复创建
- 「项目」与「Conversation」各自最多创建一次；不得出现两个专题指向同一邀请

**UI 规则**：

1. 点击接受后立即 `accepting = true`，按钮禁用并显示处理中；处理中禁止再次点击
2. 成功后卡片状态 `accepted`，跳转 `/chat/{createdConversationId}`
3. 网络失败：恢复按钮可重试，提示「网络异常，请重试」
4. **终态不按网络失败处理**：`declined` / `expired` / `alreadyAccepted` 必须展示对应原因并禁用按钮，不能提示「请重试」
5. 拒绝后停留主对话，卡片状态 `declined`
6. 已接受的邀请卡片不再可操作

### 4.19 ChatController、ChatState 与展示列表

**ChatState 与 Provider 定义**：

```dart
class ChatState {
  // 含集合校验与不可变复制，构造函数不能是 const
  ChatState({
    List<ChatMessage> pending = const <ChatMessage>[],
    Map<String, String> sendErrors = const <String, String>{},
  })  : pending = List<ChatMessage>.unmodifiable(pending),
        sendErrors = Map<String, String>.unmodifiable(sendErrors),
        assert(
          pending.every(
            (m) => m.syncState != SyncState.synced && m.seq < 0,
          ),
          'pending list only accepts pending/queued/failed messages with negative seq',
        ),
        assert(
          pending.map((m) => m.id).toSet().length == pending.length,
          'pending message ids must be unique',
        ),
        assert(
          _isStrictlyDescending(pending.map((m) => m.seq).toList()),
          'pending must be sorted by negative seq descending',
        ),
        assert(
          sendErrors.keys.every(
            (id) => pending.any(
              (m) => m.id == id && m.syncState == SyncState.failed,
            ),
          ),
          'sendErrors keys must reference failed messages',
        ),
        assert(
          sendErrors.values.every((text) => text != ''),
          'sendErrors values must not be empty',
        );

  /// pending / queued / failed 共用；按负数 seq 降序（创建顺序）
  final List<ChatMessage> pending;

  /// clientMessageId -> 失败文案；仅 failed 的 id 存在
  final Map<String, String> sendErrors;

  ChatState copyWith({
    List<ChatMessage>? pending,
    Map<String, String>? sendErrors,
  }) {
    final nextPending = List<ChatMessage>.unmodifiable(pending ?? this.pending);
    final nextSendErrors =
        Map<String, String>.unmodifiable(sendErrors ?? this.sendErrors);
    assert(
      nextPending.every(
        (m) => m.syncState != SyncState.synced && m.seq < 0,
      ),
      'pending list only accepts pending/queued/failed messages with negative seq',
    );
    assert(
      nextPending.map((m) => m.id).toSet().length == nextPending.length,
      'pending message ids must be unique',
    );
    assert(
      _isStrictlyDescending(nextPending.map((m) => m.seq).toList()),
      'pending must be sorted by negative seq descending',
    );
    assert(
      nextSendErrors.keys.every(
        (id) => nextPending.any(
          (m) => m.id == id && m.syncState == SyncState.failed,
        ),
      ),
      'sendErrors keys must reference failed messages',
    );
    assert(
      nextSendErrors.values.every((text) => text != ''),
      'sendErrors values must not be empty',
    );
    return ChatState(pending: nextPending, sendErrors: nextSendErrors);
  }
}

bool _isStrictlyDescending(List<int> values) {
  for (var i = 1; i < values.length; i++) {
    if (values[i] >= values[i - 1]) return false;
  }
  return true;
}

final chatControllerProvider =
    NotifierProvider.family<ChatController, ChatState, String>(
  ChatController.new,
);

final chatViewProvider =
    Provider.family<AsyncValue<ChatView>, String>((ref, conversationId) {
  final channel = ref.watch(conversationChannelProvider(conversationId));
  final chatState = ref.watch(chatControllerProvider(conversationId));
  return channel.whenData((view) {
    final formalIds = view.messages.map((m) => m.id).toSet();
    final pending = chatState.pending
        .where((m) => !formalIds.contains(m.id))
        .toList()
      ..sort((a, b) => b.seq.compareTo(a.seq));
    final pendingIds = pending.map((m) => m.id).toSet();
    final sendErrors = Map<String, String>.fromEntries(
      chatState.sendErrors.entries.where((e) => pendingIds.contains(e.key)),
    );
    return ChatView(
      conversation: view.conversation,
      messages: view.messages,
      pending: pending,
      sendErrors: sendErrors,
      syncState: view.syncState,
      retryCount: view.retryCount,
      syncError: view.syncError,
    );
  });
});
```

**ChatController 实现骨架**：

```dart
import 'dart:async';

// chatControllerProvider 使用非自动释放配置；本类不持有 Timer / StreamSubscription。
class ChatController extends Notifier<ChatState> {
  ChatController(this.conversationId);

  final String conversationId;
  int _nextLocalId = 0;
  int _nextNegativeSeq = 0;
  bool _disposed = false;
  bool _flushing = false;

  @override
  ChatState build() {
    ref.onDispose(() => _disposed = true);
    ref.listen(conversationChannelProvider(conversationId), (_, next) {
      final view = next.value;
      if (view != null) _pruneConfirmed(view.messages);
    });
    ref.listen(networkStatusProvider, (_, next) {
      if (next.value == NetworkStatus.online) {
        unawaited(_flushOutbox());
      }
    });
    return ChatState();
  }

  Future<void> send(String text) async {
    final body = text.trim();
    if (body.isEmpty || _disposed) return;
    final offline =
        ref.read(networkStatusProvider).value == NetworkStatus.offline;
    final repository = ref.read(chatRepositoryProvider);
    final message = TextMessage(
      id: 'local:$conversationId:${++_nextLocalId}',
      conversationId: conversationId,
      sender: ChatSender.user,
      createdAt: ref.read(clockProvider).now(),
      seq: -(++_nextNegativeSeq),
      syncState: offline ? SyncState.queued : SyncState.pending,
      text: body,
    );
    state = state.copyWith(pending: [...state.pending, message]);
    if (!offline) {
      await _deliver(repository, message);
    }
  }

  Future<void> retry(String clientMessageId) async {
    if (_disposed) return;
    final index = state.pending.indexWhere((m) => m.id == clientMessageId);
    if (index < 0) return;
    final current = state.pending[index];
    if (current is! TextMessage || current.syncState != SyncState.failed) return;
    final offline =
        ref.read(networkStatusProvider).value == NetworkStatus.offline;
    final repository = ref.read(chatRepositoryProvider);
    final message =
        current.copyWith(syncState: offline ? SyncState.queued : SyncState.pending);
    final next = [...state.pending]..[index] = message;
    state = state.copyWith(
      pending: next,
      sendErrors: {...state.sendErrors}..remove(clientMessageId),
    );
    if (!offline) {
      await _deliver(repository, message);
    }
  }

  Future<void> retrySync() {
    if (_disposed) return Future<void>.value();
    return ref.read(chatRepositoryProvider).retrySync(conversationId);
  }

  /// 页面重新可见时调用：不等下一条事件，立即按当前 channel 值清理已确认 pending。
  void reconcile() {
    if (_disposed) return;
    final view = ref.read(conversationChannelProvider(conversationId)).value;
    if (view != null) _pruneConfirmed(view.messages);
    if (ref.read(networkStatusProvider).value == NetworkStatus.online) {
      unawaited(_flushOutbox());
    }
  }

  Future<void> _deliver(ChatRepository repository, TextMessage message) async {
    try {
      await repository.sendText(
        conversationId: conversationId,
        clientMessageId: message.id,
        text: message.text,
      );
    } catch (_) {
      if (_disposed) return;
      final index = state.pending.indexWhere((m) => m.id == message.id);
      if (index < 0) return;
      final next = [...state.pending]
        ..[index] = message.copyWith(syncState: SyncState.failed);
      state = state.copyWith(
        pending: next,
        sendErrors: {...state.sendErrors, message.id: '网络异常，请重试'},
      );
    }
  }

  Future<void> _flushOutbox() async {
    if (_flushing || _disposed) return;
    final repository = ref.read(chatRepositoryProvider);
    _flushing = true;
    try {
      while (!_disposed) {
        final index =
            state.pending.indexWhere((m) => m.syncState == SyncState.queued);
        if (index < 0) return;
        final current = state.pending[index];
        if (current is! TextMessage) return;
        final message = current.copyWith(syncState: SyncState.pending);
        final next = [...state.pending]..[index] = message;
        state = state.copyWith(pending: next);
        await _deliver(repository, message);
        if (_disposed) return;
        final failed = state.pending.any(
          (m) => m.id == message.id && m.syncState == SyncState.failed,
        );
        if (failed) return;
      }
    } finally {
      _flushing = false;
    }
  }

  void _pruneConfirmed(List<ChatMessage> formalMessages) {
    final ids = formalMessages.map((m) => m.id).toSet();
    final remaining = state.pending.where((m) => !ids.contains(m.id)).toList();
    if (remaining.length == state.pending.length) return;
    state = state.copyWith(
      pending: remaining,
      sendErrors: {...state.sendErrors}
        ..removeWhere((id, _) => ids.contains(id)),
    );
  }
}
```

**ChatController 生命周期**：

- **创建**：首次读取 `chatControllerProvider(conversationId)` 时创建；`ChatController(conversationId)` 保存 family 参数，`build()` 无参
- **订阅**：`build()` 中通过 `ref.listen(conversationChannelProvider(conversationId))` 建立唯一实时监听；不创建 `StreamSubscription`，不把订阅放进 Widget
- **保持存活**：Provider 必须 keepAlive（或锁定版本等价的非自动释放配置）；页面 pop 不销毁 Controller，pending/queued/failed 保留
- **页面离开**：Riverpod 3 会暂停不可见 Widget 的 listener；Controller 的 keepAlive 监听不受影响，但 U1 不保证 UI 不可见期间实时刷新，也不做后台确认；pending 不会因此丢失
- **返回页面**：ChatPage 在重新可见时调用 `ChatController.reconcile()`，立即按当前 channel 值清理已确认 pending；后续 `ConversationView` 仍会触发同一清理
- **重置**：debug「重置会话」或 App 重启时 `ref.invalidate(chatControllerProvider)`；Controller 释放后其 channel 监听解除，最后一个监听者移除后 Repository 的流订阅关闭
- **错误**：channel 报错时 Controller 不销毁、pending/queued/failed 保留；`ChatView.syncState` 来自 Repository 的 `ConversationView`，UI 显示同步异常横幅与手动重试
- **无 Widget 订阅**：ChatPage 不直接调用 `watchConversation`，也不创建 `StreamBuilder`
- Repository 与 Controller 的依赖方向：Controller → Repository；Repository 不认识 Controller，也不持有 `ChatState`

**Controller / StreamProvider 暂停、恢复与释放规则**：

| 对象 | 创建时机 | 暂停条件 | 恢复动作 | 释放时机 |
|---|---|---|---|---|
| `chatControllerProvider(id)` | 首次 `ref.watch` / `ref.read` | 无可见 listener 时仅暂停 UI 通知，keepAlive 不释放 | 页面可见时 `reconcile()` | `ref.invalidate`、调试重置、App 退出 |
| `conversationChannelProvider(id)` | Controller `build()` 首次 `ref.listen` | 不暂停：Controller 的 keepAlive 监听使其始终有活跃 listener | 页面可见时 `reconcile()`；`retrySync()` 不重建订阅 | Controller 释放或显式 `ref.invalidate` |
| Repository 事件流 | channel provider 首次建立订阅 | 由 channel provider 暂停/恢复 | channel provider 恢复 | channel provider `ref.onDispose` 时取消 |
| `chatViewProvider(id)` | ChatPage `watch` | 页面不可见 | 页面重建时重新计算 | ChatPage 释放监听后由 Riverpod 处理 |

实现约束：

- Repository 的 `watchConversation` 流由 `conversationChannelProvider`（`StreamProvider`）管理订阅；如内部自建 `StreamController` 或额外订阅，必须在 `ref.onDispose` 中关闭/取消，禁止泄漏
- 不得在 Widget 或 Controller 内再建第二条 Repository 订阅；`ref.listen` 监听的是 channel provider，不是 Repository 原始流
- Controller 必须 keepAlive，channel 由 Controller 的监听保持存活；禁止对 Controller 使用 autoDispose
- Controller 的 keepAlive 监听使 channel 不因页面不可见而暂停，但 U1 不保证后台实时刷新 UI；恢复时先 `reconcile()`，若 `syncState = failed` 则展示手动重试，不自动重建整个 Controller
- 重置顺序：`ref.invalidate(chatControllerProvider(id))` → `ref.invalidate(conversationChannelProvider(id))`；先解除 Controller 监听，再关闭 channel 与 Repository 流，避免悬挂监听
- 任何 `ref.read` / `ref.watch` 都不得在 `await` 之后使用同一个已可能释放的 `ref`；异步回调用 `_disposed` 标志或捕获的依赖，见 4.21

**方法契约**：

| 方法 | 行为 |
|---|---|
| `Future<void> send(String text)` | 忽略空白文本；生成 `clientMessageId` 与负数 seq；在线插 `pending` 并发送，离线插 `queued`；异常时转 `failed` |
| `Future<void> retry(String clientMessageId)` | 找到对应 failed；在线转 `pending`、离线转 `queued`；清除 `sendErrors` 项；复用原 id 与原负数 seq |
| `Future<void> retrySync()` | 调用 `ChatRepository.retrySync(conversationId)`；重置 Repository 退避计数，不改动 pending/queued/failed |
| `void reconcile()` | 页面重新可见时调用；按当前 channel 值清理已确认 pending；若在线则顺带触发 queued flush |
| `Future<void> _flushOutbox()` | 网络恢复时按创建顺序串行发送 queued；失败停止并保留后续 queued；`_flushing` 防重入 |
| `void _pruneConfirmed(List<ChatMessage> formal)` | 正式消息中出现同 id 时，从 `pending` 与 `sendErrors` 删除该项 |

**ID 与临时 seq 分配**：

- `clientMessageId`：`local:<conversationId>:<递增整数>`，同一 Controller 内唯一；U1 不引入额外 UUID 依赖
- 负数临时 seq：同一对话从 -1 开始递减，重试不重新分配
- 两者都只存在于本地，不写入事件、快照或 `lastSeq`；确认后由正式消息替代

**ChatView 展示列表（页面唯一渲染来源）**：

| 字段 | 内容 | 排序 |
|---|---|---|
| `messages` | 正式消息 | 正式 `seq` 升序 |
| `pending` | pending / queued / failed | 负数 seq 降序（-1、-2…，即创建顺序） |
| `sendErrors` | 失败文案 | 按 `clientMessageId` 索引 |
| `syncState` / `retryCount` / `syncError` | 重同步状态与错误 | 来自 `ConversationView`，UI 只读 |
| `displayMessages` | `messages` 后接 `pending` | UI 只遍历该列表 |

- `ChatView` 构造断言 pending 与 messages 的 id 集合不相交
- UI 分支：消息 `syncState = queued` 显示「等待联网」；`pending` 显示「发送中」；`failed` 显示 `sendErrors[id]` 与「重试」；`synced` 正常展示
- 同步状态：`ConversationSyncState.retrying` 显示「正在重新同步」；`failed` 显示 `syncError` 与「重试同步」按钮；`synced` 不显示横幅
- Widget 内不做去重、排序或补拉；展示顺序完全由 `ChatView.displayMessages` 决定

**清理时机总表**：

| 时机 | pending / queued / failed | sendErrors |
|---|---|---|
| 发送成功但未收到确认 | 保留 pending | 不变 |
| 正式消息（事件或快照）出现同 id | 删除该条 | 删除该 key |
| `sendText` 抛异常 | 保留并转 `failed` | 写入文案 |
| 离线发送 | 保留并标为 `queued` | 不写入 |
| 网络恢复 | `queued → pending` 后发送 | 不变 |
| 用户重试 | 在线转回 `pending`，离线转 `queued` | 删除该 key |
| 重同步 | 保留 | 保留 |
| `ConversationUpdated` | 保留 | 保留 |
| 切换对话 | 按 `conversationId` 隔离保留 | 保留 |
| App 重启 / 调试重置 | 清空 | 清空 |

**确认超时边界**：

- U1 不实现确认超时定时器：`sendText` 正常返回后若确认事件迟迟不到，消息保持 `pending`，这是已接受的 Mock 阶段边界
- Mock 必须保证每条 `sendText` 在有限时间内要么产生同 id 的确认事件，要么抛出异常转 `failed`，不允许无限挂起
- 接入真实后端时必须补确认超时与重发策略；届时只改 Repository / 同步引擎，不改 UI

**Mock 要求补充**：

- 调试面板提供「发送失败」开关；开启时 `sendText` 抛异常
- 失败后重试成功，确认事件携带相同 `clientMessageId`，最终只有一条正式消息
- 重同步快照已包含该 id 时，不等待事件，直接清理 pending

### 4.21 离线发送与 Controller 销毁保护

**离线发送策略**：

- `networkStatusProvider` 明确为 `offline` 时：仍创建本地消息，但 `syncState = queued`，**不调用** `sendText`，UI 显示「等待联网」
- `queued` 与 pending/failed 共用负数临时 seq，按创建顺序保留在 `ChatState.pending`
- 网络恢复 `online` 时按创建顺序串行 flush：每次把一条 `queued` 改为 `pending` 并调用 `sendText`；成功后继续下一条，不等待确认
- 发送失败：该条转 `failed` 并停止本轮 flush，后续消息仍保持 `queued`；用户重试或下一次网络恢复再继续，保证顺序
- 不允许并发 flush；用 `_flushing` 单飞标志保护
- `pending` 在发送过程中网络断开：不自动退回 `queued`，按失败处理为 `failed`，由用户重试；避免同一条消息被重复发送
- U1 不做离线持久化：App 重启/调试重置后 queued 丢失；这是已接受的产品边界
- `error` 状态不视为离线：仍尝试发送，失败后转 `failed`

**异步期间 Controller 被销毁**：

- `build()` 内注册 `ref.onDispose(() => _disposed = true)`
- 所有异步方法在第一个 `await` 前捕获 `ChatRepository`、`Clock`、`clientMessageId`、文本等依赖，**不得在 `await` 之后调用 `ref`**
- `await` 返回后先检查 `_disposed`；已销毁则直接返回，不写 `state`、不记录错误
- 发送成功但 Controller 已销毁：不再更新本地 pending；重新创建 Controller 后由 channel 快照恢复正式消息，不会产生重复
- 离线排队期间被销毁：queued 随 `ChatState` 释放而丢失，不做补偿
- `_flushOutbox` 在 `finally` 中释放 `_flushing`；销毁时立即停止循环，不再读取 `state`

---

### 6.2 Chat 路由

```
/chat                                → Friday 主对话
/chat/:conversationId                → 指定对话（主或专题）
/chat/:conversationId?messageId=...  → 打开并滚动到指定消息
/chat/topics                         → 专题列表（按项目分组）
```

- `/chat` 与 `/chat/:conversationId` 共用 `ChatPage`，区别只在解析哪个 Conversation
- `/chat` 不依赖全局 Agent，也不做「最后发言者」判断
- `messageId` 不存在时停在最新消息，不报错

### 6.4 对话切换器

Chat 页头部提供入口：

- 主对话：列出全部专题（按项目分组）+「返回主对话」
- 专题：同项目其他专题 + 其他项目折叠区 +「返回主对话」

选择后 `push` 对应路由。

---

## 7. Friday 主对话与 Jarvis 专题对话

### 7.1 定位

| | Friday 主对话 | Jarvis 专题对话 |
|---|---|---|
| 归属 | 永远 Friday | 永远 Jarvis |
| 内容 | 日常聊天、临时任务、提醒、日程 | 长期项目、深入研究、备考 |
| 上下文 | 日常上下文 | 仅本专题；同项目专题共享项目资料，不同项目隔离 |
| 深度 | Jarvis 只发短消息、进度、邀请 | Jarvis 做澄清、计划、深度工作 |
| 输入框 | 发给主对话 | 发给当前专题 |

### 7.2 邀请流程

1. Friday 或 Jarvis 在主对话发起 `AgentInviteCard`
2. 卡片展示：发起者、专题名、目标、范围、预期产出、「接受并进入」「暂时不用」
3. `pending`：不创建专题对话，不改变当前页面归属
4. 接受：仓库创建/关联项目与 `topic` 对话 → 卡片 `accepted` + `createdConversationId` → `push` 到专题
5. 拒绝：卡片 `declined`，不创建对话，停留主对话，不修改项目计划
6. 过期：`expired`，按钮禁用

### 7.3 禁止事项

- 禁止按最近发言者切换 Chat 头部
- 禁止全局 `activeAgent`
- 禁止在邀请 pending 时创建专题
- 禁止不同专题共享消息列表
- 禁止前端拼 Prompt 指定 Agent

---

## 10. 全局紧急提醒

### 10.1 组成与职责

- `PriorityAlert`：提醒数据（原因、截止、操作、状态）
- `AlertResumeContext`：弹窗前的页面恢复信息（路由、对话、消息、滚动、草稿）
- `UrgentAlertController`：Shell 持有 `(alert, resumeContext)`，负责展示与恢复

### 10.2 交互流程

1. 用户正在任意页面（Today、主对话、专题对话）
2. Shell 收到 `PriorityAlert` → 采集 `AlertResumeContext`：
   - `previousRoute`（当前路由）
   - `conversationId`（Chat 页时）
   - `messageId`（深链定位时）
   - `scrollOffset` 与 `draftText`（从 `ChatSessionStore` 读取）
3. 以 App 级 Overlay/Dialog 展示，不改变路由，不关闭对话，不插入消息列表
4. 用户点击操作或关闭：
   - 调 `handleAlert` / `dismissAlert`
   - 处理动作时把实际执行的 `actionId` 写入 `handledActionId`，状态置 `handled`
   - 关闭覆盖层，按 `resumeContext` 恢复页面
   - 恢复滚动位置与草稿
5. 普通提醒不弹窗，只在页面内展示非打断式提示

### 10.3 U1 边界

- 仅 App 内 Mock 弹窗；调试面板提供「模拟紧急提醒」
- 不实现系统通知、后台推送、权限、优先级判定

---

### 12.1 对话与项目

| 项目 | 专题对话 | 说明 |
|---|---|---|
| — | Friday 主对话 | 默认入口 |
| CFA 备考 | 「会计科目难点」 | 目标：三周完成 FRA 会计部分；范围：折旧、摊销、减值 |
| CFA 备考 | 「数量方法刷题」 | 同项目第二专题，验证多专题 |
| 个人知识库 | 「读书笔记整理」 | 不同项目，验证隔离 |

- 主对话包含：Jarvis 简短进度摘要、`ConfirmCard`、`ChoiceCard`、`MemoryConfirmCard`、`PlanProposalCard`、pending `AgentInviteCard`
- 「会计科目难点」包含：`ChoiceCard`、`ThinkingCard`、`PlanProposalCard`
- 其他专题各含少量互不相同的消息

### 12.3 紧急提醒样例（与 Today 时间一致）

「11:30 的客户电话还有 10 分钟」→ 在任意页面（含专题对话）触发弹窗，操作为「知道了 / 改期」；关闭后回到原页面，滚动与草稿不变。

### 12.4 消息衔接演示数据

- 打开「会计科目难点」时，`loadConversationSnapshot` 延迟 300ms
- 延迟期间仓库推送一条新的 `TextMessage` 与一次 `ConversationUpdated`（`seq` 大于快照 `lastSeq`）
- 合并后消息只出现一次，对话信息为最新
- 另提供一条重复 `messageId`、一条旧 `seq`、一条 `seq` 缺口事件，用于去重、过期忽略与重同步演示
- 提供「发送 pending → 触发缺口重同步 → 服务端确认同一 `clientMessageId`」的演示数据
- 提供「发送失败 → failed → 重试 → 确认」的演示数据，确认后 pending 与 sendErrors 同时清理

---
