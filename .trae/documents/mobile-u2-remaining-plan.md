# Mobile U2 剩余功能实施计划（任务页 / 我的页 / 应用内提醒 / SSE 真流式）

## Context

Mobile U1 与 U2-A 已完成：Today、Chat 已接真实后端，任务页与我的页仍是占位页；后端没有移动推送基础设施；LLM provider 内部已用 SSE 但只返回最终结果。用户已确认四项范围：

- 任务页：列表 + 完成/跳过/撤销/排期，复用 Today 写接口，不做创建/编辑。
- 我的页：只读资料与状态。
- 系统通知：仅 App 前台应用内提醒，不引入通知插件、不做 OS 通知或远程推送。
- 真实流式：服务端 SSE，逐 token 渲染，失败回退到现有轮询。

不新增 Flutter 依赖；SSE 与进程内 broker 沿用“单进程 API”约束。

## 批次 1：任务页

### 后端

- 新增 `app/api/routes/mobile_tasks.py`，复用 `mobile.py` 的 `get_mobile_user`、`get_session`：
  - `GET /api/mobile/tasks?status=open|done|all&limit=100`（limit 1–100，默认 50）。
  - `open` → `work_item.status='active'`；`done` → `'done'`；`all` → `active/done/dropped`；任务状态映射沿用 Today：`dropped→skipped`。
  - 先查 `WorkItem(type='item', user_id)`，再按 `work_item_id IN (...)` 一次查 `PlannedBlock`（`status='planned'` 且 `ends_at >= now`），按任务取最早块作为 `upcomingBlock`，避免 N+1。
  - 响应：`{id,title,description,status,createdAt,updatedAt,upcomingBlock}`；按 `updated_at DESC, id DESC` 排序。
- 写操作全部复用现有 Today 端点，不新增任务写接口：
  - `POST /api/mobile/today/items/{id}/complete|skip|restore`
  - `POST /api/mobile/today/tasks/{id}/schedule`
- 在 `app/main.py` 的 `enable_mobile_api` 分支挂载。
- 测试 `tests/integration/test_mobile_tasks.py`：401/403、状态过滤、排序、计划块关联、用户隔离、limit 边界。

### Flutter

- 新增 `domain/models/task.dart`、`domain/repositories/task_repository.dart`（load/complete/skip/restore/scheduleToday）。
- 新增 `data/remote/remote_task_repository.dart`（复用 `ApiClient`，写操作生成 `Idempotency-Key`）、`data/mock/mock_task_repository.dart`（种子任务 + 内存状态变更）。
- 把 `today_page.dart` 的 `nextScheduleStart` 抽到 `core/schedule_time.dart`，Today 与任务页共用；任务页排期只提供“排进今天”（默认 18:00 / 5 分钟取整 / 23:00 上限）。
- 新增 `features/tasks/task_controller.dart`、`tasks_page.dart`：过滤（未完成/已完成/全部）、下拉刷新、完成/跳过/撤销、排进今天、操作失败 SnackBar。
- `core/providers.dart` 增加 `taskRepositoryProvider`；`shell/app_router.dart` 替换占位页。
- 测试：`remote_task_repository_test.dart`、`tasks_page_test.dart`、`app_providers_test.dart` 增任务 Provider 断言。

## 批次 2：我的页

### 后端

- 新增 `app/api/routes/mobile_profile.py`：`GET /api/mobile/profile` 返回 `{displayName, timezone, dayStart("HH:MM"), createdAt}`；只读。
- 挂载到 `enable_mobile_api` 分支；测试 `tests/integration/test_mobile_profile.py`（401/403、字段与时区格式、用户隔离）。

### Flutter

- 新增 `domain/models/profile.dart`、`domain/repositories/profile_repository.dart`、`data/remote/remote_profile_repository.dart`、`data/mock/mock_profile_repository.dart`。
- 新增 `features/profile/profile_controller.dart`、`profile_page.dart`：账号资料、时区、day_start、数据源（Mock/Remote 与 base URL）、版本号、“调试面板”入口（仅 `kDebugMode`）。
- 版本号放 `core/app_info.dart`：`const appVersion = String.fromEnvironment('APP_VERSION', defaultValue: '0.1.0+1')`，不引入 `package_info_plus`；与 pubspec 手工同步。
- `providers.dart` 增加 `profileRepositoryProvider`；路由替换占位。
- 说明：Today 当前按本地零点切日，`day_start` 仅作资料展示，不暗示生效切日。
- 测试：profile repository、页面渲染、数据源/版本/调试入口、Provider 切换。

## 批次 3：应用内提醒

### 后端

- 新增 `app/api/routes/mobile_reminders.py`：`GET /api/mobile/reminders/due?graceMinutes=30&limit=20`。
  - 条件：本用户、`kind='reminder'`、`fire_at <= now`、`fire_at >= now - graceMinutes`、`expires_at` 为空或 `> now`、`status IN ('pending','claimed','fired')`。
  - 返回 `{id,note,fireAt,expiresAt,status}`，按 `fire_at ASC`；`note` 取 payload。
  - 不改 worker：手机用户复用飞书/Console 身份，提醒已在对应渠道投递；纯无渠道用户不在 U2 范围。
- 测试 `tests/integration/test_mobile_reminders.py`：时间窗、状态过滤、过期排除、用户隔离、limit 与参数校验。

### Flutter

- 新增 `domain/repositories/reminder_repository.dart` + `data/remote/remote_reminder_repository.dart` + `data/mock/mock_reminder_repository.dart`（Mock 为空或固定种子）。
- 新增 `features/reminders/reminder_controller.dart`：App 前台每 30 秒轮询；进程内 `Set<triggerId>` 去重；`resumed` 立即刷新，非前台停止。
- `shell/shell_scaffold.dart` 改为 `ConsumerStatefulWidget + WidgetsBindingObserver`，在 `navigationShell` 上方渲染提醒横幅；“知道了”仅本地隐藏，不写后端 ack。
- 测试：仓库解析、去重、前后台暂停/恢复、横幅显示与关闭。

## 批次 4：SSE 真流式

### 后端

- 新增 `app/engine/streaming.py` 进程内 `StreamBroker`：
  - 按入站 event id 保存累计文本、终态、订阅队列、reply/outbound id、`updated_at`；TTL 600 秒与事件数/字符上限，惰性清理。
  - 晚订阅先推快照再推增量；`finish` 推最终文本与 outbound id；`fail` 推错误。
- 流式链路：
  - `BaseProvider.complete(..., on_delta=None)`；`OpenAICompatProvider._stream_once` 对每个 content delta 回调“本次调用的累计文本”；`LLMGateway.chat`、`FridayAgent.handle` 透传。
  - `InboundPipeline` 可选注入 broker；手机分支把回调接到 broker，`_append_mobile_reply` 返回 outbound event id，commit 后 `broker.finish`；兜底回复同样 finish；外层崩溃 `broker.fail`。
  - 工具调用场景：每步累计文本覆盖上一步；`done` 携带最终持久化回复，客户端以 done 覆盖，保证 UI 与库内一致。
- 新增 SSE 端点 `GET /api/mobile/chat/messages/{id}/stream`（`mobile_chat.py`）：
  - 校验归属/渠道（用短生命周期 session，不长期占用连接）；事件 `delta{text累计}`、`done{messageId,text,replyToId,createdAt}`、`error{code}`、心跳注释。
  - 已处理完成或晚订阅：broker 有终态直接推；broker 无状态但已 done/failed 时查 outbound 兜底；processing 且无 broker 状态返回 `stream_unavailable`，客户端回退轮询。
  - 断开仅退订；单进程约束与内存上限写入 docstring/契约。
- `app/main.py` 创建 broker，注入 pipeline 与 `app.state`。
- 测试 `tests/integration/test_mobile_chat_stream.py`：delta→done 顺序、晚订阅快照、工具前导文本被最终回复覆盖、无 broker 回退、归属 404、断开清理、非手机渠道拒绝。

### Flutter

- `api_client.dart` 新增独立 `SseClient` 接口（不改 `ApiClient`，避免破坏现有 Fake）；`HttpApiClient` 实现，用 `dart:io` 流式响应 + `LineSplitter` 解析 `event/data`。
- `RemoteChatRepository`：若 client 实现 `SseClient`，POST 成功拿到入站 id 后开流，插入 `stream-<inboundId>` 的 Friday 流式气泡；delta 覆盖文本；done 落为正式消息（serverId=replyId、replyToId=入站 id）并清除流式气泡。
- 轮询到的 outbound 与流式气泡按 `replyToId/serverId` 去重；`setActive(false)`/dispose 取消流；SSE 失败静默回退轮询，不新增错误横幅。
- 测试：SSE 事件解析、增量覆盖、done 落库、与轮询去重、取消、失败回退；现有 Mock 流式保持。

## 跨批次约定

- 每批结束运行：后端 `ruff`、`mypy app`、相关 `pytest`；移动端 `analyze`、`dart format --output=none --set-exit-if-changed lib test`、`flutter test`、`build apk --debug`。
- 后端与移动端改动分开提交；每批汇报结果与未做项。
- 文档：每批同步 `docs/feature-status-matrix.md`、`mobile/README.md`；批次 4 同步 `docs/contracts.md`（SSE、MobileAdapter streaming 能力、提醒 API）。
- 不新增表/迁移；单进程 API 约束与开发期认证边界保持。

## 验证

- 后端：各批新增集成测试 + 最终全量 pytest；SSE 用 ASGITransport 流式断言。
- 移动端：仓库/页面/Provider 测试 + 现有 122 项回归；APK 构建。
- 手工：`ENABLE_MOBILE_API=1` + `adb reverse`，验证任务列表与状态操作、我的页资料、前台提醒横幅、SSE 逐 token 渲染与断线回退。

## 风险与明确未做

- SSE broker 与用户串行锁均在进程内：多 worker/副本会退化为轮询，需后续跨进程机制。
- 工具调用时的前导文本会在 done 时被最终回复覆盖，这是刻意取舍。
- 不实现 OS 通知、后台推送、通知权限、APNs/FCM。
- 不实现任务创建/编辑、记忆中心、多会话/同步协议。
- 版本号为常量维护，可能与 pubspec 漂移。
