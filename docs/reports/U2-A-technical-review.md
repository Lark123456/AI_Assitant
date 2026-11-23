# 阶段 U2-A 技术审查报告：手机端 Friday Chat 接入现有后端

> 审查性质：技术审查与实施准备，不是编码阶段。  
> 审查对象：已确认的《阶段 U2-A 技术实施方案 v1.0》（以本次任务描述中的要求为准）  
> 审查方式：以当前仓库代码为准，逐条追踪真实调用关系；不根据旧文档推断实现。  
> 本次只新增本报告，未修改业务代码、测试代码或配置。

---

## 第一部分：审查基线

### 1.1 代码版本

| 项目 | 值 |
|---|---|
| 分支 | `master` |
| 最新 commit | `faf87fd60fd727308d75ea508f4548e134ea097d` |
| 提交时间 | 2026-11-20 16:59:19 +0800 |
| 提交说明 | `阶段 U2：完善远程刷新失败处理` |
| 工作区 | 干净（`git status --short` 无输出） |
| 审查基准 | 上述 commit 的完整工作树 |

本次所有结论均基于 `faf87fd`。如果后续代码变化，需要重新核对本报告中的行号与调用关系。

### 1.2 实际审查的文件范围

后端：

- `app/main.py`
- `app/engine/pipeline.py`
- `app/agents/friday/agent.py`
- `app/agents/friday/history.py`
- `app/agents/friday/prompts.py`
- `app/adapters/base.py`
- `app/adapters/feishu_adapter.py`
- `app/adapters/console_adapter.py`
- `app/adapters/identity.py`
- `app/engine/events.py`
- `app/engine/users.py`
- `app/engine/nudge.py`（仅核对 delivery 事件的 channel）
- `app/api/routes/mobile.py`
- `app/api/routes/console.py`
- `app/db/models/event_log.py`
- `app/db/models/inbound_processing.py`
- `app/db/models/user.py`
- `app/db/models/trigger.py`
- `app/db/models/work_item.py`
- `app/db/migrations/versions/0001_init.py`
- `app/db/migrations/versions/0003_inbound_processing.py`
- `app/tools/base.py`
- `app/tools/registry.py`
- `app/tools/tasks.py`
- `app/tools/reminders.py`
- `app/tools/blocks.py`
- `app/tools/notes.py`
- `app/memory/runs.py`（仅核对抽取查询的 channel 条件）
- `app/worker/runner.py`（渠道解析与主动消息边界）
- 相关测试：`test_pipeline_features.py`、`test_idempotency.py`、`test_worker_recovery.py`、`test_console_e2e.py`、`test_followup_parse.py`、`test_full_day_replay.py`、`test_friday_memory_injection.py`、`test_mobile_today.py`、`test_mobile_today_write.py`、`test_tool_savepoint.py`

Flutter：

- `mobile/lib/domain/models/chat_message.dart`
- `mobile/lib/domain/repositories/chat_repository.dart`
- `mobile/lib/data/mock/mock_chat_repository.dart`
- `mobile/lib/data/remote/api_client.dart`
- `mobile/lib/data/remote/remote_today_repository.dart`
- `mobile/lib/core/providers.dart`
- `mobile/lib/core/remote_config.dart`
- `mobile/lib/features/chat/chat_controller.dart`
- `mobile/lib/features/chat/chat_page.dart`
- `mobile/lib/shell/shell_scaffold.dart`
- `mobile/lib/shell/app_router.dart`
- `mobile/test/chat_page_test.dart`
- `mobile/test/mock_chat_repository_test.dart`
- `mobile/test/local_message_test.dart`
- `mobile/test/app_providers_test.dart`
- `mobile/pubspec.yaml`

文档与规则：

- `docs/contracts.md`
- `docs/mobile-u1-plan.md`
- `docs/deferred/mobile-sync-and-topics.md`
- `docs/feature-status-matrix.md`
- `.trae/rules/mobile.md`、`.trae/rules/project_rules.md`（仅对照，不作为代码事实）

### 1.3 实际执行的只读检查

| 检查 | 命令 | 结果 |
|---|---|---|
| 工作区 | `git status --short` | 干净 |
| 后端 ruff | `uv run ruff check app tests scripts`（WSL） | `All checks passed!` |
| 后端 mypy | `uv run mypy app`（WSL） | `Success: no issues found in 92 source files` |
| 移动端 analyze | `dart flutter_tools.dart --no-version-check analyze` | `No issues found!` |
| 移动端测试 | `dart flutter_tools.dart --no-version-check test` | `111 passed`，3 项截图测试默认跳过 |
| 后端全量 pytest | `uv run pytest -q`（WSL） | 本次运行在 29% 后长时间无进展，手动停止；随后相关 40 项集成测试通过（见 1.5） |

说明：移动端第一次以后台方式同时执行 analyze 与 test 时，Flutter SDK 的 `D:\flutter\bin\cache\lockfile` 出现权限/占用错误；随后在前台单独重跑 analyze 与 test 成功。这是执行环境问题，不是代码失败。

### 1.4 现有测试覆盖与缺口

| 领域 | 已有测试 | 缺口（U2-A 需要新增） |
|---|---|---|
| Pipeline 入站/落库/白名单 | `test_pipeline_features.py`：白名单、首答时区、set_timezone、LLM 限额、兜底回复、inbound_processing 状态与启动恢复、process 崩溃置 failed | 手机 `ingest_for_user`、MobileAdapter、无 ChannelIdentity 断言 |
| 幂等 | `test_idempotency.py`：event_log 幂等、append-only、用户 onboarding、工具同事件/同序号重放、任务/提醒幂等 | 手机 client_message_id、同用户并发重试、outbound 幂等 |
| Console/工具 E2E | `test_console_e2e.py`：建任务+提醒+worker 投递、重复事件不重复建任务；`test_followup_parse.py`：历史指代；`test_full_day_replay.py`：整日触发/简报 | 手机渠道工具 E2E、手机/飞书业务数据互查、手机上下文隔离 |
| 恢复/租约 | `test_worker_recovery.py`：trigger 停机补偿/租约；`test_pipeline_features.py`：入站恢复 | 手机 Agent 重跑时的重复工具/回复测试 |
| Today Mobile API | `test_mobile_today.py`、`test_mobile_today_write.py`：认证/白名单/日期/读写/幂等/改期/提醒/复盘 | 现有测试不能覆盖 chat API |
| Flutter Chat | `chat_page_test.dart`、`mock_chat_repository_test.dart`、`local_message_test.dart`：Mock 种子、发送/流式、离线、卡片、缩放、错误页 | RemoteChatRepository、轮询、历史恢复、发送失败重试、clientMessageId、前后台 |
| Flutter Today | `today_page_test.dart`、`remote_today_repository_test.dart`：真实读/写、刷新错误 | 不涉及 U2-A |

### 1.5 测试结果记录

后端全量 pytest 在审查期间启动，命令为：

```bash
wsl -d Ubuntu --cd "/mnt/e/F&J/FJ v1" -- bash -lc "uv run pytest -q"
```

该次运行在输出 `[ 29%]` 后长时间没有进展（WSL/数据库环境），为避免继续占用资源手动停止；**不把该次运行记为通过**。

随后执行与 U2-A 直接相关的集成测试：

```bash
wsl -d Ubuntu --cd "/mnt/e/F&J/FJ v1" -- bash -lc "uv run pytest -q \
  tests/integration/test_pipeline_features.py \
  tests/integration/test_idempotency.py \
  tests/integration/test_mobile_today.py \
  tests/integration/test_mobile_today_write.py \
  tests/integration/test_followup_parse.py \
  tests/integration/test_console_e2e.py"
```

实际结果：**40 passed**（2 分 56 秒）。

补充：在当前 HEAD 之前一次同生产代码（无 U2-A 代码改动）的全量运行为 **244 passed, 1 skipped**；之后只新增了一个集成测试并修改了一行注释，生产逻辑未变。该历史结果不作为本次全量通过证明，仅作为背景参考。

---

## 第二部分：现有系统架构

### 2.1 一句话结论

现有后端已经具备“渠道入站 → 落库 → Friday Agent → 工具调用 → 回复 → 出站事件”的完整链路；手机端目前只有 Today 页面接入了真实后端，Chat 仍然是纯 Mock。U2-A 不需要重写 Friday Agent 或业务工具，但需要新增一个手机消息入口、一个手机 ChannelAdapter、一个 Chat API 和 Flutter 的 RemoteChatRepository；同时必须补上聊天历史的渠道隔离和回复关联。

### 2.2 手机消息进入后端（目标链路）

U2-A 完成后的目标调用链应为：

```text
Flutter ChatPage
  → ChatController.sendText
  → RemoteChatRepository.sendText
  → POST /api/mobile/chat/messages
  → get_mobile_user（X-Butler-User + ENABLE_MOBILE_API + ALLOWED_OPEN_IDS）
  → InboundPipeline.ingest_for_user(event, user)
  → event_log(direction=inbound, channel=mobile, type=message)
  → inbound_processing(status=processing)
  → spawn(InboundPipeline.process)
  → FridayAgent.handle(channel=mobile, source_event_id=入站事件 id)
  → build_history(user_id, channel=mobile)
  → 工具调用（任务/提醒/日程/笔记）
  → 回复写入 event_log(direction=outbound, channel=mobile, type=message)
  → inbound_processing(status=done)
  → Flutter 轮询 GET /api/mobile/chat/messages
  → ChatPage 渲染用户消息与 Friday 回复
```

### 2.3 当前实际链路（代码事实）

#### 2.3.1 飞书入口

- `app/adapters/feishu_adapter.py:65-103`：`FeishuAdapter.start` 启动长连接，SDK 回调把消息转成 `InboundEvent`。
- `app/feishu_main.py:42-48`：`_dispatch` 调用 `pipeline.ingest(event)`，只有 `ingested.created` 为真时才 `spawn(pipeline.process(ingested))`。
- `app/feishu_main.py:51-55`：feishu 服务启动时调用 `pipeline.recover_unfinished()`，然后启动长连接。

#### 2.3.2 Console 入口

- `app/api/routes/console.py:19-40`：`POST /console/messages` 构造 `InboundEvent(channel="console")`，调用 `pipeline.ingest`，新事件才 `spawn(pipeline.process)`，立即返回 202。

#### 2.3.3 入站落库与用户识别

- `app/engine/pipeline.py:70-129` `InboundPipeline.ingest`：
  - 先执行 `ALLOWED_OPEN_IDS` 白名单（`pipeline.py:72-77`）。
  - 调用 `get_or_create_user(channel=event.channel, external_id=event.external_user_id, ...)`（`pipeline.py:80-88`）。
  - 用 `append_event` 写入 `event_log`，`direction="inbound"`、`type=event.kind`（`pipeline.py:89-105`）。
  - 如果是新事件，同事务写入 `InboundProcessing(status="processing")`（`pipeline.py:106-115`）。
  - 返回 `IngestedEvent(event, event_id, user_id, trace_id, is_new_user, created)`（`pipeline.py:122-129`）。
- `app/engine/users.py:16-63` `get_or_create_user` 按 `(channel, external_id)` 查 `channel_identity`；不存在则创建 `User` + `ChannelIdentity`。
- `app/db/models/user.py:35-49`：`ChannelIdentity` 的 CHECK 约束只允许 `feishu` 和 `console`（`user.py:39`），迁移 `0001_init.py:49` 同样只有这两个值。

#### 2.3.4 处理与 Friday Agent

- `app/engine/pipeline.py:131-213` `process` / `_process_one`：
  - `process` 捕获未处理异常，置 `inbound_processing.status="failed"`（`pipeline.py:135-139`）。
  - `_process_one` 通过 `self._adapters[ingested.event.channel]` 取 adapter（`pipeline.py:143`）。
  - 读取 `User`，先 commit 释放连接（`pipeline.py:146-151`）。
  - 调用 `self._friday.handle(session=..., clock=..., settings=..., user=..., trace_id=..., channel=ingested.event.channel, source_event_id=ingested.event_id, text=..., embedder=...)`（`pipeline.py:153-163`）。
  - agent 失败时 rollback，使用 `FALLBACK_REPLY`（`pipeline.py:164-168`）。
  - agent + 工具写入 commit（`pipeline.py:169`）。
  - 新用户首答追加时区说明（`pipeline.py:171-176`）。
  - 调用 `adapter.send(OutboundIntent(type="text", user_id=..., body={"text": reply}, reply_to_event_id=ingested.event_id))`（`pipeline.py:181-190`）。
  - 另开事务写 `event_log(direction="outbound", type="message")` 和 `inbound_processing(status="done")`（`pipeline.py:196-213`）。

#### 2.3.5 Friday Agent 与短期历史

- `app/agents/friday/agent.py:43-149` `FridayAgent.handle`：
  - 构造 `ToolContext`（`agent.py:57-66`）。
  - 调用 `build_history(session, user_id=user.id, exclude_event_id=source_event_id, clock=clock)`（`agent.py:69-74`）。
  - 构造检索查询（`agent.py:75`），长期记忆注入仅在 `settings.memory_inject_enabled` 时执行（`agent.py:78-95`）。
  - 写 `memory_context` 审计并 commit（`agent.py:98-113`）。
  - 组装 system + history + 当前 user 消息（`agent.py:115-122`）。
  - 最多 4 步 tool-use 循环（`agent.py:125-149`），工具通过 `execute_tool` 执行。
- `app/agents/friday/history.py:36-96` `build_history`：
  - 条件只有 `EventLog.user_id == user_id`、时间窗口、`direction/type` 过滤（`history.py:45-53`）。
  - **没有 `EventLog.channel == channel`**。
  - 最近 12 条或 24 小时、总长度 4000 字符（`history.py:17-19`、`87-96`）。

#### 2.3.6 工具与业务数据

- `app/tools/registry.py:29-47` 注册 14 个工具；`app/tools/registry.py:62-93` 执行工具，写工具的幂等键为 `inbound_event_id:tool_name:call_index`（`registry.py:50-54`、`79-93`）。
- `app/tools/base.py:24-48` `ToolContext` 携带 `user`、`channel`、`source_event_id`；`require_source_event_id` 强制写工具必须来自入站事件（`base.py:70-74`）。
- 业务工具均按 `ctx.user.id` 查询/写入：
  - 任务：`app/tools/tasks.py`（create/list/complete）
  - 提醒：`app/tools/reminders.py`（set/list/cancel）
  - 日程：`app/tools/blocks.py`（schedule/list/update_status/reschedule）
  - 笔记：`app/tools/notes.py`（capture_note，写入 `event_log(type="note")`）
- 因此同一 `user_id` 在飞书、Console、手机入口下操作的是同一份业务数据。

#### 2.3.7 移动端 API 现状

- `app/api/routes/mobile.py` 目前只有 Today 读写接口：
  - `GET /api/mobile/today`
  - `POST /api/mobile/today/items/{id}/complete|skip|restore|reschedule`
  - `POST /api/mobile/today/tasks/{id}/schedule`
  - `POST /api/mobile/today/review`
- `app/api/routes/mobile.py:94-127` `get_mobile_user`：
  - 读取 `X-Butler-User`，支持 UUID 或 `feishu:` 前缀的 open_id。
  - 白名单 `ALLOWED_OPEN_IDS` 在 `_check_whitelist` 中执行（`mobile.py:70-91`）。
  - 没有任何 token/JWT/签名校验；这是开发期身份头。
- `app/main.py:81-84`：只有 `ENABLE_MOBILE_API=1` 时才挂载 mobile router。

#### 2.3.8 Flutter Chat 现状

- `mobile/lib/domain/repositories/chat_repository.dart:9-20`：
  - `Stream<List<ChatMessage>> watchMessages()`
  - `Future<void> sendText(String text)`
  - `Future<void> respondToCard({required String messageId, required CardAction action})`
- `mobile/lib/core/providers.dart:29-38`：`chatRepositoryProvider` 永远创建 `MockChatRepository`，没有 `USE_REMOTE` 分支。
- `mobile/lib/data/mock/mock_chat_repository.dart:44-84`：Mock 仓库持有消息列表，`sendText` 直接在仓库内创建用户消息，随后模拟回复、流式增长、离线 queued。
- `mobile/lib/features/chat/chat_controller.dart:18-84`：
  - 订阅 `watchMessages()`，维护 `ChatState(messages, sendError)`。
  - `sendText` 只调用仓库；`retry(TextMessage)` 只把 `message.text` 再传给 `sendText`，**不携带原消息 id**。
  - 没有任何轮询、生命周期或可见性控制。
- `mobile/lib/domain/models/chat_message.dart:8-49`：
  - 基类字段：`id`、`sender`、`createdAt`、`reason`、`syncState`。
  - `TextMessage` 只有 `text`、`streaming`。
  - 没有 `serverId`、`clientMessageId`、`replyToId`。
- `mobile/lib/features/chat/chat_page.dart:12-59`：
  - 直接监听 `chatControllerProvider`。
  - 网络横幅来自 `networkStatusProvider`，而该 Provider 由 `MockNetworkStatusSource` 驱动（`providers.dart:17-27`）。
  - 没有页面生命周期/后台暂停逻辑。
- `mobile/lib/shell/app_router.dart:20-63` 使用 `StatefulShellRoute.indexedStack`；`ShellScaffold` 只暴露 `navigationShell.currentIndex`（`shell_scaffold.dart:7-46`），没有把当前 Tab 暴露成 Provider。

### 2.3.9 手机消息的后台恢复归属

- API 服务启动时会在 lifespan 中调用 `pipeline.recover_unfinished()`（`app/main.py:66-71`）。
- 飞书服务启动时也会调用 `pipeline.recover_unfinished()`（`feishu_main.py:51-55`）。
- `recover_unfinished()` 查询所有 `inbound_processing.status == "processing"` 的事件，并**按当前服务注册的 adapters 过滤 channel**：`if event.channel not in self._adapters: continue`（`pipeline.py:220-238`）。
- 因此：
  - **API 进程**：adapters 包含 console；A2 注册 MobileAdapter 后包含 mobile。API 重启后，手机 processing 事件由 API 进程恢复。
  - **飞书进程**：adapters 只有 feishu（`feishu_main.py:83-90`），不会捡到 `channel="mobile"` 的事件；它只会跳过并记录日志。
  - **A1 阶段**：API 进程不注册 MobileAdapter，所以 API 启动恢复也会跳过 mobile；这些消息会停留在 processing，直到 A2 注册 adapter。A1 单独部署时不要对外启用手机聊天。
- 恢复时：
  - `user_id` 来自 `inbound_processing.user_id`（不是外部 id），所以仍使用同一个用户；
  - `channel` 来自 `event_log.channel`（mobile）；
  - `kind`/`text` 来自 `event_log.payload`（`pipeline.py:241-254`）；
  - `external_user_id` 为空占位，不会触发 `get_or_create_user`（`process` 直接按 user_id 加载用户）。
- 因此手机消息恢复不需要 ChannelIdentity，也不会被飞书进程误处理；但必须保证 `ingest_for_user` 把 `kind="message"` 和 `text` 写入 inbound payload，否则恢复时没有原文。
- 必须补测试：
  1. API pipeline 注册 MobileAdapter 后，`recover_unfinished` 能处理 mobile processing 事件，并保持同一 user_id/channel。
  2. 只有 feishu adapter 的 pipeline（模拟飞书进程）不会处理 mobile 事件。
  3. A1 未注册 MobileAdapter 时，API 恢复也不会处理 mobile，事件保持 processing。

### 2.4 文档与代码的差异

- `docs/mobile-u1-plan.md:103-129` 明确当前 U1 的 ChatRepository 就是上述三个方法，且 U1 只有一条 Friday 主对话。
- `docs/deferred/mobile-sync-and-topics.md` 描述了 `ConversationSyncEngine`、快照、seq、pending 归属等完整同步协议；该文档开头明确标注“延后，不参与当前批次实现”。
- 当前代码**没有** `ConversationSyncEngine`、`ChatView`、`chatViewProvider`。`.trae/rules/mobile.md` 中关于 `chatViewProvider`/`ConversationSyncEngine` 的条款与当前代码不一致。
- U2-A 是普通 HTTP 轮询，不应借机实现 deferred 的完整同步协议；否则范围会大幅扩大。建议在 U2-A 开始前同步更新规则/文档，明确“当前实现是 ChatController + ChatRepository 的简化模型”。

---

## 第三部分：逐项方案可行性审查

状态定义：

- **可直接复用**：现有代码已经满足，不需要修改。
- **部分实现**：已有基础，但必须修改。
- **未实现**：需要新增。
- **方案需修订**：方案与代码/产品原则冲突，先改方案。
- **依赖其他工作**：当前不能做，需前置。

| # | U2-A 要求 | 状态 | 代码证据与判断 |
|---|---|---|---|
| 1 | 手机与飞书共用同一个 `user_id` | **部分实现** | `get_mobile_user` 能按 UUID/open_id 解析已有用户（`mobile.py:94-127`）；但 `pipeline.ingest` 始终调用 `get_or_create_user(channel=event.channel, ...)`（`pipeline.py:80-88`）。如果手机事件 channel=`mobile`，会尝试创建 `ChannelIdentity(channel="mobile")`，被 `user.py:39` 的 CHECK 约束拒绝，或在没有约束时创建出一个错误的手机用户。必须新增 `ingest_for_user`，直接使用已认证的 `User`。 |
| 2 | 共用同一套 Friday Agent | **可直接复用** | `InboundPipeline.__init__` 只创建一个 `FridayAgent`（`pipeline.py:65`）；`_process_one` 调用同一 `self._friday.handle`（`pipeline.py:153`）。手机入口只需复用 Pipeline，不需要复制 Agent。 |
| 3 | 共用同一套工具 | **可直接复用** | `registry.py:29-47` 注册全局工具；工具上下文只依赖 `User`、`channel`、`source_event_id`（`base.py:24-48`）。没有飞书 SDK 或飞书消息 ID 依赖。 |
| 4 | 任务数据共用 | **部分实现，U2-A4 补齐** | `tasks.py` 的 create/list/complete 都按 `ctx.user.id` 查询，天然共用；方案目标包含“修改任务”，需在 U2-A4 新增 `update_task`（只允许改标题/描述等明确字段，不改状态）。 |
| 5 | 提醒数据共用 | **部分实现，U2-A4 补齐** | `reminders.py` 的 set/list/cancel 按 `user.id`；需新增 `update_reminder`，直接更新现有 trigger 的 fire_at/expires_at/payload.note，不做“取消旧提醒再新建”。 |
| 6 | 日程数据共用 | **部分实现，U2-A4 统一规则** | `blocks.py` 的 schedule/list/update_block_status/reschedule 均可用；但 `reschedule_block` 工具没有终态/最短时长/跨天校验，与移动端 Today API 的约束不一致。U2-A4 必须统一，不能作为可选项。 |
| 7 | 笔记创建与查询 | **部分实现，U2-A4 补齐** | `capture_note` 已实现（`notes.py:13-30`），写入 `event_log(type="note", direction="tool")`；需新增 `list_notes` 查询当前用户历史笔记。 |
| 8 | 长期记忆共用 | **部分实现，按方案保持关闭** | `app/memory/runs.py:126-136`、`251-271` 抽取入站 `direction=inbound,type=message` 事件，只按 `user_id` 过滤，没有 channel 限制，因此手机消息会被写入同一用户级记忆空间。`FridayAgent` 只有在 `settings.memory_inject_enabled` 时才检索注入（`agent.py:78-95`），默认配置为 `false`。U2-A 不需要改记忆代码，也不要把“共用数据空间”表述成“已实现跨端读取”。 |
| 9 | 聊天记录完全隔离 | **未实现，必须修改** | `build_history` 只按 `user_id`、时间、direction/type 过滤（`history.py:45-53`），没有 `channel`。当前如果手机和飞书共用用户，手机 Agent 会读到飞书历史，直接违反产品原则。聊天 API 也必须加 `channel="mobile"` 过滤。 |
| 10 | 短期对话上下文隔离 | **未实现，必须修改** | 同 #9；`build_history` 是唯一的短期上下文来源（`agent.py:69-74`）。长期记忆检索不应加 channel 过滤（`retrieve_memory_context` 没有 channel 参数）。 |
| 11 | 手机发送文字并获得真实回复 | **未实现** | 现有 Pipeline 支持文本入站，但没有手机入口、没有 MobileAdapter、没有 chat API。需新增 `POST /api/mobile/chat/messages`、`ingest_for_user`、`MobileAdapter`，并让 Flutter 使用 RemoteChatRepository。 |
| 12 | 调用现有 Friday 工具 | **可直接复用** | 工具由 Agent 的 tool-use 循环调用（`agent.py:125-149`），与渠道无关。手机入口只要把 `channel="mobile"` 和 `source_event_id` 传入即可。 |
| 13 | 恢复手机聊天历史 | **未实现** | `event_log` 已保存入站/出站消息，但没有 chat 查询 API；Flutter 没有 RemoteChatRepository。需要新增 `GET /api/mobile/chat/messages`，从 `event_log` 读取 `channel="mobile"` 的消息。 |
| 14 | 手机与飞书不共享聊天记录 | **未实现** | 见 #9；必须同时修改 `build_history` 和 chat API 查询条件。业务数据（任务/提醒/日程/笔记）继续按 `user_id` 共用。 |
| 15 | 不开发 Jarvis/通知/语音/图片/流式 | **范围已明确，当前代码无冲突** | 现有 Chat UI 有卡片和 Mock Jarvis 流程，但 U2-A 不做后端 Jarvis、不做本地通知、不做流式；RemoteChatRepository 只处理文本消息即可。 |
| 16 | 不启用长期记忆注入 | **可直接保持** | `memory_inject_enabled` 默认 `False`（`app/core/config.py`），`.env` 未要求开启。U2-A 不改这个开关。 |
| 17 | 手机身份认证 | **部分实现，仅限本机/adb reverse** | `get_mobile_user` 只认 `X-Butler-User`，不校验 token；任何知道 UUID/open_id 的调用者都可以访问对应用户。当前 compose 将 API 绑定在 `127.0.0.1`，风险限于本机；一旦改为局域网/公网部署，这是越权入口。U2-A 可以复用该方案，但只允许本机或 `adb reverse`，`ALLOWED_OPEN_IDS` 不能替代认证，也不允许据此暴露局域网。 |
| 18 | 是否需要 MobileAdapter | **需要新增** | `pipeline._process_one` 无条件执行 `self._adapters[ingested.event.channel]`（`pipeline.py:143`）。如果 channel=`mobile` 没有注册 adapter，会抛 `KeyError`，`process` 把事件置 failed。最小方案是新增一个 no-op `MobileAdapter`；它不负责实际发送，只让 Pipeline 正常走完。 |
| 19 | 手机是否能通过数据库查询获得回复 | **可以，但不建议客户端直连数据库** | `event_log` 是可重建的叙事日志，出站回复会写入 `event_log(direction="outbound",type="message")`（`pipeline.py:196-213`）。客户端应通过 Mobile API 读取，而不是直连数据库。 |
| 20 | `reply_to_event_id` 是否已有等价字段 | **已有意图字段，但未持久化** | `OutboundIntent.reply_to_event_id` 存在（`base.py:27-34`），Pipeline 也构造了它（`pipeline.py:181-190`），但 `event_log` 的 outbound payload 只写 `text/send_ok/provider_msg_id`（`pipeline.py:198-211`），没有 `reply_to_event_id`。不需要新数据库列，只需把它写入 payload。 |
| 21 | 消息幂等 | **已有基础设施，需接入手机 key** | `event_log.idempotency_key` 唯一（`event_log.py:27`、`0001_init.py:71`），`append_event` 用 `ON CONFLICT DO NOTHING`（`engine/events.py:52-65`）。手机使用 `mobile-chat:{user_id}:{client_message_id}` 即可；无需新表。 |
| 22 | 并发重复插入风险 | **低，前提是使用 append_event** | `append_event` 的唯一约束 + `ON CONFLICT` 能保证同一 key 只有一条事件；`inbound_processing` 只在 `created=True` 时插入（`pipeline.py:106-115`）。不要自己写“先查再插”的幂等逻辑。 |
| 23 | 不同用户相同 client_message_id | **不会互相影响** | key 包含 `user_id`；`event_log.idempotency_key` 全局唯一但字符串带用户 id。 |
| 24 | 幂等检查与消息插入的事务边界 | **已有正确范式** | `ingest` 在同一事务中写事件、写 `inbound_processing`、commit（`pipeline.py:89-116`）。`ingest_for_user` 应复用这个事务边界，不要在事务外做检查。 |
| 25 | 工具执行成功但回复失败 | **高风险，方案需修订** | Pipeline 先 commit agent+工具（`pipeline.py:169`），再 adapter.send（`pipeline.py:183-190`），最后另开事务写 outbound（`pipeline.py:197-213`）。如果进程在 169 与 213 之间崩溃：`inbound_processing` 仍是 processing，启动 recovery 会重跑整个 Agent。工具幂等键是 `inbound_event_id:tool_name:call_index`（`registry.py:50-54`），如果 LLM 重跑后工具顺序/序号变化，可能产生重复业务数据；outbound 事件也没有幂等键，可能产生两条回复。U2-A 必须为手机设计“回复与 Agent 同事务落库 + outbound 幂等键”的路径，或明确接受该风险。 |
| 26 | Recovery 能否识别已执行工具 | **可以部分识别，但不完整** | `event_log` 的 `tool_call/tool_result` 已持久化（`registry.py:83-115`）；同一 `inbound_event_id + tool_name + call_index` 会返回旧结果（`registry.py:83-88`）。但 call_index 依赖 LLM 的调用顺序，重跑不保证一致，因此不能简单说“已有 event_log 幂等，所以不会重复执行”。 |
| 27 | 是否存在工具结果无法确定 | **当前工具基本可确定** | 工具写入与 tool_result 在同一 savepoint/外层事务（`registry.py:96-115`）；当前工具没有外部副作用（都是数据库写入），崩溃后要么都回滚，要么都提交。真正的不确定性来自“Agent 重跑后调用序列变化”，不是单个工具的原子性。 |
| 28 | 是否需要业务级幂等保护 | **需要评估；手机先做回复幂等** | 任务/提醒工具目前只有调用序号幂等，没有“语义幂等”（例如同一用户同一标题同日只建一个任务）。U2-A 至少需要：入站消息幂等 + outbound 回复幂等 + 同一用户串行处理。语义级工具幂等可作为后续增强。 |
| 29 | 多用户数据隔离 | **已有基础，需新增测试** | 所有工具按 `user_id`；`event_log` 查询按 `user_id`。缺少手机 chat 层的多用户测试。 |
| 30 | 手机历史恢复 | **需要新增 API 与仓库** | `event_log` 可作为唯一事实来源；没有 chat 表是合理的。需新增 `GET` 历史接口和 Flutter RemoteChatRepository 的初始抓取。 |
| 31 | 轮询方案 | **未实现** | 现无轮询、Timer、生命周期处理。需要在 RemoteChatRepository 中实现单飞轮询；ChatPage 需要前后台/可见性控制；不能只给概念性建议。 |
| 32 | Mock/Remote 切换 | **部分实现** | Today 已有 `USE_REMOTE` 分支（`providers.dart:49-63`）；Chat 没有。需要给 `chatRepositoryProvider` 加同样的分支，保证不混用数据源。 |
| 33 | 不复制业务工具 | **可直接复用** | 工具注册表是全局的；手机入口不需要复制。 |
| 34 | 不重建 Friday Agent | **可直接复用** | 见 #2。 |
| 35 | 数据库迁移 | **不需要（U2-A 范围内）** | `ChannelIdentity` CHECK 只允许 feishu/console，但手机不创建 ChannelIdentity；`event_log.channel` 没有 CHECK，`mobile` 可以直接写入；`reply_to_event_id/client_message_id` 放 JSONB payload；`inbound_processing` 已有 status/error。见第六部分。 |
| 36 | 历史查询性能 | **可接受，建议后续加索引** | `event_log` 已有 `(user_id, occurred_at)` 索引（`0001_init.py:78`）。chat 查询再加 `channel/type/direction` 过滤，P0 数据量下可接受；如果历史很大，后续加 `(user_id, channel, occurred_at)`。 |
| 37 | 文档与规则一致性 | **需修订** | 当前代码没有 `ConversationSyncEngine`/`chatViewProvider`；`docs/deferred/mobile-sync-and-topics.md` 是延后方案。U2-A 不应按该文档实现完整同步协议。建议先更新规则/文档，避免开发和审查口径冲突。 |

---

## 第四部分：风险清单

### 高风险

#### H1. 手机与飞书短期上下文会串线

- **问题**：`build_history` 只按 `user_id` 查最近消息，没有 `channel` 条件（`app/agents/friday/history.py:45-53`；调用点 `app/agents/friday/agent.py:69-74`）。
- **原因**：U1 只有单渠道 Mock，当时没有跨渠道隔离需求；U2-A 引入 `channel=mobile` 后，查询条件没有同步扩展。
- **后果**：手机用户说“还是按刚才那个来”，Friday 可能引用飞书对话；飞书也可能看到手机上下文。这直接违反“聊天记录完全隔离”的产品原则。
- **建议**：给 `build_history` 增加 `channel` 参数，SQL 加 `EventLog.channel == channel`；`FridayAgent.handle` 传入已有的 `channel`。聊天 API 查询也加 `channel="mobile"`。长期记忆检索不加 channel。
- **最终筛选规则**：

| 场景 | 筛选条件 |
|---|---|
| 手机短期历史 | `user_id = 当前用户 AND channel = 'mobile'` |
| 飞书短期历史 | `user_id = 当前用户 AND channel = 'feishu'` |
| Console 短期历史 | `user_id = 当前用户 AND channel = 'console'` |
| 长期记忆检索 | `user_id = 当前用户`（**不加 channel**） |

- **是否影响 U2-A**：是，必须在 U2-A2 之前修复，否则不能验收 #5/#6。

#### H2. Agent 重跑可能导致重复工具执行或重复回复

- **问题**：Pipeline 先 commit agent/工具（`pipeline.py:169`），再发送（`pipeline.py:183-190`），最后写 outbound（`pipeline.py:197-213`）。进程在这两步之间崩溃时，`inbound_processing` 仍是 `processing`，启动 recovery 会重跑整个 Agent（`pipeline.py:215-258`）。
- **原因**：工具幂等键是 `inbound_event_id:tool_name:call_index`（`registry.py:50-54`），call_index 依赖 LLM 的调用顺序；LLM 重跑不保证顺序一致。outbound 事件没有幂等键，重跑可能写第二条回复。
- **具体例子**：首次运行 LLM 先 `create_task`（call 1）再 `set_reminder`（call 2）；崩溃后重跑，LLM 先 `set_reminder`（call 1）再 `create_task`（call 2）。两个键都不存在，结果创建第二条提醒和第二个任务。
- **后果**：用户收到重复任务/提醒，或看到两条 Friday 回复；这是业务数据污染，不只是“重复消息”。
- **建议**：
  1. 手机消息采用“Agent 结果与 outbound 回复同事务落库”：在 `_process_one` 中，`friday.handle` 返回后，在同一个 session 内写 outbound 事件、写 `inbound_processing(status=done)`，然后 commit；手机路径不再依赖 adapter.send 的时点。
  2. 实现上建议在手机分支完成上述写入后直接返回，跳过现有 `adapter.send` + transaction B；如果复用 transaction B，必须识别已写入的 outbound（同一 `mobile-reply:{inbound_event_id}` 幂等键）并只补 status，不能再次写第二条回复。
  3. outbound 事件使用幂等键 `mobile-reply:{inbound_event_id}`，保证同一入站事件只有一条回复。
  4. 同一用户消息串行处理（见 H3/M1），避免多个 Agent 并发重跑。
  5. 保留现有工具 call_index 幂等；不要声称它已完全解决重跑问题。
- **是否影响 U2-A**：是，必须在 U2-A2/A5 处理；否则“重复请求不会重复执行工具”的验收无法保证。

#### H3. Pipeline 不支持使用已认证的 User，直接复用会创建错误手机身份

- **问题**：`pipeline.ingest` 无条件调用 `get_or_create_user(channel=event.channel, external_id=event.external_user_id)`（`pipeline.py:80-88`）。
- **原因**：现有入口只有 Feishu/Console，用户身份由渠道外部 id 创建；手机入口已经通过 `get_mobile_user` 得到 `User`，不应再按渠道外部 id 建用户。
- **后果**：如果手机事件 channel=`mobile`，`get_or_create_user` 会插入 `ChannelIdentity(channel="mobile")`，被 `user.py:39` 的 CHECK 拒绝；如果未来放松约束，会创建一个与飞书用户不共享数据的手机 user。
- **建议**：新增 `InboundPipeline.ingest_for_user(event, user)`；复用 `ingest` 的事件写入/`InboundProcessing` 事务边界，但跳过 `get_or_create_user`。手机 API 的 `get_mobile_user` 已经完成认证和白名单校验，`ingest_for_user` **不应再拿 `event.external_user_id` 做一次白名单判断**（手机事件可能使用空占位或 UUID），否则会被误丢弃；如果需要保留白名单检查，应直接检查已认证用户已有身份，而不是检查 `external_user_id`。
- **是否影响 U2-A**：是，U2-A1 的第一项。

#### H4. 没有 MobileAdapter 会导致手机事件直接 failed

- **问题**：`_process_one` 第一行 `adapter = self._adapters[ingested.event.channel]`（`pipeline.py:143`）。`app/main.py:53-55` 只注册 `console`；`feishu_main.py:88` 只注册 `feishu`。
- **后果**：`channel="mobile"` 的事件在 process 阶段抛 `KeyError`，`process` 捕获后置 failed（`pipeline.py:135-139`）；用户永远收不到回复。
- **建议**：新增 `app/adapters/mobile_adapter.py`，实现 `ChannelAdapter`：
  - `channel="mobile"`
  - `Capabilities(can_push_unsolicited=False, streaming=False, supports_buttons=False)`
  - `start` no-op
  - `send` 返回 `DeliveryResult(ok=True)`，不实际发送
  - **MobileAdapter 的 send 只返回结果，不写 `event_log`；outbound 事件只由 Pipeline 写一次**，避免 adapter 与 Pipeline 各写一份
  - 在 `app/main.py` 的 `adapters` 中按 `enable_mobile_api` 注册
- **对 Pipeline 状态/异常的影响**：
  - A1 只接收/落库，不启动真实 Agent，因此不会调用 `send`，也没有 outbound 状态。
  - A2 注册 MobileAdapter 后，手机专用完成路径**不调用 `send`，也不写 `send_ok`**；outbound 状态使用 `delivery="persisted"`，API 返回 `available`。真正的“成功”定义是：outbound 事件已提交，手机可以查询到。
  - 不要用 `send_ok` 驱动手机 UI 状态；手机没有外部推送动作。
- **是否影响 U2-A**：是，U2-A1 必须完成。

**手机完成路径的职责划分（必须统一）**：

| 职责 | 负责方 | 说明 |
|---|---|---|
| 保存 outbound 回复 | `InboundPipeline._process_one` 的手机分支 | 唯一写入者；MobileAdapter 不写 event_log |
| outbound 状态 | Pipeline 手机分支 | `delivery="persisted"`，API 返回 `available`；不使用 `send_ok`，不伪装成渠道发送成功 |
| 把 `inbound_processing` 置 done | 同一手机分支、同一事务 | 与 outbound 一起 commit |
| outbound 幂等 | `append_event(idempotency_key="mobile-reply:{inbound_event_id}")` | 同一条入站事件最多一条回复 |
| 处理 Agent 失败 | Pipeline | rollback 后写 fallback outbound + done（新事务），仍然只写一条 |
| MobileAdapter.send | 正常手机路径**不调用** | 仅作为 adapter 注册/恢复/能力声明的防御性 no-op；如果被调用，只返回 `ok=True`，不写任何记录 |
| 谁改 done | Pipeline 手机分支 | 不是 Adapter，不是 API 路由 |
| 谁保证不重复 | Pipeline + event_log 唯一约束 | 不是 Adapter 自身 |

实现建议：`_process_one` 检测 `ingested.event.channel == "mobile"`，在 `friday.handle` 返回后、commit 前追加 outbound 和 status done，然后 commit 并 `return`；不要继续执行 `adapter.send` 和 transaction B。MobileAdapter 仍然注册，是为了 `self._adapters[channel]` 查找、recovery 渠道过滤和 capabilities；正常路径不依赖它的发送。

#### H5. 回复与用户消息没有持久关联

- **问题**：`OutboundIntent.reply_to_event_id` 只有 adapter 层使用（`base.py:27-34`；`console_adapter.py:33`），`pipeline.py:198-211` 的 outbound payload 没有写它。
- **后果**：手机 chat API 无法知道哪条回复对应哪条用户消息；并发/重跑时无法正确归并，历史恢复也无法配对。
- **建议**：在 outbound payload 增加 `reply_to_event_id`（字符串）和 `delivery="persisted"`；在入站 payload 增加 `client_message_id`。不需要新列；JSONB 足够。如果希望强类型，可新增可选字段，但需要走契约确认。手机不复用 `send_ok` 语义。
- **是否影响 U2-A**：是，U2-A2 必须完成。

#### H6. ChatRepository 的重试会丢失 clientMessageId

- **问题**：当前接口是 `sendText(String text)`（`chat_repository.dart:12`），`ChatController.retry` 只传 `message.text`（`chat_controller.dart:54-61`）。
- **后果**：手机网络失败后重试，如果 RemoteChatRepository 重新生成 `client_message_id`，服务端会把它当成新消息，可能重复执行工具；如果沿用旧 id 但没有传入接口，则无法保证。
- **建议**：把接口改为 `sendText(String text, {String? clientMessageId})` 或等价的命名参数；本地重试必须复用原 `clientMessageId`。Mock 仓库也实现该参数，保持两种模式一致。
- **是否影响 U2-A**：是，U2-A3 必须完成。

#### H7. 方案目标超出当前工具覆盖

- **问题**：方案要求“修改任务、修改提醒、查询笔记”；现有工具只有：
  - 任务：`create_task` / `list_tasks` / `complete_task`，没有 `update_task`
  - 提醒：`set_reminder` / `list_reminders` / `cancel_reminder`，没有 `update_reminder`
  - 笔记：`capture_note`，没有 `list_notes`
- **后果**：U2-A 验收时无法完成“修改任务/提醒、查询笔记”；如果临时让 LLM 用“取消+重建”代替修改，会导致 trigger/task 语义变化和额外副作用。
- **产品决定（已确认）**：保留原 U2-A 范围，不通过收窄验收来减少开发量。在 U2-A4 新增三个工具：
  1. `update_task(task_id, title?, description?)`
     - 按 `ctx.user.id` 校验归属；只允许修改标题/描述；不改 status（状态仍由 `complete_task` 负责）。
     - 更新 `rev`、`updated_at`；工具幂等键沿用 `inbound_event_id:tool_name:call_index`。
  2. `update_reminder(trigger_id, fire_at?, note?)`
     - 只允许 `status=pending` 的提醒；`claimed/fired/missed/dropped/failed` 一律拒绝。
     - **必须防 Worker 竞争**：不能先查 pending 再无条件 UPDATE。使用 `SELECT ... FOR UPDATE` 锁定该行后再检查 status，或使用 `UPDATE ... WHERE id=:id AND user_id=:uid AND status='pending'` 并检查 rowcount；只有成功抢到仍然 pending 的提醒才允许修改。如果 Worker 已经 claim，返回明确错误（例如“提醒已被处理，无法修改”），由 Friday 告知用户。
     - 直接更新现有 `trigger_instance` 的 `fire_at`、`expires_at=fire_at+reminder_late_window_hours`、`payload.note`；不取消旧提醒、不新建第二条 trigger。
     - `fire_at` 必须是未来时间；更新后写 `event_log(type="trigger", payload={status:"updated", reason:"user_updated"})` 留痕。
     - 工具幂等键沿用入站事件派生；重复调用返回同一次结果，不重复更新。
     - 测试：pending 更新成功且 trigger id 不变；status=claimed 时返回错误；并发 claim/update 不会出现“按旧时间执行但数据库已改”的静默不一致。
  3. `list_notes(limit=20)`
     - 按 `ctx.user.id` 查 `event_log(direction="tool", type="note")`，按 `occurred_at DESC, id DESC` 取最近 N 条（上限 100）；返回 `note_event_id/text/created_at`。
     - 不新增表；笔记仍以 event_log 为事实来源。
- **注册**：在 `app/tools/registry.py` 的 `TOOLS` 中注册三个工具；更新工具 schema 测试。
- **是否影响 U2-A**：是，U2-A4 必须完成；不能把“修改任务/提醒、查询笔记”悄悄移出验收。

#### H8. `X-Butler-User` 不是真实认证，公网部署会越权

- **问题**：`get_mobile_user` 只读取 `X-Butler-User`，支持 UUID 或 open_id（`mobile.py:94-127`）；没有 token、签名、设备绑定或会话校验。
- **原因**：U1/U2 开发期为了快速联调，使用了固定的开发用户头。
- **后果**：任何知道用户 UUID/open_id 的调用者都可以读写该用户的任务、提醒、日程、笔记和聊天。当前 compose 将 api 绑定在 `127.0.0.1`（`docker-compose.yml`），风险限于本机；一旦改成 `0.0.0.0`、局域网或公网，就是明确的越权入口。
- **建议**：U2-A 开发和测试阶段**只允许本机访问**（api 绑定 `127.0.0.1`）或通过 `adb reverse` 的受控手机调试；**不要因为配置了 `ALLOWED_OPEN_IDS` 就暴露到普通局域网，更不能暴露公网**。`ALLOWED_OPEN_IDS` 只检查标识是否在名单内，不能证明请求者就是该用户，不构成认证。公网前必须补真实认证（JWT/OAuth/设备绑定）、HTTPS、速率限制和审计。
- **是否影响 U2-A**：是部署边界；本机开发不阻塞，任何局域网/公网暴露都阻塞。

### 中高风险

#### M1. 同一用户的多条消息可能并发处理，回复顺序不稳定

- **问题**：Mobile API 的 POST 若直接 `spawn(pipeline.process)`，同一用户两条消息会并发进入 Agent；`build_history` 可能看到对方未完成的入站消息，但看不到对方回复。
- **后果**：LLM 上下文顺序不符合用户实际发送顺序；回复可能交错。
- **建议**：在手机 chat 服务内按 `user_id` 串行化 `pipeline.process`（例如 `app.state.mobile_chat_locks: dict[uuid.UUID, asyncio.Lock]`），POST 仍快速返回 202；或让 Flutter 在收到上一条回复前禁止发送下一条。前者更符合“多条待处理消息”的产品要求。
- **运行环境限制**：`asyncio.Lock` 只在当前 Python 进程内有效。**U2-A 明确只支持单进程 api 服务**（当前 compose 的 uvicorn 默认单 worker）；如果启动多个 worker 或多副本，每个进程各有自己的锁，可能同时处理同一用户的消息。
- **多进程方案**：必须改为数据库队列/租约、Postgres advisory lock（注意不要在长 LLM 调用期间持有事务级锁）或其他跨进程协调机制；U2-A 不实现，只记录限制。
- **是否影响 U2-A**：是，建议 U2-A2，并在 README/部署说明中写明单进程约束。

#### M2. 远程网络状态仍是 Mock

- **问题**：`chatRepositoryProvider` 永远 Mock（`providers.dart:29-38`）；Chat 页网络横幅来自 `MockNetworkStatusSource`（`chat_page.dart:18`、`35-38`；`providers.dart:17-27`）。
- **后果**：切换到真实后端后，离线/同步中横幅仍是模拟值；发送失败只覆盖 `sendError`，轮询失败没有状态。
- **建议**：为远程 Chat 增加 `syncError`/连接状态（扩展 `ChatState` 或单独 `chatConnectionProvider`），由 RemoteChatRepository 的轮询/发送错误驱动；Mock 模式保留现有模拟横幅。
- **是否影响 U2-A**：是，U2-A3/A5 的“网络异常”验收。

#### M3. Chat API 无现成实现，需新增分页/游标

- **问题**：现有 `/api/mobile/today` 只按日期返回 Today；没有 chat 端点。`event_log` 有 `(user_id, occurred_at)` 索引，但没有 chat 专用索引。
- **后果**：不做分页会导致历史增长后单次返回过大；不做游标会导致轮询重复抓取。
- **建议**：新增 `limit`（默认 50，最大 100）和 `after`/`before` 游标；游标使用 `occurred_at + id`，不使用 offset。P0 可先只做最近 100 条 + `after` 增量，索引后续再加。
- **首屏顺序**：必须先取最新 N 条再反转为升序返回；不能按升序取前 N 条，否则用户打开 Chat 看到的是最早历史。
- **是否影响 U2-A**：是，U2-A2。

#### M4. 处理失败的状态与重试语义未定义

- **问题**：`InboundProcessing.status` 有 `failed`，但 `_mark_status` 不写 `error`（`pipeline.py:260-276`）；`recover_unfinished` 只恢复 `processing`，不恢复 `failed`（`pipeline.py:215-258`）。
- **另一个隐蔽问题**：chat 的 after 增量只返回新事件；inbound 从 processing 变成 failed 不会产生新 event。如果客户端只查 after，会一直停在“正在处理”，发现不了失败。
- **后果**：手机轮询看到 `failed` 后，用户重试同一条消息（同 clientMessageId）会返回既有 failed 事件，不会重新处理；用户只能发一条新消息（新 id），可能产生重复输入。
- **建议**：
  1. RemoteChatRepository 维护 `_pendingInboundIds`，用 `GET /api/mobile/chat/messages/{id}` 补偿 processing→done/failed（见 7.2.3.1）。
  2. 明确 U2-A 的失败语义：`failed` 是终态，客户端提示用户用**新的 clientMessageId** 重新发送；或者后续新增 `POST /api/mobile/chat/messages/{id}/retry`，仅对 failed 的入站事件重新入队，并记录重试次数。U2-A 先采用“终态 + 重新发送”。
  3. `_apply_status` 可把异常摘要写入 `inbound_processing.error`，便于状态接口/日志诊断。
- **是否影响 U2-A**：是，U2-A3 必须实现 pending 状态补偿，否则验收 #10 不通过。

#### M5. ChatMessage 模型不足以表达服务端 id、clientMessageId 与回复关联

- **问题**：`ChatMessage` 只有 `id`、sender、createdAt、reason、syncState（`chat_message.dart:8-22`）；`TextMessage` 只有 text/streaming（`chat_message.dart:24-49`）。
- **后果**：RemoteChatRepository 无法在“本地乐观消息”和“服务端回显消息”之间去重；无法保存 replyToId；`ChatController.retry` 也没有稳定 id 可用。
- **建议**：最小改动是在 `TextMessage` 增加可选 `serverId`、`clientMessageId`、`replyToId`，并在 `copyWith` 中保留；卡片类型不需要这些字段。另一种方案是 API 直接把入站消息的 `id` 设为 `clientMessageId`，但这会丢失事件 id，且出站回复仍需 replyToId，不推荐作为唯一方案。
- **是否影响 U2-A**：是，U2-A3。

#### M6. Mock/Remote 切换需要同时处理调试动作

- **问题**：`DebugActions.injectJarvisIntro` 依赖 `repository is MockChatRepository`（`providers.dart:66-77`）；远程模式下按钮可能仍显示，但不会生效。
- **后果**：调试面板行为不一致，容易误判“远程模式已生效”。
- **建议**：`chatRepositoryProvider` 增加 `remoteConfig.enabled` 分支；调试面板在远程模式下禁用 Mock-only 动作，或显示“当前为真实数据源”。
- **是否影响 U2-A**：低，但影响可测试性。

### 中风险

#### M7. 事件日志作为聊天事实来源的查询边界

- **问题**：`event_log` 里还有 `tool_call`、`tool_result`、`note`、`memory_context`、`delivery` 等事件；chat API 必须只取 `type="message"` 且 `direction in ("inbound","outbound")`，否则会把工具参数、笔记、记忆审计当成聊天消息。
- **建议**：chat 查询固定条件：`user_id == user.id AND channel == "mobile" AND type == "message" AND direction IN ("inbound","outbound")`；不要复用 `build_history` 的 delivery 分支（U2-A 无手机主动消息）。
- **是否影响 U2-A**：是，U2-A2。

#### M8. `InboundProcessing.error` 未写入

- **问题**：`process` 捕获异常后只调用 `_mark_status(failed)`（`pipeline.py:137-139`、`260-266`），没有保存异常信息。
- **后果**：手机状态接口只能返回 failed，无法给出可诊断原因；排查只能靠日志。
- **建议**：扩展 `_mark_status`/`_apply_status` 接受 `error: str | None`，把异常类型/摘要写入 `inbound_processing.error`（避免写入敏感内容）。这不是 U2-A 的硬阻塞，但很实用。

#### M9. Feishu 聊天回复没有 collapse_key 发送幂等

- **问题**：`OutboundIntent` 支持 `collapse_key`，但 `pipeline.py:181-190` 的聊天回复没有设置；FeishuAdapter.send 只有在 `collapse_key` 存在时才传 uuid（`feishu_adapter.py:145-169`）。
- **后果**：如果 Feishu 发送成功但 outbound 事务失败，恢复重跑可能重复发送。U2-A 手机路径不受此影响，但共享 Pipeline 的可靠性问题仍在。
- **建议**：U2-A 不扩大范围；在方案中记录为已知问题，后续为聊天回复增加 outbox/幂等键。手机路径采用 H2 的同事务回复方案。

#### M10. `reschedule_block` 工具与移动端 Today API 约束不一致

- **问题**：移动端 Today API 已拒绝终态块、跨天和不足 5 分钟（`app/api/routes/mobile.py` 的 reschedule 端点）；`app/tools/blocks.py:211-250` 的 `reschedule_block` 没有这些约束。
- **后果**：手机用户通过 Chat 让 Friday 改期时，可能产生与 Today 页面不一致的结果。
- **建议**：**列为 U2-A4 必做，不再作为可选项**。`reschedule_block` 与移动端 Today 改期采用同一套规则：
  - 拒绝 `status != planned`（done/skipped/moved）；
  - 拒绝跨本地日期；
  - 拒绝新时长不足 5 分钟；
  - 过去时间处理需明确：Today 目前允许修正逾期块，而工具使用 `parse_future_time` 拒绝过去；两者必须在文档/测试中写明同一策略，不能一个允许一个不允许而无人知道。
  - 增加 Chat 与 Today 的端到端对照测试，验证同一输入得到同样的成功/失败结果。

### 低风险

- **L1**：`event_log` 的 chat 查询没有专用索引；P0 可接受，后续按需加 `(user_id, channel, occurred_at)`。
- **L2**：没有限流/配额；手机 API 依赖 `LLM_DAILY_LIMIT` 控制模型成本，但 HTTP 层没有速率限制。
- **L3**：没有真正的用户认证；只适合本机或 `adb reverse`，不能用于局域网/公网。
- **L4**：没有消息删除、编辑、已读、未读数；U2-A 不需要。
- **L5**：没有多设备同时在线/多端已读同步；U2-A 只需要单设备轮询。
- **L6**：Mock 与 Remote 的聊天数据源切换后，调试数据集/失败注入只对 Mock 生效；需在 UI 标注。

---

## 第五部分：文件级开发清单

### 5.1 后端

| 文件路径 | 当前作用 | 需要做什么 | 修改类型 | 优先级 | 验收方式 |
|---|---|---|---|---|---|
| `app/adapters/mobile_adapter.py` | 不存在 | 新增 `MobileAdapter`：channel=mobile，start no-op，send 返回 ok，capabilities 不支持推送/流式 | 新增 | P0 | 单元测试 `send` 返回 ok；Pipeline 不再 KeyError |
| `app/engine/pipeline.py` | 入站 ingest/process | 新增 `ingest_for_user(event, user)`；复用事件写入 + InboundProcessing；手机 channel 的 outbound 回复与 status done 同事务落库，并加 `mobile-reply:{event_id}` 幂等键；outbound payload 写 `reply_to_event_id` | 修改 | P0 | 集成测试：手机事件使用已有 user；无新 ChannelIdentity；崩溃后 recovery 不重复回复/工具 |
| `app/agents/friday/agent.py` | Agent 入口 | 调用 `build_history(..., channel=channel)` | 修改 | P0 | 跨渠道历史隔离测试 |
| `app/agents/friday/history.py` | 短期历史 | 增加 `channel` 参数与 `EventLog.channel == channel` 条件 | 修改 | P0 | 手机/飞书历史互不可见 |
| `app/api/routes/mobile_chat.py` | 不存在 | 新增 POST 发送、GET 历史、GET 单条状态；复用 `get_mobile_user`/`get_session`；按 user 串行 process；返回 202/200 | 新增 | P0 | API 集成测试：发送、幂等、历史、权限、分页 |
| `app/api/routes/mobile.py` | Today API + 用户识别 | 保持 Today 不变；导出/复用 `get_mobile_user`、`get_session`、`_settings`；不把 chat 逻辑塞进该文件 | 复用/小改 | P0 | Today 现有测试全通过 |
| `app/main.py` | 应用组装 | A1 挂载 chat router；A2 按 `enable_mobile_api` 注册 MobileAdapter；保持 settings/pipeline 注入 | 修改 | P0 | 启动后 `/api/mobile/chat/messages` 可用；关闭开关时 404 |
| `app/db/models/event_log.py` | 事件日志 | 不改表结构；明确 payload 中 `client_message_id`、`reply_to_event_id`、`delivery="persisted"` 的约定 | 复用 | P0 | chat API 能读取字段；手机不使用 send_ok |
| `app/db/models/inbound_processing.py` | 处理状态 | 可选：把错误摘要写入 `error`；不新增列 | 复用/小改 | P1 | failed 状态可返回错误摘要 |
| `app/tools/tasks.py` | 任务工具 | 新增 `update_task(task_id, title?, description?)`；校验 user 归属，只改标题/描述，更新 rev/updated_at | 新增 | P0 | 工具测试：修改标题/描述；非本人/不存在拒绝 |
| `app/tools/reminders.py` | 提醒工具 | 新增 `update_reminder(trigger_id, fire_at?, note?)`；只允许 pending，`SELECT FOR UPDATE`/原子 UPDATE 防 Worker 竞争，直接更新现有 trigger 的 fire_at/expires_at/payload，不取消重建 | 新增 | P0 | 工具测试：trigger id 不变、只更新一条、claimed 拒绝、并发安全 |
| `app/tools/notes.py` | 笔记工具 | 新增 `list_notes(limit=20)`：按 user_id 查 event_log type=note，按时间倒序取最近 N 条 | 新增 | P0 | 工具测试：最近笔记、limit 上限、用户隔离 |
| `app/tools/registry.py` | 工具注册 | 注册 `update_task`/`update_reminder`/`list_notes` | 修改 | P0 | 工具 schema 与执行测试 |
| `app/tools/blocks.py` | 日程工具 | 统一 `reschedule_block` 与移动端 Today 规则：拒绝终态/跨天/不足 5 分钟；明确过去时间策略 | 修改 | P0 | Chat 与 Today 对照测试；终态/最短时长/跨天 |
| `app/db/migrations/versions/` | 迁移 | U2-A 不需要迁移；不要新增表/列 | 不需要修改 | P0 | Alembic head 不变 |
| `tests/integration/test_pipeline_mobile.py` | 不存在 | 新增 `ingest_for_user`、MobileAdapter、手机 outbound 同事务、recovery 测试 | 新增 | P0 | 全部通过 |
| `tests/integration/test_mobile_chat_api.py` | 不存在 | 新增发送/历史/状态/幂等/权限/多用户/分页测试 | 新增 | P0 | 全部通过 |
| `tests/integration/test_friday_history_isolation.py` | 不存在 | 新增手机/飞书历史隔离与记忆检索不隔离测试 | 新增 | P0 | 全部通过 |
| `tests/integration/test_mobile_chat_tools.py` | 不存在 | 新增手机入口调用任务/提醒/日程/笔记工具的端到端测试 | 新增 | P1 | 全部通过 |
| `tests/integration/test_idempotency.py` | 已有 | 扩展手机 client_message_id 重试、并发同键测试 | 修改 | P0 | 不重复建任务/提醒，不重复回复 |
| `docs/contracts.md` | 契约 | 补充 mobile chat 事件字段、`ingest_for_user`、outbound payload；需先确认 | 修改（需确认） | P0 | 契约评审通过 |

### 5.2 Flutter

| 文件路径 | 当前作用 | 需要做什么 | 修改类型 | 优先级 | 验收方式 |
|---|---|---|---|---|---|
| `mobile/lib/domain/repositories/chat_repository.dart` | Chat 抽象 | `sendText` 增加 `clientMessageId`；增加 `setActive(bool)`（Mock no-op）；卡片应答在 Remote 明确不支持 | 修改 | P0 | Mock/Remote 均编译；测试覆盖 |
| `mobile/lib/domain/models/chat_message.dart` | 消息模型 | `TextMessage` 增加可选 `serverId`、`clientMessageId`、`replyToId`，`copyWith` 保留；processing 用 `syncState=pending` 表达，failed 用 `syncState=failed` | 修改 | P0 | copyWith/去重/状态映射测试 |
| `mobile/lib/data/remote/remote_chat_repository.dart` | 不存在 | 新增：首屏最新 N 条、定时轮询、单飞、after/before 游标、乐观消息、发送失败标记、重试复用 clientMessageId、`_pendingInboundIds` 状态补偿、setActive 立即刷新、dispose | 新增 | P0 | 仓库单测：首屏最新 N 条、增量/去重/失败/processing→failed/重试/停止 |
| `mobile/lib/data/remote/api_client.dart` | HTTP 客户端 | 复用 `getJson`/`postJson`；chat POST 用 clientMessageId 作为幂等键；如需查询参数可拼 path | 复用/小改 | P0 | 仓库测试验证请求路径/头/体 |
| `mobile/lib/data/mock/mock_chat_repository.dart` | Mock 聊天 | 实现新的 `sendText` 签名与 `setActive` no-op；保留流式与离线语义 | 修改 | P0 | 现有 Mock 测试通过 |
| `mobile/lib/core/providers.dart` | Provider 装配 | `chatRepositoryProvider` 按 `remoteConfig.enabled` 选择 Remote/Mock；Remote 注入 ApiClient；dispose | 修改 | P0 | Provider 测试：默认 Mock，USE_REMOTE 为 Remote |
| `mobile/lib/features/chat/chat_controller.dart` | Chat 状态 | `retry` 传原 clientMessageId；增加 `setPollingActive`；增加 syncError/连接状态（或单独 provider） | 修改 | P0 | Controller/页面测试：失败重试、轮询错误 |
| `mobile/lib/features/chat/chat_page.dart` | Chat 页面 | 前后台/可见性生命周期（只调 setPollingActive）；远程模式错误横幅；processing/failed 提示；不混用 Mock 数据 | 修改 | P0 | 组件测试：历史恢复、发送、回复、processing→failed、前后台 |
| `mobile/lib/shell/shell_scaffold.dart` | 4 Tab 外壳 | 暴露当前 Tab/可见性给 Chat（如 selectedTabProvider），用于暂停/恢复轮询 | 修改 | P1 | 切 Tab 时轮询暂停/恢复 |
| `mobile/lib/core/strings.dart` | 文案 | 新增聊天处理中/同步失败/网络/超时文案（如 `S.chatProcessing`） | 修改 | P1 | 无硬编码文案 |
| `mobile/test/remote_chat_repository_test.dart` | 不存在 | 新增：初始历史、增量、去重、乐观消息、发送失败、重试 id、轮询停止、错误退避 | 新增 | P0 | 全部通过 |
| `mobile/test/chat_page_test.dart` | 已有 | 增加 Remote 模式、历史恢复、发送后回复、失败/重试、前后台暂停 | 修改 | P0 | 全部通过 |
| `mobile/test/mock_chat_repository_test.dart` | 已有 | 适配 `sendText` 新签名；确认 Mock 流式/离线不变 | 修改 | P0 | 全部通过 |
| `mobile/test/app_providers_test.dart` | 已有 | 增加 chat provider 的 Mock/Remote 切换断言 | 修改 | P0 | 全部通过 |
| `mobile/pubspec.yaml` | 依赖 | 不新增网络/轮询库；继续用 `dart:io` + `dart:async` | 不需要修改 | P0 | `analyze` 通过 |
| `mobile/README.md` | 说明 | 增加 Chat 远程模式、轮询、失败重试、数据源切换说明 | 修改 | P1 | 文档评审 |

---

## 第六部分：数据库变更方案

### 6.1 结论

**U2-A 不需要数据库迁移。**

理由如下：

1. **不新增手机 ChannelIdentity**
   - `channel_identity.channel` 的 CHECK 只允许 `feishu`/`console`（`app/db/models/user.py:35-40`；`0001_init.py:49`）。
   - 手机 API 通过 `get_mobile_user` 解析已有 `User`，再用 `ingest_for_user` 直接复用该 User；不调用 `get_or_create_user(channel="mobile")`，因此不需要插入手机身份，也不需要修改 CHECK。

2. **event_log.channel 没有枚举约束**
   - `event_log` 只有 `direction` 的 CHECK（`0001_init.py:72-75`），`channel` 是普通 `Text` 列（`0001_init.py:62`）。
   - 写入 `channel="mobile"` 不需要迁移。

3. **回复关联与 clientMessageId 放 JSONB**
   - `event_log.payload` 是 JSONB（`0001_init.py:65`）。
   - 入站 payload 增加 `client_message_id`；出站 payload 增加 `reply_to_event_id`。不需要新列。
   - `OutboundIntent.reply_to_event_id` 已经存在（`base.py:33`），只是 Pipeline 没有持久化。

4. **inbound_processing 已有状态与错误字段**
   - `event_id`、`user_id`、`status`、`error`、`updated_at` 已存在（`inbound_processing.py:12-25`；`0003_inbound_processing.py:22-42`）。
   - 手机消息复用同一张表；不需要新增手机状态表。

5. **聊天历史不需要新表**
   - `event_log` 已经按 `(user_id, occurred_at)` 建索引（`0001_init.py:78`）。
   - 手机 chat 查询条件为 `user_id + channel='mobile' + type='message' + direction in (inbound,outbound)`；P0 数据量下可接受。
   - 不建议新增 `chat_message` 表；这会造成 event_log 与 chat 表双写和一致性问题。

### 6.2 可选索引（不属于 U2-A 必需）

如果上线后聊天历史查询变慢，可新增迁移：

```sql
CREATE INDEX ix_event_log_user_channel_occurred
ON event_log (user_id, channel, occurred_at);
```

- **迁移原因**：chat 查询固定按用户 + channel + 时间排序。
- **影响**：只增加索引，不改数据；写入 event_log 会有少量索引维护成本。
- **兼容**：向后兼容，无数据回填。
- **回滚**：`DROP INDEX ix_event_log_user_channel_occurred;`
- **建议**：U2-A 先不加，等真实数据量证明需要再加。

### 6.3 如果未来要做“手机独立身份”

只有在以下情况才需要迁移：

- 手机端不再复用飞书/已有用户，而是需要独立的手机账号体系；
- 需要 `channel_identity(channel='mobile')` 作为正式身份。

那时需要：

1. 新迁移放松 `ck_channel_identity_channel_values`，加入 `mobile`；
2. 明确用户合并/迁移策略（手机身份如何绑定到已有 user）；
3. 回滚时需先处理 `channel='mobile'` 的存量行；
4. 这超出 U2-A，不在本阶段实施。

---

## 第七部分：API 最终设计

### 7.1 现有接口（保留）

| 方法 | 路径 | 用途 | 认证 | 说明 |
|---|---|---|---|---|
| GET | `/api/mobile/today` | Today 只读 | `X-Butler-User` + `ENABLE_MOBILE_API` + `ALLOWED_OPEN_IDS` | 已实现 |
| POST | `/api/mobile/today/items/{id}/complete` | 完成 | 同上 + `Idempotency-Key` | 已实现 |
| POST | `/api/mobile/today/items/{id}/skip` | 跳过 | 同上 + `Idempotency-Key` | 已实现 |
| POST | `/api/mobile/today/items/{id}/restore` | 撤销 | 同上 + `Idempotency-Key` | 已实现 |
| POST | `/api/mobile/today/items/{id}/reschedule` | 改期 | 同上 + `Idempotency-Key` | 已实现 |
| POST | `/api/mobile/today/tasks/{id}/schedule` | 排期 | 同上 + `Idempotency-Key` | 已实现 |
| POST | `/api/mobile/today/review` | 晚间复盘 | 同上 + `Idempotency-Key` | 已实现 |

### 7.2 新增接口

#### 7.2.1 发送消息

```http
POST /api/mobile/chat/messages
X-Butler-User: <uuid | feishu:open_id | open_id>
Content-Type: application/json

{
  "clientMessageId": "c-01J...",
  "text": "明天 9 点提醒我交报告"
}
```

- **认证**：复用 `get_mobile_user`；`ENABLE_MOBILE_API=1`；白名单同 Today。
- **参数校验**：
  - `clientMessageId`：必填，1–200 字符；同一用户同一条消息重试必须复用。
  - `text`：必填，trim 后 1–4000 字符（建议上限 4000，和历史预算一致）。
- **幂等**：
  - 服务端 key：`mobile-chat:{user.id}:{clientMessageId}`。
  - 写入 `event_log.idempotency_key`；使用 `append_event` 的 `ON CONFLICT`，不要先查后插。
  - 同用户同 key 返回同一 `id`；不同用户互不影响。
- **成功响应（新消息）**：`202 Accepted`

```json
{
  "id": "<inbound event id>",
  "clientMessageId": "c-01J...",
  "status": "processing",
  "createdAt": "2026-11-23T09:00:00+08:00",
  "duplicate": false
}
```

- **重复请求**：`200 OK`，返回既有 `id` 和当前 `status`（`processing|done|failed`）；`duplicate: true`；不得再次 spawn Agent。
- **错误**：
  - `400`：缺少/非法 `clientMessageId`、空文本、文本过长。
  - `401`：缺少 `X-Butler-User` 或未知用户。
  - `403`：不在 `ALLOWED_OPEN_IDS`。
  - `503`：Pipeline 未就绪（正常启动后不应出现）。
- **幂等标识唯一规则**：
  - `clientMessageId` 是手机消息的唯一业务标识；服务端幂等键固定为 `mobile-chat:{user_id}:{clientMessageId}`。
  - `Idempotency-Key` 请求头**可选**；如果客户端发送了该头，它必须与 body 的 `clientMessageId` 完全相同，否则返回 `400`（不允许“服务端忽略头”或“两个标识不一致但继续处理”）。
  - Flutter 的 `ApiClient.postJson` 目前要求一个 `idempotencyKey` 参数，直接传 `clientMessageId`，保证头/体一致。
  - 不允许出现两个不同的幂等标识；排查网络重试时只认 `clientMessageId`。
- **其他**：服务端不创建手机 ChannelIdentity；使用 `ingest_for_user`。

#### 7.2.2 查询历史

```http
GET /api/mobile/chat/messages?limit=50&after=<event_id>
```

- **认证**：同 Today。
- **查询条件**：
  - `user_id = 当前用户`
  - `channel = 'mobile'`
  - `type = 'message'`
  - `direction in ('inbound','outbound')`
- **首屏加载（无游标）**：
  - 后端先按 `occurred_at DESC, id DESC` 取最新 `limit` 条，再在返回前反转为 `occurred_at ASC, id ASC`。
  - 这样首次打开 Chat 看到的是最近 50 条，而不是最早的 50 条；客户端拿到升序列表后直接滚动到底部。
  - **不要**先按升序取前 N 条；那会返回最早的历史。
- **增量加载（after）**：
  - `after`：只返回该事件之后的增量（用于轮询），按 `occurred_at ASC, id ASC`；游标使用 `occurred_at + id`，服务端先解析事件。
  - 返回 `nextCursor`（最后一条的 `id`）和 `hasMore`。
- **更早历史（before）**：
  - `before`：用于向上加载更早历史；按 `occurred_at DESC, id DESC` 取游标之前的 `limit` 条，再反转为升序返回。
  - 返回 `previousCursor` 和 `hasMore`。U2-A 可以先只实现首屏 + after，但接口语义必须按这个方向定义，避免以后改协议。
- **消息列表顺序**：无论首屏、after 还是 before，响应中的 `messages` 始终按 `occurred_at ASC, id ASC` 返回；客户端不得自行重排。
- **消息结构**：

```json
{
  "id": "<event id>",
  "clientMessageId": "c-01J...",
  "role": "user | friday",
  "text": "……",
  "status": "processing | done | failed | available",
  "replyToId": "<inbound event id | null>",
  "createdAt": "2026-11-23T09:00:00+08:00"
}
```

- **状态映射**：
  - 入站：join `inbound_processing.status`，返回 `processing | done | failed`；没有状态行时按 `failed` 并记录告警。
  - 手机出站 Friday 回复：返回 `available`。手机不需要服务器主动推送；**只要 outbound 事件已经提交到 event_log，就代表手机 API 可以取到这条回复**。
  - 不得再用 `payload.send_ok=true → sent` 描述手机回复：手机路径没有调用 `MobileAdapter.send()`，也不存在“发送成功”这个动作。`send_ok` 只属于 Feishu/Console 等真正执行 adapter.send 的渠道。
- **手机 outbound payload 约定**：
  - `text`、`reply_to_event_id`、`client_message_id`
  - `delivery: "persisted"`（替代 `send_ok`；表示已落库、可供轮询）
  - 不写 `send_ok`；不把“数据库提交”伪装成“渠道发送成功”。
- **排除**：`tool_call`、`tool_result`、`note`、`memory_context`、`delivery`、`trigger` 等事件不得进入 chat 历史。
- **错误**：401/403；400 非法 limit/cursor；200 空列表。
- **状态不会通过 after 增量自动更新**：after 只返回“新事件”；已存在的 inbound 消息从 processing 变成 done/failed 不会产生新事件。客户端必须额外刷新这些消息的状态（见 7.2.3）。
- **状态枚举**：`processing | done | failed | available`。其中 `processing/done/failed` 只用于入站，`available` 只用于手机出站；不要混用 `sent`。

#### 7.2.3 查询单条状态

```http
GET /api/mobile/chat/messages/{id}
```

- **认证**：同 Today；必须校验 `event.user_id == 当前用户` 且 `channel='mobile'`，否则 404。
- **响应**：同 7.2.2 的单条结构。
- **入站消息**：包含 `status`；如果有 outbound 回复，返回 `replyToId` 或 `reply` 摘要。
- **用途**：POST 返回 202 后，客户端可以用 `id` 轮询这一条。**对于 processing 的入站消息，这是必须使用的补偿接口**；列表增量只能发现新消息，不能替代状态补偿。
- **错误**：404 不存在/不属于当前用户；401/403。

**7.2.3.1 客户端必须如何处理 processing → done/failed**

1. `RemoteChatRepository` 维护 `Set<String> _pendingInboundIds`。
2. POST 返回 202 且 `status=processing` 时，把 `id` 加入集合。
3. 首屏/增量历史中任何 `role=user` 且 `status=processing` 的消息，也加入集合。
4. 每次轮询（或独立的 2 秒状态 tick）对集合中的每个 `id` 调用 `GET /api/mobile/chat/messages/{id}`：
   - `processing`：本地消息保持 `pending`，UI 显示“Friday 正在处理”，继续跟踪。
   - `done`：本地消息转 `synced`，移出集合；回复消息会由增量历史带回。
   - `failed`：本地消息转 `failed`，移出集合，显示错误提示；用户可以用**新的 clientMessageId** 重新发送，或由后续阶段提供 failed 重试接口。
5. 集合上限（建议 20）。超限时不要无限增长；退化为“刷新最近一页历史并读取其中 status”，或后续增加批量状态接口 `POST /api/mobile/chat/messages/status`（U2-A 不强制）。
6. `setActive(false)` / dispose 时停止状态 tick；`setActive(true)` 时立即执行一次状态刷新，然后恢复定时轮询。
7. 不允许只靠 after 轮询就断定“还在思考”；after 没有新事件不代表 processing 没有变成 failed。

**UI 状态建议**：

- 入站 `processing`：`TextMessage.syncState = pending`，气泡显示“Friday 正在处理”（新增 `S.chatProcessing`）。
- 入站 `failed`：`TextMessage.syncState = failed`，显示“处理失败”与“重新发送”；重新发送必须使用新的 `clientMessageId`，不能复用已 failed 的旧 id（旧 id 会返回既有 failed 事件）。
- 入站 `done`：显示为已发送；Friday 回复作为单独消息出现。
- 手机出站 `available`：在 Flutter 中映射为 `TextMessage.syncState = synced`；它表示“已落库可取”，不表示“手机推送成功”。
- 测试断言：手机 outbound payload 为 `delivery="persisted"` 且**没有 `send_ok`**；chat API 返回 `status="available"`。

### 7.3 错误与状态约定

| 场景 | HTTP | 响应 |
|---|---|---|
| 未登录/缺少头 | 401 | `{"detail": "缺少 X-Butler-User"}` |
| 用户不在白名单 | 403 | `{"detail": "用户不在白名单"}` |
| 文本为空/超长 | 400 | `{"detail": "..."}` |
| clientMessageId 缺失/超长 | 400 | `{"detail": "..."}` |
| Idempotency-Key 与 clientMessageId 不一致 | 400 | `{"detail": "Idempotency-Key 必须与 clientMessageId 一致"}` |
| 重复发送同 key | 200 | 既有事件 + 当前状态 |
| 消息处理中 | 200/202 | `status: processing` |
| 处理失败 | 200 | `status: failed`（终态，客户端提示重发） |
| 消息不存在/非本人 | 404 | `{"detail": "消息不存在"}` |

### 7.4 认证边界

- U2-A 继续使用开发期 `X-Butler-User`。
- 该方案**只适合**：
  - 本机开发（api 绑定 `127.0.0.1`）；
  - 通过 `adb reverse` 连接本机 api 的受控手机调试。
- **`ALLOWED_OPEN_IDS` 不是认证**：它只检查标识是否在名单内，不验证请求者身份。即使配置了白名单，也不允许把 API 暴露到普通局域网或公网。
- 公网部署前必须补：真实登录态（JWT/OAuth/设备绑定）、请求签名/HTTPS、速率限制、审计。U2-A 不做这些，但报告必须明确不能直接把该 API 暴露公网。

---

## 第八部分：分批开发计划

### U2-A1：后端消息入口

**目标**：手机消息能以已有 User 进入 Pipeline，并能落库、生成 processing 状态，不创建手机身份。

**修改文件**：

- 修改 `app/engine/pipeline.py`（`ingest_for_user`）
- 新增 `app/api/routes/mobile_chat.py`（**本批只做 POST 接收入口**）
- 修改 `app/main.py`（挂载 chat router；**本批不注册 MobileAdapter**）
- 新增 `tests/integration/test_pipeline_mobile.py`
- 新增 `tests/integration/test_mobile_chat_api.py`（本批先覆盖 POST）

**开发内容**：

1. `ingest_for_user(event, user)`：
   - 跳过 `get_or_create_user`；
   - 复用 `append_event` + `InboundProcessing`；
   - 写入 `channel="mobile"`、`type="message"`、`payload.text`、`payload.client_message_id`；
   - 返回与 `ingest` 相同的 `IngestedEvent`。
2. `app/api/routes/mobile_chat.py` 的 `POST /api/mobile/chat/messages`：
   - 复用 `get_mobile_user`；
   - 校验 clientMessageId/text；
   - 调用 `ingest_for_user`；
   - **只落库，不 `spawn(process)`、不调用 Friday Agent**；重复事件不处理；
   - 返回 202（新）/200（重复），带事件 id 与 status=processing。
3. 本批不注册 MobileAdapter，`recover_unfinished` 会因没有 mobile adapter 跳过手机事件；A2 注册后再启用处理。
4. 测试：已有用户复用、无新 ChannelIdentity、同 key 重复只落一条、不同用户同 key 互不影响、POST 参数校验/权限、`Idempotency-Key` 与 `clientMessageId` 不一致返回 400；断言没有 outbound/tool 事件、没有 Agent 调用。

**前置依赖**：无。

**完成标准**：

- 手机 POST 能落库并返回 202/200；
- `inbound_processing` 为 processing；
- 不产生 `channel_identity(channel='mobile')`；
- **本批不启动真实 Agent、不产生 outbound、不执行工具**；
- 本批不要求 GET 历史/状态；
- 现有 Feishu/Console 测试不回归。

> 注意：A1 单独部署时手机消息会停留在 processing；A2 注册 MobileAdapter 后，API 服务的 `recover_unfinished()` 才会接手处理。U2-A 未完成 A2 前不要对外启用手机聊天。

### U2-A2：后端回复与历史隔离

**目标**：Friday 回复正确落库、与用户消息关联；手机/飞书短期上下文隔离；历史 API 可用。

**修改文件**：

- 新增 `app/adapters/mobile_adapter.py`
- `app/engine/pipeline.py`（手机 outbound 同事务、reply_to_event_id、mobile-reply 幂等键）
- `app/agents/friday/agent.py`（传 channel）
- `app/agents/friday/history.py`（channel 过滤）
- 修改 `app/api/routes/mobile_chat.py`（**新增 GET 历史、GET 单条状态**）
- `app/main.py`（注册 MobileAdapter）
- 扩展 `tests/integration/test_mobile_chat_api.py`（GET/状态）
- 新增 `tests/integration/test_friday_history_isolation.py`
- 扩展 `tests/integration/test_idempotency.py`

**开发内容**：

1. 注册 `MobileAdapter`；A1 的 POST 在 A2 开始 `spawn(process)`。
2. `build_history(..., channel=channel)` 加 channel 条件。
3. 手机 `_process_one`：agent 返回后，在同一事务写 outbound（含 `reply_to_event_id`、`client_message_id`、`delivery="persisted"`）和 `inbound_processing(done)`；outbound 使用 `mobile-reply:{inbound_event_id}` 幂等键。手机分支写入后直接返回，跳过现有 `adapter.send` + transaction B；不要重复写 outbound。
4. 在 A1 的 POST 基础上新增 GET 历史、GET 单条状态；查询只取 mobile message；首屏取最新 N 条再升序返回。
5. 按 user_id 串行处理（见 M1；单进程限制）。
6. 测试：手机/飞书历史隔离；回复关联；重复 recovery 不重复回复；幂等；首屏/after/before 分页；processing→failed 状态可查；API 服务重启后能恢复 mobile processing 事件。

**前置依赖**：U2-A1。

**完成标准**：

- 手机 Agent 读不到飞书历史，飞书读不到手机历史；
- outbound 事件含 `reply_to_event_id`、`delivery="persisted"`，不含 `send_ok`；
- 同一入站事件最多一条 outbound；
- chat API 只返回 mobile message；手机 outbound 状态为 `available`；
- 首屏返回最近 N 条（升序）；after/before 游标语义正确；
- GET 单条能反映 processing→done/failed 的最新状态。

### U2-A3：Flutter 真实聊天接入

**目标**：Chat 页面从 Mock 切到真实后端，支持发送、历史恢复、轮询回复、失败重试。

**修改文件**：

- `mobile/lib/domain/repositories/chat_repository.dart`
- `mobile/lib/domain/models/chat_message.dart`
- 新增 `mobile/lib/data/remote/remote_chat_repository.dart`
- `mobile/lib/data/mock/mock_chat_repository.dart`
- `mobile/lib/core/providers.dart`
- `mobile/lib/features/chat/chat_controller.dart`
- `mobile/lib/features/chat/chat_page.dart`
- `mobile/lib/shell/shell_scaffold.dart`
- `mobile/lib/core/strings.dart`
- 新增/修改测试：`remote_chat_repository_test.dart`、`chat_page_test.dart`、`mock_chat_repository_test.dart`、`app_providers_test.dart`

**开发内容**：

1. `ChatRepository.sendText` 增加 `clientMessageId`；`setActive(bool)`。
2. `TextMessage` 增加 `serverId/clientMessageId/replyToId`。
3. `RemoteChatRepository`：
   - 初始 GET 最近 N 条（后端已按最新 N 条返回升序）；
   - 轮询增量（单飞、失败退避、停止条件）；
   - `_pendingInboundIds` + 单条状态补偿，发现 processing→failed；
   - 乐观消息、发送失败标记、重试复用 ID；
   - 合并去重，不整表覆盖；setActive(true) 内部立即刷新。
4. `chatRepositoryProvider` 按 `USE_REMOTE` 选择；默认 Mock 不变。
5. `ChatPage` 前后台/可见性控制；远程错误横幅。
6. 测试：历史、发送、回复、失败、重试、前后台、Mock/Remote 切换。

**轮询实现位置（具体到文件）**：

- `mobile/lib/data/remote/remote_chat_repository.dart`：
  - 字段：`Timer? _pollTimer`、`bool _inFlight`、`bool _active`、`String? _cursor`、`List<ChatMessage> _messages`、`Set<String> _pendingInboundIds`
  - 方法：`_startPolling()`、`_stopPolling()`、`_pollOnce()`、`_refreshPendingStatuses()`、`_merge(List<ChatMessage>)`、`_emitIfChanged()`
  - 单飞：`_pollOnce` 入口检查 `_inFlight`；请求结束在 `finally` 复位
  - 启动：`watchMessages` 首次历史成功后，如果 `_active` 为真则 `_startPolling`
  - 立即刷新：`setActive(true)` 内部统一执行“立即 `_pollOnce` + `_refreshPendingStatuses`，再启动定时器”；**ChatPage 不直接调用 `_pollOnce` 等私有方法**
  - 状态补偿：`_pollOnce` 拉取 after 增量；`_refreshPendingStatuses` 对 `_pendingInboundIds` 逐条调用 `GET /api/mobile/chat/messages/{id}`，处理 processing→done/failed（见 7.2.3.1）
  - 停止：`setActive(false)`、`dispose`、初始历史失败且未恢复时
  - 旧回复覆盖：只按 `after` 增量合并，按 `id/clientMessageId` 去重，不整表替换；已存在的 inbound 状态变化由 `_refreshPendingStatuses` 更新
- `mobile/lib/features/chat/chat_page.dart`：
  - 改为 `ConsumerStatefulWidget`，实现 `WidgetsBindingObserver`
  - `didChangeAppLifecycleState`：`paused/inactive` → `chatController.setPollingActive(false)`；`resumed` → `chatController.setPollingActive(true)`；立即刷新由 Repository 的 `setActive(true)` 内部完成，**不要**从 ChatPage 调用 `_pollOnce()`
  - Tab 可见性：优先使用 `ShellScaffold` 暴露的当前 Tab Provider；如果 go_router 18 的 `indexedStack` 已对非活动分支关闭 `TickerMode`，也可以监听 `TickerMode.of(context)`。不要仅依赖页面 `dispose`，因为 shell 会保留分支状态。
- `mobile/lib/shell/shell_scaffold.dart`：
  - 新增/更新一个当前 Tab Provider（例如 `selectedTabProvider`），在 `NavigationBar.onDestinationSelected` 中写入；Chat 页监听它，切走时暂停轮询。
- `mobile/lib/features/chat/chat_controller.dart`：
  - 新增 `setPollingActive(bool)`，转发给 `ChatRepository.setActive`；Mock 实现为 no-op。
  - 轮询错误写入 `syncError`（或独立连接 Provider），页面显示横幅；不要关闭消息流。

**前置依赖**：U2-A2 的 API。

**完成标准**：

- 真实模式发送文字后能看到 Friday 回复；
- App 重启后初始 GET 返回最近 N 条 mobile 历史（升序），不是最早 N 条；
- processing 的入站消息变为 failed 时，页面能通过单条状态补偿发现并显示失败；
- 发送失败可重试，且服务端不重复执行；
- 前后台切换由 `setPollingActive` 控制，回前台立即刷新；
- Mock 模式仍可用，数据源不混用。

### U2-A4：日常工具端到端验证

**目标**：手机聊天能创建/查询任务、提醒、日程、笔记，并与飞书共享业务数据。

**修改文件**：

- `app/tools/tasks.py`（新增 `update_task`）
- `app/tools/reminders.py`（新增 `update_reminder`）
- `app/tools/notes.py`（新增 `list_notes`）
- `app/tools/registry.py`（注册三个工具）
- 新增 `tests/integration/test_mobile_chat_tools.py`
- 可能修改 `app/tools/blocks.py`（统一改期校验）

**开发内容**：

1. 用 FakeProvider 脚本让 Friday 在手机渠道调用工具；
2. 验证任务/提醒/日程按 user_id 落库；
3. 用 Console/Feishu 渠道查询同一用户数据；
4. 反向：Console/Feishu 创建，手机查询；
5. 验证工具事件 channel=mobile、source_event_id 正确；
6. 实现并验证三个新增工具：
   - `update_task`：修改标题/描述，不新建任务；
   - `update_reminder`：用行锁/原子条件更新现有 trigger 的 fire_at/expires_at/payload.note，trigger id 不变，不产生第二条 trigger；被 Worker claim 时明确失败；
   - `list_notes`：查询当前用户历史笔记；
7. 统一 `reschedule_block` 与移动端 Today 改期规则：终态/跨天/最短 5 分钟；补 Chat 与 Today 的对照 E2E。
8. 工具只执行一次，重复消息不重复创建/更新。

**前置依赖**：U2-A1/A2/A3。

**完成标准**：

- 手机创建的任务在 Console/飞书可见，反之亦然；
- 手机修改任务/提醒后，另一渠道查询到更新后的值；
- `update_reminder` 前后 trigger id 相同、只更新一条；
- `list_notes` 能返回当前用户最近笔记，且多用户隔离；
- 工具只执行一次，重复消息不重复创建/更新；
- 不复制一套手机专用任务/提醒工具。

### U2-A5：可靠性与整体验收

**目标**：验证崩溃恢复、重复请求、多用户隔离、网络异常与整体验收。

**修改文件**：

- 测试为主；可能微调 Pipeline/RemoteChatRepository。
- `docs/feature-status-matrix.md`、`mobile/README.md` 更新。

**开发内容**：

1. 模拟“agent 已 commit、outbound 未写”崩溃，验证手机恢复不重复工具/回复；
2. 并发同 clientMessageId；
3. 多用户同时聊天；
4. 轮询失败/恢复、App 后台/前台；
5. 全量 analyze/format/test/build apk；
6. 后端 ruff/mypy/pytest。

**前置依赖**：U2-A1–A4。

**完成标准**：

- 第九部分 10 项验收全部通过；
- 测试与静态检查全绿；
- 文档更新，明确 U2-A 边界与未做项。

---

## 第九部分：验收测试计划

| # | 场景 | 预期 | 测试层 |
|---|---|---|---|
| 1 | 手机正常聊天 | POST 返回 202；轮询看到用户消息和 Friday 文本回复；回复有 replyToId | 后端 API + Flutter 仓库/页面 |
| 2 | 手机创建任务 | 手机说“建个任务…”，工具创建 `work_item(user_id=同一用户)`；回复确认 | 后端工具 E2E |
| 3 | 飞书查询手机创建的任务 | Console/Feishu 渠道的 Agent 调 `list_tasks`，能看到手机创建的任务 | 后端跨渠道 E2E |
| 4 | 手机查询飞书创建的任务 | 手机 Agent 调 `list_tasks`，能看到 Console/Feishu 创建的任务 | 后端跨渠道 E2E |
| 5 | 手机与飞书聊天历史隔离 | 手机 chat API 只返回 channel=mobile；手机 Agent 的 system prompt 历史不包含 Feishu；反之亦然 | 后端 API + Agent 历史测试 |
| 6 | 短期上下文隔离 | 手机连续两轮对话能引用手机上一轮；不能引用 Feishu 上一轮 | FakeProvider 检查 messages |
| 7 | 重复请求不重复执行工具 | 同一 clientMessageId 重试两次，只产生一条入站事件、一个任务/提醒、一条回复 | 后端幂等/恢复测试 |
| 8 | App 重启恢复历史 | 关闭并重开 App，Chat 初始 GET 返回**最近 N 条** mobile 消息（升序展示），顺序正确、无重复；不是最早 N 条 | Flutter 仓库/页面测试 + 后端 API |
| 9 | 多用户数据隔离 | 用户 A/B 同 clientMessageId，各自只看到自己的消息/任务/提醒 | 后端 API/工具测试 |
| 10 | 网络异常与后台恢复 | 发送失败显示错误并可重试；processing→failed 能通过单条状态接口发现；轮询失败保留旧消息并提示；App 后台停止轮询，回前台由 setActive(true) 立即刷新 | Flutter 仓库/页面测试 |

补充测试：

- 同一用户快速发送两条消息，回复顺序与发送顺序一致（per-user 串行）。
- 用户已有 500 条历史时，首次 GET 返回最近 50 条（升序展示），不是最早 50 条。
- processing 的入站消息在后台变为 failed 后，客户端通过单条状态接口发现并显示失败，不会一直停在“正在处理”。
- 手机 Friday 回复落库后，chat API 返回 `status="available"`；outbound payload 为 `delivery="persisted"`，没有 `send_ok`，也不出现 `sent`。
- 处理失败（failed）后，用户用新的 clientMessageId 重发可正常处理；同 clientMessageId 不会重新执行。
- 手机修改任务标题/描述后，飞书/Console 查询到新值。
- 手机修改提醒时间后，trigger id 不变、只更新一条、expires_at 同步更新、不产生第二条 trigger。
- 提醒已被 Worker claim 时，`update_reminder` 返回明确错误，不出现“数据库已改但按旧时间执行”的静默不一致。
- 手机查询历史笔记，返回当前用户最近笔记且不包含其他用户。
- 通过 Chat 和 Today 页面分别对终态/跨天/不足 5 分钟的日程改期，得到一致的失败结果；合法改期都成功。
- `ENABLE_MOBILE_API=0` 时 chat 路由 404。
- 白名单外用户 403；无 `X-Butler-User` 401。
- `Idempotency-Key` 与 `clientMessageId` 不一致时 400；一致或缺省时按 body 幂等。
- API 进程重启后能恢复 mobile processing 事件，并保持同一 user_id/channel；只有 feishu adapter 的进程不会处理 mobile 事件。
- 手机消息能写入长期记忆抽取队列（只验证写入路径，不验证注入读取）。
- `MEMORY_INJECT_ENABLED=false` 时手机 Agent 不注入记忆。
- `event_log` 查询不会返回 tool/note/memory_context/delivery 事件。
- Feishu/Console 现有测试全部不回归。

---

## 第十部分：最终结论

### 10.1 U2-A v1.0 是否可以直接进入开发？

**不能直接按原方案开发，需要先做方案修订。**  
不是因为架构不可行，而是因为方案中有几处与当前代码事实不一致，且聊天隔离、幂等这些原则必须先用代码落实：

1. 当前 `build_history` 没有渠道隔离，手机/飞书短期上下文会串线。
2. 当前 Pipeline 没有 `ingest_for_user`，直接复用会尝试创建 `channel=mobile` 的 `ChannelIdentity`，被数据库 CHECK 拒绝或产生错误用户。
3. 当前 Pipeline 没有 `mobile` adapter，手机会在 process 阶段 KeyError。
4. 当前 outbound 事件没有持久化 `reply_to_event_id`，聊天回复无法关联用户消息。
5. 当前 ChatRepository 的 `sendText` 没有 `clientMessageId`，网络重试无法保证消息幂等。
6. 当前工具没有“修改任务/提醒、查询笔记”能力，方案目标与工具覆盖不一致。
7. Agent 重跑存在重复工具执行/重复回复风险；手机路径需要“回复与 Agent 同事务 + outbound 幂等键”。

### 10.2 是否需要先修订技术方案？

**需要，但只需局部修订，不需要推翻整体架构。**  
建议修订点：

- 明确 `ingest_for_user(event, authenticated_user)` 是手机入口的唯一方式。
- 明确 `MobileAdapter` 为 no-op adapter，只用于 Pipeline 注册与恢复，不承担实际发送。
- 明确手机 outbound 回复与 Agent/工具同事务落库，并使用 `mobile-reply:{inbound_event_id}` 幂等键。
- 明确手机 outbound 状态为 `delivery="persisted"` / API `available`，不使用 `send_ok` 或 `sent`。
- 明确 `build_history` 增加 channel 参数；长期记忆检索不加 channel。
- 明确 Chat API 的三个端点、消息结构、幂等键、分页和状态。
- 明确首屏历史取最新 N 条再升序返回；after 只做增量；before 用于更早历史。
- 明确 Flutter `ChatRepository.sendText` 增加 `clientMessageId`，重试复用原 id；RemoteChatRepository 必须补偿 processing→done/failed 状态。
- 明确 U2-A 的工具覆盖范围：**保留原范围，在 U2-A4 新增 `update_task`/`update_reminder`/`list_notes`**，不收窄验收。
- 明确 U2-A 仍为开发期 `X-Butler-User` 认证，只允许本机/`adb reverse`，不适用局域网或公网。
- 明确 U2-A 只支持单进程 api；多 worker/多副本的用户串行需要跨进程机制，留到后续。

### 10.3 是否存在阻止开发的高风险问题？

有，但都是“必须先解决的具体实现问题”，不是“必须重写系统”：

1. 跨渠道历史隔离（必须改 `history.py`）。
2. `ingest_for_user` 与 `MobileAdapter`（必须新增）。
3. 手机 outbound 回复同事务 + 幂等（必须改 `pipeline.py`）。
4. `clientMessageId` 贯穿 API/Repository/Controller（必须改接口）。
5. 工具覆盖缺口：已确认保留原范围，U2-A4 新增 `update_task`/`update_reminder`/`list_notes`。
6. 开发期 `X-Butler-User` 认证不能直接上公网；U2-A 只允许本机或 `adb reverse`（部署边界）。
7. `asyncio.Lock` 只支持单进程 api；多 worker/多副本需要跨进程协调（运行环境边界）。

### 10.4 推荐的最小改动路径

1. **U2-A1**：`ingest_for_user` + 手机 POST 入口 + 状态初始化 + 测试；**只落库，不启动 Agent**。
2. **U2-A2**：MobileAdapter + 手机安全处理路径（Agent/工具/outbound/done 同事务 + 幂等）+ `build_history` channel 过滤 + chat GET/单条状态 + 首屏最新 N 条 + per-user 串行（单进程）+ 恢复测试。
3. **U2-A3**：Flutter `ChatRepository` 增加 `clientMessageId`；`TextMessage` 增加服务端 id/replyTo；新增 `RemoteChatRepository` 轮询、pending 状态补偿、生命周期；Provider 切换；测试。
4. **U2-A4**：工具 E2E；新增 `update_task`/`update_reminder`/`list_notes`，并统一 `reschedule_block` 与 Today 改期规则。
5. **U2-A5**：崩溃恢复、重复请求、多用户、网络异常、单进程约束验证、全量检查与文档。

这条路径复用现有 Friday Agent、工具、event_log、InboundProcessing、TaskManager、Today API 模式和 ApiClient；不需要新建聊天表，不需要新增 ChannelIdentity，不需要数据库迁移。

### 10.5 哪些内容应留到后续阶段？

- Jarvis 专题对话、长期任务、重规划、周复盘。
- 手机系统通知、后台推送、通知权限。
- WebSocket/SSE、真实流式回复。
- 语音、图片、文件输入。
- 长期记忆自动读取/注入（`MEMORY_INJECT_ENABLED` 保持关闭）。
- 多会话、会话同步协议、`ConversationSyncEngine`、多端已读/未读。
- 公网真实认证、HTTPS、速率限制、设备管理（U2-A 只允许本机或 `adb reverse`，不能用 `ALLOWED_OPEN_IDS` 代替认证）。
- 多 API worker/多副本下的跨进程用户串行（U2-A 只支持单进程 `asyncio.Lock`）。
- Feishu 聊天回复的完整 outbox/发送幂等（U2-A 只处理手机路径；共享 Pipeline 的 Feishu 发送幂等作为后续可靠性工作）。
- 任务/提醒的语义级业务幂等（当前只有入站事件 + 调用序号幂等）。

### 10.6 审查结论一句话

**U2-A 可以基于现有 Friday Agent、工具和 event_log 实现，但不能直接照搬方案：先补手机专用入口、渠道隔离、回复关联、首屏最新历史、pending 状态补偿和客户端幂等，并在 U2-A4 补齐 `update_task`/`update_reminder`/`list_notes`；按 U2-A1–A5 分批开发，不需要新数据库表或迁移。**

---

## 审查执行记录

### 后端

命令：

```bash
wsl -d Ubuntu --cd "/mnt/e/F&J/FJ v1" -- bash -lc "uv run ruff check app tests scripts && uv run mypy app && uv run pytest -q"
```

结果：

- ruff：`All checks passed!`
- mypy：`Success: no issues found in 92 source files`
- 全量 pytest：本次运行在 `[ 29%]` 后长时间无进展，手动停止；不记为通过。
- 相关集成测试：`40 passed`（命令见 1.5）。
- 背景参考：当前 HEAD 之前一次同生产代码的全量运行为 `244 passed, 1 skipped`；之后只新增了一个测试与一行注释，生产逻辑未变。

### Flutter

命令：

```powershell
Set-Location "E:\F&J\FJ v1\mobile"
$env:FLUTTER_ROOT="D:\flutter"
$env:ANDROID_HOME="E:\AutoPunch\.android-sdk"
$env:ANDROID_SDK_ROOT="E:\AutoPunch\.android-sdk"
$DART="D:\flutter\bin\cache\dart-sdk\bin\dart.exe"
$FLUTTER="D:\flutter\packages\flutter_tools\bin\flutter_tools.dart"
& $DART $FLUTTER --no-version-check analyze
& $DART $FLUTTER --no-version-check test
```

结果：

- analyze：`No issues found!`
- test：`111 passed`，3 项截图生成测试默认跳过。
- 备注：首次以后台方式同时执行 analyze/test 时，Flutter SDK `D:\flutter\bin\cache\lockfile` 报权限/占用错误；前台单独重跑成功。该失败属于执行环境，不是代码失败。

### 未执行项

- 未执行 `build apk --debug`（本次为审查任务，未改 UI；上一轮基线已有构建记录，但不作为本次结果）。
- 未执行真实 LLM/真实飞书端到端（需要外部凭据与运行环境）。
- 未执行数据库迁移（U2-A 不需要迁移）。
