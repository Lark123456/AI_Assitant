# Butler Mobile（U1/U2）

Flutter 子项目，对应 `docs/mobile-u1-plan.md`。
历史技术报告已归档到 `docs/archive/mobile-u1-technical-plan-v2.4.4.md`（冻结）；
会话同步、多会话与专题、邀请卡、PriorityAlert 见 `docs/deferred/mobile-sync-and-topics.md`（延后）。
U1 只做客户端与 Mock；U2 起接入真实后端，Today 与 Chat 已接真实 API。

## 环境

- Flutter 3.47.2（`D:\flutter`），Dart 3.13.2
- JDK 21，Android SDK 36（`E:\AutoPunch\.android-sdk`）
- 本机 `flutter.bat` 会挂起，统一用 Dart 直接调用 `flutter_tools`

## 运行

```powershell
Set-Location "E:\F&J\FJ v1\mobile"
$env:FLUTTER_ROOT="D:\flutter"
$env:ANDROID_HOME="E:\AutoPunch\.android-sdk"
$env:ANDROID_SDK_ROOT="E:\AutoPunch\.android-sdk"
$DART="D:\flutter\bin\cache\dart-sdk\bin\dart.exe"
$FLUTTER="D:\flutter\packages\flutter_tools\bin\flutter_tools.dart"

& $DART $FLUTTER --no-version-check run
```

## 构建与检查

```powershell
Set-Location "E:\F&J\FJ v1\mobile"
$env:FLUTTER_ROOT="D:\flutter"
$env:ANDROID_HOME="E:\AutoPunch\.android-sdk"
$env:ANDROID_SDK_ROOT="E:\AutoPunch\.android-sdk"
$DART="D:\flutter\bin\cache\dart-sdk\bin\dart.exe"
$FLUTTER="D:\flutter\packages\flutter_tools\bin\flutter_tools.dart"

& $DART $FLUTTER --no-version-check analyze
& $DART format --output=none --set-exit-if-changed lib test
& $DART $FLUTTER --no-version-check test
& $DART $FLUTTER --no-version-check build apk --debug
& "$env:ANDROID_HOME\build-tools\36.0.0\aapt.exe" dump badging `
  "build\app\outputs\flutter-apk\app-debug.apk" | Select-String "sdkVersion"
```

首次下载依赖如失败，设置代理后重试：

```powershell
$env:GRADLE_OPTS="-Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=7890 -Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=7890"
```

## 环境变量

U1 无运行时环境变量；所有数据来自 Mock。模拟时间、网络、主题、数据集等开关在应用内调试面板。

## gradlew 补丁

仓库路径含 `&` 与空格，`android/gradlew.bat` 的三处路径赋值必须加引号：

```bat
set "DIRNAME=%~dp0"
set "APP_HOME=%DIRNAME%"
set "CLASSPATH=%APP_HOME%\gradle\wrapper\gradle-wrapper.jar"
```

不要重新生成 `android/`，否则补丁会被覆盖。

## 与计划文档的对应

| 计划章节 | 本目录 |
|---|---|
| 2 分层 | `lib/core`、`lib/domain`、`lib/data/mock`、`lib/features`、`lib/shell` |
| 3 领域模型与卡片 | `lib/domain/models` |
| 4 仓库接口 | `lib/domain/repositories` |
| 5 Mock 语义 | `lib/data/mock` |
| 6.1 导航外壳 | `lib/shell` |
| 6.2-6.3 今日页与对话页 | `lib/features/today`、`lib/features/chat` |
| 6.4 调试面板 | `lib/features/debug` |
| 6.5 主题 | `lib/core/theme` |

## 出站意图与卡片对应

| 意图 | 卡片类型 |
|---|---|
| text | `TextMessage` |
| confirm_card | `ConfirmCard` |
| choice | `ChoiceCard` |
| nudge | `TextMessage`（带 `reason`） |
| schedule_view | 今日页时间线 |
| plan_proposal | `PlanProposalCard` |
| memory_confirm | `MemoryConfirmCard` |

Jarvis 引荐使用 `JarvisIntroCard`，接受后由 Mock 仓库在同一消息流追加诊断 `ChoiceCard`、`ThinkingCard`、`PlanProposalCard`。

## 调试面板

debug 构建下长按 Today 页标题进入。支持模拟时间、网络状态、数据集、主题、文字缩放、Jarvis 引荐与发送失败。

## 截图

存放在 `mobile/screenshots/`，使用虚构数据，共 6 张：

- `today_light.png` / `today_dark.png`
- `chat_light.png` / `chat_dark.png`
- `debug_light.png` / `debug_dark.png`

由 `test/screenshot_test.dart` 渲染生成（默认跳过，需显式开启）：

```powershell
$env:SCREENSHOTS="1"
& $DART $FLUTTER --no-version-check test --update-goldens test/screenshot_test.dart
```

当前环境未连接 Android 设备或模拟器，因此这些是组件渲染截图，不是真机截图；真机验收仍标记为「待验收」。

## 远程 Today 与 Chat（U2）

默认仍是 Mock；用 `--dart-define` 开启真实 Today 与 Chat 数据。后端 `.env` 需先开启移动端 API：

```dotenv
ENABLE_MOBILE_API=1
# 非本机部署时建议同时配置，留空 = 不限制
ALLOWED_OPEN_IDS=
```

```powershell
adb reverse tcp:8000 tcp:8000
& $DART $FLUTTER --no-version-check build apk --debug `
  --dart-define=USE_REMOTE=true `
  --dart-define=BUTLER_API_BASE_URL=http://127.0.0.1:8000 `
  --dart-define=BUTLER_USER=<用户 UUID 或飞书 open_id>
```

后端接口：`GET /api/mobile/today?date=YYYY-MM-DD`，开发期用户头 `X-Butler-User`；配置 `ALLOWED_OPEN_IDS` 后，UUID 与 open_id 都必须是白名单用户。
写操作：`POST /api/mobile/today/items/{id}/complete|skip|restore|reschedule`、
`POST /api/mobile/today/tasks/{id}/schedule`、`POST /api/mobile/today/review`。
写接口必须带 `Idempotency-Key`，重复提交同一键返回上次结果。
改期只允许未结束的日程块，新开始时间需在同一天且距结束至少 5 分钟。
一个任务可以有多个时间块（分段推进）；移动端「排进今天」只从未排期列表创建第一个块，后续块可由对话或任务页补充。
已完成/跳过的提醒会取消触发并保留终态；失败或已取消的提醒不可再操作。
未勾选的晚间复盘条目保持原状态；失效或不可操作的条目会被跳过，不影响其余条目。
晨间/晚间简报暂返回空；`USE_REMOTE=true` 时 Chat 也已接真实接口。

### 远程 Chat

后端接口：

- `POST /api/mobile/chat/messages`：body `{clientMessageId, text}`；`clientMessageId` 是唯一业务标识，请求头 `Idempotency-Key` 若出现必须与它一致。
- `GET /api/mobile/chat/messages?limit=50&after=<id>&before=<id>`：首屏先取最新 N 条再升序返回；`after` 只取增量，`before` 向上翻更早历史。
- `GET /api/mobile/chat/messages/{id}`：单条状态补偿，用于发现 processing → done/failed。

客户端行为：

- 首屏最近 50 条；之后每 2 秒用 `after` 游标轮询，单飞防重入，失败指数退避（上限 30 秒）并显示同步横幅。
- 本地乐观消息按 `clientMessageId` 与服务端回显合并；发送失败可重试，未到达服务器时复用原 id。
- 服务端已确认 `failed` 的消息不会原地重跑，重试会生成新的 `clientMessageId`。
- `processing` 的入站消息由单条状态接口补偿，不会一直停在“Friday 正在处理”。
- App 进入后台或切离 Chat Tab 时停止轮询；回前台/回到 Chat 时由 `setActive(true)` 立即刷新。
- Remote 模式暂不支持卡片应答与流式回复；卡片仅在 Mock 模式可用。

开发期边界：

- `ENABLE_MOBILE_API=1` 才挂载 `/api/mobile/chat/*`；关闭时返回 404。
- 仍是开发期 `X-Butler-User` 认证，只允许本机或 `adb reverse` 调试，`ALLOWED_OPEN_IDS` 不能替代真实认证。
- API 服务只支持单进程（同一用户的串行锁是进程内 `asyncio.Lock`）；多 worker/多副本需要跨进程队列或租约。
- 手机没有服务端推送：Friday 回复落库后由 App 轮询取回，状态为 `available`（不是 `sent`）。

## 任务页（U2）

- `GET /api/mobile/tasks?status=open|done|all&limit=100`：返回当前用户 `type=item` 的任务，`upcomingBlock` 取最早的未来计划块。
- 状态映射：`active→open`、`done→done`、`dropped→skipped`。
- 写操作复用 Today 端点：`POST /api/mobile/today/items/{id}/complete|skip|restore`、`POST /api/mobile/today/tasks/{id}/schedule`；写接口必须带 `Idempotency-Key`。
- 任务页支持未完成/已完成/全部过滤、下拉刷新、完成/跳过/撤销与“排进今天”；不提供创建/编辑。
- 默认仍为 Mock；`USE_REMOTE=true` 时走真实接口。

## 我的页（U2）

- `GET /api/mobile/profile`：返回当前用户 `displayName`、`timezone`、`dayStart("HH:MM")`、`createdAt`；只读，无写接口。
- 页面展示账号资料、数据源（Mock/Remote 与接口地址）、版本号（`APP_VERSION`，默认 `0.1.0+1`）与调试入口（仅 debug）。
- `dayStart` 仅作资料展示；Today 当前按本地零点切日。
- 默认仍为 Mock；`USE_REMOTE=true` 时走真实接口。

## 验收状态

- `analyze` / `format` / `test` / `build apk --debug`：通过（135 项测试；3 项截图生成测试默认跳过）
- APK SDK：`sdkVersion 26`、`targetSdkVersion 36`
- 应用名：`Butler`（Android label；包名仍为 `com.butler.mobile`）
- 最新 Debug APK：`build/app/outputs/flutter-apk/app-debug.apk`
- 真机验收：待执行（当前无可用设备）

## U1 补缺与规格出入

本次补齐：左滑完成/右滑跳过与撤销、长按操作面板（改期/跳过/详情/为什么这样排）、简报调整面板、下拉刷新同步态、今日页按住语音面板、主动消息理由行与「为什么推给我」、输入条快捷词、拍照/相册面板、新消息跳转按钮、副标题「常驻 · 秒回」。

与归档规格的出入：

- 今日页只补了语音按钮（FAB + 录音面板），没有补归档 8.1.7 的「文本 + 语音」完整输入条；今日页文本发送与跳转主对话仍不在本次范围。
- 对话页未新增语音入口；归档 9.5 的语音输入仍待后续。
- 语音、拍照、相册、简报调整、少打扰、关闭这一类均为仅界面，不申请权限、不录音、不上传。
- 快捷词按确认结果「点击直接发送」，不会先填入输入框。
- 下拉刷新只模拟同步状态并重新加载 Mock 当天数据，不发真实网络请求。
- 撤销通过 `TodayRepository.restore` 在 Mock 内恢复状态，不涉及真实同步。
- 时间选择器使用 Material 默认本地化；未新增 `flutter_localizations`，英文/测试环境下按钮显示英文。
- 新消息按钮按 120dp 阈值判断，不提供未读计数。
- 截图是组件渲染图，不是真机截图；截图测试使用系统黑体与 MaterialIcons 字体，仅影响测试，不改变应用依赖。
