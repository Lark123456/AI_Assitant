# Butler Mobile（U1）

Flutter 子项目，对应 `docs/mobile-u1-plan.md`。
历史技术报告已归档到 `docs/archive/mobile-u1-technical-plan-v2.4.4.md`（冻结）；
会话同步、多会话与专题、邀请卡、PriorityAlert 见 `docs/deferred/mobile-sync-and-topics.md`（延后）。
U1 只做客户端与 Mock，不连接真实后端。

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

存放于 `mobile/screenshots/`，使用虚构数据。当前开发环境未连接 Android 设备或模拟器，截图与真机验收标记为「待验收」，完成后补充。

## 验收状态

- `analyze` / `format` / `test` / `build apk --debug`：通过（82 项测试）
- APK SDK：`sdkVersion 26`、`targetSdkVersion 36`
- 真机验收与截图：待执行（当前无可用设备）
