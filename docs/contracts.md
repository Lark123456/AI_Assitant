# 契约 v0（变更需经确认）

## 变更记录

### 变更（阶段 3b：记忆确认与注入默认开启）
1. 记忆检索注入默认开启：`MEMORY_INJECT_ENABLED` 默认 true；显式设为 false 时仍按阶段 3 修复 F 的规则写 `memory_context` 审计，只是不注入。
2. `remember` 槽位冲突时不再降低旧 active 记忆权重，只把 `contradict_count` 加 1；同时创建 `status=pending`、`supersedes_id=旧记忆` 的候选，返回 `pending_confirmation` 并附 pending 记忆 id、subject、value、type、slot_key。
3. 用户确认 pending 记忆：pending → active、`source_class=confirmed`、weight=1.0，旧记忆 superseded；拒绝：pending → retracted 并记录 rejected_at，旧记忆保持 active。确认/拒绝分别写 memory_decision_log（SUPERSEDE/user_confirmed、NOOP/user_rejected）；旧记忆已非 active 时 pending 置 retracted（NOOP/stale_target）；同一旧记忆的其它 pending 在确认时一并 retracted（NOOP/superseded_pending）。
4. 手机聊天新增卡片事件：`event_log(type="card", direction="outbound", channel="mobile")`，payload `{card_type:"memory_confirm", text, items:[{item_id, label}]}`；幂等键 `mobile-card:{inbound_event_id}:{pending_memory_id}`；`occurred_at` 比同轮文本回复晚 1µs，文本回复为空时也写卡片。
5. Chat 历史/游标/单条状态扩展为 `type IN ('message','card')`；文本消息 `kind="text"`，记忆卡片 `kind="memory_confirm"`。卡片 item 状态按 Memory 当前状态实时派生：pending | confirmed | rejected（retracted 或未确认的历史记忆按 rejected 展示），卡片事件本身只存快照。
6. 新增 `POST /api/mobile/chat/messages/{id}/card-actions`：body `{action: "confirm" | "reject", itemId?}`；省略 itemId 表示确认卡片内全部 pending item；itemId 必须属于该卡片，否则 400。
7. 移动端记忆卡片改为逐条双按钮「确认替换 / 保留原值」；远程仅支持记忆卡片的卡片应答，其它卡片仍由 Mock 支撑。

### 变更（U2-B Mobile U2 剩余）
1. 新增 `GET /api/mobile/tasks`：只读任务列表（open/done/all），附带最早的未来计划块；写操作复用 Today 端点，不新增任务写接口。
2. 新增 `GET /api/mobile/profile`：只读用户资料（displayName、timezone、dayStart、createdAt）。
3. 新增 `GET /api/mobile/reminders/due`：返回最近时间窗内已到点、未过期的 reminder，供 App 前台应用内提醒；不做 OS 通知或远程推送。
4. 新增 `GET /api/mobile/chat/messages/{id}/stream`（SSE）：`delta` 为本次模型调用的累计文本，`done` 携带最终持久化回复与 outbound 事件 id，`error` 表示失败/不可用；晚订阅先收到快照；处理完成后可从 broker 或数据库兜底返回。
5. 流式实现为进程内 `ChatStreamBroker`：与 per-user 串行锁一样只支持单进程 API；多 worker/副本时订阅可能返回 `stream_unavailable`，客户端回退轮询。
6. 工具调用场景允许先输出前导文本；`done` 以最终持久化回复覆盖，保证 UI 与 event_log 一致。
7. `MobileAdapter` 的 `Capabilities.streaming` 改为 true，表示手机端支持 SSE 拉流，不支持主动推送。
8. Flutter 新增 `SseClient` 接口（与 `ApiClient` 分离）；RemoteChatRepository 用流式气泡展示 delta，done 后落为正式消息，与轮询按 serverId/replyToId 去重，SSE 失败静默回退轮询。

### 变更（U2-A 手机聊天）
1. 手机入口复用已认证 User：新增 `InboundPipeline.ingest_for_user(event, user, client_message_id)`；不调用 `get_or_create_user`，不创建 `channel=mobile` 的 channel_identity；白名单由 Mobile API 的 `get_mobile_user` 完成。
2. 新增 `MobileAdapter`：channel=mobile，start no-op，send 只返回 ok，不写 event_log；能力声明为不支持主动推送与按钮（U2-B4 起支持 SSE 拉流，见下方 U2-B 变更）。它只用于 adapter 注册、recovery 渠道过滤与能力声明，正常手机路径不调用 send。
3. 手机安全完成路径：`FridayAgent.handle` 返回后，在同一事务写 outbound 与 `inbound_processing(done)`，随后直接返回，跳过 `MobileAdapter.send` 与 outbound 事务 B；Agent 异常时回滚半途写入，再写兜底回复并置 done。
4. 手机 outbound payload：`{text, delivery: "persisted", reply_to_event_id, client_message_id}`；不使用 `send_ok`；幂等键 `mobile-reply:{inbound_event_id}`，同一入站事件至多一条回复。
5. 手机入站 payload：在通用 payload 基础上带 `client_message_id`；入站幂等键 `mobile-chat:{user_id}:{clientMessageId}`，同一用户同一 clientMessageId 只产生一条入站事件。
6. 渠道隔离：`build_history` 增加 channel 参数，短期上下文只取同一渠道；长期记忆检索不按渠道过滤。
7. Mobile Chat API（见「接口 / Mobile Chat API」）：POST 发送、GET 历史、GET 单条状态；首屏取最新 N 条再升序返回；手机出站状态为 `available`，不使用 `sent`。
8. 同一用户的消息处理在 API 进程内用 `asyncio.Lock` 串行；U2-A 只支持单进程 API，多 worker/多副本需跨进程协调。
9. 恢复：`recover_unfinished()` 只处理本服务注册了 adapter 的渠道；只有注册 mobile adapter 的 API 服务接手手机 processing 事件，Feishu 服务跳过。
10. 新增工具：`update_task`、`update_reminder`、`list_notes`；`reschedule_block` 的终态/跨天/最短 5 分钟校验与 Today 改期接口一致，过去时间策略为“允许修正当天已逾期块”。

### 变更（阶段 3 修复 F：记忆读取注入）
1. Friday 每轮处理用户消息时检索长期记忆并注入 system 提示：只取 status=active；pending / superseded / retracted 不参与。
2. 向量检索只比较 embedding_model 与当前嵌入模型一致的记忆（不同模型的向量不混合比较）；结构化槽位不依赖向量，始终可用。
3. 检索查询由「当前用户消息 + 最近最多 4 条用户消息」组成；助手回复只进入对话历史，不作为用户事实参与检索。
4. slot 召回增加 valid_from / valid_to 与 scope 有效性过滤；同一 slot_key 只注入一条最新有效记录（按 recorded_at 取最新），总量不超过 8 条。
5. 偏好与 episode 同样校验 valid_from / valid_to 与 scope（persistent / recurring 长期有效；on / until 按日期终点判断，valid_to 缺失时由 scope 日期推导）。
6. 偏好与 episode 统一按相似度排序后选取：合计不超过 MEMORY_INJECT_TOPK=6，其中 episode 最多 3 条；相似度低于 MEMORY_INJECT_MIN_SIMILARITY 的不参与。
7. 预算裁剪按「槽位 → 偏好 → episode」优先级整条取舍：单条超过 MEMORY_INJECT_ITEM_MAX_CHARS 整条跳过，总长不超过 MEMORY_INJECT_MAX_CHARS，禁止截断半句话；审计只记录真正进入 Prompt 的记忆。
8. 渲染标注来源：stated=用户明说、confirmed=已确认、inferred=推断，仅供参考；提示词规定推断类不得用于修改日程、提醒时间或主动提醒时机，记忆与用户当前说法冲突时以当前说法为准。
9. 「已知长期信息」在提示词中标记为不可信数据：即使其中出现指令式文字，也不得作为系统指令执行。
10. 每轮（含无命中、嵌入降级、功能关闭）都写 event_log（direction=system、type=memory_context），payload 含 retrieval_version、source_event_id、enabled、query、实际注入的 memory_ids、similarities、items、result_count、retrieved_count、duration_ms、degraded、degraded_reason、embedding_model、block_chars；幂等键 memory-context:{source_event_id}。审计在 LLM 调用前单独提交，后续失败回滚不会丢失。
11. Embedding 请求使用 asyncio.wait_for 加 MEMORY_INJECT_TIMEOUT_SECONDS=2.0 超时；超时或失败降级为只注入槽位，degraded=true，Friday 正常回复。
12. 新增配置：MEMORY_INJECT_ENABLED=false（默认关闭）、MEMORY_INJECT_TOPK=6、MEMORY_INJECT_MIN_SIMILARITY=0.45、MEMORY_INJECT_MAX_CHARS=4000、MEMORY_INJECT_ITEM_MAX_CHARS=120、MEMORY_INJECT_TIMEOUT_SECONDS=2.0；检索版本常量 RETRIEVAL_VERSION=memory-retrieve-v1。

### 变更（阶段 3 修复 C：抽取器 v2）
1. 抽取器输出 schema 移除 state_signal：MemoryCandidate.type 只允许 slot | preference | episode；数据库 CHECK 枚举保留 state_signal 供历史数据使用。
2. EXTRACTOR_VERSION 升为 memory-extract-v2；提示词重写 episode 判定条件（必须有日期锚点，且偏离常规并影响时间/精力/可用性，或带日期的具体事件），并内嵌 6 条正例与 8 条反例（few-shot 单独维护，不得取自评测用例）。
3. slot 的 scope 只能是 persistent | recurring，否则 rejected:slot_scope；episode 的 scope 必须是 on | until 且日期可解析，否则 rejected:episode_scope / rejected:scope_unparsed；episode confidence 低于 0.6 拒绝（rejected:episode_low_confidence）；每个 run 最多写入 5 条 episode，超出记 rejected:episode_cap。
4. 12 小时制按槽位窗口确定性纠正为 24 小时制：wake 04:00–11:00、work_start 06:00–12:00、lunch 10:30–14:30、work_end 14:00–23:30、sleep 20:00–04:00；commute / energy_peak / fixed_event 不自动翻转；两种读法都合理或都不合理时保留原话。
5. episode 的 valid_to：日期 D 的 D+2 天 00:00（用户本地时区转 UTC）；until 采用同一终点。valid_to 已早于当前时间的 episode 拒绝（rejected:episode_date_past），昨天这类仍在有效期内的接受。
6. episode 去重（duplicate_open_fact）必须 subject、value、scope 全部相同；不同日期的同类事件视为独立事实。
7. 敏感关键词兜底只检查候选项自身（subject、value_text、quote），不扫描整条事件文本，避免同批次中的敏感词误伤无关候选；命中时拒绝原因为 rejected:sensitive_keyword:{类别}:{命中词}；remember 同步路径不受兜底影响。

### 变更（阶段 3 修复 D：策略与评测口径）
1. 敏感类别改为「异步抽取一律拒绝」：即使原话包含「记住」，异步路径也返回 rejected:sensitive；只有 remember 同步工具（explicit_remember=True）可写入。原「证据中出现明确记住意图即放行」作废。
2. 新增 docs/memory-policy.md，定义记忆/非记忆边界：episode 必须有日期锚点且偏离常规并影响时间/精力/可用性；会议、出差、缴费、截止日期等可表达为任务或时间块的内容不算记忆。
3. 评测用例调整：r01/r02/r03/r06/r07/r08 期望为空；r05 期望 rejected:sensitive；y01/y03/y05/y07 期望为空并标记 category=sensitive_explicit；新增 j04–j07 无语境槽位用例、14 条低价值/假设/疑问/转述负例、3 条过去日期用例（b01/b03 有效期内接受，b02 期望 rejected:episode_date_past）。
4. 评测新增 category 分类写入统计（injection / sensitive / sensitive_explicit / past，目标写入为 0）与 expect_rejected / reject_prefix 断言；结果新增 write_by_category。
5. 评测溯源：拿不到 git_sha 或 dirty 时必须退出，可用 --git-sha / --git-dirty 显式指定；v1 基线记录已补录 git_sha=ea730d6、dirty=false 并注明基于独立 worktree。

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
10. 敏感类别：health | finance | exact_location | third_party | credentials；默认拒绝。异步抽取一律拒绝（即使原话含「记住」），只有 remember 同步工具（explicit_remember=True）放行（阶段 3 修复 D 调整）。
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
【变更（U2-A）】手机聊天不写入 channel=mobile：手机 API 通过开发期用户头解析已有 User 后调用 `ingest_for_user`，CHECK 约束保持不变。

### event_log（阶段 1，append-only）
id、user_id、channel、direction（inbound | outbound | system | tool）、type（message | callback | tool_call | tool_result | trigger | delivery 等）、payload（jsonb）、idempotency_key（可空，唯一）、trace_id、occurred_at、recorded_at
约束：数据库层面禁止 UPDATE 与 DELETE（触发器或权限）；索引 (user_id, occurred_at)
【变更（U2-A）】手机消息 channel=mobile：入站 payload 额外带 `client_message_id`；手机出站 payload 为 `{text, delivery: "persisted", reply_to_event_id, client_message_id}`，不写 `send_ok`。

### inbound_processing（阶段 1 修订 2）
event_id（主键，FK event_log.id）、user_id、status（processing | done | failed）、error（可空）、updated_at
说明：event_log 只追加，入站事件的处理状态放此独立表；ingest 与入站事件同事务写入 processing，process 结束置 done/failed；服务启动时补处理仍为 processing 的事件（工具幂等键保证重放安全）
【变更（U2-A）】启动补处理按服务已注册的 adapter 过滤渠道：手机事件只由注册 mobile adapter 的 API 服务接手，Feishu 服务跳过。

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
【变更（U2-A）】MobileAdapter：channel=mobile；start no-op；send(intent) 返回 ok 但不发送、不写 event_log；Capabilities(can_push_unsolicited=false, streaming=false, supports_buttons=false)。手机正常回复由 Pipeline 写入 event_log，不调用 send。
【变更（U2-B）】MobileAdapter 的 `streaming` 改为 true：手机端通过 SSE 拉流；send 仍为 no-op，不支持主动推送。

### Mobile Tasks / Profile / Reminders API（U2-B）

开发期认证同 Mobile Chat：`X-Butler-User` + `ENABLE_MOBILE_API=1` + `ALLOWED_OPEN_IDS`；仅本机或 `adb reverse`。

`GET /api/mobile/tasks?status=open|done|all&limit=100`

- 只读当前用户 `type=item` 的任务；`open→active`、`done→done`、`all→active/done/dropped`。
- 状态映射 `active→open`、`done→done`、`dropped→skipped`；`upcomingBlock` 取最早的未来 `planned` 块。
- 写操作复用 Today 的 complete/skip/restore/schedule 端点。

`GET /api/mobile/profile`

- 返回 `{displayName, timezone, dayStart("HH:MM"), createdAt}`；只读。

`GET /api/mobile/reminders/due?graceMinutes=30&limit=20`

- 返回 `fire_at` 在 `[now-graceMinutes, now]`、未过期、状态为 pending/claimed/fired 的 reminder。
- 仅用于 App 前台应用内提醒；不创建系统通知、不申请通知权限、不做远程推送。

### Mobile Chat SSE（U2-B）

`GET /api/mobile/chat/messages/{id}/stream`

- 校验事件归属当前用户、`channel='mobile'`、`type='message'`、`direction='inbound'`，否则 404。
- 事件格式：
  - `event: delta`，`data: {"text": "<本次模型调用的累计文本>"}`；客户端按覆盖渲染。
  - `event: done`，`data: {"text", "messageId", "replyToId", "createdAt"}`；`messageId` 为 outbound event id。
  - `event: error`，`data: {"code": "processing_failed" | "stream_unavailable"}`。
  - 空闲时发送 `: ping` 注释，客户端忽略。
- 晚订阅：先收到当前文本快照或终态；处理完成后 broker 无状态时从数据库查 outbound 回复兜底。
- `processing` 但 broker 无状态（进程重启/多进程）返回 `stream_unavailable`，客户端回退现有轮询。
- 单进程约束：broker 不跨进程；多 worker/副本时流式不可用但轮询仍可用。

### Mobile Chat API（U2-A）

开发期认证：`X-Butler-User`（用户 UUID 或渠道外部 id）+ `ENABLE_MOBILE_API=1` + `ALLOWED_OPEN_IDS`。这不是真实认证，只允许本机或 `adb reverse` 调试，不能暴露到局域网或公网；`ALLOWED_OPEN_IDS` 不能替代认证。

`POST /api/mobile/chat/messages`

- body：`{clientMessageId(1–200), text(1–4000)}`。
- 幂等：服务端键 `mobile-chat:{user_id}:{clientMessageId}`；同用户同 key 返回既有事件，不再次处理。
- `Idempotency-Key` 头可选；若出现必须与 `clientMessageId` 完全一致，否则 400。
- 新消息返回 202：`{id, clientMessageId, status: "processing", createdAt, duplicate: false}`；重复请求返回 200、当前状态与 `duplicate: true`。
- 落库后异步处理；同一用户的消息在 API 进程内串行。

`GET /api/mobile/chat/messages?limit=50&after=<event_id>&before=<event_id>`

- 只返回 `user_id=当前用户 AND channel='mobile' AND type IN ('message','card') AND direction IN ('inbound','outbound')`。
- 首屏（无游标）：先按 `occurred_at DESC, id DESC` 取最新 `limit` 条，再反转为升序返回；`limit` 1–100，默认 50。
- `after` 取游标之后的增量；`before` 取游标之前的更早历史；二者不能同时使用。游标必须是同一用户的手机聊天事件（message 或 card），否则 400。
- `messages` 始终按 `occurred_at ASC, id ASC`；响应含 `nextCursor`、`previousCursor`、`hasMore`。

`GET /api/mobile/chat/messages/{id}`

- 校验事件归属当前用户且 `channel='mobile'`、`type='message'`，否则 404；用于 `processing → done/failed` 的状态补偿。

`POST /api/mobile/chat/messages/{id}/card-actions`

- 校验事件归属当前用户且 `channel='mobile'`、`type='card'`、`payload.card_type='memory_confirm'`，否则 404。
- body：`{action: "confirm" | "reject", itemId?}`；`itemId` 省略时对卡片内全部 pending 记忆执行该动作。
- `itemId` 必须属于该卡片的 items（即 pending 记忆 id），否则 400；找不到对应 pending 记忆返回 404。
- 返回该卡片的当前结构（见下）；重复确认幂等，不会产生第二条 active 记忆。

消息结构：`{id, kind, clientMessageId, role: user | friday, text, status, replyToId, createdAt}`。

- 文本消息 `kind="text"`；记忆确认卡片 `kind="memory_confirm"`，额外含 `items: [{itemId, label, state}]`、`allHandled`、`allConfirmed`。
- 卡片 item `state`：`pending | confirmed | rejected`，按 Memory 当前状态实时派生；`rejected` 同时覆盖用户拒绝与已失效的历史记忆。
- 入站 `status`：`processing | done | failed`；没有 `inbound_processing` 行时按 `failed` 返回并记录告警。
- 手机出站 `status`：`available`（已落库、App 可取），不使用 `sent`；`replyToId` 为对应入站事件 id。
- 不返回 `tool_call`、`tool_result`、`note`、`memory_context`、`delivery`、`trigger` 等事件。

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

### Friday 工具（阶段 1；【变更（阶段 1 修订）】幂等键派生方式变更并新增 set_timezone；【变更（阶段 2）】新增时段与偏好工具；【变更（阶段 3a）】新增 remember；【变更（U2-A）】新增 update_task / update_reminder / list_notes）
create_task、list_tasks、complete_task、set_reminder、capture_note、set_timezone
【变更（阶段 2）】schedule_block、list_schedule、update_block_status、reschedule_block、set_notif_prefs、list_reminders、cancel_reminder
【变更（阶段 3a）】remember（type 允许 slot | preference | episode，state_signal 只能异步抽取；槽位冲突返回 pending_confirmation 并附旧值；证据绑定当前入站事件）
【变更（U2-A）】update_task、update_reminder、list_notes
- 参数用 Pydantic 定义；时间参数必须是带时区偏移的 ISO 8601
- 写工具（`ToolDef.write=True`，含 create_task、complete_task、set_reminder、capture_note、set_timezone、update_task、update_reminder 等）不接受 LLM 提供的幂等键：由代码按入站事件派生，tool_call / tool_result 事件的 idempotency_key 形如 tool-call:{inbound_event_id}:{tool_name}:{call_index}（call_index 跨步骤递增）；幂等键写入与业务写入在同一事务
- set_timezone：参数为 IANA 时区名；校验通过后更新 user.timezone 并 rev+1
- 【变更（U2-A）】update_task：按 user_id 校验归属；只修改 title / description（至少提供一个），不改 status，不新建任务；rev+1、updated_at 刷新；非本人或不存在返回 error。
- 【变更（U2-A）】update_reminder：只允许 status=pending；`SELECT ... FOR UPDATE` 锁行后再校验状态，原地更新现有 trigger 的 fire_at、expires_at 与 payload.note（fire_at 与 note 至少提供一个），trigger id 不变，不取消重建；fire_at 必须是未来时间；更新后写 event_log(type="trigger", payload={status:"updated", reason:"user_updated"})；已被 worker claim 或其他终态返回 error（由 Friday 告知用户）。
- 【变更（U2-A）】list_notes：按 user_id 查询 direction=tool、type=note 的 event_log，按 occurred_at DESC、id DESC 取最近 N 条（limit 1–100，默认 20）；返回 note_event_id、text、created_at；不新增表。
- 【变更（U2-A）】reschedule_block 与移动端 Today 改期规则一致：只允许 planned 状态；拒绝跨本地日期；新时长不得少于 5 分钟；与 Today 一致允许把当天已逾期的块修正到过去时刻。
- 返回统一结构：status（ok | pending_confirmation | error）、data、message
- 系统提示中注入当前时间与用户时区；代码负责校验并拒绝过去时间或缺少时区的参数
- 新用户首次回复由代码（非 LLM）追加所用时区说明