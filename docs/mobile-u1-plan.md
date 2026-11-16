# Butler Mobile U1 执行计划

> 状态：生效（2026-11-16）。U1 的唯一执行依据，不再新增版本号。
> 历史技术报告已归档：`docs/archive/mobile-u1-technical-plan-v2.4.4.md`（冻结，仅参考）。
> 会话同步、多会话与 Jarvis 专题、邀请卡、PriorityAlert：`docs/deferred/mobile-sync-and-topics.md`（延后，待后端接口确定）。

## 一、U1 范围

做：

- Flutter 工程、设计令牌、浅色/深色主题
- 4 Tab 导航外壳与路由
- 今日页：时间线、简报、完成/跳过/调整、未排期
- 对话页：Friday 主对话、7 类消息卡片、流式回复、输入条
- 调试面板：模拟时间、网络、数据集、主题、文字缩放
- 假数据仓库：简单 Stream + 模拟延迟
- 单元测试、组件测试、对比度测试、截图

只 Mock：消息发送与流式、网络与同步状态、Today 数据与简报、Jarvis 引荐。

不做：真实 Agent/模型、数据库、系统通知、任务页/我的页内容、多会话、专题对话、邀请幂等、同步协议、PriorityAlert、iOS/HarmonyOS 原生、后端改动。

## 二、分层

```
mobile/lib/
  core/       主题、令牌、文案、Clock、格式化
  domain/     模型与仓库抽象（无 Flutter 依赖）
  data/mock/  假数据实现，仅被 provider 装配层引用
  features/   today、chat、tasks、profile、debug
  shell/      路由、4 Tab 外壳
```

依赖方向：`features → domain ← data/mock`；features 不直接 import data/mock。

约定：

- 所有时间走 `clockProvider`，禁止 `DateTime.now()`（`SystemClock` 除外）
- 文案集中在 `core/strings.dart`
- 领域模型不变量用构造/copyWith 的 assert；终态转换用 `StateTransitionException`
- 集合字段一律 `List.unmodifiable` / `Map.unmodifiable`
- `copyWith` 可空字段用 `unset` 哨兵：不传保持、显式 null 清空
- 不新增状态管理、网络、代码生成库

## 三、领域模型（U1 精简版）

### 3.1 枚举

- `ChatSender { user, friday, jarvis }`
- `SyncState { synced, pending, queued, failed }`
- `NetworkStatus { online, offline, syncing, error }`
- `TodayItemKind { block, reminder, task }`
- `TodayItemStatus { planned, inProgress, done, skipped }`（overdue 由 `isOverdueAt` 派生）
- `BriefKind { morning, evening }`
- `ConfirmCardState { pending, confirmed, revoked }`
- `PlanDecision { accept, adjust, veto }`
- `PlanProposalState { pending, accepted, adjusted, vetoed }`
- `PlanChangeType { add, remove, move }`
- `MemoryCandidateState { pending, confirmed, rejected }`
- `ThinkingPhase { thinking, organizing, drafting, executing }`
- `JarvisIntroState { open, accepted, declined }`

### 3.2 ChatMessage（sealed）

字段：`id`、`sender`、`createdAt`、`reason`（可空）、`syncState`。

- 无 `seq`、无 `conversationId`；U1 只有一条 Friday 主对话
- 排序：`createdAt` 升序，相同则按 `id` 字典序（稳定）
- 七种类型：

| 类型 | 关键字段 |
|---|---|
| TextMessage | text、streaming |
| ConfirmCard | title、body、primaryLabel、secondaryLabel、state、actedAt |
| ChoiceCard | question、options（2–4）、answer |
| MemoryConfirmCard | items（MemoryCandidateItem 列表） |
| PlanProposalCard | summary、changes、rationale、state |
| JarvisIntroCard | summary、previewQuestions（最多 3）、state |
| ThinkingCard | phase |

JarvisIntroCard：

- 不创建会话；`state = open` 时展示「请 Jarvis 规划」「暂时不用」
- 点「请 Jarvis 规划」→ `state = accepted`，同一消息流依次追加：诊断 `ChoiceCard` → `ThinkingCard` → `PlanProposalCard`
- 点「暂时不用」→ `state = declined`
- 接受/拒绝都通过 `respondToCard(messageId, ConfirmAction(confirmed: true/false))`，仓库按 messageId 识别卡片类型
- 终态不可回到 `open`，`copyWith` 抛 `StateTransitionException`

### 3.3 Today

- `TodayItem`：id、kind、title、status、compressible、syncState、start、end、durationMin、sourceTag、reason
  - block：start/end 必填、end > start、durationMin > 0，start 不可清空
  - reminder：start 必填，end/durationMin 为空
  - task：start 可空；只有 task 可通过 `copyWith(start: null)` 移出时间线
  - overdue 派生：block 看 end、reminder 看 start+10min、task 看 start；done/skipped 永不逾期
- `Brief`：kind、text、reasonLine、mergedSuggestions
- `DayView`：date（本地零点）、items（有 start、按 start 升序）、unscheduled（无 start 的 planned task）、morningBrief、eveningBrief

### 3.4 CardAction

`ConfirmAction`、`ChoiceAction`、`MemoryAction`、`ConfirmAllMemoryAction`、`PlanProposalAction`。JarvisIntroCard 复用 `ConfirmAction`，由仓库按 messageId 识别。

## 四、仓库接口

```dart
abstract interface class ChatRepository {
  Stream<List<ChatMessage>> watchMessages();
  Future<void> sendText(String text);
  Future<void> respondToCard({
    required String messageId,
    required CardAction action,
  });
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
```

流式回复：不提供单独接口。`sendText` 后，仓库向 `watchMessages()` 同一流发射一条 `TextMessage(streaming: true)`，文字随每次发射逐步增长，完成后置 `streaming: false`。UI 只监听一个流。

## 五、Mock 语义

- `data/mock/` 内部用 `StreamController.broadcast` 持有消息列表；每次变更发射完整列表
- 模拟延迟：发送后 300–800ms 出现用户消息确认；回复流每 60–120ms 追加一段文字
- 数据集：正常、空、加载失败、离线、同步中五种，由调试面板切换
- 离线：`sendText` 不产生回复，消息保持 `SyncState.queued`；恢复在线后转 `pending` 再转 `synced`
- 失败：可注入一次发送失败，消息转 `failed`，页面提供重试
- 所有延迟用可注入的 `Clock`/`Random` 种子，测试可确定性推进

## 六、页面规格

### 6.1 导航外壳

- `StatefulShellRoute.indexedStack`：`/today`、`/chat`、`/tasks`、`/profile`
- 任务/我的为「下一阶段」占位
- Tab 切换保留各分支状态

### 6.2 今日页

1. 头部：日期星期、按时段问候、进度胶囊、前一天/后一天
2. 晨间简报卡：可折叠；正文、理由、「调整」
3. 时间线：按 start 升序；时间标签 + 卡片 + 44dp 完成按钮
4. 未排期区：无 start 的 planned task，可「排进今天」
5. 晚间复盘入口
6. 状态覆盖：加载、空、错误（可重试）、离线、同步中、待同步

### 6.3 对话页

1. 头部：Friday · 日常助理 · 随时待命
2. 消息列表：7 类卡片按 `createdAt + id` 排序
3. 流式：同一条 TextMessage 原地增长，不新增气泡
4. ThinkingCard：阶段文案 + 动画，无预计时间/倒计时
5. 输入条：文本输入、发送、草稿保留
6. 状态覆盖：加载、空、错误、离线（等待联网）、同步中、待同步（pending/queued/failed + 重试）

### 6.4 调试面板

debug 构建下长按今日页标题进入：模拟时间、网络状态、数据集、主题、文字缩放、发送失败开关。

### 6.5 主题

浅色/深色令牌已在 `core/theme`；7 组对比度断言保持通过。

## 七、测试与命令

- `mobile/test/`（单数）
- 单元：模型不变量、copyWith 哨兵、状态转换、Today 派生 overdue
- 组件：外壳、今日页、对话页、调试面板
- 对比度：7 组 WCAG 4.5:1
- 缩放：1.5 倍文字不溢出

```powershell
Set-Location "E:\F&J\FJ v1\mobile"
$env:FLUTTER_ROOT="D:\flutter"
$DART="D:\flutter\bin\cache\dart-sdk\bin\dart.exe"
$FLUTTER="D:\flutter\packages\flutter_tools\bin\flutter_tools.dart"
& $DART $FLUTTER --no-version-check analyze
& $DART format --output=none --set-exit-if-changed lib test
& $DART $FLUTTER --no-version-check test
& $DART $FLUTTER --no-version-check build apk --debug
```

`build apk` 不得与后端夜间评测同时运行。

## 八、剩余批次

| 批次 | 内容 | 结束验证 |
|---|---|---|
| 4 | 文档归档、延后章节、领域层收缩、测试修复 | analyze / format / test |
| 5 | Mock 仓库 + Provider 装配 + README 卡片对应表 | 仓库与 Provider 单测 |
| 6 | 导航外壳 `lib/shell`、4 Tab、go_router、主题接入 | `shell_test` |
| 7 | 今日页全部交互 + 状态覆盖 | 组件与缩放测试 |
| 8 | 对话页 + 7 类卡片 + 流式 + 状态覆盖 | `chat_page_test` |
| 9 | 调试面板 | 开关生效 |
| 10 | 组件测试补全、截图、全量验收 | 全部命令通过；截图归档 |

每批结束汇报：改动清单、截图（UI 批次）、analyze 与测试结果、与规格的出入。

## 九、验收

1. 4 Tab 可切换，返回保留状态
2. 今日页完成/跳过/调整生效，空/错误/离线/同步中状态可见
3. 对话页发送后出现 pending，流式回复原地增长，结束后转 synced
4. 7 类卡片均可渲染；JarvisIntroCard 点击后依次出现诊断卡、ThinkingCard、PlanProposalCard
5. 离线发送显示「等待联网」，恢复在线后转 synced
6. 7 组对比度通过；1.5 倍文字不溢出
7. analyze、format、test、build apk 全部通过
8. 截图使用虚构数据，存放在 `mobile/screenshots/`

## 十、README 卡片对应表（批次 5 补充）

`mobile/README.md` 增加出站意图与卡片类型对应：

| 意图 | 卡片类型 |
|---|---|
| text | TextMessage |
| confirm_card | ConfirmCard |
| choice | ChoiceCard |
| nudge | TextMessage（带 reason） |
| schedule_view | 今日页时间线 |
| plan_proposal | PlanProposalCard |
| memory_confirm | MemoryConfirmCard |
