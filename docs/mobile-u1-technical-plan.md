# 阶段 U1 技术报告（v2.4.4）：Flutter 子项目、设计系统、导航外壳、今日页、Friday 主对话与 Jarvis 专题对话

> 状态：已定案，可按批次开工（v2.4.4，2026-11-14）
> 本版修订日期：2026-11-14（v2.4.4）
> 历史日期：初版日期按 2026-11-11 记录；2026-11-12 为笔误，已在 15.3 定案
> 版本历史：v2（2026-11-11）→ v2.1（2026-11-11）→ v2.2（2026-11-11）→ v2.3（2026-11-11）→ v2.4（2026-11-11）→ v2.4.1（2026-11-11）→ v2.4.2（2026-11-11）→ v2.4.3（2026-11-11）→ v2.4.4（2026-11-14）
> 范围：单仓库内新增 `mobile/` 子项目，后端代码零改动
> v2.1 修订目标：补齐领域模型完整定义、拆分 `PriorityAlert` 与 `AlertResumeContext`、明确消息快照与实时事件的无遗漏衔接、补充邀请接受幂等规则，并修正依赖锁定等细节
> v2.2 修订目标：统一会话事件序列（含 `ConversationUpdated`）、明确本地临时消息与正式 seq 边界、补全并发接受幂等语义、修正 `copyWith` 清空语义、明确 Repository / Controller / UI 职责边界
> v2.3 修订目标：补全事件序号三分支规则与三阶段统一处理、贯通 `clientMessageId` 与重试、重同步保留 pending 消息、完整化可空字段清单与业务不变量、修正依赖版本表述与颜色对比度数值、明确真机验收与两处接口职责
> v2.4 修订目标（条件通过后的定向修复）：统一过期事件与同 seq 冲突判定、明确 pending 由 Controller 创建/持有/合并、补齐业务不变量总表、修正 Flutter 测试目录与命令、统一 7 组对比度表述、修正 `ChatMessage.seq` 注释与 4.16 接口约束
> v2.4.1 修订目标（定向收口）：修复快照基线与事件摘要的矛盾、完整定义 `chatControllerProvider` / `ChatState` / pending 确认清理与 `ChatView` 展示列表、把业务不变量落到构造/copyWith 的 assert、修正 pending/failed 与负数 seq 的关系、Flutter 命令先进入 `mobile/`、补 WSL `--cd` 兼容检查与快照基线测试
> v2.4.2 修订目标（有条件通过后的收口）：修正 Riverpod 3.5.0 family Notifier 写法、区分运行时校验与 assert、补重同步重试上限与退避、修正主对话 projectId 约束、修正 TodayItem overdue 与 start 规则、补遗漏不变量与集合不可变、明确 Controller/订阅生命周期、修正创建命令并落实 minSdk 26
> v2.4.3 修订目标（定向收口）：修正 `AsyncValue.value` 与全部 Riverpod 3 API 示例、明确 Controller/StreamProvider 暂停恢复释放、补事件队列串行与 buffer 原子切换、补 jitter 与首次加载失败、按类型计算 TodayItem overdue、补剩余不变量与 release 状态转换保障、明确离线发送与销毁保护、关闭 15.3 可定案事项
> v2.4.4 修订目标（开工前定案）：修正 channel 暂停与 keepAlive 监听的矛盾、明确确认超时为 U1 边界、统一 `retrySync` 语义、把同步规则集中到 `ConversationSyncEngine`、深色令牌改为批次 10 截图验收
> 审核点：无阻塞项；5.2 深色令牌在批次 10 以截图验收

---

## 0. 版本变化摘要

| 项 | v2 | v2.1 |
|---|---|---|
| 领域模型 | 部分字段示意 | 完整 Dart 定义（枚举、构造函数、继承、copyWith 约定） |
| Agent 类型 | 邀请复用 `ChatSender` | `ChatSender` 仅表示消息发送者；新增 `ConversationAgent` 表示对话负责方 |
| 紧急提醒 | `PriorityAlert` 内含 `interruptedConversationId` | 拆分为 `PriorityAlert`（提醒数据）与 `AlertResumeContext`（页面恢复信息） |
| 消息衔接 | `loadMessages` + `watch` 未定义衔接 | 先订阅、后快照、按 `seq` 合并，支持缺口检测与重取 |
| 邀请接受 | 未定义幂等 | 明确 `inviteId` 唯一性、接受/拒绝互斥、重复接受返回既有对话 |
| 依赖版本 | 「安装时最新稳定版」 | 锁定 Flutter 3.47.2 / Dart 3.13.2 与 4 个依赖的具体版本 |
| Friday 头部 | 「Friday · 常驻 · 秒回」 | 「Friday · 日常助理 · 随时待命」 |
| Mock 时间 | Today 11:30 与提醒样例 14:00 冲突 | 统一为 11:30 |
| 紧急提醒测试 | 仅专题对话内 | 增加 Today 页面触发与返回测试 |

### 0.1 v2.2 变化

| 项 | v2.1 | v2.2 |
|---|---|---|
| 事件序列 | 主要约束 `MessageUpsert` | 所有会话事件（含 `ConversationUpdated`）共用同一 `seq` 序列 |
| 快照 | 只含 messages + lastSeq | 同时含 `conversation`、`messages`、`lastSeq`，避免对话信息与消息不同步 |
| 本地临时消息 | 允许负数 seq，未定义边界 | 明确不进入正式序列、不参与缺口检查与 lastSeq，确认后按 messageId 回填归位 |
| 邀请并发 | 只写「最多创建一个」 | 补全串行化、并发请求返回同一对话、项目只创建一次、终态不按网络失败处理 |
| copyWith | `??` 无法区分「不传」与「传 null」 | 统一 sentinel 方案，可空字段支持显式清空 |
| 职责边界 | 未明确 | Repository / Controller / UI 三层职责写入 4.17 |

### 0.2 v2.3 变化

| 项 | v2.2 | v2.3 |
|---|---|---|
| 事件序号判断 | 只规定缺口重取 | 明确 `<= currentSeq` 忽略、`== +1` 应用、`> +1` 重同步三分支；初次合并、持续监听、重同步共用同一规则 |
| 事件一致性 | 未定义 | 校验 `conversationId`、消息内外 `seq`/`conversationId`；同 seq 冲突内容按协议异常处理 |
| 本地消息 | 有负数 seq，未定义发送 ID | `sendText` 增加 `clientMessageId`；确认、重试、去重全程复用同一 ID |
| 重同步 | 未定义 pending 处理 | 快照只重建正式消息，pending 保留并按 `messageId` 合并 |
| copyWith | 部分字段哨兵 | 全量可空字段清单 + 是否可改/可清空 + 业务不变量校验 |
| 依赖版本 | 「修订日最新稳定版」 | 明确为已验证基线；升级需批准并全量回归 |
| 颜色对比度 | `onPrimaryContainer` 标 7.5:1 | 复算为 6.69:1；列出 7 组测试配对 |
| 真机验收 | 只写 Mate 70 | 记录实际系统名称/版本、安装与核心交互结果，不外推全系兼容 |
| Chat 数据源 | 两个 Provider 并存 | 明确以 `conversationChannelProvider` 为唯一实时来源 |
| 邀请操作 | `InviteAction` 与专用接口并存 | 删除 `InviteAction`，邀请只走 `acceptInvite` / `declineInvite` |

### 0.3 v2.4 变化

| 项 | v2.3 | v2.4 |
|---|---|---|
| 过期与冲突 | `<= currentSeq` 一律忽略，又与「同 seq 冲突」并列 | 拆分为 `<`（过期，仅诊断）与 `==`（重复或头部冲突）；buffer 内同 seq 冲突单独判定；引入最近 200 个 seq 的事件摘要 |
| pending 归属 | Repository 重建并合并 pending | 统一由 Controller 创建、持有、合并；Repository 只处理正式状态 |
| 业务不变量 | 4 条散列 | 覆盖 Conversation、ChatMessage、ConfirmCard、ChoiceCard、MemoryConfirmCard、PlanProposalCard、AgentInviteCard、TodayItem、PriorityAlert、AlertResumeContext 的总表 |
| 测试目录与命令 | `flutter_tools format`、WSL 反斜杠转义 | `dart format --output=none`；`wsl --cd` 指定工作目录；明确 `mobile/test/` 为单数 |
| 对比度分组 | 6 组 + 可选第 7 组 | 统一为 7 组，全部必须断言 |
| seq 注释 | 「会话内单调递增」 | 明确正式事件序号与 pending 负数临时值的区别 |
| 4.16 接口约束 | 3 条 | 9 条，覆盖 clientMessageId、pending 归属、快照一致性、邀请专用接口 |

### 0.4 v2.4.1 变化

| 项 | v2.4 | v2.4.1 |
|---|---|---|
| 快照与摘要 | 摘要保留最近 200 个已应用 seq，未说明快照覆盖区间 | 引入 `baselineSeq`，摘要只对 `(baselineSeq, currentSeq]` 建立；`seq <= baselineSeq` 直接忽略，快照刚建立时不再误判头部冲突 |
| ChatController | 只写「Controller 持有 pending」 | 新增 `chatControllerProvider`、`ChatState` 完整定义；明确发送、失败、重试、确认清理与对话切换的生命周期 |
| ChatView | 只有 `messages + pending` 字段 | 增加 `sendErrors` 与 `displayMessages`，明确页面只渲染一个有序列表，pending 永不与正式消息重复 |
| 业务不变量 | 总表 + 仅 3 个模型有 assert | 每个模型在构造函数与 `copyWith` 内落地 assert，并列出测试映射与 `const` 取舍 |
| pending / failed | 只约束 pending 为负数 seq | pending 与 failed 都使用负数临时 seq、都不进入正式序列；failed 保留原 id/seq，重试复用，不因重同步被清除 |
| 命令目录 | 假定在仓库根执行 Flutter 命令 | 所有 Flutter 命令先 `Set-Location` 到 `mobile/`；后端命令仍在仓库根执行 |
| WSL `--cd` | 直接使用 | 增加兼容检查命令与 `bash -lc "cd ..."` fallback |
| 基线测试 | 未区分快照覆盖与摘要窗口 | 新增 `baselineSeq`、摘要窗口 200 条淘汰、重同步清空摘要的测试项 |

### 0.5 v2.4.2 变化

| 项 | v2.4.1 | v2.4.2 |
|---|---|---|
| Riverpod family | `Notifier.build(String)` 带参数 | Riverpod 3.5.0 写法：`Notifier` + 构造函数参数 + `build()` 无参；并关闭 provider 自动重试 |
| assert 与运行时校验 | 主要依赖 assert | 新增 4.20：assert 只校验开发者不变量；外部事件/快照/邀请数据必须运行时校验并返回类型化错误 |
| 重同步重试 | 无限重试、无退避 | 最多 3 次尝试；退避 300ms、600ms（±20% jitter）；最终 `failed` 状态，保留最后有效数据，手动重试 |
| Conversation.copyWith | 允许给主对话设置 projectId | 增加 `main → projectId == null` 断言，主对话 projectId 永远不可设置 |
| TodayItem | `overdue` 是状态值；非 block 可清空 start | `overdue` 改为派生 getter；只有 `task` 允许清空 start，block/reminder 必须非空 |
| 集合不可变 | 直接持有传入 List/Map | 所有集合字段在构造时复制为 `List.unmodifiable` / `Map.unmodifiable`；补充集合相关不变量 |
| ChatState.copyWith | 直接构造新状态 | 先计算并断言 pending/sendErrors 再构造；列表与映射不可变 |
| Controller 生命周期 | 只写 keepAlive | 明确创建、页面离开暂停、返回恢复、确认清理、重置销毁；无 Widget 级订阅 |
| 创建命令与 minSdk | `flutter create` 与表格中的 minSdk 26 | 使用 `dart flutter_tools.dart create`；`android/app/build.gradle.kts` 显式 `minSdk = 26`，并增加 APK 校验 |

### 0.6 v2.4.3 变化

| 项 | v2.4.2 | v2.4.3 |
|---|---|---|
| AsyncValue | 使用已移除的 `valueOrNull` | 统一改为 `AsyncValue.value`；新增 Riverpod 3 API 对照表 |
| 生命周期 | 只写 keepAlive 与暂停 | 增加 Controller / StreamProvider / Repository 流的创建、暂停、恢复、释放规则 |
| 事件队列 | 只要求串行 | 明确单队列串行、同步应用段、`syncGeneration`、buffer 原子切换、队列上限与溢出处理 |
| 重试测试 | 只写 300/600ms jitter | 固定种子 `Random`、±20% 区间断言、不超过 1200ms；首次加载失败 3 次转 AsyncError |
| TodayItem overdue | 全类型统一按 start | block 按 end、reminder 按 start+10min、task 按 start；无 start task 不逾期 |
| 剩余不变量 | ChoiceCard 等部分缺失 | 补 ChoiceCard 选项唯一、ChoiceAction skipped/option、AlertAction 唯一、DayView 排序与 brief、ChatView 同步状态 |
| release 保障 | 主要依赖 assert | 终态转换增加 `StateTransitionException` 运行时检查；copyWith 不得静默接受非法转换 |
| 离线发送 | 未定义 | `SyncState.queued`、联网串行 flush、失败停止保留顺序；异步返回检查 Controller 是否销毁 |
| 15.3 | 6 项待确认 | 5 项定案，仅保留深色令牌视觉验收 |

### 0.7 v2.4.4 变化

| 项 | v2.4.3 | v2.4.4 |
|---|---|---|
| channel 生命周期 | 声称 listener 全部不可见时暂停 | 改为不暂停：Controller keepAlive 监听使 channel 始终有活跃 listener；页面返回时 `reconcile()` |
| 发送确认 | 未定义确认超时 | 明确为 U1 已知边界：不实现超时定时器；Mock 必须有限时间内确认或抛错；真实后端接入时补超时与重发 |
| `retrySync` | 4.16 与 4.17 表述不一致（是否重建订阅） | 统一为：不重建订阅、重置退避、清空旧队列后重新取快照；仅 `failed` 状态下允许手动重试 |
| 同步规则实现位置 | 分散在 Repository 描述中 | 全部集中到 `ConversationSyncEngine`（`core/sync/`），Repository 委托，Controller/UI 不感知 |
| 深色令牌 | 唯一待确认项，阻塞语义 | 改为按 5.2 表实现，批次 10 截图验收，不阻塞编码 |

---

## 1. 环境验证结论（已完成）

### 1.1 已确认可用

| 项 | 实际值 |
|---|---|
| Flutter | 3.47.2 stable（`D:\flutter`，未加入 PATH） |
| Dart | 3.13.2（支持 sealed class、records、模式匹配） |
| JDK | 21（`C:\Program Files\Java\jdk-21`） |
| Android SDK | `E:\AutoPunch\.android-sdk`（Autopunch 项目通过 `local.properties` 使用） |
| 已补装 | `platforms;android-36`、`build-tools;36.0.0` |
| `flutter doctor` | Android toolchain √（SDK 36.0.0） |
| Gradle 分发包 | 9.3.1 已缓存于 `~/.gradle/wrapper/dists` |

### 1.2 特殊路径问题与修复

仓库路径 `E:\F&J\FJ v1` 含 `&` 与空格。Dart 工具链（create / pub get / analyze）不受影响；Gradle Wrapper 受影响，根因是 `gradlew.bat` 三处未加引号的路径赋值：

```bat
set "DIRNAME=%~dp0"
set "APP_HOME=%DIRNAME%"
set "CLASSPATH=%APP_HOME%\gradle\wrapper\gradle-wrapper.jar"
```

实测结果：

| 场景 | 结果 |
|---|---|
| 仓库路径，未打补丁 | 失败：`系统找不到指定的路径` + `ClassNotFoundException GradleWrapperMain` |
| 仓库路径，仅修 CLASSPATH | 仍失败（DIRNAME 已先被截断） |
| 仓库路径，三处全修 | 成功，66.9 秒产出 `app-debug.apk` |
| 同路径，依赖缓存后、无代理 | 成功，16.6 秒 |
| 对照：`D:\fp_clean`（无特殊字符） | 成功，首次 798 秒（含 Gradle 9.3.1 下载） |

结论：三行补丁即可在现有仓库路径下正常构建，无需搬家或目录联接。

### 1.3 构建环境约定

首次下载依赖可能需要代理（本机 `127.0.0.1:7890`）：

```powershell
$env:GRADLE_OPTS="-Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=7890 -Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=7890"
```

缓存后无需代理。`flutter.bat` 在本机会挂起，统一改用：

```powershell
$env:FLUTTER_ROOT="D:\flutter"
$env:ANDROID_HOME="E:\AutoPunch\.android-sdk"
$env:ANDROID_SDK_ROOT="E:\AutoPunch\.android-sdk"
& "D:\flutter\bin\cache\dart-sdk\bin\dart.exe" "D:\flutter\packages\flutter_tools\bin\flutter_tools.dart" --no-version-check <command>
```

---

## 2. 仓库准备（批次 1，待审核后执行）

### 2.1 创建 Flutter 项目

拟执行（在仓库根，使用 Dart 直接调用 `flutter_tools`，避免 `flutter.bat` 挂起）：

```powershell
Set-Location "E:\F&J\FJ v1"

$env:FLUTTER_ROOT="D:\flutter"
$DART="D:\flutter\bin\cache\dart-sdk\bin\dart.exe"
$FLUTTER="D:\flutter\packages\flutter_tools\bin\flutter_tools.dart"

& $DART $FLUTTER --no-version-check create `
  --template=app `
  --project-name mobile `
  --org com.butler `
  --platforms=android `
  --empty `
  mobile
```

- `--platforms=android`：只生成 `android/`，不生成 ios/web/windows/linux/macos
- `--empty`：不生成计数器示例
- 必须在仓库根执行，最后参数 `mobile` 是目标目录；执行前确认 `mobile/` 不存在
- 执行后检查 `mobile/pubspec.yaml` 与 `mobile/android/app/build.gradle.kts` 存在
- **包名结果**：`applicationId = com.butler.mobile`、`namespace = com.butler.mobile`、Dart 包名 `mobile`（import 形如 `package:mobile/...`）

**命名结论**：U1 保持 Dart 包名 `mobile` 与 `applicationId = com.butler.mobile`；后续若拆仓库或引入多端，再单独评估 `butler_mobile` 迁移，不在本阶段改动。

### 2.2 生成后立即打的补丁

| 文件 | 改动 |
|---|---|
| `mobile/android/gradlew.bat` | 上述 3 行加引号 |
| `mobile/android/app/build.gradle.kts` | `compileSdk = 36`、`targetSdk = 36`、`minSdk = 26`；不使用 `flutter.minSdkVersion` 默认值 |
| `mobile/.gitignore` | 保留 Flutter 默认；不追加 `screenshots/`（截图按 15.3 定案提交） |
| `mobile/README.md` | 运行方式、环境变量、gradlew 补丁原因、契约对应表、调试面板说明、截图位置 |
| `mobile/analysis_options.yaml` | 使用 `flutter_lints`，追加少量规则 |

`android/app/build.gradle.kts` 关键片段：

```kotlin
android {
    namespace = "com.butler.mobile"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.butler.mobile"
        minSdk = 26
        targetSdk = 36
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }
}
```

生成后检查：

```powershell
Select-String -Path "mobile\android\app\build.gradle.kts" -Pattern "minSdk\s*=\s*26"
```

若该版本生成的是 Groovy `build.gradle`，使用 `minSdk 26` / `targetSdk 36` 的对应写法；文件路径以实际生成结果为准，但数值要求不变。

### 2.3 根目录文件

| 文件 | 动作 | 说明 |
|---|---|---|
| `.trae/rules/monorepo.md` | 新建 | 按你提供的原文 |
| `.trae/rules/mobile.md` | 新建 | 按你提供的原文 |
| `.dockerignore` | 新建 | 内容仅 `mobile/`；当前文件不存在 |
| `.gitattributes` | 追加 | `*.bat text eol=crlf`；现有内容为 `* text=auto eol=lf` |

后端目录（`app/`、`tests/`、`scripts/`）不做任何修改。报告位置已定案：保留 `docs/mobile-u1-technical-plan.md`。

### 2.4 回归验证

```powershell
docker compose build api

wsl -d Ubuntu --cd "/mnt/e/F&J/FJ v1" -- bash -lc "uv run ruff check app tests scripts && uv run pytest -q"
```

`--cd` 的兼容检查与 fallback 见 13.2；若本机 WSL 不支持，直接使用 fallback 命令。

---

## 3. 架构、分层与依赖锁定

```
mobile/lib/
  core/      主题、令牌、文案、Clock、格式化
  domain/    实体、仓库抽象接口（不含 Flutter 依赖）
  data/mock/ 假数据实现，仅被 provider 装配层引用
  features/  today、chat、tasks、profile、debug
  shell/     路由、4 Tab 外壳、全局提醒宿主
```

依赖方向：`features → domain ← data/mock`，`features` 不直接 import `data/mock`。

### 3.1 Provider 清单

| Provider | 类型 | 作用 |
|---|---|---|
| `clockProvider` | `Provider<Clock>` | 唯一时间来源 |
| `chatRepositoryProvider` | `Provider<ChatRepository>` | 默认指向 Mock |
| `todayRepositoryProvider` | `Provider<TodayRepository>` | 默认指向 Mock |
| `alertRepositoryProvider` | `Provider<AlertRepository>` | 紧急提醒来源（Mock） |
| `networkStatusProvider` | `StreamProvider<NetworkStatus>` | 网络/同步状态 |
| `scenarioProvider` | `NotifierProvider<ScenarioController, Scenario>` | 调试面板场景 |
| `mainConversationProvider` | `FutureProvider<Conversation>` | Friday 主对话 |
| `topicConversationsProvider` | `FutureProvider<List<Conversation>>` | 全部专题对话 |
| `conversationProvider` | `FutureProvider.family<Conversation, String>` | 单次查询对话基础信息（深链解析、列表展示、路由预取） |
| `conversationChannelProvider` | `StreamProvider.family<ConversationView, String>` | 该对话的持续实时状态：最新 `Conversation` + 正式 `messages` + 同步状态/重试次数/错误 |
| `chatControllerProvider` | `NotifierProvider.family<ChatController, ChatState, String>` | 每个对话本地 pending / queued / failed 消息与发送错误的唯一持有者；发送、离线排队、失败、重试与确认清理都在这里 |
| `chatViewProvider` | `Provider.family<AsyncValue<ChatView>, String>` | 展示层唯一来源：合并 `conversationChannelProvider` 的正式状态与 `chatControllerProvider` 的 pending / sendErrors |
| `chatSessionProvider` | `NotifierProvider<ChatSessionStore, Map<String, ChatSessionState>>` | 每个对话的草稿与滚动位置 |
| `urgentAlertProvider` | `NotifierProvider<UrgentAlertController, PriorityAlert?>` | Shell 级紧急提醒状态 |
| `alertResumeProvider` | `NotifierProvider<AlertResumeController, AlertResumeContext?>` | 弹窗前的页面恢复信息 |
| `todayControllerProvider` | `AsyncNotifierProvider<TodayController, TodayState>` | 今日页状态与动作 |
| `debugPanelProvider` | `NotifierProvider<DebugController, DebugState>` | 调试面板 |

**明确删除**：全局 `activeAgentProvider`、`currentAgent` 等单值状态。Agent 归属只来自当前路由解析出的 `Conversation.agent`。

**Chat 页面数据来源分层**：

- `conversationChannelProvider` 是正式状态（Conversation + 正式消息）的**唯一实时来源**
- `chatControllerProvider` 是本地 pending / queued / failed 与发送错误的**唯一持有者**，不向 Repository 渗透
- `chatViewProvider` 是页面的**唯一展示来源**：它在 channel 之上合并 Controller 的 pending 与 sendErrors，UI 只监听这一个 Provider
- `conversationProvider` 只用于首次解析/单次查询，不参与页面实时渲染
- 页面不得同时监听多个 Provider 后自行拼接 Conversation、正式消息与 pending
- `mainConversationProvider` / `topicConversationsProvider` 只用于入口解析与列表展示，进入具体对话后以 channel + chatView 为准
- 同步规则（事件队列、快照合并、缺口重同步、摘要与 generation）全部由 `ConversationSyncEngine`（`core/sync/conversation_sync_engine.dart`）实现；Repository 委托它，Provider / Controller / UI 不得复制这些规则

### 3.2 依赖与版本锁定

| 组件 | 版本 | 说明 |
|---|---|---|
| Flutter | 3.47.2（stable） | 已验证可用，不主动升级 |
| Dart | 3.13.2 | 随 Flutter 固定 |
| JDK | 21 | Gradle 使用 |
| Android compileSdk / targetSdk | 36 | 已安装 platform 36 |
| Android minSdk | 26 | 在 `mobile/android/app/build.gradle.kts` 显式设置，不使用 Flutter 默认值 |
| Gradle | 9.3.1 | Wrapper 固定，已缓存 |
| `flutter_riverpod` | 3.5.0 | 状态管理与依赖注入 |
| `go_router` | 18.1.4 | 路由与 shell |
| `intl` | 0.20.3 | zh_CN 日期格式 |
| `flutter_lints`（dev） | 6.0.0 | 静态检查基线 |

版本性质说明：

- 上表的 Flutter 3.47.2、Dart 3.13.2、JDK 21、Android SDK 36、Gradle 9.3.1 是**本机已经实际验证过的开发基线**，不是「修订日最新稳定版」
- `flutter_riverpod` 3.5.0、`go_router` 18.1.4、`intl` 0.20.3、`flutter_lints` 6.0.0 是报告修订时查询 pub.dev 得到的稳定版本，作为**待安装验证的目标版本**；若与本机环境不兼容，先记录问题再提调整建议，不擅自替换
- 是否存在更新版本只作为后续评估信息，不构成本次升级理由

Riverpod 3.5.0 写法约束：

- family Notifier 不再有 `FamilyNotifier` 等变体；统一使用 `Notifier`，family 参数通过**构造函数**传入，`build()` 不带参数
- 例：`NotifierProvider.family<ChatController, ChatState, String>(ChatController.new)`，`ChatController(this.conversationId)` + `ChatState build()`
- 不使用 `Notifier.build(String arg)` 的 Riverpod 2 迁移前写法
- Riverpod 3 默认会对失败的 provider 自动重试；`conversationChannelProvider` 必须显式关闭该行为，重试只由 Repository 的退避策略负责

**Riverpod 3 API 对照表（本报告示例必须全部符合）**：

| 场景 | 正确写法（3.5.0） | 禁止/已移除 |
|---|---|---|
| family Notifier | `class ChatController extends Notifier<ChatState>` + 构造函数参数 + `build()` | `FamilyNotifier`、`build(String arg)` |
| 读取异步数据 | `AsyncValue.value`（loading/error 时为 null） | `valueOrNull`；依赖旧版 `value` 抛异常的行为 |
| 仅处理 data | `whenData(...)` 或 `switch (value) { case AsyncData(...) }` | 依赖旧 `value` 抛异常行为 |
| 关闭自动重试 | provider 的 `retry: (_, __) => null` | 依赖默认 10 次自动重试 |
| 保持状态 | `ref.keepAlive()` 或非自动释放配置 | 依赖页面 Widget 持有状态 |
| 订阅 | `ref.listen(provider, (prev, next) {...})` | Widget 内 `StreamBuilder` / 手动 `StreamSubscription` |
| 失效重建 | `ref.invalidate(provider)` | 手动清空内部字段伪装释放 |
| 暂停恢复 | 接受 Riverpod 3 对不可见 listener 的暂停；返回页面调用 `reconcile()` | 用 `TickerMode(enabled: true)` 强制后台运行 |

锁定策略：

- `pubspec.yaml` 使用**精确版本**（如 `flutter_riverpod: 3.5.0`），不使用 `^`
- 提交 `pubspec.lock`，本地与未来 CI 均以 lock 为准
- 当前已验证环境为默认开发基线，不得仅因存在新版本就自行升级
- 任何 Flutter / Dart / 依赖升级都必须先经项目负责人批准，说明原因、兼容性与影响范围
- 获批升级后必须重新执行 `analyze`、`format`、`test`、`build apk --debug`，全部通过才允许提交

### 3.3 状态与副作用约定

- 读：页面 `watch` 当前 conversation 的合并消息流与对话信息
- 写：控制器先乐观更新；Today 条目失败回滚并提示；Chat 消息置 `pending`，离线置 `queued`，失败转 `failed` 并保留原 id/seq 等待重试（见 4.19 / 4.21），不回滚删除
- 离线恢复后按创建顺序补发 queued；异步返回后必须检查 Controller 是否已释放，禁止在销毁后写状态
- 所有时间读取走 `clockProvider`；`DateTime.now()` 只允许出现在 `SystemClock`
- 文案集中在 `core/strings.dart`
- 发送消息时 Controller 生成 `clientMessageId`，与 pending 消息、`sendText`、确认事件全程一致；接受/拒绝邀请携带 `inviteId`；前端不构造 Prompt、不选模型

---

## 4. 领域模型（完整定义）

### 4.1 枚举

```dart
enum ConversationType { main, topic }

enum ConversationAgent { friday, jarvis }

enum ConversationStatus { active, archived }

enum ChatSender { user, friday, jarvis }

enum SyncState { synced, pending, queued, failed }

enum NetworkStatus { online, offline, syncing, error }

enum TodayItemKind { block, reminder, task }

// overdue 不进入持久状态；由 TodayItem.isOverdueAt(now) 派生
enum TodayItemStatus { planned, inProgress, done, skipped }

enum BriefKind { morning, evening }

enum ConversationSyncState { syncing, synced, retrying, failed }

enum ConfirmCardState { pending, confirmed, revoked }

enum PlanDecision { accept, adjust, veto }

enum PlanProposalState { pending, accepted, adjusted, vetoed }

enum PlanChangeType { add, remove, move }

enum MemoryCandidateState { pending, confirmed, rejected }

enum AgentInviteStatus { pending, accepted, declined, expired }

enum ThinkingPhase { thinking, organizing, drafting, executing }

enum AlertPriority { urgent }

enum AlertStatus { pending, handled, dismissed }

enum InviteRejectReason { declined, expired, notFound, notOwner, alreadyAccepted }

/// 业务状态转换失败；debug/release 都必须抛出。
class StateTransitionException implements Exception {
  const StateTransitionException({
    required this.model,
    required this.from,
    required this.to,
    required this.reason,
  });

  final String model;
  final String from;
  final String to;
  final String reason;

  @override
  String toString() =>
      'StateTransitionException($model: $from -> $to, $reason)';
}
```

命名说明：

- `ChatSender` 只表示**消息发送者**，包含 `user`
- `ConversationAgent` 只表示**对话负责方**，不含 `user`
- `SyncState` 表示条目/消息的同步状态：`synced` 已确认、`pending` 发送中、`queued` 离线等待、`failed` 失败待重试；`NetworkStatus` 表示整体网络状态，二者不可混用

### 4.2 Conversation

```dart
class Conversation {
  // 含 DateTime 比较的 assert 不能用于 const 构造，故本类为非 const
  Conversation({
    required this.conversationId,
    required this.type,
    required this.agent,
    required this.status,
    required this.createdAt,
    required this.lastActivityAt,
    this.projectId,
    this.projectTitle,
    this.topic,
    this.goal,
    this.scopeSummary,
    this.parentConversationId,
    this.originInviteId,
  })  : assert(conversationId != '', 'conversationId must not be empty'),
        assert(
          !lastActivityAt.isBefore(createdAt),
          'lastActivityAt must not be earlier than createdAt',
        ),
        assert(
          type != ConversationType.main || projectId == null,
          'main conversation must not have projectId',
        ),
        assert(
          type != ConversationType.main ||
              (parentConversationId == null && originInviteId == null),
          'main conversation must not have parent or origin invite',
        ),
        assert(
          type != ConversationType.main ||
              (topic == null && goal == null && scopeSummary == null),
          'main conversation must not have topic/goal/scopeSummary',
        ),
        assert(
          type != ConversationType.topic || projectId != null,
          'topic conversation requires projectId',
        ),
        assert(
          projectId != null || projectTitle == null,
          'projectTitle requires projectId',
        ),
        assert(
          type != ConversationType.main || agent == ConversationAgent.friday,
          'main conversation must belong to friday',
        ),
        assert(
          type != ConversationType.topic || agent == ConversationAgent.jarvis,
          'topic conversation must belong to jarvis',
        ),
        assert(
          type != ConversationType.topic ||
              (topic != null && goal != null && scopeSummary != null),
          'topic conversation requires topic/goal/scopeSummary',
        );

  final String conversationId;
  final ConversationType type;
  final ConversationAgent agent;
  final ConversationStatus status;
  final DateTime createdAt;
  final DateTime lastActivityAt;

  final String? projectId;        // 专题必填；主对话为空
  final String? projectTitle;
  final String? topic;            // 专题名称
  final String? goal;             // 专题目标
  final String? scopeSummary;     // 讨论范围
  final String? parentConversationId;
  final String? originInviteId;

  bool get isMain => type == ConversationType.main;

  Conversation copyWith({
    ConversationStatus? status,
    DateTime? lastActivityAt,
    Object? projectId = unset,
    Object? projectTitle = unset,
  }) {
    final nextProjectId =
        identical(projectId, unset) ? this.projectId : projectId as String?;
    final nextProjectTitle = identical(projectTitle, unset)
        ? this.projectTitle
        : projectTitle as String?;
    final nextLastActivityAt = lastActivityAt ?? this.lastActivityAt;
    assert(
      type != ConversationType.topic || nextProjectId != null,
      'cannot clear projectId of a topic conversation',
    );
    assert(
      type != ConversationType.main || nextProjectId == null,
      'main conversation projectId must stay null',
    );
    assert(
      nextProjectId != null || nextProjectTitle == null,
      'projectTitle requires projectId',
    );
    assert(
      !nextLastActivityAt.isBefore(createdAt),
      'lastActivityAt must not be earlier than createdAt',
    );
    return Conversation(
      conversationId: conversationId,
      type: type,
      agent: agent,
      status: status ?? this.status,
      createdAt: createdAt,
      lastActivityAt: nextLastActivityAt,
      projectId: nextProjectId,
      projectTitle: nextProjectTitle,
      topic: topic,
      goal: goal,
      scopeSummary: scopeSummary,
      parentConversationId: parentConversationId,
      originInviteId: originInviteId,
    );
  }
}
```

#### 4.2.1 copyWith 约定（可空字段的显式清空）

文件级定义一次哨兵值，所有模型共用：

```dart
const Object unset = Object();
```

通用规则：

- **不传参数** → 保持原值
- **显式传 `null`** → 清空该字段（仅限允许清空的字段）
- **显式传非空值** → 更新为新值
- **非空字段**不提供 `null` 入口，无法被清空
- 参数类型写成 `Object?`，实现内用 `identical(value, unset)` 判断，再 `as T?` 转型
- 所有允许清空的可空字段统一使用该约定；不允许出现「一部分用 sentinel、一部分用 `?? this.field`」的混用
- 不接受「传 null 等于不传」的旧写法

**可空字段清单与修改权限**（逐一核对，避免开发人员自行猜测）：

| 模型 | 可空字段 | copyWith 是否可改 | 是否可显式清空 | 约束 |
|---|---|---|---|---|
| Conversation | projectId | 仅 `topic` 可改 | 否 | `main` 恒为 null，不可设置；`topic` 必须有且不可清空 |
| Conversation | projectTitle | 是 | 是 | 与 projectId 同步；无 projectId 时应为空 |
| Conversation | topic / goal / scopeSummary | 否（构造时设置） | — | 主对话为 null；专题构造时必填 |
| Conversation | parentConversationId / originInviteId | 否（构造时设置） | — | 创建后不可变；主对话必须为 null |
| ChatMessage 基类 | reason | 否（构造时设置） | — | 主动消息创建后不可变 |
| ConfirmCard | actedAt | 是 | 是（回到未处理时） | 状态为 pending 时应为 null |
| ChoiceCard | answer | 是 | 是（撤销选择） | 清空后恢复为未回答 |
| MemoryCandidateItem | 无可空字段 | — | — | state 非空 |
| PlanChange | detail | 否（构造时设置） | — | 不可变 |
| PlanProposalCard | 无可空字段 | — | — | state 非空 |
| ThinkingCard | 无可空字段 | — | — | phase 非空 |
| AgentInviteCard | projectId | 否（构造时设置） | — | 接受后可回填，但不由 UI 随意清空 |
| AgentInviteCard | createdConversationId | 是（仅仓库回填） | 否 | accepted 时必须非空；pending/declined/expired 时必须为空 |
| TodayItem | start / end | start 可改 | 仅 `kind = task` 可清空 | block/reminder 的 start 不可清空；end 构造时设置 |
| TodayItem | durationMin / sourceTag / reason / projectId / projectTitle | 否（构造时设置） | — | 不可变 |
| Brief | 无可空字段 | — | — | — |
| DayView | morningBrief / eveningBrief | 否（构造时设置） | — | 缺失即表示当天没有该简报 |
| AlertAction | 无可空字段 | — | — | — |
| PriorityAlert | deadline | 否（构造时设置） | — | 不可变 |
| AlertResumeContext | conversationId / messageId / scrollOffset / draftText | 否（构造时设置） | — | 由 Shell 采集后不可变 |

**业务不变量总表（构造与 copyWith 均不得破坏）**：

| 模型 | 不变量 |
|---|---|
| Conversation | `main` → `agent = friday`、`projectId = null`、`topic/goal/scopeSummary/parentConversationId/originInviteId = null` |
| Conversation | `topic` → `agent = jarvis`、`projectId != null`、`topic/goal/scopeSummary` 非空；`projectTitle` 非空时必须有 `projectId` |
| Conversation | `lastActivityAt >= createdAt`；`status = archived` 后仍允许读取，不再产生新事件 |
| ChatMessage | `id`、`conversationId` 非空；`seq != 0` |
| ChatMessage | `synced` → `seq > 0`（正式消息）；`pending/queued/failed` → `seq < 0` |
| ChatMessage | 正式消息的 `seq` 必须等于其 `MessageUpsert.seq`；pending/queued/failed 不参与事件序列、不写入 `lastSeq` |
| ChatMessage | pending/queued/failed 使用同一负数临时 seq 与同一 `clientMessageId`；重试只改 `syncState`，不新建消息 |
| ConfirmCard | `pending` → `actedAt = null`；`confirmed / revoked` → `actedAt != null` |
| ConfirmCard | `title/body/primaryLabel/secondaryLabel` 非空；主次按钮文案不得相同 |
| ChoiceCard | `options.length` 在 2–4；选项非空且不重复；`answer` 为 null 或必须属于 `options` |
| ChoiceCard | 同一卡片只有一个 `answer`；清空表示撤销并回到未回答，不允许同时保留多个答案 |
| ChoiceAction | `skipped = true` → `option = null`；`skipped = false` → `option != null` 且非空；option 必须属于目标 ChoiceCard（运行时校验） |
| MemoryConfirmCard | `items` 非空；`itemId` 在卡片内唯一；`allConfirmed` 仅当全部 confirmed |
| PlanProposalCard | `changes` 非空；`summary/rationale` 非空；终态不可回退到 pending |
| AgentInviteCard | `targetAgent = jarvis`；`initiatorAgent` 为 friday 或 jarvis（不含 user） |
| AgentInviteCard | `accepted` → `createdConversationId != null`；`pending/declined/expired` → 必须为 null |
| AgentInviteCard | `topic/goal/scopeSummary/expectedOutcome` 非空；`accepting` 仅在 pending 时可为 true |
| TodayItem | `kind = block` → `start/end != null` 且 `end > start`、`durationMin > 0`；block 的 `start` 不可清空 |
| TodayItem | `kind = reminder` → `start != null`，`end/durationMin` 必须为空；reminder 的 `start` 不可清空 |
| TodayItem | `kind = task` → `start` 可为空；只有 task 允许通过 `copyWith(start: null)` 移出时间线 |
| TodayItem | `overdue` 不是状态值，按类型派生：block 在 `now > end` 时逾期；reminder 在 `now > start + 10min` 时逾期；task 在 `now > start` 时逾期；无 start 的 task 与 done/skipped 永不逾期 |
| TodayItem | `done/skipped` 与完成按钮状态一致；状态字段不得写入 overdue |
| PriorityAlert | `actions` 非空；`actionId` 非空且唯一；`label` 非空；`status = handled` 时 `handledActionId` 非空且必须属于 `actions` |
| PriorityAlert | `handledActionId` 仅在 `status = handled` 时非空；`deadline` 可空 |
| AlertResumeContext | `previousRoute` 非空；`capturedAt` 为采集时刻；字段创建后不可变 |
| AlertResumeContext | `conversationId` 为空时，`messageId/scrollOffset/draftText` 必须为空；`scrollOffset` 为空或非负 |
| ChatEvent | `conversationId` 非空、`seq > 0`；`MessageUpsert` 的消息归属/seq/syncState 与事件一致；`ConversationUpdated` 的对话 id 与事件一致 |
| ConversationSnapshot | `lastSeq >= 0`；仅正式消息、同一 conversation、`seq <= lastSeq`、id 唯一、按 seq 升序 |
| ConversationView | 消息约束同快照；`retryCount` 在 0–2；`syncError` 非空字符串；`failed` 必须有 `syncError`，非 failed 不得有；`syncing/synced` 时 retryCount = 0，`retrying/failed` 时 retryCount > 0 |
| ChatState | pending 仅 pending/queued/failed 且负数 seq、id 唯一、按负数 seq 降序；sendErrors 只指向 failed 且文案非空 |
| ChatView | 正式消息与 pending 的约束同源；两组 id 不重复；sendErrors 只指向 pending 中的 failed 且文案非空；同步状态/retryCount/syncError 关系同 ConversationView |
| Brief | `text/reasonLine` 非空；`mergedSuggestions` 不含空字符串 |
| DayView | `date` 为本地零点；`items` 均有 start 且按 start 升序；`unscheduled` 均为无 start 的 planned task；两组 id 合并不重复；brief 类型与字段匹配 |

说明：`Conversation.archived 后不再产生事件`、`done/skipped 与按钮一致` 属于 Repository / UI 行为约束，无法在单条模型构造时判定，由对应测试覆盖，不写成虚假 assert。`TodayItem.overdue` 已改为模型内派生方法，不再依赖 UI 约定。

**集合不可变约定**：

- 所有对外暴露的 `List` / `Map` 字段都必须在构造时复制为不可变视图：`List.unmodifiable(...)`、`Map.unmodifiable(...)`
- 不接受调用方传入的可变集合直接赋给字段；`copyWith` 传入的集合同样先复制再构造
- 涉及集合的构造函数不使用 `const`；默认值可写 `const []` / `const {}`，构造后仍复制
- 集合不可变不等于元素不可变：元素仍须满足自身不变量；`ChatState` / `ChatView` 的集合由 Controller 与 Provider 构造，不允许 UI 修改
- 单元测试对每个集合字段断言「写入抛 `UnsupportedError`」，并断言外部修改原集合不会影响模型

**执行方式**：

- 上述规则必须在**每个模型的构造函数**内用 `assert` 落地；提供 `copyWith` 的模型还必须在每个 `copyWith` 分支断言新值，不允许只在文档或测试里写规则
- `copyWith` 先算出新值再断言，不得先构造再依赖构造函数断言来「顺带」校验（构造函数断言仍必须保留）
- `const` 取舍：涉及集合长度/元素判断、`DateTime` 比较的构造函数不使用 `const`；字符串非空统一写 `!= ''`，使仅含字段关系断言的模型仍可 `const`。不得为了 `const` 删除断言
- 一个模型有多个 `copyWith` 分支时，每个分支都要断言；不允许只在 UI 层兜底
- 违反不变量的状态不得进入 UI；单元测试逐条覆盖，映射到 `copy_with_test` 与各模型测试
- Domain 层不引入额外校验框架；release 下 assert 被移除，外部数据必须先按 4.20 做运行时校验，业务代码不得构造非法状态

**逐模型落地位置**（与测试映射）：

| 模型 | assert 位置 | 覆盖测试 |
|---|---|---|
| Conversation | 构造函数 + `copyWith`（类型/Agent/projectId/时间） | `copy_with_test`、`conversation_test` |
| ChatMessage 基类 | 构造函数（id、conversationId、seq 与 syncState 关系） | `local_message_test`、`copy_with_test` |
| ConfirmCard | 构造函数 + `copyWith`（状态与 actedAt、按钮文案） | `copy_with_test`、`chat_controller_test` |
| ChoiceCard | 构造函数 + `copyWith`（2–4 项、选项非空且唯一、答案属于选项） | `copy_with_test` |
| ChoiceAction | 构造函数（skipped 与 option 关系） | `copy_with_test`、`validation_test` |
| MemoryConfirmCard | 构造函数 + `copyWith`（items 非空、itemId 唯一） | `copy_with_test` |
| PlanProposalCard | 构造函数（changes/summary/rationale 非空）+ `copyWith`（终态不回退） | `copy_with_test` |
| AgentInviteCard | 构造函数 + `copyWith`（targetAgent、非空文本、accepted 与 createdConversationId、accepting） | `copy_with_test`、`invite_test` |
| TodayItem | 构造函数 + `copyWith`（block/reminder 时间关系、only task 可清空 start） | `copy_with_test`、`today_controller_test` |
| PriorityAlert | 构造函数（actions 非空、actionId 唯一、handledActionId） | `copy_with_test`、`urgent_alert_test` |
| AlertResumeContext | 构造函数（字段联动） | `copy_with_test` |
| ChatEvent / MessageUpsert / ConversationUpdated | 构造函数（conversationId、seq、消息与对话归属一致性） | `conversation_event_test`、`validation_test` |
| ConversationSnapshot / ConversationView | 构造函数（lastSeq、正式消息、id 唯一、seq 升序、同步状态与 error 联动） | `message_merge_test`、`conversation_event_test` |
| Brief / DayView | 构造函数（文本非空、date 零点、items 排序、unscheduled 归类、brief 类型、id 唯一） | `copy_with_test`、`today_controller_test` |
| ChatState | 构造函数 + `copyWith`（pending 负数/唯一/降序、sendErrors 只指向 failed） | `local_message_test`、`chat_controller_test` |
| ChatView | 构造函数（正式/pending 各自约束、两组 id 不重复、sendErrors 匹配） | `local_message_test`、`chat_page_test` |

**copyWith 状态转换的 release 保障**：

- `assert` 在 release 被移除，**不能**作为业务状态转换的唯一保障；终态转换必须使用运行时 `if` 检查并抛出 `StateTransitionException`
- `copyWith` 只负责字段复制；业务转换统一走显式方法（如 `ConfirmCard.act()`、`PlanProposalCard.decide()`、`AgentInviteCard.markAccepted()`），方法内部先做运行时校验，再调用 `copyWith`
- 为保证 release 安全，终态转换相关的 `copyWith` 也必须内置运行时检查，不能只依赖调用方；禁止出现「debug 下 assert、release 下静默接受」的分支
- `StateTransitionException` 携带 `model`、`from`、`to`、`reason`；由 Presenter 转为用户提示，不崩溃
- 转换规则表：

| 模型 | 运行时禁止的转换 | release 行为 |
|---|---|---|
| ConfirmCard | `confirmed/revoked → pending`；状态变化但 `actedAt` 不匹配 | 抛 `StateTransitionException` |
| ChoiceCard | `answer` 不属于 `options`；已回答后改成另一个答案（只允许清空撤销） | 抛 `StateTransitionException` |
| PlanProposalCard | 终态 → `pending`；终态之间互相回退 | 抛 `StateTransitionException` |
| AgentInviteCard | `accepted → pending/declined/expired`；`accepted` 缺少 `createdConversationId`；非 accepted 携带 `createdConversationId` | 抛 `StateTransitionException` |
| TodayItem | block/reminder 清空 `start`；block 的 `start >= end` | 抛 `StateTransitionException` |
| ChatMessage | 负数 seq 的 pending/queued/failed 改为 `synced` | 抛 `StateTransitionException` |

- `copy_with_test` 除 assert 外，必须用「运行时异常」断言覆盖上表；这些测试不依赖 `--enable-asserts`，release 同样有效
- UI / Controller 不得直接改 `ConfirmCard/PlanProposalCard/AgentInviteCard` 的终态字段；只调用模型方法或 Controller 的卡片动作方法

对话规则：

- 每个用户有且只有一个 `type = main`、`agent = friday` 的主对话
- 用户可以拥有多个 `type = topic`、`agent = jarvis` 的专题对话
- 专题必须绑定 `projectId`；接受邀请时若邀请无项目，由后端（U1 为 Mock）创建或关联项目
- 同一项目可有多个专题；不同项目的数据与消息必须隔离
- 归属由仓库数据决定，前端不得用「最近发言者」推断

### 4.3 ChatMessage（sealed）

```dart
sealed class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.conversationId,
    required this.sender,
    required this.createdAt,
    required this.seq,
    this.reason,
    this.syncState = SyncState.synced,
  })  : assert(id != '', 'message id must not be empty'),
        assert(conversationId != '', 'conversationId must not be empty'),
        assert(seq != 0, 'seq must be positive (formal) or negative (local)'),
        assert(
          syncState != SyncState.synced || seq > 0,
          'synced message requires a positive seq',
        ),
        assert(
          syncState == SyncState.synced || seq < 0,
          'pending/queued/failed message requires a negative seq',
        );

  final String id;               // 全局唯一
  final String conversationId;   // 必填
  final ChatSender sender;
  final DateTime createdAt;
  // 正式事件序号：与产生该消息的 MessageUpsert.seq 相等，用于排序/去重/缺口检测，必须 > 0。
  // 本地 pending / queued / failed 使用负数临时值（-1、-2、…），仅用于本地排序，
  // 不是正式事件序号，不参与连续性检查，也不写入 lastSeq。
  final int seq;
  final String? reason;          // 主动消息的理由
  final SyncState syncState;
}
```

`seq` 由仓库分配，正式消息不得由前端生成；同一 conversation 内严格递增。排序规则见 4.17。

### 4.4 TextMessage

```dart
final class TextMessage extends ChatMessage {
  const TextMessage({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    this.text = '',
    this.streaming = false,
  });

  final String text;
  final bool streaming;

  TextMessage copyWith({
    String? text,
    bool? streaming,
    SyncState? syncState,
  }) {
    final nextSyncState = syncState ?? this.syncState;
    if (nextSyncState == SyncState.synced && seq <= 0) {
      throw StateTransitionException(
        model: 'TextMessage',
        from: this.syncState.name,
        to: nextSyncState.name,
        reason: 'local message cannot become synced without a formal seq',
      );
    }
    assert(
      nextSyncState != SyncState.synced || seq > 0,
      'cannot mark a local message as synced without a formal seq',
    );
    return TextMessage(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: nextSyncState,
      text: text ?? this.text,
      streaming: streaming ?? this.streaming,
    );
  }
}
```

### 4.5 ConfirmCard

```dart
final class ConfirmCard extends ChatMessage {
  const ConfirmCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.title,
    required this.body,
    required this.primaryLabel,
    required this.secondaryLabel,
    this.state = ConfirmCardState.pending,
    this.actedAt,
  })  : assert(title != '', 'title must not be empty'),
        assert(body != '', 'body must not be empty'),
        assert(primaryLabel != '', 'primaryLabel must not be empty'),
        assert(secondaryLabel != '', 'secondaryLabel must not be empty'),
        assert(
          primaryLabel != secondaryLabel,
          'primary and secondary labels must differ',
        ),
        assert(
          (state == ConfirmCardState.pending) == (actedAt == null),
          'pending requires actedAt == null; confirmed/revoked require actedAt != null',
        );

  final String title;
  final String body;
  final String primaryLabel;
  final String secondaryLabel;
  final ConfirmCardState state;
  final DateTime? actedAt;

  ConfirmCard copyWith({ConfirmCardState? state, Object? actedAt = unset}) {
    final nextState = state ?? this.state;
    final nextActedAt =
        identical(actedAt, unset) ? this.actedAt : actedAt as DateTime?;
    if ((nextState == ConfirmCardState.pending) != (nextActedAt == null)) {
      throw StateTransitionException(
        model: 'ConfirmCard',
        from: this.state.name,
        to: nextState.name,
        reason: 'pending requires actedAt == null; terminal requires actedAt != null',
      );
    }
    if (this.state != ConfirmCardState.pending && nextState != this.state) {
      throw StateTransitionException(
        model: 'ConfirmCard',
        from: this.state.name,
        to: nextState.name,
        reason: 'terminal confirm card cannot change state',
      );
    }
    assert(
      (nextState == ConfirmCardState.pending) == (nextActedAt == null),
      'pending requires actedAt == null; confirmed/revoked require actedAt != null',
    );
    return ConfirmCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      title: title,
      body: body,
      primaryLabel: primaryLabel,
      secondaryLabel: secondaryLabel,
      state: nextState,
      actedAt: nextActedAt,
    );
  }
}
```

### 4.6 ChoiceCard

```dart
final class ChoiceCard extends ChatMessage {
  // 含集合元素判断与不可变复制，构造函数不能是 const
  ChoiceCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.question,
    required List<String> options,
    this.answer,
  })  : options = List<String>.unmodifiable(options),
        assert(question != '', 'question must not be empty'),
        assert(
          options.length >= 2 && options.length <= 4,
          'choice card requires 2-4 options',
        ),
        assert(
          options.every((o) => o != ''),
          'choice options must not be empty',
        ),
        assert(
          options.toSet().length == options.length,
          'choice options must be unique',
        ),
        assert(
          answer == null || options.contains(answer),
          'answer must be one of options',
        );

  final String question;
  final List<String> options;   // 2–4 项
  final String? answer;         // 已选项；null = 未回答

  ChoiceCard copyWith({Object? answer = unset}) {
    final nextAnswer =
        identical(answer, unset) ? this.answer : answer as String?;
    if (nextAnswer != null && !options.contains(nextAnswer)) {
      throw StateTransitionException(
        model: 'ChoiceCard',
        from: this.answer ?? 'unanswered',
        to: nextAnswer,
        reason: 'answer must be one of options',
      );
    }
    if (this.answer != null &&
        nextAnswer != null &&
        nextAnswer != this.answer) {
      throw StateTransitionException(
        model: 'ChoiceCard',
        from: this.answer!,
        to: nextAnswer,
        reason: 'answered choice can only be cleared, not replaced',
      );
    }
    assert(
      nextAnswer == null || options.contains(nextAnswer),
      'answer must be one of options',
    );
    return ChoiceCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      question: question,
      options: options,
      answer: nextAnswer,
    );
  }
}
```

### 4.7 MemoryConfirmCard

```dart
class MemoryCandidateItem {
  const MemoryCandidateItem({
    required this.itemId,
    required this.label,
    this.state = MemoryCandidateState.pending,
  })  : assert(itemId != '', 'itemId must not be empty'),
        assert(label != '', 'label must not be empty');

  final String itemId;
  final String label;
  final MemoryCandidateState state;

  MemoryCandidateItem copyWith({MemoryCandidateState? state}) {
    return MemoryCandidateItem(
      itemId: itemId,
      label: label,
      state: state ?? this.state,
    );
  }
}

final class MemoryConfirmCard extends ChatMessage {
  // 含集合非空、唯一性与不可变复制，构造函数不能是 const
  MemoryConfirmCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required List<MemoryCandidateItem> items,
  })  : items = List<MemoryCandidateItem>.unmodifiable(items),
        assert(items.length > 0, 'memory card requires at least one item'),
        assert(
          items.map((e) => e.itemId).toSet().length == items.length,
          'itemId must be unique within a memory card',
        );

  final List<MemoryCandidateItem> items;

  bool get allConfirmed =>
      items.isNotEmpty && items.every((e) => e.state == MemoryCandidateState.confirmed);
  bool get allHandled =>
      items.isNotEmpty && items.every((e) => e.state != MemoryCandidateState.pending);

  MemoryConfirmCard copyWith({List<MemoryCandidateItem>? items}) {
    final nextItems = items ?? this.items;
    assert(nextItems.length > 0, 'memory card requires at least one item');
    assert(
      nextItems.map((e) => e.itemId).toSet().length == nextItems.length,
      'itemId must be unique within a memory card',
    );
    return MemoryConfirmCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      items: nextItems,
    );
  }
}
```

### 4.8 PlanProposalCard

```dart
class PlanChange {
  const PlanChange({
    required this.type,
    required this.title,
    this.detail,
  }) : assert(title != '', 'plan change title must not be empty');

  final PlanChangeType type;
  final String title;
  final String? detail;
}

final class PlanProposalCard extends ChatMessage {
  // 含集合非空与不可变复制，构造函数不能是 const
  PlanProposalCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.summary,
    required List<PlanChange> changes,
    required this.rationale,
    this.state = PlanProposalState.pending,
  })  : changes = List<PlanChange>.unmodifiable(changes),
        assert(summary != '', 'summary must not be empty'),
        assert(changes.length > 0, 'plan proposal requires at least one change'),
        assert(rationale != '', 'rationale must not be empty');

  final String summary;
  final List<PlanChange> changes;
  final String rationale;
  final PlanProposalState state;

  PlanProposalCard copyWith({PlanProposalState? state}) {
    final nextState = state ?? this.state;
    if (this.state != PlanProposalState.pending && nextState != this.state) {
      throw StateTransitionException(
        model: 'PlanProposalCard',
        from: this.state.name,
        to: nextState.name,
        reason: 'terminal plan proposal cannot change state',
      );
    }
    assert(
      !(this.state != PlanProposalState.pending &&
          nextState == PlanProposalState.pending),
      'terminal plan proposal cannot return to pending',
    );
    return PlanProposalCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      summary: summary,
      changes: changes,
      rationale: rationale,
      state: nextState,
    );
  }
}
```

### 4.9 AgentInviteCard

```dart
final class AgentInviteCard extends ChatMessage {
  const AgentInviteCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    required this.inviteId,
    required this.initiatorAgent,
    required this.targetAgent,
    required this.topic,
    required this.goal,
    required this.scopeSummary,
    required this.expectedOutcome,
    this.projectId,
    this.status = AgentInviteStatus.pending,
    this.createdConversationId,
    this.accepting = false,
  })  : assert(inviteId != '', 'inviteId must not be empty'),
        assert(
          targetAgent == ConversationAgent.jarvis,
          'U1 invite target must be jarvis',
        ),
        assert(
          topic != '' && goal != '' && scopeSummary != '' && expectedOutcome != '',
          'invite requires topic/goal/scopeSummary/expectedOutcome',
        ),
        assert(
          status == AgentInviteStatus.pending || !accepting,
          'accepting is only allowed while pending',
        ),
        assert(
          status != AgentInviteStatus.accepted ||
              createdConversationId != null,
          'accepted invite requires createdConversationId',
        ),
        assert(
          status == AgentInviteStatus.accepted ||
              createdConversationId == null,
          'unaccepted invite must not have createdConversationId',
        ),
        assert(
          createdConversationId == null || createdConversationId != '',
          'createdConversationId must not be empty',
        );

  final String inviteId;
  final ConversationAgent initiatorAgent;  // 不含 user
  final ConversationAgent targetAgent;     // U1 固定 jarvis
  final String? projectId;
  final String topic;
  final String goal;
  final String scopeSummary;
  final String expectedOutcome;
  final AgentInviteStatus status;
  final String? createdConversationId;     // 接受后回填
  final bool accepting;                    // UI 处理中，防重复点击

  AgentInviteCard copyWith({
    AgentInviteStatus? status,
    Object? createdConversationId = unset,
    bool? accepting,
  }) {
    final nextStatus = status ?? this.status;
    final nextCreatedConversationId = identical(createdConversationId, unset)
        ? this.createdConversationId
        : createdConversationId as String?;
    final nextAccepting = accepting ?? this.accepting;
    if (this.status != AgentInviteStatus.pending &&
        nextStatus != this.status) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'terminal invite cannot change status',
      );
    }
    if (nextStatus != AgentInviteStatus.pending && nextAccepting) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'accepting is only allowed while pending',
      );
    }
    if (nextStatus == AgentInviteStatus.accepted &&
        nextCreatedConversationId == null) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'accepted invite requires createdConversationId',
      );
    }
    if (nextStatus != AgentInviteStatus.accepted &&
        nextCreatedConversationId != null) {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'unaccepted invite must not have createdConversationId',
      );
    }
    if (nextCreatedConversationId != null &&
        nextCreatedConversationId == '') {
      throw StateTransitionException(
        model: 'AgentInviteCard',
        from: this.status.name,
        to: nextStatus.name,
        reason: 'createdConversationId must not be empty',
      );
    }
    assert(
      nextStatus == AgentInviteStatus.pending || !nextAccepting,
      'accepting is only allowed while pending',
    );
    assert(
      nextStatus != AgentInviteStatus.accepted ||
          nextCreatedConversationId != null,
      'accepted invite requires createdConversationId',
    );
    assert(
      nextStatus == AgentInviteStatus.accepted ||
          nextCreatedConversationId == null,
      'unaccepted invite must not have createdConversationId',
    );
    assert(
      nextCreatedConversationId == null || nextCreatedConversationId != '',
      'createdConversationId must not be empty',
    );
    return AgentInviteCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      inviteId: inviteId,
      initiatorAgent: initiatorAgent,
      targetAgent: targetAgent,
      topic: topic,
      goal: goal,
      scopeSummary: scopeSummary,
      expectedOutcome: expectedOutcome,
      projectId: projectId,
      status: nextStatus,
      createdConversationId: nextCreatedConversationId,
      accepting: nextAccepting,
    );
  }
}
```

### 4.10 ThinkingCard

```dart
final class ThinkingCard extends ChatMessage {
  const ThinkingCard({
    required super.id,
    required super.conversationId,
    required super.sender,
    required super.createdAt,
    required super.seq,
    super.reason,
    super.syncState,
    this.phase = ThinkingPhase.thinking,
  });

  final ThinkingPhase phase;

  ThinkingCard copyWith({ThinkingPhase? phase}) {
    return ThinkingCard(
      id: id,
      conversationId: conversationId,
      sender: sender,
      createdAt: createdAt,
      seq: seq,
      reason: reason,
      syncState: syncState,
      phase: phase ?? this.phase,
    );
  }
}
```

不包含任何预计完成时间或倒计时字段。

### 4.11 TodayItem 与 Brief

```dart
class TodayItem {
  // 含 DateTime 比较，构造函数不能是 const
  TodayItem({
    required this.id,
    required this.kind,
    required this.title,
    required this.status,
    required this.compressible,
    required this.syncState,
    this.start,
    this.end,
    this.durationMin,
    this.sourceTag,
    this.reason,
    this.projectId,
    this.projectTitle,
  })  : assert(id != '', 'id must not be empty'),
        assert(title != '', 'title must not be empty'),
        assert(
          kind != TodayItemKind.block || (start != null && end != null),
          'block requires start and end',
        ),
        assert(
          kind != TodayItemKind.block || end!.isAfter(start!),
          'block end must be after start',
        ),
        assert(
          kind != TodayItemKind.block ||
              (durationMin != null && durationMin > 0),
          'block requires a positive durationMin',
        ),
        assert(
          kind != TodayItemKind.reminder || start != null,
          'reminder requires start',
        ),
        assert(
          kind == TodayItemKind.block || (end == null && durationMin == null),
          'end/durationMin are only allowed for block items',
        );

  final String id;
  final TodayItemKind kind;
  final String title;
  final TodayItemStatus status;
  final bool compressible;
  final SyncState syncState;
  final DateTime? start;
  final DateTime? end;
  final int? durationMin;
  final String? sourceTag;
  final String? reason;
  final String? projectId;
  final String? projectTitle;

  /// overdue 是派生状态，不写入 status，也不参与持久化。
  /// block 以 end 为准；reminder 有 10 分钟宽限；task 以 start 为准。
  bool isOverdueAt(DateTime now) {
    if (status == TodayItemStatus.done || status == TodayItemStatus.skipped) {
      return false;
    }
    return switch (kind) {
      TodayItemKind.block =>
        end != null && now.isAfter(end!),
      TodayItemKind.reminder =>
        start != null && now.isAfter(start!.add(const Duration(minutes: 10))),
      TodayItemKind.task =>
        start != null && now.isAfter(start!),
    };
  }

  TodayItem copyWith({
    TodayItemStatus? status,
    SyncState? syncState,
    Object? start = unset,
  }) {
    final nextStart = identical(start, unset) ? this.start : start as DateTime?;
    if (nextStart == null && kind != TodayItemKind.task) {
      throw StateTransitionException(
        model: 'TodayItem',
        from: this.start?.toIso8601String() ?? 'null',
        to: 'null',
        reason: 'only task items can clear start',
      );
    }
    if (kind == TodayItemKind.block && !end!.isAfter(nextStart!)) {
      throw StateTransitionException(
        model: 'TodayItem',
        from: this.start?.toIso8601String() ?? 'null',
        to: nextStart.toIso8601String(),
        reason: 'block end must be after start',
      );
    }
    assert(
      nextStart != null || kind == TodayItemKind.task,
      'only task items can clear start',
    );
    assert(
      kind != TodayItemKind.block || end!.isAfter(nextStart!),
      'block end must be after start',
    );
    return TodayItem(
      id: id,
      kind: kind,
      title: title,
      status: status ?? this.status,
      compressible: compressible,
      syncState: syncState ?? this.syncState,
      start: nextStart,
      end: end,
      durationMin: durationMin,
      sourceTag: sourceTag,
      reason: reason,
      projectId: projectId,
      projectTitle: projectTitle,
    );
  }
}

class Brief {
  // 含集合不可变复制，构造函数不能是 const
  Brief({
    required this.kind,
    required this.text,
    required this.reasonLine,
    List<String> mergedSuggestions = const <String>[],
  })  : mergedSuggestions = List<String>.unmodifiable(mergedSuggestions),
        assert(text != '', 'brief text must not be empty'),
        assert(reasonLine != '', 'brief reasonLine must not be empty'),
        assert(
          mergedSuggestions.every((s) => s != ''),
          'mergedSuggestions must not contain empty strings',
        );

  final BriefKind kind;
  final String text;
  final String reasonLine;
  final List<String> mergedSuggestions;
}

class DayView {
  // 含集合不可变复制，构造函数不能是 const
  DayView({
    required this.date,
    required List<TodayItem> items,
    required List<TodayItem> unscheduled,
    this.morningBrief,
    this.eveningBrief,
  })  : items = List<TodayItem>.unmodifiable(items),
        unscheduled = List<TodayItem>.unmodifiable(unscheduled),
        assert(
          !date.isUtc,
          'DayView.date must be a local DateTime',
        ),
        assert(
          date.hour == 0 &&
              date.minute == 0 &&
              date.second == 0 &&
              date.millisecond == 0 &&
              date.microsecond == 0,
          'DayView.date must be normalized to local midnight',
        ),
        assert(
          items.every((e) => e.start != null) &&
              unscheduled.every(
                (e) => e.start == null && e.kind == TodayItemKind.task,
              ),
          'items require start; unscheduled must be tasks without start',
        ),
        assert(
          unscheduled.every(
            (e) => e.status == TodayItemStatus.planned,
          ),
          'unscheduled items must stay planned',
        ),
        assert(
          [...items, ...unscheduled].map((e) => e.id).toSet().length ==
              items.length + unscheduled.length,
          'TodayItem ids must be unique within a DayView',
        ),
        assert(
          _isSortedByStart(items),
          'DayView.items must be sorted by start ascending',
        ),
        assert(
          morningBrief == null || morningBrief.kind == BriefKind.morning,
          'morningBrief must be a morning brief',
        ),
        assert(
          eveningBrief == null || eveningBrief.kind == BriefKind.evening,
          'eveningBrief must be an evening brief',
        );

  final DateTime date;
  final List<TodayItem> items;
  final List<TodayItem> unscheduled;
  final Brief? morningBrief;
  final Brief? eveningBrief;
}

bool _isSortedByStart(List<TodayItem> items) {
  for (var i = 1; i < items.length; i++) {
    if (items[i].start!.isBefore(items[i - 1].start!)) return false;
  }
  return true;
}
```

### 4.12 PriorityAlert 与 AlertResumeContext（职责分离）

```dart
class AlertAction {
  const AlertAction({
    required this.actionId,
    required this.label,
    this.destructive = false,
  })  : assert(actionId != '', 'actionId must not be empty'),
        assert(label != '', 'label must not be empty');

  final String actionId;
  final String label;
  final bool destructive;
}

class PriorityAlert {
  // 含集合非空、元素判断与不可变复制，构造函数不能是 const
  PriorityAlert({
    required this.alertId,
    required this.priority,
    required this.reason,
    required List<AlertAction> actions,
    required this.status,
    required this.createdAt,
    this.deadline,
    this.handledActionId,
  })  : actions = List<AlertAction>.unmodifiable(actions),
        assert(alertId != '', 'alertId must not be empty'),
        assert(reason != '', 'reason must not be empty'),
        assert(actions.length > 0, 'alert requires at least one action'),
        assert(
          actions.map((a) => a.actionId).toSet().length == actions.length,
          'alert action ids must be unique',
        ),
        assert(
          status != AlertStatus.handled ||
              (handledActionId != null &&
                  actions.any((a) => a.actionId == handledActionId)),
          'handled alert requires a handledActionId from actions',
        ),
        assert(
          status == AlertStatus.handled || handledActionId == null,
          'handledActionId is only allowed when handled',
        );

  final String alertId;
  final AlertPriority priority;
  final String reason;
  final DateTime? deadline;
  final List<AlertAction> actions;
  final AlertStatus status;
  final DateTime createdAt;
  final String? handledActionId;   // handled 时记录实际执行的动作
}

class AlertResumeContext {
  const AlertResumeContext({
    required this.previousRoute,
    required this.capturedAt,
    this.conversationId,
    this.messageId,
    this.scrollOffset,
    this.draftText,
  })  : assert(previousRoute != '', 'previousRoute must not be empty'),
        assert(
          conversationId != null ||
              (messageId == null && scrollOffset == null && draftText == null),
          'messageId/scrollOffset/draftText require conversationId',
        ),
        assert(
          scrollOffset == null || scrollOffset >= 0,
          'scrollOffset must not be negative',
        );

  final String previousRoute;       // 如 /chat/c-123?messageId=m-9
  final String? conversationId;     // 当前对话（Today 页面时为空）
  final String? messageId;          // 深链定位的消息
  final double? scrollOffset;
  final String? draftText;
  final DateTime capturedAt;
}
```

职责：

- `PriorityAlert` 只描述提醒本身，不记录用户在看哪个页面
- `AlertResumeContext` 由 App Shell 在弹窗出现前采集，弹窗关闭/处理后用于恢复
- 两者不互相引用；Shell 内部以 `(alert, resumeContext)` 成对持有

### 4.13 CardAction（卡片应答）

```dart
sealed class CardAction {
  const CardAction();
}

final class ConfirmAction extends CardAction {
  const ConfirmAction({required this.confirmed});
  final bool confirmed;
}

final class ChoiceAction extends CardAction {
  const ChoiceAction({this.option, this.skipped = false})
      : assert(
          skipped || option != null,
          'non-skipped choice action requires an option',
        ),
        assert(
          !skipped || option == null,
          'skipped choice action must not carry an option',
        ),
        assert(option == null || option != '', 'option must not be empty');
  final String? option;
  final bool skipped;
}

final class MemoryAction extends CardAction {
  const MemoryAction({required this.itemId, required this.confirmed})
      : assert(itemId != '', 'itemId must not be empty');
  final String itemId;
  final bool confirmed;
}

final class ConfirmAllMemoryAction extends CardAction {
  const ConfirmAllMemoryAction();
}

final class PlanProposalAction extends CardAction {
  const PlanProposalAction({required this.decision});
  final PlanDecision decision;
}
```

**邀请卡片不走 `CardAction`**：

- `AgentInviteCard` 的接受/拒绝只能调用 `ChatRepository.acceptInvite(inviteId)` / `declineInvite(inviteId)`
- `respondToCard()` 只处理 Confirm / Choice / Memory / PlanProposal 四类卡片；收到邀请卡片 id 时应拒绝并记录错误
- 删除 `InviteAction`，避免同一操作存在两条路径而绕过邀请幂等与 `accepting` 状态

### 4.14 ChatEvent 与快照

```dart
sealed class ChatEvent {
  const ChatEvent({
    required this.conversationId,
    required this.seq,
  })  : assert(conversationId != '', 'event conversationId must not be empty'),
        assert(seq > 0, 'event seq must be positive');

  final String conversationId;  // 所有会话事件都必须携带
  final int seq;                // 会话内唯一、按事件产生顺序递增
}

final class MessageUpsert extends ChatEvent {
  const MessageUpsert({
    required super.conversationId,
    required super.seq,
    required this.message,
  })  : assert(
          message.conversationId == conversationId,
          'message conversationId must match event',
        ),
        assert(message.seq == seq, 'message seq must match event'),
        assert(
          message.syncState == SyncState.synced,
          'event message must be a formal synced message',
        );
  final ChatMessage message;
}

final class ConversationUpdated extends ChatEvent {
  const ConversationUpdated({
    required super.conversationId,
    required super.seq,
    required this.conversation,
  }) : assert(
          conversation.conversationId == conversationId,
          'conversation id must match event',
        );
  final Conversation conversation;
}

class ConversationSnapshot {
  // 含集合不可变复制，构造函数不能是 const
  ConversationSnapshot({
    required this.conversation,
    required List<ChatMessage> messages,
    required this.lastSeq,
  })  : messages = List<ChatMessage>.unmodifiable(messages),
        assert(lastSeq >= 0, 'lastSeq must not be negative'),
        assert(
          messages.every(
            (m) =>
                m.syncState == SyncState.synced &&
                m.seq > 0 &&
                m.seq <= lastSeq &&
                m.conversationId == conversation.conversationId,
          ),
          'snapshot only accepts formal messages of the same conversation, seq <= lastSeq',
        ),
        assert(
          messages.map((m) => m.id).toSet().length == messages.length,
          'snapshot message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(messages.map((m) => m.seq).toList()),
          'snapshot messages must be sorted by seq ascending',
        );

  final Conversation conversation;   // 与 messages 同一快照点
  final List<ChatMessage> messages;
  final int lastSeq;
  // lastSeq = 快照已完整反映该会话中所有 seq <= lastSeq 的事件所产生的状态
}

class ConversationView {
  // 含集合不可变复制，构造函数不能是 const
  ConversationView({
    required this.conversation,
    required List<ChatMessage> messages,
    this.syncState = ConversationSyncState.synced,
    this.retryCount = 0,
    this.syncError,
  })  : messages = List<ChatMessage>.unmodifiable(messages),
        assert(
          messages.every(
            (m) =>
                m.syncState == SyncState.synced &&
                m.seq > 0 &&
                m.conversationId == conversation.conversationId,
          ),
          'view only accepts formal messages of the same conversation',
        ),
        assert(
          messages.map((m) => m.id).toSet().length == messages.length,
          'view message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(messages.map((m) => m.seq).toList()),
          'view messages must be sorted by seq ascending',
        ),
        assert(
          retryCount >= 0 && retryCount <= 2,
          'retryCount must be within 0..2',
        ),
        assert(
          syncState == ConversationSyncState.failed || syncError == null,
          'syncError is only allowed when failed',
        ),
        assert(
          syncState != ConversationSyncState.failed || syncError != null,
          'failed sync state requires syncError',
        ),
        assert(
          syncError == null || syncError != '',
          'syncError must not be empty',
        ),
        assert(
          (syncState == ConversationSyncState.failed ||
                  syncState == ConversationSyncState.retrying) ==
              (retryCount > 0),
          'retrying/failed require retryCount > 0; synced/syncing require 0',
        );

  final Conversation conversation;
  final List<ChatMessage> messages;  // 仅正式消息
  final ConversationSyncState syncState;
  final int retryCount;              // 已执行的重试次数，0–2
  final String? syncError;
}

class ChatView {
  // 含集合去重、排序与不可变复制，构造函数不能是 const
  ChatView({
    required this.conversation,
    required List<ChatMessage> messages,
    required List<ChatMessage> pending,
    Map<String, String> sendErrors = const <String, String>{},
    this.syncState = ConversationSyncState.synced,
    this.retryCount = 0,
    this.syncError,
  })  : messages = List<ChatMessage>.unmodifiable(messages),
        pending = List<ChatMessage>.unmodifiable(pending),
        sendErrors = Map<String, String>.unmodifiable(sendErrors),
        assert(
          messages.every(
            (m) =>
                m.syncState == SyncState.synced &&
                m.seq > 0 &&
                m.conversationId == conversation.conversationId,
          ),
          'messages must be formal messages of the same conversation',
        ),
        assert(
          messages.map((m) => m.id).toSet().length == messages.length,
          'formal message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(messages.map((m) => m.seq).toList()),
          'formal messages must be sorted by seq ascending',
        ),
        assert(
          pending.every(
            (p) =>
                p.syncState != SyncState.synced &&
                p.seq < 0 &&
                p.conversationId == conversation.conversationId,
          ),
          'pending must contain local pending/queued/failed messages of the same conversation',
        ),
        assert(
          pending.map((p) => p.id).toSet().length == pending.length,
          'pending message ids must be unique',
        ),
        assert(
          _isStrictlyAscending(pending.map((p) => -p.seq).toList()),
          'pending must be sorted by negative seq descending',
        ),
        assert(
          pending.every((p) => !messages.any((m) => m.id == p.id)),
          'pending must not contain ids already present in formal messages',
        ),
        assert(
          sendErrors.keys.every(
            (id) => pending.any(
              (p) => p.id == id && p.syncState == SyncState.failed,
            ),
          ),
          'sendErrors keys must reference failed pending messages',
        ),
        assert(
          sendErrors.values.every((text) => text != ''),
          'sendErrors values must not be empty',
        ),
        assert(
          retryCount >= 0 && retryCount <= 2,
          'retryCount must be within 0..2',
        ),
        assert(
          syncState == ConversationSyncState.failed || syncError == null,
          'syncError is only allowed when failed',
        ),
        assert(
          syncState != ConversationSyncState.failed || syncError != null,
          'failed sync state requires syncError',
        ),
        assert(
          syncError == null || syncError != '',
          'syncError must not be empty',
        ),
        assert(
          (syncState == ConversationSyncState.failed ||
                  syncState == ConversationSyncState.retrying) ==
              (retryCount > 0),
          'retrying/failed require retryCount > 0; synced/syncing require 0',
        );

  final Conversation conversation;
  final List<ChatMessage> messages;  // 正式消息，按 seq 升序
  final List<ChatMessage> pending;   // pending/queued/failed，负数 seq，按创建顺序排在正式消息之后
  final Map<String, String> sendErrors; // clientMessageId -> 失败文案，仅 failed 存在
  final ConversationSyncState syncState;
  final int retryCount;              // 已执行的重试次数，0–2
  final String? syncError;

  /// 页面唯一渲染顺序：正式消息 → pending/queued/failed。
  /// UI 不得自行拼接或再次排序。
  List<ChatMessage> get displayMessages => [...messages, ...pending];
}

bool _isStrictlyAscending(List<int> values) {
  for (var i = 1; i < values.length; i++) {
    if (values[i] <= values[i - 1]) return false;
  }
  return true;
}
```

**统一事件序列**：

- `MessageUpsert`、`ConversationUpdated` 以及未来新增的会话事件，全部属于**同一条**按 `seq` 递增的事件序列
- 不允许不同事件类型各自维护序号；`seq` 在单个 Conversation 内唯一
- 事件处理必须参与连续性检查；暂不支持业务处理的新事件类型，可以安全忽略其业务效果，但必须推进 `currentSeq`，不能破坏序列

**不同事件的处理方式**：

| 事件 | 处理 |
|---|---|
| `MessageUpsert` | 按 `message.id` upsert 消息 |
| `ConversationUpdated` | 用事件内的 Conversation 覆盖当前对话信息（状态、最近活动、项目标题等） |
| 未来事件类型 | 推进 `currentSeq`；如无法处理则记录并安全忽略，不改变已有状态 |

**事件一致性校验**（任何一条不满足都不得直接应用；这些是运行时校验，不得只依赖构造 assert，失败路径见 4.20）：

| 校验 | 要求 |
|---|---|
| 外层会话 | `event.conversationId` 必须等于当前监听的 `conversationId` |
| 消息归属 | `MessageUpsert.message.conversationId == event.conversationId` |
| 消息序号 | `MessageUpsert.message.seq == event.seq` |
| 对话归属 | `ConversationUpdated.conversation.conversationId == event.conversationId` |
| 消息 ID | `MessageUpsert.message.id` 非空；同一事件内保持一致 |

校验失败的处理：

- 不应用到正式状态
- 记录诊断信息（事件类型、conversationId、seq、校验失败原因）
- 进入安全恢复流程：重新获取快照；恢复失败则保留上一份有效状态并提示同步异常

**重复、过期与冲突的统一判定**：

Repository 为每个 `seq` 记录**事件摘要**（事件类型 + 关键字段，如 `messageId`、文本、对话状态；不要求暴露给上层）。摘要只对 `(baselineSeq, currentSeq]` 建立，并保留最近 200 个已应用 `seq` 的摘要；`baselineSeq` 定义见 4.17：

| 条件 | 判定 | 处理 |
|---|---|---|
| `seq <= baselineSeq` | 快照已覆盖 | 直接忽略，不比对摘要、不报冲突 |
| `baselineSeq < seq < currentSeq`，摘要相同或已淘汰 | 过期事件 | 忽略，不改变状态 |
| `baselineSeq < seq < currentSeq`，摘要不同 | 迟到冲突 | 忽略其业务效果；记录 `late_conflict` 诊断；不触发重同步（快照与后续事件已是权威） |
| `seq == currentSeq > baselineSeq`，摘要相同 | 重复事件 | 忽略 |
| `seq == currentSeq > baselineSeq`，摘要不同 | 头部冲突 | 视为协议冲突，触发重新同步 |
| `seq == currentSeq == baselineSeq` | 快照已覆盖 | 按第一行忽略，不能误判为重复或头部冲突 |
| buffer 内同一 `seq` 摘要相同 | 重复 | 合并为一条，只应用一次 |
| buffer 内同一 `seq` 摘要不同 | 缓冲冲突 | 停止应用该 seq 及后续事件，触发重新同步 |

约束：

- 冲突事件一律不得任意选一个覆盖另一个
- 重同步开始时清除全部旧摘要，并重设 `baselineSeq = currentSeq = newLastSeq`；新摘要只对之后的事件建立
- `seq <= baselineSeq` 的事件不记录摘要，避免把快照覆盖区间误当成「已应用事件」
- 若冲突重复出现，Repository 记录错误并向上层暴露同步异常状态

### 4.15 邀请结果类型

```dart
sealed class InviteAcceptResult {
  const InviteAcceptResult();
}

final class InviteAccepted extends InviteAcceptResult {
  const InviteAccepted({required this.conversation, required this.alreadyAccepted});
  final Conversation conversation;
  final bool alreadyAccepted;
}

final class InviteCannotAccept extends InviteAcceptResult {
  const InviteCannotAccept({required this.reason});
  final InviteRejectReason reason;
}

sealed class InviteDeclineResult {
  const InviteDeclineResult();
}

final class InviteDeclined extends InviteDeclineResult {
  const InviteDeclined();
}

final class InviteCannotDecline extends InviteDeclineResult {
  const InviteCannotDecline({required this.reason});
  final InviteRejectReason reason;
}
```

### 4.16 仓库接口

```dart
abstract interface class ChatRepository {
  Future<Conversation> loadMainConversation();
  Future<List<Conversation>> loadTopicConversations();
  Future<Conversation> getConversation(String conversationId);

  // 先订阅，保证不漏事件
  Stream<ChatEvent> watchConversation(String conversationId);

  // 后取快照；与事件按 4.17 的规则合并
  Future<ConversationSnapshot> loadConversationSnapshot(String conversationId);

  // 手动重试同步：重置退避计数并重新走一次 4.17 的重同步流程
  Future<void> retrySync(String conversationId);

  // clientMessageId 由 Controller 生成；确认事件必须复用同一 id
  Future<void> sendText({
    required String conversationId,
    required String clientMessageId,
    required String text,
  });

  // 仅用于 Confirm / Choice / Memory / PlanProposal；邀请卡片走 acceptInvite/declineInvite
  Future<void> respondToCard({
    required String conversationId,
    required String messageId,
    required CardAction action,
  });

  Future<InviteAcceptResult> acceptInvite(String inviteId);
  Future<InviteDeclineResult> declineInvite(String inviteId);
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

abstract interface class AlertRepository {
  Stream<PriorityAlert> watchAlerts();
  Future<void> handleAlert({required String alertId, required String actionId});
  Future<void> dismissAlert(String alertId);
}
```

接口约束：

- `sendText` 必须携带 Controller 生成的 `clientMessageId`，且与本地 pending 的 `id` 完全一致；失败重试复用同一 id
- `sendText` 正常返回只表示请求已被接受，**不代表消息已确认**；确认只认正式消息或事件中出现的同一 `id`
- `sendText` 失败必须抛出异常，由 Controller 将该条消息置为 `failed`；Repository 不得吞异常或伪造确认
- Repository **不创建、不持有、不返回** pending；pending 由 Controller 持有，合并规则见 4.17 与 4.19
- `loadConversationSnapshot` 返回的 `conversation`、`messages`、`lastSeq` 必须来自同一快照点；不得由两个请求拼接
- `retrySync` 只用于用户手动重试：不取消、不重建订阅，重置退避计数并从第 1 次尝试重新开始；仅 `failed` 状态下清空旧事件队列后重新取快照，不得绕过运行时校验
- 调用方必须先 `watchConversation` 再取快照；Repository 负责缓存、排序、去重与缺口恢复，调用方不做这些判断
- `respondToCard` 只接受 Confirm / Choice / Memory / PlanProposal；邀请卡片一律走 `acceptInvite` / `declineInvite`
- `acceptInvite` 幂等：重复或并发调用最多创建一个 Conversation，成功结果指向同一 `conversationId`
- 前端只传 `conversationId`、`clientMessageId`、文本、卡片动作、`inviteId`
- 不传 Prompt、不选模型、不指定 Agent；路由与模型选择属于后端
- Mock 实现必须体现 4.17（事件合并、快照基线、重试退避、pending 归属、本地消息边界）、4.18（邀请幂等）、4.19（pending/queued/failed 生命周期、确认清理）与 4.21（离线发送、销毁保护）的语义，含延迟事件、重复事件、流式更新、发送失败、非法 payload 与并发接受；`retrySync` 必须可被 UI 触发

### 4.17 事件序列与快照衔接规则（关键）

**目标**：历史快照与实时事件之间不能出现消息遗漏或对话状态不同步；同一消息不能重复出现。

**订阅顺序**：先 `watchConversation`，再 `loadConversationSnapshot`。

**基线定义**：

- `baselineSeq`：最近一次快照的 `lastSeq`，表示「该 seq 及之前的状态已由快照完整覆盖」
- `currentSeq`：当前已应用的最大 seq，始终满足 `currentSeq >= baselineSeq`
- 摘要只对 `seq > baselineSeq` 的事件建立；`seq <= baselineSeq` 不建立摘要，也不做内容比对
- 初次加载与每次重同步都会重设 `baselineSeq = lastSeq`、`currentSeq = lastSeq`，并清除旧摘要

**统一事件应用规则**（初次合并、持续监听、重同步三个阶段共用）：

| 收到的事件 | 处理 |
|---|---|
| `event.seq <= baselineSeq` | 快照已覆盖：直接忽略，不比对内容、不报冲突 |
| `baselineSeq < event.seq < currentSeq` | 过期事件：忽略；若摘要存在且不同，记录 `late_conflict`，不回滚、不重同步 |
| `event.seq == currentSeq == baselineSeq` | 快照已覆盖：直接忽略，不判重复、不判头部冲突 |
| `event.seq == currentSeq > baselineSeq` | 重复或头部事件：摘要相同则忽略；摘要不同则判定头部冲突并进入重新同步 |
| `event.seq == currentSeq + 1` | 正常应用，记录摘要，`currentSeq = event.seq` |
| `event.seq > currentSeq + 1` | 发现缺口，停止应用后续事件，进入重新同步 |

约束：

- `MessageUpsert`、`ConversationUpdated` 及未来会话事件全部遵循同一规则
- 不能只在持续监听阶段检查缺口；初次 buffer 合并与重同步后的再次合并都必须逐条检查
- 快照刚建立时 `currentSeq == baselineSeq`，此时收到 `seq == currentSeq` 的事件属于快照覆盖范围，按第一行忽略，不能误判为头部冲突
- 已到 15 又收到 13：若 13 > baselineSeq 且摘要不同，记录 `late_conflict`；若 13 <= baselineSeq，直接忽略
- 同一 `seq` 的重复事件只应用一次；同 `seq` 不同内容按上表冲突分支处理，不任选其一
- 摘要只保留 `(baselineSeq, currentSeq]` 范围内最近 200 个 seq；更早的过期事件只按过期忽略，不再做内容比对

**阶段一：初次加载**

1. 建立 `watchConversation` 订阅，事件立即进入 `buffer`
2. 请求 `ConversationSnapshot(conversation, messages, lastSeq)`
3. 用快照的 `conversation` 与 `messages` 初始化正式状态：
   - `baselineSeq = lastSeq`
   - `currentSeq = lastSeq`
   - 清空旧摘要
4. 丢弃 buffer 中 `seq <= baselineSeq` 的事件（快照已覆盖，不做内容比对）
5. 将剩余事件按 `seq` 升序排序，逐条按 4.17 统一事件判定规则处理
6. 每次应用前先做 4.14 的事件一致性校验
7. 若遇到缺口：停止应用，保留未处理事件，转入重新同步
8. 若全部事件连续处理完毕，进入持续监听

**初次 buffer 缺口的例子**：

- 快照 `lastSeq = 10`
- buffer 收到 `MessageUpsert(seq=11)`、`ConversationUpdated(seq=13)`
- 处理 11 后，13 不满足 `== 12`，判定缺口
- 不得直接应用 13 后进入监听；必须重新取快照并重新合并

**阶段二：持续监听**

- 每条事件先校验一致性，再按统一事件判定规则处理
- `currentSeq` 只随成功应用的事件推进
- 收到缺口立即转入重新同步，不尝试跳过缺失事件

**阶段三：重新同步**

1. 进入「重新同步」状态，**不取消订阅**，新事件继续进入 buffer
2. 请求新快照；请求期间到达的事件同样保留
3. 新快照返回后，用其 `conversation` 与 `messages` 重建**正式状态**（Repository 不持有 pending），并重设：
   - `baselineSeq = newLastSeq`
   - `currentSeq = newLastSeq`
   - 清除旧摘要（含旧 baseline 区间）
4. Controller 保留自己持有的 pending，并在收到新 `ConversationView` 后重新合并（见下文）
5. 丢弃 buffer 中 `seq <= baselineSeq` 的事件
6. 对剩余事件重新执行统一事件判定规则
7. 若仍有缺口，重复本阶段，但受 3 次尝试上限约束；超过上限转 `failed`，不得无限循环
8. 同一时刻只允许一个同步流程修改会话状态；禁止两个监听器并行写入

**事件队列串行与 buffer 原子切换**：

- 每个 conversation 只有一条事件队列；初次 buffer、持续监听事件、重同步期间事件全部进入同一队列，按 `seq` 排序后**逐条串行**处理
- 事件应用函数必须是同步段：`seq` 判定、状态写入、`currentSeq`/摘要更新在同一个同步块内完成，中间不得 `await`；IO/通知在状态提交后另行触发
- 每次重同步递增 `syncGeneration`；快照请求携带发起时的 generation，返回时若 generation 已变化则丢弃该快照，不能覆盖更新的状态
- buffer 切换必须原子：处理快照时一次性取出当前 buffer 并替换为空 buffer；切换期间到达的新事件进入新 buffer，待当前批处理完再按序处理，不能丢失或重复
- 禁止两个 `async` 流程同时写 `baselineSeq`/`currentSeq`/摘要/消息；用单飞（in-flight）标志或互斥锁保证同一时刻只有一个同步任务
- 事件队列设置上限（U1 为 1000 条）；溢出时丢弃队列并直接进入重同步，以新快照为准，禁止无限堆积
- 重同步失败进入 `failed` 后停止消费队列；手动 `retrySync` 不重建订阅，只清空旧队列、重置退避并重新取快照
- 应用顺序固定为：一致性校验 → 序号判定 → 状态/消息写入 → 摘要更新 → 通知监听者；任一步失败不得留下半应用状态
- 测试必须覆盖：事件到达与快照返回交错、切换 buffer 瞬间插入事件、旧 generation 快照晚到、队列溢出、重同步失败后手动重试

**同步引擎实现位置**：

- 4.17 的全部规则（单队列串行、buffer 原子切换、`syncGeneration`、摘要窗口、重同步退避）集中在 `ConversationSyncEngine` 一个类中，文件为 `mobile/lib/core/sync/conversation_sync_engine.dart`
- `ChatRepository` 的实现内部持有或调用该引擎；Provider / Controller / Widget 不出现 `baselineSeq`、摘要、`syncGeneration` 等概念
- 引擎对外只暴露 `Stream<ConversationView> watch(String conversationId)`、`Future<ConversationSnapshot> loadSnapshot(String conversationId)` 与 `Future<void> retrySync(String conversationId)`；全部状态变更在引擎内部串行完成
- 将来接入真实后端协议时只替换引擎与 Repository，不动 Controller 与 UI

**重同步重试上限与退避**：

- 每次发现缺口后，重同步最多尝试 **3 次**（首次 + 2 次重试）；不得无限循环
- 退避在每次重试前执行：第 1 次重试前 300ms，第 2 次重试前 600ms；上限 1200ms；每次叠加 ±20% jitter
- 退避通过可注入的 `Sleeper` 执行（`Future<void> sleep(Duration)`）；jitter 通过可注入的 `Random` 生成；测试注入固定 seed，断言延迟落在 [0.8×base, 1.2×base] 且不超过 1200ms；禁止在 Repository 内直接硬编码 `Future.delayed`
- 第 3 次尝试仍失败：停止自动重试，保留最后一次有效 `ConversationView`，将 `syncState = failed`、`retryCount = 2`（已执行 2 次重试）、`syncError` 置为可展示文案
- 成功后 `retryCount = 0`、`syncState = synced`、清空 `syncError`；下一次新的缺口重新从 3 次额度开始
- 用户手动「重试同步」视为新周期，从第 1 次尝试重新计数；不再自动触发
- `conversationChannelProvider` 必须关闭 Riverpod 3 的 provider 自动重试（`retry: (_, __) => null`），避免与 Repository 自己的退避策略叠加
- 重试期间订阅不取消，事件继续进入 buffer；每次尝试都用新快照重设 `baselineSeq/currentSeq` 并清空旧摘要
- `late_conflict` 只记录诊断，不触发重试；只有缺口、头部冲突、缓冲冲突、快照校验失败进入重试流程

**首次加载失败处理**：

- 初次 `loadConversationSnapshot` 与重同步共用同一重试策略：最多 3 次尝试、300ms/600ms 退避、±20% jitter
- 3 次仍失败时不得构造半成品 `ConversationView`：`conversationChannelProvider` 返回 `AsyncError(SyncInitialLoadException)`，不设置 `baselineSeq/currentSeq`，不建立摘要
- UI 显示整页错误态「加载失败」+「重试」；输入条禁用，不能创建 pending
- `retrySync` 对首次加载失败同样有效：重新发起首次快照请求，成功后再进入正常同步流程
- 初次加载失败不写入同步 `failed` 横幅（没有旧消息可保留），与「已有数据后重同步失败」区分
- Mock 必须提供「首次快照连续失败 3 次 → AsyncError → 手动重试成功」的数据

**MessageUpsert 语义**：

- 以 `message.id` 为键 upsert：存在则替换，不存在则插入
- 重复收到同一 `messageId` 的事件不产生重复消息
- 流式文字增长始终更新同一条消息（同一 `id` 的 `text` 变化），不创建新消息
- `seq` 更新为事件 `seq`；`createdAt` 不变

**ConversationUpdated 语义**：

- 以事件内的 `Conversation` 整体覆盖当前值（同 `conversationId`）
- 与消息事件一样参与连续性与冲突检查
- 重复事件按 `seq` 去重，不产生重复状态变更

**排序规则**：

- 正式消息按正式 `seq` 升序展示
- 不按 `createdAt` 排序（时钟漂移会导致乱序）；`createdAt` 仅用于界面时间显示

**本地临时消息、clientMessageId 与重试**：

- 正式 `seq` 只由仓库/服务端分配；Controller 与 UI 不得分配正式 `seq`
- Controller 为每次发送生成唯一 `clientMessageId`，用它创建本地 pending 消息，并原样传给 `sendText`
- 服务端确认事件的 `message.id` 必须等于 `clientMessageId`；Repository 通过该 id 完成确认
- 本地 pending / queued / failed 使用**负数临时 seq**（从 -1 开始递减：-1、-2、-3…），仅用于本地排序：不参与连续性检查、不写入 `lastSeq`、不进入 `ConversationSnapshot`、不得作为 `ChatEvent`
- 排序：正式消息按 `seq` 升序；pending / queued / failed 按负数临时 seq **降序**（-1 在 -2 之前，即创建顺序）排在正式消息之后，不依赖 `createdAt`，避免时钟回拨
- 同一会话的多条 pending 使用各自 `clientMessageId` 与临时 seq，互不覆盖
- 网络失败重试必须复用原 `clientMessageId` 与原负数 seq；同一 `clientMessageId` 的重复发送不得创建第二条消息
- 失败消息保留原 id 与原负数 seq，只把 `syncState` 改为 `failed`；重试在线改回 `pending`、离线改回 `queued`，不新建消息

**pending / queued / failed 状态机**：

| 状态 | `syncState` | `seq` | 进入条件 | 退出条件 |
|---|---|---|---|---|
| 离线排队 | `queued` | 负数 | 离线时 Controller 创建消息 | 网络恢复转 `pending` 并补发 |
| 发送中 | `pending` | 负数 | 在线创建 pending 并上屏 | 发送成功等确认；或发送失败转 `failed` |
| 发送失败 | `failed` | 同一负数 | `sendText` 抛异常/超时 | 用户重试转 `pending/queued`；确认到达则直接清理 |
| 已确认 | `synced` | 正式正数 | 正式消息/事件/快照出现同一 `id` | 终态，不再回到本地状态 |

**pending 的创建、持有、合并与清理（统一归属 Controller）**：

- **创建**：Controller 生成 `clientMessageId` 与负数临时 seq，在线创建 `TextMessage(syncState: pending)`、离线创建 `queued`，并立即上屏
- **持有**：pending / queued / failed 只存在于 `ChatState.pending`；Repository 不创建、不存储、不返回
- **合并**：`chatViewProvider` 读取 `conversationChannelProvider` 的正式 `ConversationView` 与 `chatControllerProvider` 的 `ChatState`，过滤掉正式消息中已存在的 id 后生成 `ChatView`
- **确认清理**：`ChatController.build()` 监听 `conversationChannelProvider`，只要正式消息或重同步快照中出现 `id == clientMessageId`，就从 `ChatState.pending` 与 `sendErrors` 中删除该条；UI 不再显示 pending
- **失败**：`sendText` 抛异常时，把同一消息的 `syncState` 改为 `failed`，并在 `sendErrors[clientMessageId]` 记录文案；不删除消息、不改 id、不改负数 seq
- **重试**：复用原 `clientMessageId` 与原负数 seq，把 `syncState` 改回 `pending`，清除 `sendErrors` 对应项，再次调用 `sendText`
- **重同步**：Repository 只重建正式状态；Controller 收到新 `ConversationView` 后重新合并 pending，pending / queued / failed 都不会因快照而消失
- **去重**：合并以 `messageId` 为键；正式消息优先，`ChatView` 构造断言保证 pending 与正式消息无重复 id
- **不自动清理 failed**：failed 不会因重同步、流式更新或 `ConversationUpdated` 被删除；只有确认到达或用户重试成功才离开列表

**重同步期间保留 pending**：

- 快照只包含正式消息，Controller 不得因新快照而清空 pending
- 若快照或随后事件中已存在相同 `clientMessageId` / `messageId`，Controller 必须把该 pending 转为已确认并复用已有消息，不能再次插入
- 合并后正式消息与临时消息不得重复显示

**Mock 要求**：

- `loadConversationSnapshot` 人为延迟 300ms，期间推入一条新消息与一次 `ConversationUpdated`
- 能模拟初次 buffer 缺口、持续监听缺口、重同步期间继续到达事件、重同步后仍有缺口
- 能模拟旧事件迟到、重复事件、同 seq 冲突、conversationId 不一致、消息内外 seq 不一致
- 能模拟「发送 pending → 重同步 → pending 保留 → 服务端确认同一 id」，最终只有一条消息
- 能模拟连续快照失败：验证 3 次尝试、300ms/600ms 退避、最终 `failed` 与手动重试
- 能模拟非法事件/快照 payload：验证运行时校验拒绝、类型化异常与不部分应用
- 流式回复通过同一 `TextMessage` 的多次 `MessageUpsert` 模拟

**职责边界**：

| 层 | 负责 | 不负责 |
|---|---|---|
| Repository | 订阅、快照获取、事件缓存与一致性校验、统一序号判定与摘要、缺口恢复、按 messageId upsert、分配正式 seq（Mock 内） | 页面状态、Widget 生命周期、创建/持有 pending/queued/failed、合并 pending |
| Controller / Notifier | 生成 `clientMessageId`、创建并持有 pending/queued/failed 与 `sendErrors`、与正式 `ConversationView` 合并、卡片乐观更新与回滚、离线队列与 flush、消息失败转 `failed`、失败重试（复用原 id/seq）、草稿与滚动 | 判断事件是否遗漏、分配正式 seq、决定 Agent 归属 |
| UI / Widget | 展示 `ChatView.displayMessages`、发送中/失败标记、对话头部与专题信息；触发用户操作 | 同步合并、seq 分配、缺口恢复、Agent 路由、pending 去重 |

UI 不得在 Widget 内做事件去重、重排或补拉；这些逻辑只能存在于 Repository（或 Repository 与 Controller 之间的同步层）。

### 4.18 邀请接受与拒绝的幂等规则

**唯一操作路径**：

- `AgentInviteCard` 的接受/拒绝**只允许**调用 `acceptInvite` / `declineInvite`
- 不提供 `InviteAction`，也不能通过 `respondToCard()` 处理邀请，避免绕过幂等与 `accepting` 状态
- 若 `respondToCard()` 收到邀请卡片 id，直接拒绝并记录错误

**唯一性范围**：

- `inviteId` 全局唯一（UUID），由后端/Mock 生成
- 仓库内部记录 `inviteId → { ownerUserId, mainConversationId, status, createdConversationId }`
- 只有 `ownerUserId` 对应的用户、且在 `mainConversationId` 中出现的邀请可被操作；其他情况返回 `InviteCannotAccept(reason: notFound/notOwner)`

**规则表**：

| 场景 | 行为 |
|---|---|
| 首次接受 | 创建项目（如需）与一个 `topic` 对话，`status = accepted`，回填 `createdConversationId` |
| 重复接受（已接受） | 返回此前创建的同一个 Conversation，`alreadyAccepted = true`，不新建 |
| 接受已拒绝/已过期 | `InviteCannotAccept(reason: declined/expired)`，不创建 |
| 并发接受（双击/重试/重复事件） | 以 `inviteId` 为键串行化或等效原子处理；最多创建 1 个 Conversation，项目最多创建/关联一次 |
| 并发接受的返回值 | 所有成功返回都指向同一个 `conversationId`；后到请求 `alreadyAccepted = true` |
| 首次拒绝 | `status = declined`，不创建 Conversation |
| 重复拒绝 | 幂等返回 `InviteDeclined` |
| 拒绝已接受 | `InviteCannotDecline(reason: alreadyAccepted)`，不改变对话 |
| 接受与拒绝同时到达 | 以先到者为准，后到者返回对应 `Cannot*`，二者互斥 |

**并发实现约定（U1 用 Mock 模拟）**：

- 仓库内部以 `inviteId` 为锁键，接受流程串行执行：检查状态 → 创建/关联项目 → 创建 Conversation → 更新邀请
- 创建 Conversation 与更新邀请必须在同一个原子步骤内完成；失败则整体回滚，邀请保持 `pending`
- 网络重试若服务端已完成创建，只返回既有 Conversation，不重复创建
- 「项目」与「Conversation」各自最多创建一次；不得出现两个专题指向同一邀请

**UI 规则**：

1. 点击接受后立即 `accepting = true`，按钮禁用并显示处理中；处理中禁止再次点击
2. 成功后卡片状态 `accepted`，跳转 `/chat/{createdConversationId}`
3. 网络失败：恢复按钮可重试，提示「网络异常，请重试」
4. **终态不按网络失败处理**：`declined` / `expired` / `alreadyAccepted` 必须展示对应原因并禁用按钮，不能提示「请重试」
5. 拒绝后停留主对话，卡片状态 `declined`
6. 已接受的邀请卡片不再可操作

### 4.19 ChatController、ChatState 与展示列表

**ChatState 与 Provider 定义**：

```dart
class ChatState {
  // 含集合校验与不可变复制，构造函数不能是 const
  ChatState({
    List<ChatMessage> pending = const <ChatMessage>[],
    Map<String, String> sendErrors = const <String, String>{},
  })  : pending = List<ChatMessage>.unmodifiable(pending),
        sendErrors = Map<String, String>.unmodifiable(sendErrors),
        assert(
          pending.every(
            (m) => m.syncState != SyncState.synced && m.seq < 0,
          ),
          'pending list only accepts pending/queued/failed messages with negative seq',
        ),
        assert(
          pending.map((m) => m.id).toSet().length == pending.length,
          'pending message ids must be unique',
        ),
        assert(
          _isStrictlyDescending(pending.map((m) => m.seq).toList()),
          'pending must be sorted by negative seq descending',
        ),
        assert(
          sendErrors.keys.every(
            (id) => pending.any(
              (m) => m.id == id && m.syncState == SyncState.failed,
            ),
          ),
          'sendErrors keys must reference failed messages',
        ),
        assert(
          sendErrors.values.every((text) => text != ''),
          'sendErrors values must not be empty',
        );

  /// pending / queued / failed 共用；按负数 seq 降序（创建顺序）
  final List<ChatMessage> pending;

  /// clientMessageId -> 失败文案；仅 failed 的 id 存在
  final Map<String, String> sendErrors;

  ChatState copyWith({
    List<ChatMessage>? pending,
    Map<String, String>? sendErrors,
  }) {
    final nextPending = List<ChatMessage>.unmodifiable(pending ?? this.pending);
    final nextSendErrors =
        Map<String, String>.unmodifiable(sendErrors ?? this.sendErrors);
    assert(
      nextPending.every(
        (m) => m.syncState != SyncState.synced && m.seq < 0,
      ),
      'pending list only accepts pending/queued/failed messages with negative seq',
    );
    assert(
      nextPending.map((m) => m.id).toSet().length == nextPending.length,
      'pending message ids must be unique',
    );
    assert(
      _isStrictlyDescending(nextPending.map((m) => m.seq).toList()),
      'pending must be sorted by negative seq descending',
    );
    assert(
      nextSendErrors.keys.every(
        (id) => nextPending.any(
          (m) => m.id == id && m.syncState == SyncState.failed,
        ),
      ),
      'sendErrors keys must reference failed messages',
    );
    assert(
      nextSendErrors.values.every((text) => text != ''),
      'sendErrors values must not be empty',
    );
    return ChatState(pending: nextPending, sendErrors: nextSendErrors);
  }
}

bool _isStrictlyDescending(List<int> values) {
  for (var i = 1; i < values.length; i++) {
    if (values[i] >= values[i - 1]) return false;
  }
  return true;
}

final chatControllerProvider =
    NotifierProvider.family<ChatController, ChatState, String>(
  ChatController.new,
);

final chatViewProvider =
    Provider.family<AsyncValue<ChatView>, String>((ref, conversationId) {
  final channel = ref.watch(conversationChannelProvider(conversationId));
  final chatState = ref.watch(chatControllerProvider(conversationId));
  return channel.whenData((view) {
    final formalIds = view.messages.map((m) => m.id).toSet();
    final pending = chatState.pending
        .where((m) => !formalIds.contains(m.id))
        .toList()
      ..sort((a, b) => b.seq.compareTo(a.seq));
    final pendingIds = pending.map((m) => m.id).toSet();
    final sendErrors = Map<String, String>.fromEntries(
      chatState.sendErrors.entries.where((e) => pendingIds.contains(e.key)),
    );
    return ChatView(
      conversation: view.conversation,
      messages: view.messages,
      pending: pending,
      sendErrors: sendErrors,
      syncState: view.syncState,
      retryCount: view.retryCount,
      syncError: view.syncError,
    );
  });
});
```

**ChatController 实现骨架**：

```dart
import 'dart:async';

// chatControllerProvider 使用非自动释放配置；本类不持有 Timer / StreamSubscription。
class ChatController extends Notifier<ChatState> {
  ChatController(this.conversationId);

  final String conversationId;
  int _nextLocalId = 0;
  int _nextNegativeSeq = 0;
  bool _disposed = false;
  bool _flushing = false;

  @override
  ChatState build() {
    ref.onDispose(() => _disposed = true);
    ref.listen(conversationChannelProvider(conversationId), (_, next) {
      final view = next.value;
      if (view != null) _pruneConfirmed(view.messages);
    });
    ref.listen(networkStatusProvider, (_, next) {
      if (next.value == NetworkStatus.online) {
        unawaited(_flushOutbox());
      }
    });
    return ChatState();
  }

  Future<void> send(String text) async {
    final body = text.trim();
    if (body.isEmpty || _disposed) return;
    final offline =
        ref.read(networkStatusProvider).value == NetworkStatus.offline;
    final repository = ref.read(chatRepositoryProvider);
    final message = TextMessage(
      id: 'local:$conversationId:${++_nextLocalId}',
      conversationId: conversationId,
      sender: ChatSender.user,
      createdAt: ref.read(clockProvider).now(),
      seq: -(++_nextNegativeSeq),
      syncState: offline ? SyncState.queued : SyncState.pending,
      text: body,
    );
    state = state.copyWith(pending: [...state.pending, message]);
    if (!offline) {
      await _deliver(repository, message);
    }
  }

  Future<void> retry(String clientMessageId) async {
    if (_disposed) return;
    final index = state.pending.indexWhere((m) => m.id == clientMessageId);
    if (index < 0) return;
    final current = state.pending[index];
    if (current is! TextMessage || current.syncState != SyncState.failed) return;
    final offline =
        ref.read(networkStatusProvider).value == NetworkStatus.offline;
    final repository = ref.read(chatRepositoryProvider);
    final message =
        current.copyWith(syncState: offline ? SyncState.queued : SyncState.pending);
    final next = [...state.pending]..[index] = message;
    state = state.copyWith(
      pending: next,
      sendErrors: {...state.sendErrors}..remove(clientMessageId),
    );
    if (!offline) {
      await _deliver(repository, message);
    }
  }

  Future<void> retrySync() {
    if (_disposed) return Future<void>.value();
    return ref.read(chatRepositoryProvider).retrySync(conversationId);
  }

  /// 页面重新可见时调用：不等下一条事件，立即按当前 channel 值清理已确认 pending。
  void reconcile() {
    if (_disposed) return;
    final view = ref.read(conversationChannelProvider(conversationId)).value;
    if (view != null) _pruneConfirmed(view.messages);
    if (ref.read(networkStatusProvider).value == NetworkStatus.online) {
      unawaited(_flushOutbox());
    }
  }

  Future<void> _deliver(ChatRepository repository, TextMessage message) async {
    try {
      await repository.sendText(
        conversationId: conversationId,
        clientMessageId: message.id,
        text: message.text,
      );
    } catch (_) {
      if (_disposed) return;
      final index = state.pending.indexWhere((m) => m.id == message.id);
      if (index < 0) return;
      final next = [...state.pending]
        ..[index] = message.copyWith(syncState: SyncState.failed);
      state = state.copyWith(
        pending: next,
        sendErrors: {...state.sendErrors, message.id: '网络异常，请重试'},
      );
    }
  }

  Future<void> _flushOutbox() async {
    if (_flushing || _disposed) return;
    final repository = ref.read(chatRepositoryProvider);
    _flushing = true;
    try {
      while (!_disposed) {
        final index =
            state.pending.indexWhere((m) => m.syncState == SyncState.queued);
        if (index < 0) return;
        final current = state.pending[index];
        if (current is! TextMessage) return;
        final message = current.copyWith(syncState: SyncState.pending);
        final next = [...state.pending]..[index] = message;
        state = state.copyWith(pending: next);
        await _deliver(repository, message);
        if (_disposed) return;
        final failed = state.pending.any(
          (m) => m.id == message.id && m.syncState == SyncState.failed,
        );
        if (failed) return;
      }
    } finally {
      _flushing = false;
    }
  }

  void _pruneConfirmed(List<ChatMessage> formalMessages) {
    final ids = formalMessages.map((m) => m.id).toSet();
    final remaining = state.pending.where((m) => !ids.contains(m.id)).toList();
    if (remaining.length == state.pending.length) return;
    state = state.copyWith(
      pending: remaining,
      sendErrors: {...state.sendErrors}
        ..removeWhere((id, _) => ids.contains(id)),
    );
  }
}
```

**ChatController 生命周期**：

- **创建**：首次读取 `chatControllerProvider(conversationId)` 时创建；`ChatController(conversationId)` 保存 family 参数，`build()` 无参
- **订阅**：`build()` 中通过 `ref.listen(conversationChannelProvider(conversationId))` 建立唯一实时监听；不创建 `StreamSubscription`，不把订阅放进 Widget
- **保持存活**：Provider 必须 keepAlive（或锁定版本等价的非自动释放配置）；页面 pop 不销毁 Controller，pending/queued/failed 保留
- **页面离开**：Riverpod 3 会暂停不可见 Widget 的 listener；Controller 的 keepAlive 监听不受影响，但 U1 不保证 UI 不可见期间实时刷新，也不做后台确认；pending 不会因此丢失
- **返回页面**：ChatPage 在重新可见时调用 `ChatController.reconcile()`，立即按当前 channel 值清理已确认 pending；后续 `ConversationView` 仍会触发同一清理
- **重置**：debug「重置会话」或 App 重启时 `ref.invalidate(chatControllerProvider)`；Controller 释放后其 channel 监听解除，最后一个监听者移除后 Repository 的流订阅关闭
- **错误**：channel 报错时 Controller 不销毁、pending/queued/failed 保留；`ChatView.syncState` 来自 Repository 的 `ConversationView`，UI 显示同步异常横幅与手动重试
- **无 Widget 订阅**：ChatPage 不直接调用 `watchConversation`，也不创建 `StreamBuilder`
- Repository 与 Controller 的依赖方向：Controller → Repository；Repository 不认识 Controller，也不持有 `ChatState`

**Controller / StreamProvider 暂停、恢复与释放规则**：

| 对象 | 创建时机 | 暂停条件 | 恢复动作 | 释放时机 |
|---|---|---|---|---|
| `chatControllerProvider(id)` | 首次 `ref.watch` / `ref.read` | 无可见 listener 时仅暂停 UI 通知，keepAlive 不释放 | 页面可见时 `reconcile()` | `ref.invalidate`、调试重置、App 退出 |
| `conversationChannelProvider(id)` | Controller `build()` 首次 `ref.listen` | 不暂停：Controller 的 keepAlive 监听使其始终有活跃 listener | 页面可见时 `reconcile()`；`retrySync()` 不重建订阅 | Controller 释放或显式 `ref.invalidate` |
| Repository 事件流 | channel provider 首次建立订阅 | 由 channel provider 暂停/恢复 | channel provider 恢复 | channel provider `ref.onDispose` 时取消 |
| `chatViewProvider(id)` | ChatPage `watch` | 页面不可见 | 页面重建时重新计算 | ChatPage 释放监听后由 Riverpod 处理 |

实现约束：

- Repository 的 `watchConversation` 流由 `conversationChannelProvider`（`StreamProvider`）管理订阅；如内部自建 `StreamController` 或额外订阅，必须在 `ref.onDispose` 中关闭/取消，禁止泄漏
- 不得在 Widget 或 Controller 内再建第二条 Repository 订阅；`ref.listen` 监听的是 channel provider，不是 Repository 原始流
- Controller 必须 keepAlive，channel 由 Controller 的监听保持存活；禁止对 Controller 使用 autoDispose
- Controller 的 keepAlive 监听使 channel 不因页面不可见而暂停，但 U1 不保证后台实时刷新 UI；恢复时先 `reconcile()`，若 `syncState = failed` 则展示手动重试，不自动重建整个 Controller
- 重置顺序：`ref.invalidate(chatControllerProvider(id))` → `ref.invalidate(conversationChannelProvider(id))`；先解除 Controller 监听，再关闭 channel 与 Repository 流，避免悬挂监听
- 任何 `ref.read` / `ref.watch` 都不得在 `await` 之后使用同一个已可能释放的 `ref`；异步回调用 `_disposed` 标志或捕获的依赖，见 4.21

**方法契约**：

| 方法 | 行为 |
|---|---|
| `Future<void> send(String text)` | 忽略空白文本；生成 `clientMessageId` 与负数 seq；在线插 `pending` 并发送，离线插 `queued`；异常时转 `failed` |
| `Future<void> retry(String clientMessageId)` | 找到对应 failed；在线转 `pending`、离线转 `queued`；清除 `sendErrors` 项；复用原 id 与原负数 seq |
| `Future<void> retrySync()` | 调用 `ChatRepository.retrySync(conversationId)`；重置 Repository 退避计数，不改动 pending/queued/failed |
| `void reconcile()` | 页面重新可见时调用；按当前 channel 值清理已确认 pending；若在线则顺带触发 queued flush |
| `Future<void> _flushOutbox()` | 网络恢复时按创建顺序串行发送 queued；失败停止并保留后续 queued；`_flushing` 防重入 |
| `void _pruneConfirmed(List<ChatMessage> formal)` | 正式消息中出现同 id 时，从 `pending` 与 `sendErrors` 删除该项 |

**ID 与临时 seq 分配**：

- `clientMessageId`：`local:<conversationId>:<递增整数>`，同一 Controller 内唯一；U1 不引入额外 UUID 依赖
- 负数临时 seq：同一对话从 -1 开始递减，重试不重新分配
- 两者都只存在于本地，不写入事件、快照或 `lastSeq`；确认后由正式消息替代

**ChatView 展示列表（页面唯一渲染来源）**：

| 字段 | 内容 | 排序 |
|---|---|---|
| `messages` | 正式消息 | 正式 `seq` 升序 |
| `pending` | pending / queued / failed | 负数 seq 降序（-1、-2…，即创建顺序） |
| `sendErrors` | 失败文案 | 按 `clientMessageId` 索引 |
| `syncState` / `retryCount` / `syncError` | 重同步状态与错误 | 来自 `ConversationView`，UI 只读 |
| `displayMessages` | `messages` 后接 `pending` | UI 只遍历该列表 |

- `ChatView` 构造断言 pending 与 messages 的 id 集合不相交
- UI 分支：消息 `syncState = queued` 显示「等待联网」；`pending` 显示「发送中」；`failed` 显示 `sendErrors[id]` 与「重试」；`synced` 正常展示
- 同步状态：`ConversationSyncState.retrying` 显示「正在重新同步」；`failed` 显示 `syncError` 与「重试同步」按钮；`synced` 不显示横幅
- Widget 内不做去重、排序或补拉；展示顺序完全由 `ChatView.displayMessages` 决定

**清理时机总表**：

| 时机 | pending / queued / failed | sendErrors |
|---|---|---|
| 发送成功但未收到确认 | 保留 pending | 不变 |
| 正式消息（事件或快照）出现同 id | 删除该条 | 删除该 key |
| `sendText` 抛异常 | 保留并转 `failed` | 写入文案 |
| 离线发送 | 保留并标为 `queued` | 不写入 |
| 网络恢复 | `queued → pending` 后发送 | 不变 |
| 用户重试 | 在线转回 `pending`，离线转 `queued` | 删除该 key |
| 重同步 | 保留 | 保留 |
| `ConversationUpdated` | 保留 | 保留 |
| 切换对话 | 按 `conversationId` 隔离保留 | 保留 |
| App 重启 / 调试重置 | 清空 | 清空 |

**确认超时边界**：

- U1 不实现确认超时定时器：`sendText` 正常返回后若确认事件迟迟不到，消息保持 `pending`，这是已接受的 Mock 阶段边界
- Mock 必须保证每条 `sendText` 在有限时间内要么产生同 id 的确认事件，要么抛出异常转 `failed`，不允许无限挂起
- 接入真实后端时必须补确认超时与重发策略；届时只改 Repository / 同步引擎，不改 UI

**Mock 要求补充**：

- 调试面板提供「发送失败」开关；开启时 `sendText` 抛异常
- 失败后重试成功，确认事件携带相同 `clientMessageId`，最终只有一条正式消息
- 重同步快照已包含该 id 时，不等待事件，直接清理 pending

### 4.20 运行时校验与 assert 的边界

**原则**：

- `assert` 只用于**开发者不变量**：内部代码构造出的对象必须满足模型约束；违反代表编程错误，debug 下立即失败
- `assert` 在 release 中被移除，**不得**用于校验网络数据、用户输入、权限、幂等或业务前置条件
- 外部数据（事件、快照、邀请结果、卡片动作、Today 数据）必须先经过运行时校验，再构造领域模型
- 运行时校验失败必须返回/抛出类型化错误，并进入明确恢复路径；不得用 `assert` 代替错误处理

**分界表**：

| 场景 | 方式 | 失败处理 |
|---|---|---|
| 模型字段关系（类型、Agent、projectId、状态与 actedAt、集合唯一性） | `assert` | debug 崩溃；release 不依赖 |
| 事件外层与消息内外 `conversationId` / `seq` 一致性 | 运行时校验 | 拒绝事件，记录诊断，触发安全恢复 |
| 快照 `lastSeq`、消息 seq、重复 id、排序 | 运行时校验 + 构造断言 | 拒绝快照，进入重同步；重试耗尽转 `failed` |
| 邀请 `inviteId` 归属、状态、owner、并发 | 运行时校验 + 幂等锁 | 返回 `InviteCannot*`，不构造非法 Conversation |
| 卡片动作是否属于该消息/选项 | 运行时校验 | 拒绝动作并提示；不调用 `copyWith` |
| 用户输入空白、超长、非法字符 | 运行时校验 | 禁用发送或提示；不构造 pending |
| Today 外部数据的 kind/start/end/status | 运行时校验 | 丢弃该条并记录；不进入 DayView |
| `copyWith` 内部状态迁移（终态回退、清空必填） | `assert` | debug 失败；release 由调用方前置校验 |

**实现要求**：

- Repository 在把外部 payload 转为 `ChatEvent` / `ConversationSnapshot` / `ConversationView` 之前完成校验；构造断言是最后一道防线，不是唯一防线
- 定义 `ChatProtocolException`、`SnapshotValidationException`、`SyncInitialLoadException` 等类型化异常，携带 `conversationId`、`seq`、失败字段；日志带 `trace_id`
- 校验失败不得部分应用：要么整条事件/整份快照被拒绝，要么完整应用
- UI 只消费已经过校验的 `ChatView`；Widget 内不重复做协议校验
- 测试拆分：`copy_with_test` 覆盖 assert；`validation_test` 覆盖外部非法 payload、错误类型与恢复路径

### 4.21 离线发送与 Controller 销毁保护

**离线发送策略**：

- `networkStatusProvider` 明确为 `offline` 时：仍创建本地消息，但 `syncState = queued`，**不调用** `sendText`，UI 显示「等待联网」
- `queued` 与 pending/failed 共用负数临时 seq，按创建顺序保留在 `ChatState.pending`
- 网络恢复 `online` 时按创建顺序串行 flush：每次把一条 `queued` 改为 `pending` 并调用 `sendText`；成功后继续下一条，不等待确认
- 发送失败：该条转 `failed` 并停止本轮 flush，后续消息仍保持 `queued`；用户重试或下一次网络恢复再继续，保证顺序
- 不允许并发 flush；用 `_flushing` 单飞标志保护
- `pending` 在发送过程中网络断开：不自动退回 `queued`，按失败处理为 `failed`，由用户重试；避免同一条消息被重复发送
- U1 不做离线持久化：App 重启/调试重置后 queued 丢失；这是已接受的产品边界
- `error` 状态不视为离线：仍尝试发送，失败后转 `failed`

**异步期间 Controller 被销毁**：

- `build()` 内注册 `ref.onDispose(() => _disposed = true)`
- 所有异步方法在第一个 `await` 前捕获 `ChatRepository`、`Clock`、`clientMessageId`、文本等依赖，**不得在 `await` 之后调用 `ref`**
- `await` 返回后先检查 `_disposed`；已销毁则直接返回，不写 `state`、不记录错误
- 发送成功但 Controller 已销毁：不再更新本地 pending；重新创建 Controller 后由 channel 快照恢复正式消息，不会产生重复
- 离线排队期间被销毁：queued 随 `ChatState` 释放而丢失，不做补偿
- `_flushOutbox` 在 `finally` 中释放 `_flushing`；销毁时立即停止循环，不再读取 `state`

---

## 5. 设计系统

### 5.1 浅色令牌（给定值）

| 语义 | 值 | 对比度（对背景） |
|---|---|---|
| 背景 `bg` | #FAF8F4 | — |
| 卡片 `surface` | #FFFFFF | — |
| 描边 `outline` | #E4DED3 | 非文本 |
| 正文 `text` | #1F2328 | 14.9:1 |
| 次要文字 `textMuted` | #5B6168 | 5.9:1 |
| 主色 `primary` | #2F6F62 | 5.5:1 |
| 主色浅底 `primaryContainer` | #E1EFEA | — |
| 主色深字 `onPrimaryContainer` | #245A4F | **6.69:1**（对主色浅底，v2.3 复算修正） |
| Jarvis `jarvis` | #2B3A55 | 10.8:1 |
| 警示 `warning` | #B4540A | 4.7:1 |

### 5.2 深色令牌（推导，待审核）

| 语义 | 值 | 对比度（对深色背景） |
|---|---|---|
| 背景 `bg` | #12100E | — |
| 卡片 `surface` | #1B1917 | — |
| 描边 `outline` | #33302A | 非文本 |
| 正文 `text` | #ECE8E1 | 15.5:1 |
| 次要文字 `textMuted` | #AAA49B | 7.7:1 |
| 主色 `primary` | #7FBFAF | 9.0:1 |
| 主色浅底 `primaryContainer` | #1E3A34 | — |
| 主色深字 `onPrimaryContainer` | #D6EDE6 | 10.0:1（对主色浅底） |
| Jarvis `jarvis` | #9FB0CE | 8.7:1 |
| Jarvis 底 `jarvisContainer` | #1C2637 | — |
| 警示 `warning` | #E08A3C | 7.1:1 |

实现后写单元测试按 WCAG 公式计算 7 组关键配对，低于 4.5 失败。

### 5.3 字号、间距、圆角、触控

| 项 | 值 |
|---|---|
| 页面标题 / 正文 / 小字 / 标签 | 28 / 15 / 12 / 11 |
| 间距刻度 | 4、8、12、16、20、24 |
| 卡片圆角 | 14 / 16 |
| 按钮圆角 | 12 |
| 胶囊 | 999 |
| 最小触控 | 44dp |
| 动画时长 | 120ms / 220ms / 25ms 每字（流式） |

字体使用系统默认中文字体；数值只存在于 `core/theme/tokens.dart`。

### 5.4 对比度测试配对（`color_contrast_test`）

普通文本最低 4.5:1；大号文本（≥18pt 常规或 ≥14pt 粗体）与非文本图形不得套用同一标准。U1 未引入独立的大号文本配色，因此 7 组全部按普通文本 4.5:1 要求。

| # | 前景色 | 背景色 | 实际使用位置 | 最低要求 | 复算值 |
|---|---|---|---|---|---|
| 1 | #1F2328 | #FAF8F4 | 浅色主题正文 / 页面背景 | 4.5:1 | 14.9:1 |
| 2 | #5B6168 | #FAF8F4 | 浅色主题次要文字 / 页面背景 | 4.5:1 | 5.9:1 |
| 3 | #FFFFFF | #2F6F62 | 主色按钮文字 / 主色背景 | 4.5:1 | 5.9:1 |
| 4 | #ECE8E1 | #12100E | 深色主题正文 / 页面背景 | 4.5:1 | 15.5:1 |
| 5 | #AAA49B | #12100E | 深色主题次要文字 / 页面背景 | 4.5:1 | 7.7:1 |
| 6 | #9FB0CE | #1C2637 | 深色 Jarvis 文字 / Jarvis 容器 | 4.5:1 | 6.9:1 |
| 7 | #245A4F | #E1EFEA | 浅色主色浅底上的标签文字 | 4.5:1 | 6.69:1 |

补充约束：

- 第 7 组对应 `onPrimaryContainer` 与 `primaryContainer`，必须与其余 6 组一起断言，不再表述为「可选扩展」
- 测试必须用 WCAG 相对亮度公式计算，不硬编码期望值以外的手算结果；颜色值集中在令牌文件
- 若后续调整配色，先更新本表与测试，再改 UI

---

## 6. 导航外壳与路由

### 6.1 四个 Tab

`StatefulShellRoute.indexedStack`：`/today`、`/chat`、`/tasks`、`/profile`。每个分支独立 Navigator，切换保留状态。任务/我的为「下一阶段」占位。

### 6.2 Chat 路由

```
/chat                                → Friday 主对话
/chat/:conversationId                → 指定对话（主或专题）
/chat/:conversationId?messageId=...  → 打开并滚动到指定消息
/chat/topics                         → 专题列表（按项目分组）
```

- `/chat` 与 `/chat/:conversationId` 共用 `ChatPage`，区别只在解析哪个 Conversation
- `/chat` 不依赖全局 Agent，也不做「最后发言者」判断
- `messageId` 不存在时停在最新消息，不报错

### 6.3 状态保留策略

1. 主对话 → 专题用 `push`，返回栈保留上层页面
2. `ChatSessionStore` 以 `conversationId` 为 key 保存草稿与滚动偏移
3. Tab 切换由 `indexedStack` 保留
4. 紧急提醒作为 Shell 级 Overlay/Dialog，不改变路由，页面不销毁

### 6.4 对话切换器

Chat 页头部提供入口：

- 主对话：列出全部专题（按项目分组）+「返回主对话」
- 专题：同项目其他专题 + 其他项目折叠区 +「返回主对话」

选择后 `push` 对应路由。

---

## 7. Friday 主对话与 Jarvis 专题对话

### 7.1 定位

| | Friday 主对话 | Jarvis 专题对话 |
|---|---|---|
| 归属 | 永远 Friday | 永远 Jarvis |
| 内容 | 日常聊天、临时任务、提醒、日程 | 长期项目、深入研究、备考 |
| 上下文 | 日常上下文 | 仅本专题；同项目专题共享项目资料，不同项目隔离 |
| 深度 | Jarvis 只发短消息、进度、邀请 | Jarvis 做澄清、计划、深度工作 |
| 输入框 | 发给主对话 | 发给当前专题 |

### 7.2 邀请流程

1. Friday 或 Jarvis 在主对话发起 `AgentInviteCard`
2. 卡片展示：发起者、专题名、目标、范围、预期产出、「接受并进入」「暂时不用」
3. `pending`：不创建专题对话，不改变当前页面归属
4. 接受：仓库创建/关联项目与 `topic` 对话 → 卡片 `accepted` + `createdConversationId` → `push` 到专题
5. 拒绝：卡片 `declined`，不创建对话，停留主对话，不修改项目计划
6. 过期：`expired`，按钮禁用

### 7.3 禁止事项

- 禁止按最近发言者切换 Chat 头部
- 禁止全局 `activeAgent`
- 禁止在邀请 pending 时创建专题
- 禁止不同专题共享消息列表
- 禁止前端拼 Prompt 指定 Agent

---

## 8. Today 页

### 8.1 结构与交互

1. 头部：日期星期、按时间问候、进度胶囊、前一天/后一天
2. 晨间简报卡：折叠；正文、一行理由、「调整」
3. 时间线：按 `start` 升序；行 = 时间标签 + 卡片 + 44dp 完成按钮
   - 时间块：标题、来源标签、时长、可压缩提示
   - 提醒：圆点 + 标题，无完成按钮
   - 状态：进行中、已完成、已跳过、待同步；逾期由 `isOverdueAt(Clock.now())` 按类型派生（block 看 end、reminder 宽限 10 分钟、task 看 start），不写入 `status`
4. 手势：左滑完成 / 右滑跳过（撤销）；长按面板（改期、跳过、详情、为什么这样排）；点击详情
5. 晚间复盘卡：晚间时间后出现；勾选清单；提交后小结
6. 未排期区：折叠计数；每项「排进今天」
7. 底部输入条：文本 + 语音（假波形）；发送后进入 **Friday 主对话** 并显示消息
8. 下拉刷新：切换网络状态；空状态「今天还没有安排」+「告诉 Friday」

### 8.2 项目入口

- `TodayItem.projectId != null` 时来源标签可点击
- 0 个专题 → 面板空状态 +「去主对话发起邀请」（不自动创建）
- 1 个专题 → 直接进入
- 多个专题 → 面板列出（名称、目标摘要、最近活动）后选择
- Today 操作不改写任何对话归属；底部输入固定发往主对话

---

## 9. Chat 页

### 9.1 头部

- 主对话：Friday 头像 +「Friday · 日常助理 · 随时待命」
- 专题：Jarvis 色 +「Jarvis · 战略规划」+ 专题名 + 项目名；副标题展示 `goal` 摘要
- 头部信息全部来自 `Conversation`，不读取消息发送者

### 9.2 消息与卡片

- 用户右侧（主色底白字）；Friday 左侧（卡片底）；Jarvis 左侧（Jarvis 浅底 + 描边）
- 主动消息下方理由 +「为什么推给我」→ 面板（触发原因、少打扰、关闭这一类）
- 卡片行为：Confirm / Choice / Memory / PlanProposal 通过 `respondToCard()`；`AgentInviteCard` **只能**通过 `acceptInvite` / `declineInvite`（见 4.18）；ThinkingCard 见 9.4
- 离线：顶部条「离线，消息将在联网后发送」；待发送标记
- **唯一展示来源**：页面只监听 `chatViewProvider`，渲染 `ChatView.displayMessages`；它由 `conversationChannelProvider`（正式状态）与 `chatControllerProvider`（pending/queued/failed / sendErrors）合并而来；不拼接 `conversationProvider`，也不在 Widget 内合并或排序 pending
- **页面恢复**：Chat 页重新可见时调用 `ref.read(chatControllerProvider(id)).reconcile()`；Widget 不直接订阅 Repository 流，也不持有 `StreamSubscription`

### 9.3 流式、pending 与滚动

- Mock 流式：同一 `TextMessage` 多次 `MessageUpsert`，25ms/字；`disableAnimations` 时一次性显示
- 发送：Controller 生成 `clientMessageId` → 创建负数临时 seq 的 `pending`（在线）或 `queued`（离线）消息 → 在线立即调 `sendText`，离线等待网络恢复 flush
- pending 显示在正式消息之后（底部），带「发送中」标记；离线消息标记 `queued` 并显示「等待联网」；发送失败显示 `sendErrors[id]` 与「重试」，重试复用原 `clientMessageId` 与负数 seq
- 网络恢复后按创建顺序自动补发 queued；某条失败时停止本轮补发并保留后续 queued
- 确认后同一 `messageId` 的 `MessageUpsert` 触发 Controller 清理 pending，正式消息按正式 seq 归位且只保留一条
- 重同步时 pending/queued/failed 都不消失；若快照已包含该 id，直接清理 pending 并只显示正式消息
- 首次加载失败（`AsyncError`）显示整页「加载失败」+「重试」，输入条禁用；重试走 `retrySync`，成功后再允许发送
- 同步状态来自 `ChatView.syncState`：`retrying` 显示「正在重新同步」；`failed` 保留最后有效消息并显示 `syncError` 与「重试同步」；`synced` 不显示横幅
- 新消息自动贴底；上翻超过 120dp 显示「新消息」
- 键盘：`resizeToAvoidBottomInset` + `SafeArea`
- 每个 conversation 独立滚动与草稿

### 9.4 ThinkingCard

- 仅阶段：正在思考 / 正在整理资料 / 正在生成计划 / 正在执行任务
- 不显示任何预计完成时间或倒计时
- 不确定进度动画；文案注明「由 Jarvis 处理中」
- U1 为 Mock 状态流转；真实进度必须来自后端事件

### 9.5 输入条

文本、语音、发送；快捷词「加个提醒 / 排一下今天 / 你记得我什么」；「＋」拍照与相册面板（仅界面）。

---

## 10. 全局紧急提醒

### 10.1 组成与职责

- `PriorityAlert`：提醒数据（原因、截止、操作、状态）
- `AlertResumeContext`：弹窗前的页面恢复信息（路由、对话、消息、滚动、草稿）
- `UrgentAlertController`：Shell 持有 `(alert, resumeContext)`，负责展示与恢复

### 10.2 交互流程

1. 用户正在任意页面（Today、主对话、专题对话）
2. Shell 收到 `PriorityAlert` → 采集 `AlertResumeContext`：
   - `previousRoute`（当前路由）
   - `conversationId`（Chat 页时）
   - `messageId`（深链定位时）
   - `scrollOffset` 与 `draftText`（从 `ChatSessionStore` 读取）
3. 以 App 级 Overlay/Dialog 展示，不改变路由，不关闭对话，不插入消息列表
4. 用户点击操作或关闭：
   - 调 `handleAlert` / `dismissAlert`
   - 处理动作时把实际执行的 `actionId` 写入 `handledActionId`，状态置 `handled`
   - 关闭覆盖层，按 `resumeContext` 恢复页面
   - 恢复滚动位置与草稿
5. 普通提醒不弹窗，只在页面内展示非打断式提示

### 10.3 U1 边界

- 仅 App 内 Mock 弹窗；调试面板提供「模拟紧急提醒」
- 不实现系统通知、后台推送、权限、优先级判定

---

## 11. 调试面板

入口：debug 构建下长按 Today 页标题。

| 开关 | 选项 |
|---|---|
| 模拟时间 | 08:00 / 10:20 / 21:30 |
| 网络状态 | 在线 / 离线 / 同步中 / 错误 |
| 数据集 | 空 / 正常 / 满载 50 |
| 主题 | 浅色 / 深色 / 跟随系统 |
| 文字缩放 | 1.0 / 1.25 / 1.5 |
| 模拟紧急提醒 | 触发一次 `PriorityAlert`（任意页面） |
| 模拟邀请 | 向主对话插入 pending `AgentInviteCard` |
| 模拟发送失败 | 下一次 `sendText` 抛异常，消息转 `failed`，用于验证重试 |

---

## 12. 假数据

### 12.1 对话与项目

| 项目 | 专题对话 | 说明 |
|---|---|---|
| — | Friday 主对话 | 默认入口 |
| CFA 备考 | 「会计科目难点」 | 目标：三周完成 FRA 会计部分；范围：折旧、摊销、减值 |
| CFA 备考 | 「数量方法刷题」 | 同项目第二专题，验证多专题 |
| 个人知识库 | 「读书笔记整理」 | 不同项目，验证隔离 |

- 主对话包含：Jarvis 简短进度摘要、`ConfirmCard`、`ChoiceCard`、`MemoryConfirmCard`、`PlanProposalCard`、pending `AgentInviteCard`
- 「会计科目难点」包含：`ChoiceCard`、`ThinkingCard`、`PlanProposalCard`
- 其他专题各含少量互不相同的消息

### 12.2 Today（正常数据集）

| 时间 | 条目 | 类型 | 状态 | 项目 |
|---|---|---|---|---|
| 08:30 | 回复客户邮件 | block | done | — |
| 09:30–11:00 | 写季度总结 | block（可压缩） | planned | — |
| 11:30 | 给客户回电话 | reminder | planned | — |
| 14:00 | 复习折旧与摊销（CFA · 会计 · 第 3 章） | block | planned | CFA 备考 |

未排期 2 项：「整理报销单」「预约体检」。

### 12.3 紧急提醒样例（与 Today 时间一致）

「11:30 的客户电话还有 10 分钟」→ 在任意页面（含专题对话）触发弹窗，操作为「知道了 / 改期」；关闭后回到原页面，滚动与草稿不变。

### 12.4 消息衔接演示数据

- 打开「会计科目难点」时，`loadConversationSnapshot` 延迟 300ms
- 延迟期间仓库推送一条新的 `TextMessage` 与一次 `ConversationUpdated`（`seq` 大于快照 `lastSeq`）
- 合并后消息只出现一次，对话信息为最新
- 另提供一条重复 `messageId`、一条旧 `seq`、一条 `seq` 缺口事件，用于去重、过期忽略与重同步演示
- 提供「发送 pending → 触发缺口重同步 → 服务端确认同一 `clientMessageId`」的演示数据
- 提供「发送失败 → failed → 重试 → 确认」的演示数据，确认后 pending 与 sendErrors 同时清理

---

## 13. 测试方案

### 13.1 测试矩阵

| 层级 | 文件 | 覆盖 |
|---|---|---|
| 单元 | `conversation_test` | 主对话唯一、专题归属、项目隔离 |
| 单元 | `message_merge_test` | 快照建立 `baselineSeq` 与 `currentSeq`；`seq <= baselineSeq` 按快照覆盖忽略且不判冲突；快照刚建立时 `seq == currentSeq` 不误判头部冲突；摘要只对 `(baselineSeq, currentSeq]` 建立；摘要窗口 200 条淘汰后旧事件按过期处理；重同步清除旧摘要；先订阅后快照；初次 buffer 缺口、持续监听缺口、重同步后仍缺口；重同步期间事件不丢；`seq < currentSeq` 的迟到事件按过期忽略并记录 `late_conflict`；`seq == currentSeq` 同摘要忽略、不同摘要触发重同步；buffer 内同 seq 冲突；conversationId 不匹配、内外 seq 不一致；混合事件最终状态；事件队列串行、buffer 原子切换、切换瞬间到达事件、旧 generation 快照晚到、队列溢出重同步；重同步最多 3 次、退避 300ms/600ms 且带 jitter、失败后不再自动重试；jitter 用固定种子注入 `Random`，断言每次延迟落在 ±20% 区间且不超过 1200ms；首次加载连续失败 3 次返回 `AsyncError`，手动重试成功；`late_conflict` 不触发重试 |
| 单元 | `conversation_event_test` | `ConversationUpdated` 更新对话；与 `MessageUpsert` 混合按 seq 应用；两类事件共用统一判定规则；快照中 conversation 与 messages 一致；事件/快照 `conversationId`、`seq`、`lastSeq`、排序与唯一性断言 |
| 单元 | `local_message_test` | pending 由 Controller 创建并持有；failed 保留原 id 与原负数 seq；重试复用同一 id/seq 并回到 pending；`ChatState` 只接受 pending/queued/failed 且负数 seq、按负数 seq 降序、sendErrors 只指向 failed；`ChatState.copyWith` 校验新值；Repository 不返回 pending；`chatViewProvider` 合并正式消息与 pending 且 id 不重复；`ChatView.displayMessages` 顺序为正式后 pending；确认后同时清理 pending 与 sendErrors；多条 pending 互不覆盖；重同步后 pending/failed 仍保留；快照已含该消息时不重复插入；`ChatState` 按 conversationId 隔离；页面离开后返回仍保留，`reconcile()` 立即清理已确认项；离线发送标 queued、恢复后按顺序串行 flush、失败停止并保留后续 queued；Controller 销毁后异步返回不写 state |
| 单元 | `copy_with_test` | 不传保持原值；显式 null 清空允许字段；非空字段不可清空；各模型行为一致；逐条覆盖 4.2.1 业务不变量总表（Conversation 类型/Agent/项目/时间、主对话 projectId 不可设置、ChatMessage seq 与 syncState、ConfirmCard 状态与 actedAt、ChoiceCard 答案属于选项、MemoryConfirmCard items 非空且 id 唯一、PlanProposalCard 终态不回退、AgentInviteCard 状态与 createdConversationId 及 accepting、TodayItem 时间关系/only task 可清空 start、PriorityAlert handledActionId、AlertResumeContext 字段联动）；每个集合字段写入抛 `UnsupportedError`；非法构造在 debug 下抛 `AssertionError`，非法状态转换在 debug/release 均抛 `StateTransitionException` |
| 单元 | `validation_test` | 外部非法 payload 的运行时校验：事件 conversationId/seq 不一致、快照 lastSeq/重复 id/排序非法、邀请归属与状态非法、卡片动作不属于消息/选项、TodayItem kind/start/end 非法；返回类型化异常而非 assert；失败不部分应用 |
| 单元 | `invite_test` | 接受幂等、重复接受返回同一对话、并发接受只创建 1 个对话与 1 个项目、重复请求返回同一 createdConversationId、拒绝/过期/已接受不可接受、接受拒绝互斥、owned by user |
| 单元 | `today_controller_test` | 完成/跳过/改期/排进今天、乐观更新与回滚；`overdue` 按类型派生：block 以 end、reminder 以 start+10min、task 以 start 判断；无 start task 与 done/skipped 永不逾期；task 可清空 start，block/reminder 不可 |
| 单元 | `chat_controller_test` | `chatControllerProvider` 按对话隔离且保持 keepAlive；family 参数由构造函数注入、`build()` 无参；发送→pending→failed→重试→pending→确认清理；failed 不因重同步或 `ConversationUpdated` 消失；`sendErrors` 写入与清除；同步错误时 Controller 不销毁、`retrySync` 重置退避；离线 queued → online 串行 flush；flush 单飞；异步返回时 Controller 已销毁则不写 state；卡片动作、草稿与滚动 |
| 单元 | `mock_repositories_test` | 按 conversationId 返回、专题列表、项目分组、延迟事件、重复事件、发送失败开关与失败后确认；fake sleeper 验证重试延迟序列 |
| 单元 | `format_clock_test` | 问候语、时长、星期、Clock |
| 单元 | `color_contrast_test` | 5.4 节 7 组配对按 WCAG 公式计算 ≥ 4.5:1；含 onPrimaryContainer 6.69:1 断言 |
| 组件 | `shell_test` | 4 Tab 状态、`/chat/:id` 深链、`messageId` 定位 |
| 组件 | `conversation_header_test` | 主对话永远 Friday；专题显示 Jarvis + 专题 + 项目；Jarvis 在主对话发言不改头部 |
| 组件 | `conversation_switch_test` | 主 ↔ 专题、专题 ↔ 专题、消息不串线、返回状态保留 |
| 组件 | `agent_invite_test` | pending/接受/拒绝/过期；双击只创建一次；响应丢失后重试返回原对话；终态不显示「请重试」；接受后进入；拒绝留主对话 |
| 组件 | `today_page_test` | 滑动完成/跳过与撤销、状态外观（含派生 overdue）、空/离线、晚间复盘、项目入口 |
| 组件 | `chat_page_test` | 卡片动作（邀请卡片经专用接口）、流式完成、pending/queued/failed 与重试文案、确认后只保留一条、首次加载失败整页错误、同步失败横幅与手动重试、滚动、离线横幅；只渲染 `chatViewProvider` 的 `displayMessages` |
| 组件 | `urgent_alert_test` | 专题内触发 → 不关闭对话 → 处理/关闭 → 回原专题 → 滚动与草稿保留 |
| 组件 | `urgent_alert_today_test` | Today 页面触发 → 弹窗 → 关闭 → 回到 Today → 页面状态不变 |
| 组件 | `text_scale_test` | 1.5 倍下 Today、主对话、专题、邀请卡无溢出 |

### 13.2 验证命令

```powershell
# 所有 Flutter 命令必须在 mobile/ 下执行；不要假设当前目录是仓库根
Set-Location "E:\F&J\FJ v1\mobile"

$env:FLUTTER_ROOT="D:\flutter"
$env:ANDROID_HOME="E:\AutoPunch\.android-sdk"
$env:ANDROID_SDK_ROOT="E:\AutoPunch\.android-sdk"
$FLUTTER="D:\flutter\packages\flutter_tools\bin\flutter_tools.dart"
$DART="D:\flutter\bin\cache\dart-sdk\bin\dart.exe"

& $DART $FLUTTER --no-version-check analyze
& $DART format --output=none --set-exit-if-changed lib test
& $DART $FLUTTER --no-version-check test
& $DART $FLUTTER --no-version-check build apk --debug

# 校验 APK 的 minSdk 实际为 26
& "$env:ANDROID_HOME\build-tools\36.0.0\aapt.exe" dump badging `
  "build\app\outputs\flutter-apk\app-debug.apk" |
  Select-String "sdkVersion"
```

说明：

- 命令必须在 `mobile/` 内执行：`pubspec.yaml`、`lib/`、`test/`、`android/` 都在该目录；在仓库根执行会找不到工程
- `aapt dump badging` 必须输出 `sdkVersion:'26'` 与 `targetSdkVersion:'36'`；输出其他值视为构建配置未生效
- `Set-Location` 每次新开终端都要执行；脚本或 CI 也要显式切换，不依赖调用者当前目录
- `dart format` 直接使用 Dart SDK 可执行文件；`flutter_tools` 没有 `format` 子命令
- `--output=none` 只检查不改写，配合 `--set-exit-if-changed` 用于验收
- Flutter 测试目录固定为 `mobile/test/`（与 `flutter create` 默认一致，单数），不使用 `tests/`；后端测试目录 `tests/` 不受影响
- `flutter test` 默认运行 `test/` 下的全部测试

后端回归（在仓库根执行；路径含 `&` 与空格）：

```powershell
# 后端命令在仓库根执行；若上一步在 mobile/，先切回根目录
Set-Location "E:\F&J\FJ v1"

# 1) 兼容检查：确认 WSL 支持 --cd
wsl --version
wsl -d Ubuntu --cd "/mnt/e/F&J/FJ v1" -- bash -lc "pwd"

# 2) --cd 可用时
wsl -d Ubuntu --cd "/mnt/e/F&J/FJ v1" -- bash -lc "uv run ruff check app tests scripts && uv run pytest -q"

# 3) 若 --cd 不可用（旧版 WSL 报 Invalid command line option），使用 fallback
wsl -d Ubuntu -- bash -lc "cd '/mnt/e/F&J/FJ v1' && uv run ruff check app tests scripts && uv run pytest -q"
```

说明：

- `--cd` 依赖较新的 WSL；先跑 `wsl --version` 与 `pwd` 检查，输出 `/mnt/e/F&J/FJ v1` 才可直接使用
- 兼容检查失败时不修改系统 WSL，直接用 fallback；fallback 的 `cd` 在 bash 内执行，路径用单引号包裹，`&` 与空格不会破坏命令
- 两种写法都必须整体给 bash 命令加双引号；不要在 PowerShell 双引号里用反斜杠转义空格
- WSL 发行版名以 `wsl -l -v` 实际输出为准；本机为 `Ubuntu`

### 13.3 截图与存放

- 主对话浅/深色
- 专题对话浅/深色（含 Jarvis 头部与专题信息）
- 邀请 pending 与已接受
- 紧急提醒覆盖在专题对话上
- 紧急提醒覆盖在 Today 上
- Today 浅/深/空/离线
- 调试面板

截图放 `mobile/screenshots/`，使用虚构数据，按 15.3 定案提交进仓库。

---

## 14. U1 与后续阶段边界

### 14.1 U1 真正实现（前端）

- Flutter 工程、目录、设计令牌与浅深主题
- 4 Tab 外壳与深链路由
- Today 页全部交互（含项目入口）
- Chat 页：Friday 主对话 + Jarvis 专题对话 + 切换器
- Conversation、7 类消息、`AgentInviteCard`、`PriorityAlert`、`AlertResumeContext` 完整定义
- 多会话仓库接口与 Mock；统一事件序列（消息 + 对话更新）、无遗漏合并、缺口恢复、快照基线与摘要窗口、最多 3 次重同步与退避
- `chatControllerProvider` / `ChatState` / `ChatView`：Riverpod 3.5 family 写法、pending/queued/failed 的创建、离线补发、失败、重试、确认清理与唯一展示列表
- 业务不变量在构造与 `copyWith` 的 assert 落地；外部数据运行时校验（4.20）
- 所有集合字段不可变；`ChatState.copyWith` 显式校验
- 本地临时消息与正式 seq 的边界处理
- 邀请幂等流程（含并发接受）
- Shell 级紧急提醒与页面恢复
- `android/app/build.gradle.kts` 落实 minSdk 26 / targetSdk 36
- 单元、组件、对比度、缩放测试

### 14.2 U1 仅 Mock

- 消息发送与流式
- 邀请后的项目/专题创建
- 项目知识、项目记忆、项目进度
- 紧急提醒来源与优先级
- 网络与同步状态
- Today 数据与简报

### 14.3 U1 明确不做

- 真实 Agent/Coordinator/模型路由、真实流式
- 数据库读写、真实项目知识库
- 系统通知、后台推送、通知权限
- Jarvis 重规划、周复盘、长期执行
- 任务页/我的页内容、日程页、记忆中心、引导
- iOS / HarmonyOS 原生
- 任何后端代码改动

### 14.4 验收

1. 在 `mobile/` 下执行 `analyze` / `format` / `test` / `build apk --debug`，全部通过
2. 真机验收记录（**尚未执行，标记为待验收**）：
   - 设备型号：Mate 70
   - 实际系统名称与版本号（以设备「关于手机」为准，例如 HarmonyOS 4.3.0）
   - APK 是否安装成功
   - 应用是否正常启动
   - 核心交互是否完成：主对话发送、接受邀请、专题切换、Today 手势、紧急提醒恢复
   - 结论仅针对该设备该版本，不外推 Mate 70 全系或所有 HarmonyOS 版本
3. 模拟器可安装运行
4. 主对话接受邀请 → 专题 → 切换另一专题 → 返回主对话，不串线
5. 专题内与 Today 页面分别触发紧急提醒，处理后回到原页面，滚动与草稿保留
6. 消息与对话更新均无遗漏、无重复；快照基线覆盖的事件被忽略；旧事件、重复事件、同 seq 冲突按规则处理
7. 发送 pending/queued → 失败转 failed → 重试 → 重同步 → 服务端确认，只有一条消息且按正式 seq 归位；离线队列联网后按顺序补发
8. 邀请重复点击/并发只创建一个专题
9. 浅/深色 7 组对比度断言通过，截图齐全
10. `aapt dump badging` 输出 `sdkVersion:'26'`、`targetSdkVersion:'36'`
11. 外部非法事件/快照/Today 数据被运行时校验拒绝并返回类型化错误，未部分写入状态
12. 首次加载失败 3 次显示 AsyncError，输入禁用且可手动重试；事件队列与 buffer 原子切换有测试
13. 非法状态转换在 release 下仍抛 `StateTransitionException`
14. 后端 `ruff` 与 `pytest` 通过

---

## 15. 风险、假设与待确认

### 15.1 风险与对策

| 风险 | 对策 |
|---|---|
| `gradlew.bat` 补丁被重新生成覆盖 | README 记录；不重新生成 `android/` |
| `flutter.bat` 挂起 | 统一用 `dart flutter_tools.dart` |
| 首次构建网络失败 | 文档记录代理命令 |
| HarmonyOS 兼容性 | 纯 Flutter Android APK；真机验收记录实际系统名称与版本，结论不外推全系；不升级用户设备系统 |
| 文字缩放溢出 | 1.5 倍专项测试 |
| 会话切换状态丢失 | `ChatSessionStore` + push 导航 |
| 消息遗漏/重复 | 先订阅后快照 + seq 合并 + 缺口重取 |
| 邀请重复创建 | inviteId 幂等表 + UI 处理中状态 |
| 依赖版本漂移 | 精确版本 + 提交 lock + 升级后全量回归 |
| Riverpod / go_router API 差异 | 按锁定版本编写；family Notifier 用构造函数参数 + `build()` 无参；关闭 channel provider 自动重试 |
| 重同步无限循环 | 最多 3 次尝试 + 退避 + 最终 `failed` + 手动重试 |
| minSdk 被 Flutter 默认值覆盖 | `build.gradle.kts` 显式 26，构建后用 `aapt dump badging` 校验 |

### 15.2 假设

1. U1 单用户；主对话唯一；专题 3 个（Mock）
2. Jarvis 在主对话只发短消息与邀请
3. 同项目专题共享资料属于后端职责；前端按 projectId 分组与隔离
4. Mock 数据不持久化，热重启恢复
5. 前一天/后一天用不同数据集演示，不做真实日期推算
6. 语音、拍照、相册仅界面
7. `agent_invite` / `priority_alert` / `conversation` 后端协议未定义，当前字段为前端提案
8. `ThinkingCard` 阶段与动画均为 Mock
9. 真机测试尚未执行；交付前必须补记录，未完成时验收状态为「待验收」，不得写成已通过
10. 应用仅在 Android 兼容层运行，不使用 HarmonyOS 原生能力
11. `conversationChannelProvider` 由 Controller 的 keepAlive 监听保持存活，不因页面不可见而暂停；U1 不保证 UI 不可见期间实时刷新，返回页面时通过 `reconcile()` 与后续事件完成确认清理，pending 不丢失

### 15.3 已定案与剩余待确认

**已定案（v2.4.3 关闭）**：

| 事项 | 结论 |
|---|---|
| 包名 | U1 保持 `com.butler.mobile` + Dart 包名 `mobile`；改名属于后续独立迁移，不在本阶段 |
| 截图 | 提交 `mobile/screenshots/` 下的指定截图，使用虚构数据 |
| 邀请入口 | U1 只做「调试面板插入 + 主对话预置」，不增加其他入口 |
| 报告位置 | 保留 `docs/mobile-u1-technical-plan.md` |
| 初版日期 | 以 2026-11-11 为准；初版标注的 2026-11-12 为笔误 |

**v2.4.4 追加定案**：

| 事项 | 结论 |
|---|---|
| channel 生命周期 | Controller keepAlive 监听，不暂停；页面返回时 `reconcile()` |
| 确认超时 | U1 不实现，列为已知边界；Mock 保证有限时间内确认或抛错 |
| `retrySync` | 不重建订阅；重置退避、清空旧队列后重新取快照 |
| 同步引擎 | 全部规则集中到 `ConversationSyncEngine` |
| 深色令牌 | 按 5.2 表实现，批次 10 截图验收 |

**仍待确认**：

（无；v2.4.4 起没有阻塞编码的产品决策）

---

## 16. 执行批次

| 批次 | 内容 | 结束验证 |
|---|---|---|
| 1 | 仓库准备、规则文件、`.dockerignore`、`.gitattributes`、gradlew 补丁、`build.gradle.kts` 的 minSdk 26 / targetSdk 36 | 后端 ruff + pytest；analyze 通过；APK sdkVersion 26 |
| 2 | 令牌、主题、strings、Clock、format、对比度测试 | 对比度测试通过 |
| 3 | 全部领域模型与仓库接口（含事件、快照、邀请结果、copyWith 约定、构造/copyWith assert、集合不可变） | analyze 零告警；非法状态断言测试通过 |
| 4 | Mock 仓库 + `ConversationSyncEngine` + `chatControllerProvider` / `ChatState`：主对话、3 专题、2 项目、统一事件序列合并、快照基线、单队列串行与 buffer 原子切换、重试退避、运行时校验、离线队列、本地消息回填、失败重试、并发邀请、提醒 | `message_merge_test` / `conversation_event_test` / `local_message_test` / `validation_test` / `chat_controller_test` / `invite_test` 通过 |
| 5 | shell、路由、4 Tab、深链、会话状态存储 | `shell_test` 通过 |
| 6 | Today 页全部交互 + 项目入口 | 组件与缩放测试 |
| 7 | Chat 页：主/专题、切换器、卡片、流式、草稿、离线 queued、ConversationUpdated 展示 | `chat_page_test` / `conversation_*` |
| 8 | 邀请流程与紧急提醒（Chat + Today） | `agent_invite_test` / `urgent_alert*` |
| 9 | 调试面板 | 开关生效 |
| 10 | 全量检查、截图、汇报 | 全部命令通过；aapt 校验 minSdk/targetSdk；后端回归 |

---

## 附录 A：修订说明

### A.0 v2.4.3 修订说明

1. **AsyncValue 与 Riverpod API**：`valueOrNull` 改为 `AsyncValue.value`；新增 API 对照表，覆盖 family Notifier、`value`、`whenData`、`retry`、`keepAlive`、`ref.listen`、`ref.invalidate` 与暂停恢复。
2. **生命周期**：新增 Controller / StreamProvider / Repository 流的创建、暂停、恢复、释放表；明确重置顺序与 `reconcile()`。
3. **事件队列**：新增单队列串行、同步应用段、`syncGeneration`、buffer 原子切换、1000 条上限、溢出重同步与失败后停止消费。
4. **jitter 与首次加载失败**：固定种子 `Random` 断言 ±20% 区间与 1200ms 上限；首次加载 3 次失败返回 `AsyncError`，输入禁用、手动重试。
5. **TodayItem overdue**：改为分类型计算：block 看 end、reminder 看 start+10min、task 看 start；无 start task 与 done/skipped 不逾期。
6. **剩余不变量**：补 ChoiceCard 选项非空唯一、ChoiceAction skipped/option、AlertAction id 唯一、DayView 零点/排序/brief、ChatView 同步状态与 sendErrors。
7. **release 转换保障**：新增 `StateTransitionException`；ConfirmCard、ChoiceCard、PlanProposalCard、AgentInviteCard、TodayItem、TextMessage 的 copyWith 增加运行时检查，不依赖 assert。
8. **离线与销毁**：新增 `SyncState.queued`、联网串行 flush、失败停止保留顺序；Controller `_disposed`、`_flushing` 与 await 后不写状态。
9. **15.3 定案**：包名、截图、邀请入口、报告位置、初版日期关闭；仅保留深色令牌视觉验收。

### A.1 v2.4.2 修订说明

1. **Riverpod 3.5.0 family 写法修正**：`ChatController` 改为构造函数接收 `conversationId`、`build()` 无参；明确不使用已移除的 `FamilyNotifier` 与 `build(String)` 写法；关闭 `conversationChannelProvider` 的 provider 自动重试，避免与 Repository 退避叠加。
2. **运行时校验与 assert 分界**：新增 4.20，assert 只校验开发者不变量；外部事件、快照、邀请、卡片动作、Today 数据必须运行时校验并返回类型化错误，失败不部分应用。
3. **重同步重试上限与退避**：最多 3 次尝试；重试前 300ms / 600ms、±20% jitter；失败保留最后有效数据并进入 `failed`；手动重试重置周期；`late_conflict` 不触发重试。
4. **主对话 projectId**：`Conversation.copyWith` 增加 `main → projectId == null` 断言；可空字段表改为 main 不可设置、topic 不可清空。
5. **TodayItem 修正**：`TodayItemStatus` 移除 `overdue`，改为 `isOverdueAt(now)` 派生；只有 `task` 允许清空 `start`，block/reminder 必须非空；end/durationMin 仅 block 可用。
6. **遗漏不变量与集合不可变**：补齐 ChatEvent、MessageUpsert、ConversationUpdated、ConversationSnapshot、ConversationView、ChatView、ChatState、Brief、DayView 的断言；所有集合字段复制为 `List.unmodifiable` / `Map.unmodifiable`；`ChatState.copyWith` 显式校验新值。
7. **Controller 与订阅生命周期**：明确创建、唯一 channel 监听、keepAlive、页面离开暂停、返回后清理、重置销毁、错误不销毁、无 Widget 级订阅。
8. **创建命令与 minSdk**：创建改用 `dart flutter_tools.dart create`；`android/app/build.gradle.kts` 显式 `minSdk = 26`、`targetSdk = 36`、`compileSdk = 36`；增加 `aapt dump badging` 校验。

### A.2 v2.4.1 修订说明

1. **快照基线修复**：新增 `baselineSeq`（最近快照 `lastSeq`）与 `currentSeq`；摘要只对 `(baselineSeq, currentSeq]` 建立；`seq <= baselineSeq` 按快照覆盖直接忽略，解决「快照刚建立时同 seq 无法判定重复/冲突」的矛盾；三阶段重同步均重设基线并清空旧摘要。
2. **ChatController 完整定义**：新增 4.19，定义 `chatControllerProvider`、`ChatState`、`ChatView.sendErrors` / `displayMessages`；明确发送、失败、重试、确认清理、重同步保留、切换对话隔离与 keepAlive 的生命周期。
3. **业务不变量落地**：Conversation、ChatMessage、ConfirmCard、ChoiceCard、MemoryConfirmCard、PlanProposalCard、AgentInviteCard、TodayItem、PriorityAlert、AlertResumeContext 全部在构造函数与 `copyWith` 内写 assert；新增逐模型测试映射与 `const` 取舍规则；`PriorityAlert` 增加 `handledActionId` 使「handled 必须有动作」可校验。
4. **pending / failed 与负数 seq**：pending 与 failed 都使用负数临时 seq、都不进入正式序列；failed 保留原 id 与原 seq，重试只改 `syncState`；新增状态机与清理时机总表。
5. **命令目录**：13.2 所有 Flutter 命令先 `Set-Location "E:\F&J\FJ v1\mobile"`，并说明在仓库根执行会找不到工程。
6. **WSL 兼容检查**：13.2 增加 `wsl --version` 与 `--cd` 的 `pwd` 探针，失败时退回 `bash -lc "cd '...' && ..."`。
7. **测试补强**：`message_merge_test` 增加基线、快照覆盖、`seq == currentSeq` 不误判、摘要窗口 200 条淘汰、重同步清摘要；`local_message_test` / `chat_controller_test` 增加 failed、重试、确认清理与展示列表顺序；`copy_with_test` 增加非法构造断言。

### A.3 v2.4 修订说明

1. **过期与冲突判定统一**：`seq < currentSeq` 一律按过期忽略，摘要不同只记 `late_conflict`、不回滚不重同步；`seq == currentSeq` 同摘要去重、不同摘要触发重同步；buffer 内同 seq 冲突单独判定；引入最近 200 个 seq 的事件摘要与淘汰规则。
2. **pending 归属统一**：明确 Controller 创建、持有、合并 pending；Repository 只维护正式状态，不创建/存储/返回 pending；新增 `ChatView` 与 `chatViewProvider` 作为唯一展示来源；重同步后由 Controller 重新合并。
3. **业务不变量总表**：覆盖 Conversation、ChatMessage、ConfirmCard、ChoiceCard、MemoryConfirmCard、PlanProposalCard、AgentInviteCard、TodayItem、PriorityAlert、AlertResumeContext，并写入构造/copyWith 的 assert 与测试要求。
4. **命令与目录修正**：`dart format --output=none --set-exit-if-changed` 替代错误的 `flutter_tools format`；WSL 改用 `--cd` 指定工作目录；明确 Flutter 测试目录为 `mobile/test/`（单数）。
5. **对比度统一为 7 组**：新增 `onPrimaryContainer` / `primaryContainer` 为第 7 组，全文「6 组」表述改为「7 组」，全部必须断言。
6. **seq 注释与接口约束**：`ChatMessage.seq` 注明正式事件序号与 pending 负数临时值的区别；4.16 接口约束扩展到 9 条，覆盖 `clientMessageId`、pending 归属、快照一致性、邀请专用接口。

### A.4 v2.3 修订说明

1. **事件序号三分支**：新增统一事件应用规则（`<=` 忽略、`== +1` 应用、`> +1` 重同步），明确初次合并、持续监听、重同步三阶段共用；补充初次 buffer 缺口示例。
2. **事件一致性**：新增 conversationId、消息内外 seq、对话归属校验；同 seq 冲突按协议异常处理并触发安全恢复；诊断信息记录要求。
3. **clientMessageId**：`sendText` 增加 `clientMessageId`；Controller 生成并创建 pending，Repository 用于 Mock 发送与确认；失败重试复用原 id；禁止重复创建。
4. **重同步保留 pending**：快照只重建正式消息，pending 保留并按 messageId 合并；快照已包含时转确认而非重复插入。
5. **copyWith 完整化**：新增可空字段清单（模型 / 是否可改 / 是否可清空 / 约束）；补充 Conversation、AgentInviteCard、ConfirmCard、MemoryConfirmCard 的业务不变量与 assert 约定。
6. **依赖版本表述**：区分「已验证基线」与「待安装验证的目标版本」；删除「修订日最新稳定版为准」；升级需批准并全量回归。
7. **对比度修正**：`onPrimaryContainer` 复算为 6.69:1；浅色正文 14.9、次要 5.9、主色 5.5；新增 5.4 节 7 组测试配对与使用位置。
8. **真机验收**：改为记录实际系统名称与版本、安装与核心交互结果；标记「待验收」，不外推全系兼容。
9. **数据源与接口职责**：明确 `conversationChannelProvider` 为 Chat 唯一实时来源；删除 `InviteAction`，邀请只走 `acceptInvite` / `declineInvite`，`respondToCard()` 拒绝邀请卡片。
10. **测试与批次**：扩充 `message_merge_test`、`local_message_test`、`copy_with_test`、`chat_page_test`；批次 4 验证项同步。

### A.5 v2.2 修订说明

1. **统一会话事件序列**：`ChatEvent` 基类增加 `conversationId`；`MessageUpsert` 与 `ConversationUpdated` 共用同一 `seq` 序列；未来事件类型必须推进序列，业务效果可安全忽略；`ConversationSnapshot` 增加 `conversation` 字段，`lastSeq` 明确为「快照已反映所有 `seq <= lastSeq` 事件后的状态」；4.17 合并算法重写，补齐混合事件、缺口重取期间事件暂存；新增 `ConversationView` 供 provider 使用。
2. **本地临时消息边界**：正式 `seq` 只由仓库分配；负数临时 seq 不参与连续性检查、不写入 `lastSeq`、不进入快照；确认时通过同一 `messageId` 回填并归位，避免重复展示；明确 pending 消息排序。
3. **并发接受幂等**：补充以 `inviteId` 为锁键的串行/原子流程、项目与对话各最多创建一次、重复请求返回同一 `createdConversationId`、网络重试语义、终态不按网络失败处理。
4. **copyWith 清空语义**：新增 4.2.1 约定，使用文件级哨兵 `unset`；`Conversation.projectId/projectTitle`、`ConfirmCard.actedAt`、`ChoiceCard.answer`、`AgentInviteCard.createdConversationId`、`TodayItem.start` 全部改为可显式清空。
5. **职责边界**：4.17 增加 Repository / Controller / UI 三层职责表，明确同步逻辑不得散落在 Widget。
6. **测试与批次**：新增 `conversation_event_test`、`local_message_test`、`copy_with_test`，扩充 `message_merge_test`、`invite_test`、`agent_invite_test`；批次 3、4、7 同步更新。
7. **日期说明**：v2.2 修订日期为 2026-11-11；初版标注的 2026-11-12 保留原样，并明确标注来源未确认，不改写历史日期。
8. **文档版本**：标题与版本历史升级为 v2.2。

### A.6 v2.1 修订说明

1. **领域模型补全**：新增完整枚举、构造函数、`copyWith` 约定；补齐 `MemoryCandidateItem`、`PlanChange`、`AlertAction`、`CardAction`、`ChatEvent`、`ConversationSnapshot`、`InviteAcceptResult` / `InviteDeclineResult` 等此前引用但未定义的类型。
2. **Agent 类型分离**：`ChatSender` 仅含 user/friday/jarvis；新增 `ConversationAgent`（friday/jarvis）；`AgentInviteCard.initiatorAgent/targetAgent` 改用 `ConversationAgent`。
3. **紧急提醒拆分**：`PriorityAlert` 移除 `interruptedConversationId`；新增 `AlertResumeContext`，由 Shell 采集与恢复；全文统一表述。
4. **消息无遗漏机制**：新增 `ConversationSnapshot`、`seq`、先订阅后快照、buffer 合并、缺口重取、messageId upsert、流式更新同一条、排序规则；Mock 必须体现。
5. **邀请幂等**：新增唯一性范围、状态规则表、并发处理、`accepting` 字段、`InviteRejectReason.alreadyAccepted`。
6. **小修正**：Friday 头部文案改为「Friday · 日常助理 · 随时待命」；Today 与紧急提醒时间统一为 11:30；新增 Today 页面紧急提醒测试；依赖版本精确锁定。

### A.7 保持不变

- Friday 主对话 + Jarvis 专题对话模式
- Conversation、项目隔离、多专题、AgentInviteCard、PriorityAlert 的产品定位
- Flutter 工程结构、分层、Riverpod、go_router、设计令牌、Today 页面、四 Tab
- 环境结论与 gradlew 补丁
- U1 与后续阶段边界

### A.8 v2.4.4 修订说明

1. **channel 生命周期**：删除「listener 全部不可见时暂停」的表述；明确 Controller 的 keepAlive `ref.listen` 使 channel 始终有活跃 listener，页面返回时用 `reconcile()` 清理已确认 pending。
2. **确认超时**：新增 4.19「确认超时边界」，把无超时列为 U1 已接受边界；Mock 必须有限时间内确认或抛错；真实后端接入时只改 Repository / 同步引擎。
3. **retrySync 语义**：统一 4.16 与 4.17：不取消、不重建订阅，重置退避并重新取快照；仅 `failed` 状态下清空旧队列。
4. **同步引擎集中实现**：新增 4.17「同步引擎实现位置」与 3.1 约束；全部同步规则集中在 `ConversationSyncEngine`（`core/sync/`），Repository 委托，Controller / UI 不感知。
5. **深色令牌**：5.2 不再作为阻塞项，按表实现，批次 10 截图验收；15.3 待确认清空。

---

## 附录 B：最终开发范围清单

### B.1 必须实现

- `mobile/` 工程、4 Tab、主题令牌
- Today 页全部交互与项目入口
- 完整领域模型（Conversation、7 类消息、邀请、提醒、恢复上下文、统一事件与快照）
- 多会话仓库接口与 Mock（统一事件判定规则与摘要、快照基线、一致性校验、单队列串行与 buffer 原子切换、无遗漏合并、缺口重同步、最多 3 次尝试与退避、首次加载失败、pending 归属与合并、邀请并发幂等）
- `chatControllerProvider` / `ChatState` 的 pending/queued/failed、sendErrors、离线 flush、重试与确认清理；Riverpod 3.5 family 写法与生命周期
- `chatViewProvider` / `ChatView.displayMessages` 作为唯一展示列表；同步状态与错误横幅
- 业务不变量在构造与 `copyWith` 的 assert 落地；外部数据运行时校验；终态转换的 release 运行时保障
- 所有集合字段不可变，`ChatState.copyWith` 显式校验
- `clientMessageId` 贯通的发送、重试与确认；离线 queued 与联网串行补发
- Friday 主对话、Jarvis 专题、切换器
- 邀请接受/拒绝流程（唯一专用接口）
- Shell 级紧急提醒（Chat 与 Today 均可触发）与页面恢复
- 深链 `/chat/:conversationId?messageId=`
- 调试面板（时间/网络/数据/主题/缩放/模拟提醒/模拟邀请/模拟发送失败）
- `build.gradle.kts` 落实 minSdk 26 / targetSdk 36
- 全部单元、组件、验证、7 组对比度、缩放测试

### B.2 只需 Mock

- 消息发送与流式
- 邀请后的项目/专题创建
- 项目知识、项目记忆、项目进度
- 紧急提醒来源与优先级
- 网络与同步状态
- Today 数据

### B.3 明确不做

- 真实 Agent/Coordinator/模型路由、真实流式
- 数据库与真实项目知识库
- 系统通知、后台推送、权限
- Jarvis 重规划/周复盘/长期执行
- 任务页/我的页内容、日程页、记忆中心、引导
- iOS / HarmonyOS 原生
- 后端改动

### B.4 验收

1. 四条命令全绿
2. 模拟器可运行；真机（Mate 70）记录实际系统名称与版本、安装与核心交互，结论仅限该版本
3. 会话不串线、邀请并发幂等、提醒可恢复、消息与对话更新均不遗漏且不重复
4. 初次合并、持续监听、重同步均执行同一事件判定规则；快照基线覆盖的事件直接忽略；过期事件仅诊断，头部冲突按协议异常恢复；摘要窗口 200 条淘汰行为有测试
5. 本地发送消息在服务端确认后只保留一条并按正式 seq 归位；failed 保留原 id/seq 并可重试；离线 queued 联网后按顺序补发；重同步不丢 pending/queued/failed
6. 7 组对比度断言与截图齐全
7. 全部 Flutter 命令在 `mobile/` 下执行；WSL `--cd` 探针或 fallback 至少一种可用
8. `aapt dump badging` 输出 `sdkVersion:'26'`、`targetSdkVersion:'36'`
9. 外部非法事件/快照/邀请/卡片/Today 数据被运行时校验拒绝，未部分写入状态
10. 重同步最多 3 次尝试，退避与 jitter 有测试；首次加载失败 3 次显示 AsyncError 且可手动重试
11. 事件队列串行、buffer 原子切换、旧 generation 快照丢弃、队列溢出重同步有测试
12. 非法状态转换在 release 下仍抛 `StateTransitionException`，不只依赖 assert
13. 后端 ruff 与 pytest 通过
