# 契约 v0（变更需经确认）

## 变更记录

### 变更（阶段 1 修订）
1. trigger_instance 新增 attempts、next_attempt_at、last_error、claimed_at 字段与 failed 状态；领取即持久化 claimed_at/attempts；处理异常按 30s × 2^(n-1) 指数退避重试，上限 5 次，耗尽置 failed 并写 event_log；claimed 租约超时（默认 300s，可配 TRIGGER_LEASE_SECONDS）回收；missed 仅用于停机错过（到期处理时已过 expires_at）。
2. 同一 source_trigger 已存在 sent_at 非空的 delivery 时不再重复发送（发送幂等，delivery 事件幂等键为 delivery:{trigger_id}）。
3. 写工具不再接受 LLM 提供的 idempotency_key：幂等键由代码派生，格式 tool-call:{inbound_event_id}:{tool_name}:{call_index} / tool-result:{…}，call_index 跨步骤递增；幂等键写入与业务写入在同一事务。
4. ChannelAdapter 入站处理拆为 ingest（白名单 → onboard → 幂等落库，回调同步等待上限 3 秒）与 process（异步）；飞书入站幂等键优先用 event_id，缺失退回 message_id；飞书长连接独立为单实例 feishu 服务，api 与 worker 不启动长连接。
5. 新用户首次回复由代码确定性追加所用时区说明；新增 set_timezone 工具；默认时区改为配置项 DEFAULT_TIMEZONE。
6. 新增配置：ALLOWED_OPEN_IDS（飞书 open_id 白名单，逗号分隔，空=不限制）、LLM_DAILY_LIMIT（每用户每日 LLM 调用上限，按用户时区当日计，默认 200，<=0 不限制；超限网关抛 BudgetExceededError，agent 回固定文案）。
7. nudge_candidate.reason_code 改为命名空间形式（如 commitment.reminder），统一登记在 app/engine/reasons.py 注册表。

## 通用约定
- 主键使用 UUID（v7 优先）；时间戳均为 timestamptz（UTC）；可变业务表带 rev（bigint，每次更新递增）、created_at、updated_at
- 枚举用 text + CHECK 约束，不用数据库原生 enum
- 向量列为 vector(1024)，并伴随 embedding_model（text）
- user_id 出现在所有用户数据表，并建立相应索引

## 表（括号内为创建阶段）

### user（阶段 1）
id、display_name、timezone（IANA，如 Asia/Tokyo）、day_start（time，默认 04:00，用于定义“今天”的边界）

### channel_identity（阶段 1）
id、user_id、channel（feishu | console）、external_id、tenant_id（可空）；唯一约束 (channel, external_id)

### event_log（阶段 1，append-only）
id、user_id、channel、direction（inbound | outbound | system | tool）、type（message | callback | tool_call | tool_result | trigger | delivery 等）、payload（jsonb）、idempotency_key（可空，唯一）、trace_id、occurred_at、recorded_at
约束：数据库层面禁止 UPDATE 与 DELETE（触发器或权限）；索引 (user_id, occurred_at)

### work_item（阶段 1）
id、user_id、type（seed | item | project | mission）、status（seed | clarifying | active | dormant | done | dropped）、title、description、parent_id、mission_id、clarity_score、size_estimate_min、revisit_trigger（jsonb）、source_event_id、rev
阶段 1 只使用 type=item，status=active 或 done

### planned_block（阶段 1）
id、user_id、work_item_id、starts_at、ends_at、status（planned | done | skipped | moved）、assigned_by（user | friday | jarvis）、difficulty（1 到 5，可空）、energy（low | mid | high，可空）、compressible（bool）、plan_rev（可空）、actual_started_at、actual_ended_at、rev
说明：计划安排（assigned）与实际执行（actual）必须分开记录

### trigger_instance（阶段 1；【变更（阶段 1 修订）】增加重试状态机）
id、user_id、kind（reminder | brief_morning | brief_evening | block_start | overdue_check）、key（唯一，幂等键）、fire_at、tz、precondition（jsonb）、payload（jsonb）、status（pending | claimed | fired | dropped | missed | failed）、plan_rev（可空）、expires_at、created_at、attempts（int，领取时 +1）、next_attempt_at（退避到期时刻）、last_error、claimed_at（领取时刻，租约起点）
约束：worker 用 FOR UPDATE SKIP LOCKED 领取 status=pending 且 fire_at<=now、不在退避等待、attempts<5 的记录；领取即提交；处理异常按 30s × 2^(n-1) 退避（上限 5 次，耗尽置 failed 并写 event_log）；claimed_at 超过租约（默认 300s）回收，回收时次数耗尽直接置 failed；missed 只用于停机错过

### nudge_candidate / nudge_decision / delivery / notif_prefs（阶段 1 建表，阶段 2 实现策略）
- nudge_candidate：id、user_id、class（commitment | brief | suggestion）、reason_code（【变更（阶段 1 修订）】命名空间形式，如 commitment.reminder，登记于 app/engine/reasons.py）、reason_text、value_score、expires_at、dedupe_key、precondition（jsonb）、source_trigger_id
- nudge_decision：id、candidate_id、decision（send | defer | merge | drop）、gate_reasons（jsonb）、policy_version、budget_snapshot（jsonb）、decided_at
- delivery：id、decision_id、channel、provider_msg_id、sent_at、opened_at、acted_at、dismissed_at、error；【变更（阶段 1 修订）】发送幂等：同一 source_trigger 已有 sent_at 非空的 delivery 则跳过重发
- notif_prefs：user_id（主键）、daily_budget（默认 4）、quiet_hours（jsonb）、class_enabled（jsonb）、snooze_until

### llm_call（阶段 1）
id、trace_id、user_id（可空）、alias、provider、model_id、params（jsonb）、request（jsonb）、response（jsonb）、input_tokens、cached_tokens、output_tokens、reasoning_tokens、latency_ms、ttft_ms（可空）、error、created_at

### memory / memory_source / memory_decision_log（阶段 1 仅建表，阶段 3 实现）
- memory：id、user_id、mission_id（可空）、type（slot | preference | episode | state_signal）、slot_key（可空）、subject、value（jsonb）、polarity、scope（jsonb）、source_class（confirmed | stated | inferred）、weight、confidence、status（active | superseded | retracted | pending）、supersedes_id、valid_from、valid_to、recorded_at、superseded_at、support_days、contradict_count、last_reinforced_at、rejected_at、suppress_until、extractor_version、embedding vector(1024)、embedding_model
- memory_source：memory_id、event_id（联合主键）
- memory_decision_log：id、memory_id（可空）、candidate（jsonb）、neighbors（jsonb）、action（ADD | SUPERSEDE | NOOP | MERGE | ASK）、reason、alias、llm_call_id、created_at

### 任务专属记忆（阶段 4 再建）
knowledge_node、question_log、qa_log、weakness、plan_version，均带 mission_id

## 接口

### ChannelAdapter
InboundEvent：channel、external_user_id、tenant_id、kind（message | callback）、text、attachments、callback_payload、occurred_at、idempotency_key、raw
OutboundIntent：type（text | confirm_card | choice | nudge）、user_id、body、reply_to_event_id、collapse_key
Capabilities：can_push_unsolicited、push_credits、can_update_message、supports_buttons、streaming
协议：
- start(on_event)：启动并把入站事件交给回调
- send(intent) -> DeliveryResult
- update(provider_msg_id, intent) -> DeliveryResult（仅当 can_update_message）
入站处理顺序：验签 → 白名单（ALLOWED_OPEN_IDS，仅飞书）→ 去重（idempotency_key）→ 写 event_log → 快速应答 → 异步处理【变更（阶段 1 修订）：拆为 pipeline.ingest（同步，回调最多等待 3 秒）与 pipeline.process（异步）】
入站幂等键（【变更（阶段 1 修订）】）：飞书优先使用事件 event_id，缺失时退回 message_id；其他渠道沿用渠道侧事件标识

### LLM 网关
- aliases.yaml：别名 -> provider、model、params（reasoning_effort、max_tokens、timeout、temperature）、fallback 别名
- chat(alias, messages, tools=None, response_model=None) -> LLMResult
- LLMResult：content、tool_calls、reasoning（单独存放，不混入 content）、usage（input、cached、output、reasoning）、model_id、latency_ms
- 传入 response_model 时用 Pydantic 校验，失败则带错误信息重试，最多 2 次
- provider 差异（推理内容回传、缓存字段）封装在 provider 类内部
- 【变更（阶段 1 修订）】每用户每日调用上限 LLM_DAILY_LIMIT（默认 200，<=0 不限制）：按用户时区当日 0 点起计 llm_call 数，超限在 chat 入口抛 BudgetExceededError，调用方决定兜底行为（Friday 回固定文案）

### 嵌入服务
- embed(texts, kind) -> list[list[float]]，kind 为 query 或 document
- query 使用任务指令前缀，document 不加
- 配置项：EMBEDDING_BASE_URL、EMBEDDING_MODEL、EMBEDDING_DIM=1024
- 返回前先截断到 EMBEDDING_DIM，再做 L2 归一化

### Friday 工具（阶段 1；【变更（阶段 1 修订）】幂等键派生方式变更并新增 set_timezone）
create_task、list_tasks、complete_task、set_reminder、capture_note、set_timezone
- 参数用 Pydantic 定义；时间参数必须是带时区偏移的 ISO 8601
- 写工具（create_task、complete_task、set_reminder、capture_note、set_timezone）不接受 LLM 提供的幂等键：由代码按入站事件派生，tool_call / tool_result 事件的 idempotency_key 形如 tool-call:{inbound_event_id}:{tool_name}:{call_index}（call_index 跨步骤递增）；幂等键写入与业务写入在同一事务
- set_timezone：参数为 IANA 时区名；校验通过后更新 user.timezone 并 rev+1
- 返回统一结构：status（ok | pending_confirmation | error）、data、message
- 系统提示中注入当前时间与用户时区；代码负责校验并拒绝过去时间或缺少时区的参数
- 新用户首次回复由代码（非 LLM）追加所用时区说明