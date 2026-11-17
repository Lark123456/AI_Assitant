# 计划汇总（2026-11-15）

> 本文件只汇总两条待执行计划的要点与待确认事项，不是技术方案正文。
> 两条计划目前**均未开工**，等待确认后再改代码。

## 一、总览

| 轨道 | 目标 | 状态 | 代码范围 | 结束验证 |
|---|---|---|---|---|
| A. 记忆修订（后端） | 修复 episode 时间、槽位归一化与降级、评测用例与脚本，重跑全量 | 待确认 | `app/memory/`、`scripts/run_memory_evals.py`、`tests/`、`docs/memory-policy.md` | 单元测试 + 全量评测按门槛汇报 |
| B. App U1 范围收缩（mobile） | 冻结旧报告、迁出超范围章节、收缩领域层、按原 U1 范围继续 | 待确认 | `docs/`、`mobile/lib/domain/`、`mobile/test/` | analyze / format / test / build apk |

两条轨道互不依赖，可以并行；同一时间只做一批，每批完成先汇报。

---

## 二、计划 A：记忆修订（后端）

### 1. 已核对的根因

| 现象 | 位置 | 根因 |
|---|---|---|
| e01「加班到九点」写成 09:00；b01「加班到十点」写成 10:00 | [validate.py](../app/memory/validate.py) episode 分支 | episode 的 `time_text` 直接解析，没有做角色窗口消歧 |
| j06 / v05 槽位召回失败 | [scope.py](../app/memory/scope.py) | `recurring` 且 rule 为空时返回 None → `rejected:scope_unparsed` |
| n05 / x06 被拒 | [validate.py](../app/memory/validate.py) slot 时间分支 | 槽位值解析不出时间时直接 `rejected:slot_time_unparsed` |
| 评测缺少单条 now / tz / day_start | [run_memory_evals.py](../scripts/run_memory_evals.py) | 只用 `meta.now/tz`，`day_start` 硬编码 04:00 |
| r05「后天去体检」期待拒绝日志 | [memory_cases.yaml](../tests/evals/memory_cases.yaml) | 敏感类别不出候选，就没有拒绝记录 |

### 2. 改动清单

1. **[timeparse.py](../app/memory/timeparse.py)**：新增活动词→时间角色映射（加班/下班→work_end、睡→sleep、起/起床→wake、到公司/上班→work_start、吃午饭→lunch）；新增 `resolve_episode_time()`，复用 `SLOT_TIME_WINDOWS`；有时段词或 24 小时制直接采用；无法确定返回 None，不写 `value.time`。
2. **[validate.py](../app/memory/validate.py)**：episode 改调新函数；`slot` 的 `recurring` 空 rule 归一化为 `persistent`（notes 记 `slot_scope_normalized`）；槽位值解析不出时间降级为 `preference`（notes 记降级标记）。
3. **[scope.py](../app/memory/scope.py)**：日期词补「今早 / 今晚 / 昨晚 / 昨夜」。
4. **[extract.py](../app/memory/extract.py)**：`EXTRACTOR_VERSION` 升为 `memory-extract-v2.1`；**不改提示词**（除非确定性修复不达标且经同意）。
5. **[run_memory_evals.py](../scripts/run_memory_evals.py)**：支持用例级 `now / tz / day_start`；`--check-cases` 校验新字段；`logs` 补被覆盖对象的 `source_class`，新增「静默覆盖」计数。
6. **[memory_cases.yaml](../tests/evals/memory_cases.yaml)**：
   - r05 改为 `expect: []`；关键词兜底改由确定性单测覆盖；
   - e01/e02/b01/b03 增加 `time` 期望（21:00 / 09:00 / 22:00 / 11:00）；
   - 新增 e07–e10：六点起 06:00、十一点睡 23:00、五点下班 17:00、中午一点吃饭 13:00；
   - 新增 l01（01:30 的「今天」→ 日期 2026-11-06、time 为空）、l02（05:00 的「今天要加班到九点」→ 2026-11-07、21:00）；
   - 新增 m01（同一天两次「加班到九点」只写 1 条）、m02（今天与明天各一次写 2 条、日期不同）。
7. **[memory-policy.md](./memory-policy.md)**：补充「每周几 / 每月几号」记为 `fixed_event` 槽位（recurring 且带 rule），一次性会议/聚餐/出差不记；记录 0 点到 day_start 之间「今天」按用户日解析的已知限制。
8. **测试**：角色映射与时间窗（含「映射不到角色不写 time」「两种读法都合理不写 time」）、归一化与降级，全部不依赖 LLM。

### 3. 评测与汇报

- 夜间在独立 worktree 运行全量，记录 `git_sha`、`dirty`、`case_file_sha256`。
- 门槛：错记率 ≤5%、episode 召回 ≥85%、槽位召回 ≥90%、时间归一化 ≥95%、注入与敏感写入 0、静默覆盖 0。
- 汇报：v2 与 v2.1 同用例前后对比 + 绝对数量 + 仍失败用例与根因。

### 4. 待确认（6 点）

1. 「睡」与「起」冲突：按列出顺序先匹配「睡」会让 e02 变成不确定；建议「睡到…（才）起」按 wake 处理。
2. 「昨晚」是否补为日期词（否则新用例可能 `rejected:scope_unparsed`）。
3. `slot_scope_normalized` 写进 `candidate.notes`，还是必须出现在 `reason` 字段。
4. 为「静默覆盖 = 0」在 raw 日志记录被覆盖邻居的 `source_class`。
5. 两种读法都不在窗口内时，是否同样不写 `time`（建议不写）。
6. m01 用完全相同的两条文本（依赖指纹去重），还是允许不同措辞。

### 5. 不在本计划

3b 的管理工具、确认环节、夜间任务、清除脚本；不改抽取提示词。

---

## 三、计划 B：App U1 范围收缩（mobile）

### 1. 背景

`docs/mobile-u1-technical-plan.md`（v2.4.4）包含会话同步协议、多会话与 Jarvis 专题、邀请卡幂等、PriorityAlert 等内容，依赖后端尚不存在的概念；今日页与对话页尚未开始。

### 2. 文档处理

1. **[mobile-u1-technical-plan.md](./mobile-u1-technical-plan.md)**：开头加冻结声明（不再新增版本、不再修订），U1 执行以新计划为准。
2. 新建 **`docs/deferred/mobile-sync-and-topics.md`**：原样移入 4.2、4.2.1、4.9、4.12、4.14、4.15、4.16、4.17、4.18、4.19、4.21、6.2、6.4、7、10、12.1、12.3、12.4，开头注明「延后，待后端接口方案确定后与后端一起设计」。
3. 新建 **`docs/mobile-u1-plan.md`**（≤300 行）：只对应设计令牌、导航外壳、今日页、对话页、调试面板、假数据、测试，列出剩余批次。

### 3. 领域层收缩（`mobile/lib/domain`）

| 处理 | 内容 |
|---|---|
| 删除 | `models/conversation.dart`、`models/chat_event.dart`、`models/alert.dart`、`models/invite.dart`、`repositories/alert_repository.dart` |
| 改写 | `enums.dart`：只留 ChatSender、SyncState、NetworkStatus、TodayItemKind/Status、BriefKind、ConfirmCardState、PlanDecision、PlanProposalState、PlanChangeType、MemoryCandidateState、ThinkingPhase |
| 改写 | `models/chat_message.dart`：去掉 `seq` / `conversationId`；保留 Text / Confirm / Choice / MemoryConfirm / PlanProposal / Thinking；`AgentInviteCard` 改为 `JarvisIntroCard`（topic/goal/scopeSummary/expectedOutcome，去掉 inviteId/status/accepting/projectId） |
| 改写 | `models/today.dart`：去掉 `projectId` / `projectTitle`，其余保留 |
| 改写 | `errors.dart`：只留 `StateTransitionException` |
| 改写 | `repositories/chat_repository.dart`：`watchMessages()` 返回消息列表流、`sendText()`、`respondToCard()`、流式回复；无事件序号/快照/基线/摘要 |
| 保留 | `models/card_action.dart`、`models/unset.dart`、`repositories/today_repository.dart`、`repositories/network_status_source.dart` |

### 4. 测试调整

- 删除：`conversation_test.dart`、`conversation_event_test.dart`
- 改写：`copy_with_test.dart`（去掉 Conversation / AgentInviteCard 组）、`local_message_test.dart`（只留消息状态约束）、`validation_test.dart`（去掉 PriorityAlert / AlertResumeContext）
- 新增：`JarvisIntroCard` 构造约束测试
- 保留：`color_contrast_test.dart`、`format_clock_test.dart`

### 5. 剩余批次

| 批次 | 内容 | 结束验证 |
|---|---|---|
| 4 | 文档整理 + 领域层收缩 + 测试修复 | analyze / format / test / build apk |
| 5 | Mock 仓库 + Provider 装配（简单 Stream + 模拟延迟） | 仓库与 Provider 单测 |
| 6 | 导航外壳：`lib/shell`、4 Tab、go_router、主题接入 | `shell_test` |
| 7 | 今日页：时间线、简报、完成/跳过/调整、加载/空/错误/离线/待同步 | 组件与缩放测试 |
| 8 | 对话页：消息列表、7 类卡片、流式、输入条、状态覆盖 | `chat_page_test` |
| 9 | 调试面板：模拟时间、网络、数据集、主题、文字缩放 | 开关生效 |
| 10 | 组件测试、截图、全量验收 | 全部命令通过；截图归档 |

每批结束汇报：改动清单、截图（UI 批次）、analyze 与测试结果、与规格的出入。

### 6. 约束

- 不再产出技术报告类长文档；不新增版本号；超出 U1 规格先问。
- 假数据仓库只用简单 Stream + 模拟延迟，不设计传输协议。
- 不新增状态管理/网络/代码生成库；后端代码零改动。

### 7. 待确认（5 点）

1. 章节是「物理移动」（原文档删正文，只留指针），还是复制到 deferred 后原文档不动。
2. ChatRepository 的流式形态：`watchMessages()` + `sendText()` + `respondToCard()` + `Stream<String> streamReply()` 是否可接受。
3. `ChatMessage` 是否连 `seq` 一起移除（属于同步协议）。
4. `JarvisIntroCard` 是否只做静态卡片 + 「接受并进入」提示，不创建任何对话。
5. 去掉 `projectId` 后，Today 项目入口是否直接不做。

---

## 四、当前仓库状态

- `master` 与 `origin/master` 同步，最新提交 `61c3930`（U1 批次 3：领域模型与仓库接口）。
- mobile 已完成：批次 1 工程与构建基线、批次 2 设计系统与时钟、批次 3 领域模型（本次收缩的对象）。
- 评测环境：WSL 内 `db` / `ollama` 容器运行中；Windows 侧 `127.0.0.1:11434` 连通性尚未验证，计划 A 开跑前先验证。
