# 契约 v0（变更需经确认）

## 变更记录

### 变更（阶段 3a）
1. 新表 memory_extraction_run：id、user_id（FK user）、to_event_id（FK event_log）、extractor_version、event_count、status（pending | done | failed）、stats（jsonb，含 attempts / next_attempt_at / 计数）、error、created_at、finished_at；唯一约束 (user_id, to_event_id, extractor_version)。
2. memory_decision_log 新增 user_id（FK user，NOT NULL）、run_id（FK memory_extraction_run，可空）；迁移前按 memory_id → memory.user_id 回填，剩余无法归属的存量测试行删除并记录警告，之后才加 NOT NULL。
3. memory 增加索引：(user_id, status)、(user_id, type, slot_key)，以及 embedding 的 HNSW cosine 索引。
4. LLM 别名：新增 memory_resolve（temperature 0、max_tokens 512、timeout 30）；memory_extract 的 max_tokens 提到 2048。
5. 新增 7 个配置：EMBEDDING_BASE_URL、EMBEDDING_MODEL、EMBEDDING_DIM=1024、MEMORY_IDLE_MINUTES=10、MEMORY_BATCH_MAX_EVENTS=40、MEMORY_NEIGHBOR_THRESHOLD=0.75、MEMORY_NEIGHBOR_TOPK=5。
6. memory.value 统一形状：{"text": string, "time": "HH:MM"（可空）, "date": "YYYY-MM-DD"（可空）}；memory.scope 统一形状：{"kind": "persistent"} | {"kind": "on", "date": "YYYY-MM-DD"} | {"kind": "until", "date": "YYYY-MM-DD"} | {"kind": "recurring", "rule": string}。相对日期由代码按事件时间、用户时区与 day_start 归一化，LLM 只输出 date_text。
7. 证据规则：用户消息取 payload.text；tool_result 只能引用「成功工具调用的已验证参数快照」的确定性还原文本（schedule_block 取标题/开始/结束；update_block_status 取块与状态；reschedule_block 取块/开始/结束；set_notif_prefs 取非空参数），禁止使用 payload.message（人话文案）。证据片段按忽略空白差异逐字回查。
8. 抽取 run 重试：单个 run 失败最多自动重试 3 次（共 4 次尝试），退避 30/60/120 秒，尝试次数与下次时间记录在 stats；4 次仍失败置 failed 并写错误日志，调度指针前移，不阻塞后续事件。同一 run 重试时，已处理过的候选按「run_id + 候选指纹」识别，直接跳过，不再重复写决策日志。
9. 开放事实的向量近邻只在 active 记忆中检索，pending 记忆不进入近邻候选。
10. 敏感类别：health | finance | exact_location | third_party | credentials；默认拒绝，只有证据中出现明确「记住」意图或走 remember 同步工具时放行。
11. remember 工具允许同步写入 slot、preference、episode；state_signal 只允许异步抽取。槽位冲突返回 pending_confirmation 并附旧值，不静默覆盖。
12. 阶段 3a 不写 source_class=confirmed；该值留给阶段 3b 用户确认后升级。

### 变更（阶段 2）
1. notif_prefs 新增 morning_brief_time（默认 08:30）、evening_brief_time（默认 21:00）、briefs_enabled（默认 true）。
2. trigger_instance 新增 defer_count（免打扰延后次数，上限 3）；reminder 的 expires_at 改为 fire_at + REMINDER_LATE_WINDOW_HOURS（默认 24h），block_start 同窗口，overdue_check 为 fire_at + 24h，brief 为 fire_at + 2h。
3. nudge_candidate 新增 explicit、holdout_group、propensity（本阶段只留字段）、merged_into_candidate_id（并入简报后指向简报候选）。
4. 仲裁改为纯函数 evaluate（app/engine/arbiter.py，POLICY_VERSION=stage2-v0），固定八步：kill_switch → 类别开关 / briefs_enabled / snooze → 过期与前提 → 同 dedupe_key 24h 冷却 → 免打扰（explicit 承诺类豁免，其余 defer 到免打扰结束，defer_count≥3 丢弃）→ 预算（brief 每类每天 1 条、suggestion 每天 ≤ daily_budget、commitment 硬上限 50、非承诺 12）→ suggestion 一律 merge → send；每步输入与结论写入 nudge_decision.gate_reasons。
5. 唯一发送出口为 nudge.process_candidate：先查同一 trigger 已有的成功投递（发送幂等），再仲裁；简报在发送时才渲染，空内容改判 drop（nothing_to_say）；发送成功写 delivery 与 event_log（payload 含 text、block_ids、work_item_ids、reason_code），幂等键 delivery:{trigger_id}；被并入的建议标记 merged_into_candidate_id 并追加 merged_into_brief 决策。
6. 物化器（每 MATERIALIZE_INTERVAL_SECONDS，默认 300s）：简报 key=brief_morning|brief_evening:{user_id}:{local_date}，物化未来 3 天 × 2 条；块 key=block_start|overdue_check:{block_id}:{rev}，block_start=starts_at−BLOCK_LEAD_MINUTES（10），overdue_check=ends_at+BLOCK_GRACE_MINUTES（15）；只向前物化；设置/时区变更时旧 pending 实例写 dropped(reason=superseded) 后删除以释放 key。
7. 规则引擎（不调用 LLM）：suggestion.overdue_blocks（过去 24h 至少 2 个不同计划块出现 overdue 信号）、suggestion.stale_tasks（active 且 7 天未更新，最多 3 个）；dedupe_key=suggestion.{rule}:{local_date}，同日幂等；建议只产生 merge 决策并入下一次简报，不单独发送。
8. overdue_check 只写 signal 事件，不发送消息。
9. 简报主体由确定性模板生成（晨间：今日块、未排期任务、今日提醒、昨日统计；晚间：块完成标记、并入建议、邀请回复），LLM 仅用 brief_compose 写一句开场语（取第一行、限 40 字，失败回退模板）。
10. 新增工具：schedule_block、list_schedule、update_block_status、reschedule_block、set_notif_prefs、list_reminders、cancel_reminder。
11. 新增配置：BLOCK_LEAD_MINUTES=10、BLOCK_GRACE_MINUTES=15、REMINDER_LATE_POLICY=late_send、REMINDER_LATE_WINDOW_HOURS=24、NUDGE_KILL_SWITCH=false、MATERIALIZE_INTERVAL_SECONDS=300；删除 REMINDER_TTL_MINUTES。
12. block_start 前提校验改为按时刻比较 expected_starts_at（数据库取回 UTC、payload 存原始时区，字符串比较会误判）。
13. Friday MAX_STEPS=4，注入最近对话历史（12 条或 24h 内取较小，4000 字符上限；delivery 事件作为 assistant 消息并附 block_ids 注记）。
14. 集成测试使用独立数据库 butler_test（TEST_DATABASE_URL 可覆盖），避免与运行中的 worker 争用同一批 trigger。

### 变更（阶段 1 修订 2）
1. 投递失败判定：process_trigger 在 gate 决策为 send 但 delivery.sent_at 为空时抛异常，进入指数退避重试（不再误置 fired）；deliver_trigger_nudge 返回 (delivery, gate 决策)。
2. llm_call.model_id 以模型响应内返回的实际模型 id 为准（如 ark-code-latest 模式下由方舟控制台决定），缺失时回退别名配置的 model。
3. 入站处理事务拆分：agent 与工具写入先 commit，再发送回复，outbound 事件另开事务记录；agent 会话在首次模型调用前释放读事务，不在 LLM 调用期间持有长事务。
4. 新增 inbound_processing 表（event_id 主键，status: processing | done | failed）：ingest 与入站事件同事务写入，process 结束置 done/failed；服务启动时补处理仍为 processing 的事件（工具幂等键保证重放不重复写业务数据）。后台任务统一经 app/core/tasks.spawn（引用集合 + done 回调），不再裸 create_task。
5. FeishuAdapter.send 传 uuid 作为发送幂等键：取 collapse_key，超 64 字符取其 sha256。
6. create_trigger 返回 (row, created)；set_reminder 的 deduplicated 以 created 为准。
7. 每次工具执行包在 savepoint（begin_nested）中：工具异常回滚 savepoint（含半途业务写入），不污染外层事务；error tool_result 仍写 event_log 留痕。
8. Console 路由由 ENABLE_CONSOLE 控制（默认关闭）；ALLOWED_OPEN_IDS 白名单对所有渠道生效（配置了名单即只放名单内的外部 id）。
9. docker-compose：数据库密码从 .env 读取（未设置直接报错，不再有默认值）；api 与 adminer 端口仅绑定 127.0.0.1。

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

### inbound_processing（阶段 1 修订 2）
event_id（主键，FK event_log.id）、user_id、status（processing | done | failed）、error（可空）、updated_at
说明：event_log 只追加，入站事件的处理状态放此独立表；ingest 与入站事件同事务写入 processing，process 结束置 done/failed；服务启动时补处理仍为 processing 的事件（工具幂等键保证重放安全）

### work_item（阶段 1）
id、user_id、type（seed | item | project | mission）、status（seed | clarifying | active | dormant | done | dropped）、title、description、parent_id、mission_id、clarity_score、size_estimate_min、revisit_trigger（jsonb）、source_event_id、rev
阶段 1 只使用 type=item，status=active 或 done

### planned_block（阶段 1）
id、user_id、work_item_id、starts_at、ends_at、status（planned | done | skipped | moved）、assigned_by（user | friday | jarvis）、difficulty（1 到 5，可空）、energy（low | mid | high，可空）、compressible（bool）、plan_rev（可空）、actual_started_at、actual_ended_at、rev
说明：计划安排（assigned）与实际执行（actual）必须分开记录

### trigger_instance（阶段 1；【变更（阶段 1 修订）】增加重试状态机）
id、user_id、kind（reminder | brief_morning | brief_evening | block_start | overdue_check）、key（唯一，幂等键）、fire_at、tz、precondition（jsonb）、payload（jsonb）、status（pending | claimed | fired | dropped | missed | failed）、plan_rev（可空）、expires_at、created_at、attempts（int，领取时 +1）、next_attempt_at（退避到期时刻）、last_error、claimed_at（领取时刻，租约起点）、defer_count（【变更（阶段 2）】免打扰延后次数，上限 3）
约束：worker 用 FOR UPDATE SKIP LOCKED 领取 status=pending 且 fire_at<=now、不在退避等待、attempts<5 的记录；领取即提交；处理异常按 30s × 2^(n-1) 退避（上限 5 次，耗尽置 failed 并写 event_log）；claimed_at 超过租约（默认 300s）回收，回收时次数耗尽直接置 failed；missed 只用于停机错过

### nudge_candidate / nudge_decision / delivery / notif_prefs（阶段 1 建表，阶段 2 实现策略）
- nudge_candidate：id、user_id、class（commitment | brief | suggestion）、reason_code（【变更（阶段 1 修订）】命名空间形式，如 commitment.reminder，登记于 app/engine/reasons.py）、reason_text、value_score、expires_at、dedupe_key、precondition（jsonb）、source_trigger_id；【变更（阶段 2）】explicit、holdout_group、propensity、merged_into_candidate_id（并入简报后指向简报候选）
- nudge_decision：id、candidate_id、decision（send | defer | merge | drop）、gate_reasons（jsonb）、policy_version（阶段 2 为 stage2-v0）、budget_snapshot（jsonb）、decided_at
- delivery：id、decision_id、channel、provider_msg_id、sent_at、opened_at、acted_at、dismissed_at、error；【变更（阶段 1 修订）】发送幂等：同一 source_trigger 已有 sent_at 非空的 delivery 则跳过重发
- notif_prefs：user_id（主键）、daily_budget（默认 4）、quiet_hours（jsonb，默认 23:00–07:00）、class_enabled（jsonb）、snooze_until；【变更（阶段 2）】morning_brief_time（默认 08:30）、evening_brief_time（默认 21:00）、briefs_enabled（默认 true）

### llm_call（阶段 1）
id、trace_id、user_id（可空）、alias、provider、model_id、params（jsonb）、request（jsonb）、response（jsonb）、input_tokens、cached_tokens、output_tokens、reasoning_tokens、latency_ms、ttft_ms（可空）、error、created_at

### memory / memory_source / memory_decision_log / memory_extraction_run（阶段 1 建表，阶段 3a 实现写入）
- memory：id、user_id、mission_id（可空）、type（slot | preference | episode | state_signal）、slot_key（可空）、subject、value（jsonb，形状见变更 6）、polarity、scope（jsonb，形状见变更 6）、source_class（confirmed | stated | inferred）、weight、confidence、status（active | superseded | retracted | pending）、supersedes_id、valid_from、valid_to、recorded_at、superseded_at、support_days、contradict_count、last_reinforced_at、rejected_at、suppress_until、extractor_version、embedding vector(1024)、embedding_model
- memory_source：memory_id、event_id（联合主键）
- memory_decision_log：id、【变更（阶段 3a）】user_id（FK user，NOT NULL）、【变更（阶段 3a）】run_id（FK memory_extraction_run，可空）、memory_id（可空）、candidate（jsonb，含 fingerprint）、neighbors（jsonb）、action（ADD | SUPERSEDE | NOOP | MERGE | ASK）、reason、alias、llm_call_id、created_at
- memory_extraction_run（阶段 3a）：id、user_id、to_event_id、extractor_version、event_count、status（pending | done | failed）、stats（jsonb）、error、created_at、finished_at；唯一约束 (user_id, to_event_id, extractor_version)

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
- aliases.yaml：别名 -> provider、model、params（reasoning_effort、max_tokens、timeout、temperature）、fallback 别名；【变更（阶段 2）】新增 brief_compose（仅写简报开场语，max_tokens=120、temperature=0.7、timeout=3）；【变更（阶段 3a）】新增 memory_resolve（temperature 0、max_tokens 512、timeout 30），memory_extract max_tokens 提到 2048
- chat(alias, messages, tools=None, response_model=None) -> LLMResult
- LLMResult：content、tool_calls、reasoning（单独存放，不混入 content）、usage（input、cached、output、reasoning）、model_id、latency_ms
- 传入 response_model 时用 Pydantic 校验，失败则带错误信息重试，最多 2 次
- provider 差异（推理内容回传、缓存字段）封装在 provider 类内部
- 【变更（阶段 1 修订）】每用户每日调用上限 LLM_DAILY_LIMIT（默认 200，<=0 不限制）：按用户时区当日 0 点起计 llm_call 数，超限在 chat 入口抛 BudgetExceededError，调用方决定兜底行为（Friday 回固定文案）

### 嵌入服务
- embed(texts, kind) -> list[list[float]]，kind 为 query 或 document
- query 使用任务指令前缀，document 不加；阶段 3a 按 Qwen3-Embedding 模型卡：`Instruct: Given a user message, retrieve relevant memories about the user\nQuery:{query}`
- 配置项：EMBEDDING_BASE_URL、EMBEDDING_MODEL、EMBEDDING_DIM=1024；阶段 3a 另增加 MEMORY_IDLE_MINUTES、MEMORY_BATCH_MAX_EVENTS、MEMORY_NEIGHBOR_THRESHOLD、MEMORY_NEIGHBOR_TOPK
- 返回前先截断到 EMBEDDING_DIM，再做 L2 归一化

### Friday 工具（阶段 1；【变更（阶段 1 修订）】幂等键派生方式变更并新增 set_timezone；【变更（阶段 2）】新增时段与偏好工具；【变更（阶段 3a）】新增 remember）
create_task、list_tasks、complete_task、set_reminder、capture_note、set_timezone
【变更（阶段 2）】schedule_block、list_schedule、update_block_status、reschedule_block、set_notif_prefs、list_reminders、cancel_reminder
【变更（阶段 3a）】remember（type 允许 slot | preference | episode，state_signal 只能异步抽取；槽位冲突返回 pending_confirmation 并附旧值；证据绑定当前入站事件）
- 参数用 Pydantic 定义；时间参数必须是带时区偏移的 ISO 8601
- 写工具（create_task、complete_task、set_reminder、capture_note、set_timezone）不接受 LLM 提供的幂等键：由代码按入站事件派生，tool_call / tool_result 事件的 idempotency_key 形如 tool-call:{inbound_event_id}:{tool_name}:{call_index}（call_index 跨步骤递增）；幂等键写入与业务写入在同一事务
- set_timezone：参数为 IANA 时区名；校验通过后更新 user.timezone 并 rev+1
- 返回统一结构：status（ok | pending_confirmation | error）、data、message
- 系统提示中注入当前时间与用户时区；代码负责校验并拒绝过去时间或缺少时区的参数
- 新用户首次回复由代码（非 LLM）追加所用时区说明