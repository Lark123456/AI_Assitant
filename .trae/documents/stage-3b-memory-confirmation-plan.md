# 阶段 3b 收尾实施计划（记忆注入默认开启 / confirmed 升级 / 确认卡片）

## Context

阶段 3b 现状：记忆检索注入代码已完成但默认关闭；`remember` 冲突会创建 `status=pending` 的记忆并返回 `pending_confirmation`，但没有确认写入路径，也没有真实卡片交互；手机 Remote Chat 的 `respondToCard` 直接抛 `UnsupportedError`。

本次目标（用户已确认）：
1. `MEMORY_INJECT_ENABLED` 默认改为 true，并补验证。
2. `remember` 冲突时不再降低旧记忆权重（保留 `contradict_count` 计数）。
3. 用户确认后把 pending 记忆升级为 `confirmed` 并 supersede 旧记忆；拒绝则 `retracted`，旧记忆保持 active。
4. 手机 Chat 展示记忆确认卡片，提供“确认替换 / 保留原值”双按钮，远程应答走真实后端。

## 一、后端记忆确认状态机

新增 `app/memory/confirm.py`：

- `decide_pending_memory(session, *, user, pending_id, confirm, clock) -> str`
  - `SELECT ... FOR UPDATE` 锁 pending 行；校验 `user_id` 与 `status`。
  - **确认**：
    - pending → `status=active`、`source_class=confirmed`、`weight=initial_weight("confirmed")`（1.0，按现有权重表）。
    - 若 `supersedes_id`：锁旧行并校验仍为 active；若旧记忆已非 active，则把 pending 置 `retracted`（reason `stale_target`），返回 `rejected`，避免同一槽位出现两个 active。
    - 同一旧记忆若还有其它 pending，全部置 `retracted`（reason `superseded_pending`），防止后续确认产生多条 active。
    - 旧记忆置 `superseded`、`superseded_at=now`。
    - 写 `MemoryDecisionLog(action="SUPERSEDE", reason="user_confirmed")`。
  - **拒绝**：
    - pending → `status=retracted`、`rejected_at=now`；旧记忆不变。
    - 写 `MemoryDecisionLog(action="NOOP", reason="user_rejected")`。
  - 重复操作幂等：已 confirmed 返回 `confirmed`，已 retracted 返回 `rejected`；不报错、不重复写日志。
- 决策日志不新增 action 枚举，避免迁移；reason 稳定并写入契约。

修改 `app/memory/pipeline.py` 的 ASK 分支：保留 `contradict_count += 1`，删除 `memory.weight = contradicted_weight(...)`，即确认前不降权。清理未使用 import。

## 二、Agent / Pipeline 生成并持久化卡片

- `remember` 的 `pending_confirmation` data 增补（仅新增字段）：`pending_subject`、`pending_value`、`pending_type`、`slot_key`。
- `FridayAgent.handle` 增加 `on_card: Callable[[dict], None] | None`：
  - 工具循环中，仅当工具名 `remember` 且结果 `status == "pending_confirmation"` 时构造卡片 intent。
  - 卡片结构：`{card_type:"memory_confirm", text:"有一条记忆需要确认", items:[{item_id, label}]}`；label 由服务端生成，如“起床时间：8点（原 7点）”，客户端不解析 memory.value。
  - 一条 pending 记忆一张卡。
- `InboundPipeline` 手机分支收集卡片，在文本回复之后、同一事务内写 `event_log(type="card", direction="outbound")`：
  - 幂等键 `mobile-card:{inbound_event_id}:{pending_memory_id}`，recovery 重放不重复。
  - 即使回复为空也写卡片。
  - 卡片 `occurred_at` 比文本回复晚 1µs 递增，保证 API 排序稳定为“先文本后卡片”。
  - 非手机渠道不传 `on_card`，不产生卡片事件。

## 三、Chat API 卡片序列化与确认接口

修改 `app/api/routes/mobile_chat.py`：

- 聊天事实边界 `_chat_conditions` 与 `_resolve_cursor` 从 `type='message'` 扩展为 `type IN ('message','card')`；卡片可作为分页游标。
- `_serialize` 按类型分派：
  - 文本消息增加 `kind="text"`。
  - 卡片返回 `kind="memory_confirm"`、`items:[{itemId,label,state}]`、`allHandled`、`allConfirmed`。
  - 一次查询 Memory 状态批量 enrich：`pending→pending`、`retracted→rejected`、`confirmed/superseded 且 source_class=confirmed→confirmed`；缺失按 `rejected`（避免永久 pending）。
- 新增 `POST /api/mobile/chat/messages/{id}/card-actions`：
  - body `{action:"confirm"|"reject", itemId?}`；`itemId` 省略表示该卡片全部 items。
  - 校验卡片事件属于当前用户、`channel=mobile`、`type=card`，且 itemId 必须在卡片 payload 内（防越权）。
  - 逐项调用 `decide_pending_memory`，commit 后返回 enrich 后的卡片。
  - `Idempotency-Key` 可选；重复请求天然幂等。
- `GET /messages/{id}` 与 SSE 仍只接受文本入站消息；卡片不进 SSE，卡片在下一轮轮询出现（≤2 秒）。

## 四、Flutter 卡片解析与应答

- `RemoteChatRepository._parseMessage` 返回 `ChatMessage`：
  - `kind == 'memory_confirm'` → `MemoryConfirmCard`（items 映射 itemId/label/state）。
  - `kind` 缺失或 `text` → 现有 `TextMessage`；未知 kind 且无 text 时跳过，避免整页失败。
- `_merge` 改为 `List<ChatMessage>`；卡片按 `id` 替换以更新状态，不只处理 TextMessage。
- `_signatureOf` 必须包含卡片 items 的 state，否则状态变化不会触发流发射。
- `RemoteChatRepository.respondToCard`：
  - `MemoryAction` → `{action: confirmed?'confirm':'reject', itemId}`；`ConfirmAllMemoryAction` → `{action:'confirm'}`；其它卡片仍 `UnsupportedError`。
  - POST `/api/mobile/chat/messages/{cardId}/card-actions`，带幂等键；解析返回 items 更新本地卡片并 emit；失败保留原状态并向 UI 抛错。
- `_MemoryCardView`：每个 pending item 显示“确认替换”“保留原值”两个按钮，调用 `respondToCard`；已处理项显示“已完成/已跳过”。移除仅有的“确认全部”按钮（模型与 Mock 仍保留 ConfirmAll 能力）。
- 新增文案：`memoryConfirmReplace`、`memoryKeepOld`；操作失败 SnackBar 复用 `S.actionFailed`。
- 测试：卡片解析、应答请求体/路径、状态更新触发流、未知 kind 降级、UI 双按钮。

## 五、注入默认开启与文档

- `app/core/config.py`：`memory_inject_enabled: bool = True`。
- `.env.example`：`MEMORY_INJECT_ENABLED=true`（显式 false 仍可关闭）。
- 修正依赖默认关闭的测试：`test_mobile_chat_reliability` 的 `enabled is False` 断言改为 true，并保留一条显式 false 的用例。
- 文档：
  - `docs/contracts.md`：更新默认开启、确认状态机、`card` 事件 payload、卡片 API、MemoryDecisionLog reason。
  - `docs/feature-status-matrix.md`：阶段 3b 项标记完成，更新测试计数。
  - `mobile/README.md`：记忆确认卡片与远程应答说明。

## 六、实施顺序与验证

1. 后端状态机 + ASK 不降权 + 测试。
2. Agent on_card / remember 字段 / Pipeline 落卡 + 测试。
3. Chat API 卡片序列化 + card-actions + 分页/游标测试。
4. Flutter 解析 / respondToCard / UI + 测试。
5. 注入默认开启 + 测试修正 + 文档。
6. 每批运行：后端 `ruff`、`mypy app`、相关 `pytest`；移动端 `analyze`、`dart format --output=none --set-exit-if-changed lib test`、`flutter test`、`build apk --debug`。最终跑后端全量 pytest。

### 关键测试

- ASK 不再降权，`contradict_count` 仍 +1。
- 确认：pending→active+confirmed，旧记忆 superseded，weight=1.0，日志 SUPERSEDE。
- 拒绝：pending→retracted，旧记忆 active 且权重不变。
- 重复确认/拒绝幂等；旧记忆已 superseded 时 pending 置 retracted（stale）；同旧记忆多条 pending 只保留一条 active。
- 手机 remember 冲突：文本回复 + 卡片同事务；空回复仍落卡；recovery 重放不重复卡片。
- Chat API：卡片进入首屏/分页；状态 enrich；确认/拒绝后 GET 反映新状态；越权 card/itemId 404/400。
- 注入默认 true 与显式 false 两条路径。
- Flutter：卡片解析、双按钮、POST 请求体、状态变化触发流、未知 kind。

## 明确边界

- 不做记忆中心/列表页；确认交互只通过 Chat 卡片。
- 异步抽取产生的 pending 记忆没有卡片入口，保持 pending，不影响检索。
- 不新增数据库表或迁移；不新增 Flutter 依赖。
- 卡片是手机持久化事件，不代表 MobileAdapter 支持主动推送或按钮推送。
- 飞书/Console 仍只收文本回复，不渲染卡片。
