# Butler 功能对照表

> 核对日期：2026-11-24  
> 代码基线：`master`（U2-B 完成）  
> 口径：以已确认的契约与执行计划为准，对照当前代码、测试与运行配置。  
> 依据：[contracts.md](./contracts.md)、[system-guide.md](./system-guide.md)、[mobile-u1-plan.md](./mobile-u1-plan.md)、[deferred/mobile-sync-and-topics.md](./deferred/mobile-sync-and-topics.md)、代码与测试。  
> 说明：`system-guide.md` 第二节的能力清单停留在阶段 3a，本表以当前代码为准；两者冲突时以本表与 `contracts.md` 为准。

## 一、结论摘要

- 后端 P0 阶段 1–3b 的主体机制已经落地：飞书渠道、Friday 工具调用、提醒/简报/主动消息、LLM 网关与审计、记忆写入与检索。
- 记忆检索注入代码已完成，但 `MEMORY_INJECT_ENABLED` 默认关闭，当前 `.env` 未开启；线上 Friday 还不会主动使用长期记忆。
- Jarvis 慢通道仍是零代码：只有 `work_item` 层级字段、`assigned_by=jarvis` 枚举和模型别名预留。
- Mobile U1 已完成；默认仍使用 Mock。U2 已接入 Today 读写、Chat（含 SSE 流式）、任务页、我的页（只读资料）与应用内提醒；OS 通知/推送、同步协议、多会话与 Jarvis 专题仍未开始。

## 二、阶段完成度与口径

### 2.1 阶段完成度

| 阶段 | 范围 | 状态 |
|---|---|---|
| 阶段 1 | 飞书长连接、Friday 工具调用、trigger 状态机、LLM 网关、幂等与审计 | 已完成 |
| 阶段 2 | 日程块、晨间/晚间简报、主动消息仲裁、物化器 | 已完成 |
| 阶段 3a | 记忆写入管线：异步抽取、校验、裁决、决策日志、评测 | 已完成 |
| 阶段 3b | 记忆读取与 prompt 注入 | 部分完成：代码完成，默认关闭；`confirmed` 升级与确认交互未做 |
| 阶段 4 | Jarvis 慢通道、长期任务、重规划、周复盘、任务专属记忆 | 未开始 |
| Mobile U1 | Flutter Mock 版：外壳、今日页、对话页、调试面板 | 基本完成；真机验收待补 |
| Mobile U2 | 真实后端接入、任务/我的页、通知 | 进行中：Today/Chat（SSE 流式）/任务页/我的页/应用内提醒已接入；OS 通知未接 |
| Mobile U3 | 同步协议、多会话与 Jarvis 专题 | 未开始 |

### 2.2 阶段口径

| 阶段 | 含义 | 当前状态 |
|---|---|---|
| 阶段 3b 收尾 | 记忆确认升级 `confirmed`、确认交互、检索注入启用与实机验证 | 契约已预留，未完成 |
| 阶段 4 | Jarvis 慢通道、长期任务立项/拆解/规划、重规划、周复盘、任务专属记忆 | 契约仅预留任务专属记忆表，尚无正式计划 |
| Mobile U2 | 真实后端接入、任务页/我的页、系统通知、真实流式 | 进行中：Today/Chat（SSE）/任务页/我的页/应用内提醒已落地；OS 通知与卡片应答未接 |
| Mobile U3 | 会话同步协议、多会话、Jarvis 专题、邀请幂等、PriorityAlert | 已归档到 deferred，待后端接口方案确定 |
| 未排期 | 多模态、更多渠道、多租户、iOS/HarmonyOS | 未排期 |

> 阶段 4 与 Mobile U3 是按现有契约和延后文档归纳的建议划分，不代表已正式立项；Mobile U2 已落地大部分能力。

## 三、对照表

### 3.1 渠道与基础机制

| 已确认的产品要求 | 当前实际实现 | 状态 | 后续实现阶段 |
|---|---|---|---|
| 飞书长连接收发消息，首次对话自动建档，默认时区 Asia/Shanghai 并告知用户 | 飞书 SDK 长连接独立为 `feishu` 服务；文本消息入站、自动建档、时区说明已实现（[feishu_adapter.py](../app/adapters/feishu_adapter.py)、[pipeline.py](../app/engine/pipeline.py)、[users.py](../app/engine/users.py)） | 已完成 | 无 |
| 白名单、入站去重、3 秒内快速应答、服务重启后补处理未完成消息 | `ALLOWED_OPEN_IDS` 白名单；入站幂等键优先 event_id；`inbound_processing` 记录 processing/done/failed 并在启动时补处理（[pipeline.py](../app/engine/pipeline.py)、[inbound_processing.py](../app/db/models/inbound_processing.py)、[test_pipeline_features.py](../tests/integration/test_pipeline_features.py)） | 已完成 | 无 |
| 渠道无关：核心代码不 import 飞书 SDK，出站用意图表达，由 adapter 渲染 | 核心代码不依赖飞书 SDK，`adapters/` 分为 feishu 与 console；但飞书 adapter 目前只发文本，`confirm_card` 等富卡片降级为纯文本（[base.py](../app/adapters/base.py)、[feishu_adapter.py](../app/adapters/feishu_adapter.py)） | 部分实现 | 随记忆确认/Jarvis 卡片补齐富消息渲染 |
| 全链路审计：事件日志 append-only，模型调用记录输入输出、token、耗时与错误，写操作幂等 | `event_log`、`llm_call`、`memory_decision_log`、`nudge_decision` 已落库；工具幂等键由代码派生；集成测试覆盖（[events.py](../app/engine/events.py)、[llm_call.py](../app/db/models/llm_call.py)、[test_idempotency.py](../tests/integration/test_idempotency.py)） | 已完成 | 无 |
| 多用户与多租户隔离 | `user`、`channel_identity` 已按用户隔离；`tenant_id` 字段存在但逻辑未使用 | 部分实现 | 未排期 |
| 更多渠道（微信等） | 当前只有飞书与本地 console adapter | 未实现 | 未排期 |

### 3.2 Friday 与日常工具

| 已确认的产品要求 | 当前实际实现 | 状态 | 后续实现阶段 |
|---|---|---|---|
| 建任务、查任务、完成任务 | `create_task` / `list_tasks` / `complete_task` 工具已实现，写库并写工具事件（[tasks.py](../app/tools/tasks.py)） | 已完成 | 无 |
| 设置、查询、取消提醒，到点主动推送 | `set_reminder` / `list_reminders` / `cancel_reminder` 工具与 trigger 投递已实现（[reminders.py](../app/tools/reminders.py)、[triggers.py](../app/engine/triggers.py)） | 已完成 | 无 |
| 日程块：排期、查询、完成/跳过、改期，开始前 10 分钟提醒 | `schedule_block` / `list_schedule` / `update_block_status` / `reschedule_block` 已实现；开始前提醒由物化器生成（[blocks.py](../app/tools/blocks.py)、[materializer.py](../app/engine/materializer.py)） | 已完成 | 无 |
| 随手记、修改时区、通知偏好 | `capture_note` / `set_timezone` / `set_notif_prefs` 已实现（[notes.py](../app/tools/notes.py)、[timezone.py](../app/tools/timezone.py)、[prefs.py](../app/tools/prefs.py)） | 已完成 | 无 |
| 对话连贯性：每条消息带最近对话，支持「第一个」「就那个」等指代 | 最近 12 条或 24 小时内对话进入上下文；检索查询由当前消息 + 最近 4 条用户消息组成（[history.py](../app/agents/friday/history.py)） | 已完成 | 无 |
| 工具调用失败不污染外层事务，重放不重复写业务数据 | 每次工具执行在 savepoint 中；写工具按入站事件派生幂等键（[registry.py](../app/tools/registry.py)、[test_tool_savepoint.py](../tests/integration/test_tool_savepoint.py)） | 已完成 | 无 |
| 每用户每日模型调用上限，防止失控烧钱 | `LLM_DAILY_LIMIT` 默认 200，按用户时区当日计数，超限返回固定文案（[gateway.py](../app/llm/gateway.py)） | 已完成 | 无 |
| 移动端 Today 接口：读取时间线、提醒与未排期任务，并支持完成/跳过/撤销/改期/排期/晚间复盘 | 读接口与写操作均已实现，需 `ENABLE_MOBILE_API=1` 开启；开发期用户头 `X-Butler-User` 并受 `ALLOWED_OPEN_IDS` 约束；写接口要求 `Idempotency-Key`，同键请求用事务级 advisory lock 串行；提醒完成/跳过会取消触发并保留终态；简报暂返回空（[mobile.py](../app/api/routes/mobile.py)、[test_mobile_today.py](../tests/integration/test_mobile_today.py)、[test_mobile_today_write.py](../tests/integration/test_mobile_today_write.py)） | 已完成（Today） | U2 后续补简报与聊天 |
| 移动端 Chat：发送、首屏最新历史、增量轮询、单条状态补偿，手机与飞书/Console 上下文隔离 | `POST/GET /api/mobile/chat/messages` 与 `GET /api/mobile/chat/messages/{id}` 已实现；手机回复与工具写入、done 同事务提交，outbound 幂等键 `mobile-reply:{event_id}`；`available` 表示已落库可取；同一用户进程内串行；见 [mobile_chat.py](../app/api/routes/mobile_chat.py)、[pipeline.py](../app/engine/pipeline.py)、[test_mobile_chat_api.py](../tests/integration/test_mobile_chat_api.py)、[test_mobile_chat_reliability.py](../tests/integration/test_mobile_chat_reliability.py) | 已完成（U2-A） | 真实认证与多进程串行留后续 |

### 3.3 提醒、简报与主动触达

| 已确认的产品要求 | 当前实际实现 | 状态 | 后续实现阶段 |
|---|---|---|---|
| 触发器到期处理、失败指数退避、领取租约回收、停机恢复 | `FOR UPDATE SKIP LOCKED` 领取；30s 起指数退避，最多 5 次；`claimed_at` 租约回收；启动补处理（[triggers.py](../app/engine/triggers.py)、[test_trigger_retry.py](../tests/integration/test_trigger_retry.py)、[test_worker_recovery.py](../tests/integration/test_worker_recovery.py)） | 已完成 | 无 |
| 物化器提前排未来 3 天的简报与块提醒，设置变更后重排 | 每 300 秒物化未来 3 天晨间/晚间简报；块提醒在排期/改期时生成；旧实例 superseded（[materializer.py](../app/engine/materializer.py)、[test_materializer.py](../tests/integration/test_materializer.py)） | 已完成 | 无 |
| 晨间简报与晚间复盘，时间与开关可用对话修改 | 简报主体由确定性模板生成，`brief_compose` 只写开场语；时间/开关存在 `notif_prefs`（[brief.py](../app/engine/brief.py)、[prefs.py](../app/tools/prefs.py)） | 已完成 | 待飞书实机确认 |
| 主动消息唯一出口、免打扰、预算、建议并入简报 | 仲裁器八步纯函数：kill switch、类别开关、免打扰、冷却、预算、建议 merge、send/defer/drop；唯一发送出口为 `process_candidate`（[arbiter.py](../app/engine/arbiter.py)、[nudge.py](../app/engine/nudge.py)、[test_arbiter.py](../tests/unit/test_arbiter.py)） | 已完成 | 无 |
| 每个主动消息决策可回查，发送失败留痕并重试 | `nudge_decision.gate_reasons`、投递记录、决策日志；发送失败先独立提交再退避重试（[delivery.py](../app/engine/delivery.py)、[test_send_failure_audit.py](../tests/integration/test_send_failure_audit.py)） | 已完成 | 无 |
| 主动建议：多个块逾期、任务 7 天未动 | 两条确定性规则已实现，只产生建议并并入下一次简报（[nudge_rules.py](../app/engine/nudge_rules.py)） | 已完成 | 更智能的建议归入阶段 4 |
| 更智能的主动建议/时机判断 | 当前没有基于模型或长期画像的时机判断 | 未实现 | 阶段 4（Jarvis） |

### 3.4 记忆

| 已确认的产品要求 | 当前实际实现 | 状态 | 后续实现阶段 |
|---|---|---|---|
| 异步记忆抽取：slot / preference / episode，证据逐字回查 | 抽取器 v2.6；few-shot 与评测用例分离；131 条评测 0 失败（[extract.py](../app/memory/extract.py)、[memory_cases.yaml](../tests/evals/memory_cases.yaml)、[run_memory_evals.py](../scripts/run_memory_evals.py)） | 已完成 | 无 |
| 确定性校验、规则裁决、LLM 兜底、决策日志 | 时间角色映射、scope 归一化/降级、冲突 ASK、supersede/NOOP 规则与 `memory_decision_log` 已实现（[validate.py](../app/memory/validate.py)、[resolve.py](../app/memory/resolve.py)） | 已完成 | 无 |
| 敏感类别与提示注入拦截，异步路径一律拒绝 | 敏感类别默认拒绝；注入类与敏感类写入统计为 0（[test_pipeline_features.py](../tests/integration/test_pipeline_features.py)、[memory-policy.md](./memory-policy.md)） | 已完成 | 无 |
| `remember` 同步写入，槽位冲突返回待确认并附旧值 | `remember` 工具已实现；冲突返回 `pending_confirmation`，但还没有确认卡片交互（[remember.py](../app/tools/remember.py)） | 部分实现 | 阶段 3b 收尾 |
| 记忆读取：按相关性检索 slot / preference / episode，注入 Friday 提示词 | `retrieve.py` 已实现模型隔离向量检索、slot 有效期去重、预算裁剪、来源标注、超时降级与 `memory_context` 审计；测试覆盖（[retrieve.py](../app/memory/retrieve.py)、[test_friday_memory_injection.py](../tests/integration/test_friday_memory_injection.py)） | 部分实现 | 阶段 3b 收尾（启用并实机验证） |
| 记忆检索默认开启 | `MEMORY_INJECT_ENABLED` 默认 `false`，当前 `.env` 未设置；运行中 Friday 不会注入长期记忆（[config.py](../app/core/config.py)） | 未实现 | 阶段 3b 收尾 |
| 用户确认后把 `stated` 升级为 `confirmed`，提供确认摘要/卡片 | `source_class=confirmed` 只在权重与检索中预留；没有确认写入路径与确认卡片；Mobile 的 `MemoryConfirmCard` 仅为 Mock（[weights.py](../app/memory/weights.py)、[memory_confirm 卡片](../mobile/lib/domain/models/chat_message.dart)） | 未实现 | 阶段 3b 收尾 |
| 记忆中心/画像页，可查看、修改、删除长期记忆 | 无后端接口与移动端页面 | 未实现 | 未排期（记忆确认属阶段 3b） |
| 记忆质量评测与门槛 | `memory-eval-v2`、131 条用例、precision/recall 1.0、错记 0、静默覆盖 0（[run_memory_evals.py](../scripts/run_memory_evals.py)、[memory_cases.yaml](../tests/evals/memory_cases.yaml)；历史 v2/v2.1 报告见 [memory-eval-report-v2.md](./memory-eval-report-v2.md)） | 已完成 | 无 |

### 3.5 Jarvis 慢通道

| 已确认的产品要求 | 当前实际实现 | 状态 | 后续实现阶段 |
|---|---|---|---|
| Jarvis 智能体：异步运行、显式状态机 | 没有 `app/agents/jarvis`，没有异步状态机与 worker 处理入口 | 未实现 | 阶段 4 |
| 长期任务立项、澄清、拆解与规划 | `work_item` 预留 `seed/item/project/mission`、`parent_id`、`mission_id`、`clarity_score` 等字段，但代码只创建普通 `item`（[work_item.py](../app/db/models/work_item.py)、[tasks.py](../app/tools/tasks.py)） | 未实现 | 阶段 4 |
| 重规划与周复盘 | 无代码、无工具、无触发器 | 未实现 | 阶段 4 |
| 任务专属记忆：knowledge_node、question_log、qa_log、weakness、plan_version | 契约已预留表设计，迁移未创建（[contracts.md](./contracts.md)） | 未实现 | 阶段 4 |
| Jarvis 模型档位 `jarvis_deep` / `mini_plan` | 别名已配置，但代码零调用（[aliases.yaml](../app/llm/aliases.yaml)） | 未实现 | 阶段 4 |
| Jarvis 引荐卡、诊断问题、计划提案、专题对话 | Mobile 已有 `JarvisIntroCard` Mock 流程：接受后追加诊断 ChoiceCard、ThinkingCard、PlanProposalCard；后端无对应能力（[mock_chat_repository.dart](../mobile/lib/data/mock/mock_chat_repository.dart)） | 仅 Mock | 阶段 4 + Mobile U3 |

### 3.6 Mobile U1 与后续

| 已确认的产品要求 | 当前实际实现 | 状态 | 后续实现阶段 |
|---|---|---|---|
| Flutter 工程、设计令牌、浅/深色主题、7 组对比度 | 已实现（[tokens.dart](../mobile/lib/core/theme/tokens.dart)、[app_theme.dart](../mobile/lib/core/theme/app_theme.dart)、[color_contrast_test.dart](../mobile/test/color_contrast_test.dart)） | 已完成 | 无 |
| 4 Tab 导航外壳：`/today`、`/chat`、`/tasks`、`/profile`，切换保留状态 | `StatefulShellRoute.indexedStack` 已实现；四个 Tab 均有实际页面，切换保留状态（[app_router.dart](../mobile/lib/shell/app_router.dart)、[shell_scaffold.dart](../mobile/lib/shell/shell_scaffold.dart)） | 已完成 | 无 |
| 今日页：日期问候、晨间简报、时间线、完成/跳过/调整、未排期、晚间复盘入口 | 时间线、简报、未排期、晚间复盘、完成/跳过、长按改期、未排期移入今天均已实现；远程模式写操作已接真实接口（[today_page.dart](../mobile/lib/features/today/today_page.dart)、[today_controller.dart](../mobile/lib/features/today/today_controller.dart)、[today_page_test.dart](../mobile/test/today_page_test.dart)） | 已完成 | 无 |
| 对话页：Friday 主对话、7 类卡片、流式回复、输入条、草稿、状态覆盖 | 已实现；Mock 支持 7 类卡片与逐段流式；`USE_REMOTE=true` 时 Chat 接入真实接口：首屏最新 N 条、after 轮询、单条状态补偿、失败重试、前后台暂停，以及 SSE 逐 token 流式与断线回退轮询（[chat_page.dart](../mobile/lib/features/chat/chat_page.dart)、[remote_chat_repository.dart](../mobile/lib/data/remote/remote_chat_repository.dart)、[chat_page_test.dart](../mobile/test/chat_page_test.dart)、[remote_chat_repository_test.dart](../mobile/test/remote_chat_repository_test.dart)） | 已完成 | 卡片应答后续 |
| JarvisIntroCard：接受后依次出现诊断 ChoiceCard、ThinkingCard、PlanProposalCard | Mock 仓库已实现该顺序与终态约束（[mock_chat_repository.dart](../mobile/lib/data/mock/mock_chat_repository.dart)） | 仅 Mock | Mobile U3 |
| 调试面板：模拟时间、网络、数据集、主题、文字缩放、发送失败 | 已实现，debug 下长按今日页标题进入（[debug_panel_page.dart](../mobile/lib/features/debug/debug_panel_page.dart)、[debug_panel_test.dart](../mobile/test/debug_panel_test.dart)） | 已完成 | 无 |
| Mock 仓库与 Provider 装配：简单 Stream、模拟延迟、离线队列、错误注入 | 已实现；Provider 层只暴露接口，features 不直接 import data/mock（[providers.dart](../mobile/lib/core/providers.dart)、[mock_chat_repository.dart](../mobile/lib/data/mock/mock_chat_repository.dart)） | 已完成 | 无 |
| 真实后端接入、真实流式、数据库读写 | Today、Chat、任务页与我的页均已接真实 API：`Remote*Repository`，通过 `USE_REMOTE=true` 开启；Chat 支持 SSE 流式（单进程 broker，失败回退轮询）；卡片应答仍仅 Mock（[remote_today_repository.dart](../mobile/lib/data/remote/remote_today_repository.dart)、[remote_chat_repository.dart](../mobile/lib/data/remote/remote_chat_repository.dart)、[remote_task_repository.dart](../mobile/lib/data/remote/remote_task_repository.dart)、[providers.dart](../mobile/lib/core/providers.dart)） | 部分实现 | 真实流式已接入；卡片/通知后续 |
| 任务页/我的页内容 | 任务页：列表（未完成/已完成/全部）、完成/跳过/撤销、排进今天，写操作复用 Today 接口；我的页：昵称、时区、日界线、数据源、版本与调试入口（[tasks_page.dart](../mobile/lib/features/tasks/tasks_page.dart)、[profile_page.dart](../mobile/lib/features/profile/profile_page.dart)、[mobile_tasks.py](../app/api/routes/mobile_tasks.py)、[mobile_profile.py](../app/api/routes/mobile_profile.py)） | 已完成（只读我的页） | 后续设置项 |
| 系统通知、后台推送、通知权限 | 应用内提醒已实现：App 前台每 30 秒轮询 `GET /api/mobile/reminders/due`，Shell 级横幅展示，同一 trigger 本会话只提示一次，关闭仅本地隐藏（[reminder_controller.dart](../mobile/lib/features/reminders/reminder_controller.dart)、[mobile_reminders.py](../app/api/routes/mobile_reminders.py)）。不做 OS 通知、后台推送、通知权限与 APNs/FCM | 部分实现（应用内） | OS 通知/远程推送后续 |
| 会话同步协议、多会话、Jarvis 专题、邀请卡幂等、PriorityAlert | 已从 U1 移出并归档，待后端接口方案确定（[mobile-sync-and-topics.md](./deferred/mobile-sync-and-topics.md)） | 未实现 | Mobile U3 |
| 截图归档与真机验收 | 6 张浅/深色组件渲染截图已生成；真机安装验收待执行（[README.md](../mobile/README.md)、[screenshots](../mobile/screenshots)） | 部分实现 | U1 收尾 |
| 单元/组件/对比度/缩放测试，analyze/format/test/build apk | 144 项测试通过（3 项截图生成测试默认跳过）；四条命令已通过（[README.md](../mobile/README.md)） | 已完成 | 无 |

### 3.7 多模态与平台化

| 已确认的产品要求 | 当前实际实现 | 状态 | 后续实现阶段 |
|---|---|---|---|
| 语音、图片、文件输入 | 仅处理纯文本；`InboundEvent.attachments` 字段存在但未使用；飞书非文本消息直接跳过；`vision_extract` 别名零调用（[base.py](../app/adapters/base.py)、[feishu_adapter.py](../app/adapters/feishu_adapter.py)、[aliases.yaml](../app/llm/aliases.yaml)） | 未实现 | 未排期 |
| iOS / HarmonyOS 原生 | 只有 Android 工程；U1 明确不做 iOS/HarmonyOS | 未实现 | 未排期 |
| 多租户隔离 | `tenant_id` 已存储但未参与权限、检索与预算逻辑 | 部分实现 | 未排期 |

### 3.8 U2-A 手机聊天边界（已完成）

已完成：

- 手机消息入口复用已认证 User，不创建 `channel=mobile` 身份；入站幂等键为 `mobile-chat:{user_id}:{clientMessageId}`。
- Agent/工具/回复/done 同事务提交；outbound 幂等键 `mobile-reply:{inbound_event_id}`；API 进程启动恢复手机 processing 事件，只有持有 mobile adapter 的服务会接手。
- 渠道隔离：手机/飞书/Console 短期上下文互不可见；Chat API 只返回 `channel=mobile` 的 message 事件。
- Flutter `RemoteChatRepository`：首屏最新 50 条、after 增量轮询、单条状态补偿、发送失败重试、Tab/前后台暂停与恢复。
- 日常工具：`update_task`、`update_reminder`、`list_notes`；`reschedule_block` 与 Today 改期规则统一。

明确未做 / 边界：

- 开发期 `X-Butler-User` 不是真实认证，只允许本机或 `adb reverse`，不能暴露到局域网或公网。
- 只支持单进程 API（用户串行锁是进程内 `asyncio.Lock`）；多 worker/多副本需要数据库队列或租约。
- 无服务端推送/WebSocket；SSE 真流式已实现（单进程 broker）；Remote 模式不支持卡片应答。
- 多会话、未读/已读、同步协议、Jarvis 专题仍留后续。
- 飞书聊天的发送 outbox/幂等不在 U2-A 范围内。

## 四、主要缺口清单

1. **Jarvis 慢通道**：从智能体、状态机到长期任务、重规划、周复盘、任务专属记忆全部未开始。
2. **记忆闭环**：检索注入代码已完成但默认关闭；`confirmed` 升级与确认交互未实现。
3. **真实移动端数据**：Today/Chat/任务页/我的页/应用内提醒均已接真实 API；OS 通知/远程推送与卡片应答仍未实现。
4. **富消息渲染**：后端出站意图抽象存在，但飞书 adapter 只发文本，7 类卡片无法在真实渠道渲染。
5. **多模态与多渠道**：语音/图片/文件、微信等渠道、iOS/HarmonyOS、多租户均未排期。

## 五、建议的推进顺序

1. **阶段 3b 收尾**：开启记忆注入并实机验证；补 `confirmed` 升级与确认卡片；把 `remember` 的 `pending_confirmation` 变成可交互流程。
2. **阶段 4**：先做 Jarvis 的最小闭环（立项 → 拆解 → 计划提案 → 重规划 → 周复盘），再补任务专属记忆表。
3. **Mobile U2**：Today/Chat/任务页/我的页/应用内提醒/SSE 已落地；剩余 OS 通知与远程推送、卡片应答与设置项。
4. **Mobile U3**：按 deferred 文档恢复同步协议、多会话、Jarvis 专题、邀请幂等与 PriorityAlert。
5. **未排期**：多模态、更多渠道、多租户、iOS/HarmonyOS。

> 本表是现状核对，不改变任何契约；涉及字段、接口或阶段范围的变更仍需先确认。
