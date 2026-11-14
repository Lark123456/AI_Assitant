# Mobile（Flutter）项目规则

## 技术栈（锁定，不得擅自升级）

- Flutter 3.47.2 / Dart 3.13.2
- flutter_riverpod 3.5.0、go_router 18.1.4、intl 0.20.3、flutter_lints 6.0.0
- `pubspec.yaml` 使用精确版本，不使用 `^`；提交 `pubspec.lock`

## 分层

- `features → domain ← data/mock`；features 不得直接 import data/mock
- `domain/` 不依赖 Flutter；`data/mock/` 只被 provider 装配层引用
- 页面只消费 Provider，不直接访问 Repository 原始流

## 状态

- `chatViewProvider` 是 Chat 页面唯一展示来源；UI 只渲染 `ChatView.displayMessages`
- pending / queued / failed 与 sendErrors 只由 `ChatController` 持有
- 同步规则（seq、快照基线、摘要、重同步、generation、事件队列）只在 `ConversationSyncEngine`
- 所有时间通过 `clockProvider`；禁止 `DateTime.now()`（`SystemClock` 除外）
- 文案集中在 `core/strings.dart`

## 约定

- 领域模型不变量用构造 / copyWith 的 assert；终态转换用 `StateTransitionException` 运行时检查
- 集合字段一律复制为不可变视图
- 不新增状态管理、网络、代码生成库；需要时先说明理由并等待确认

## 测试与检查

- 测试目录 `mobile/test/`（单数）；后端 `tests/` 不受影响
- 每批结束运行：`analyze`、`dart format --output=none --set-exit-if-changed lib test`、`flutter test`、`build apk --debug`
