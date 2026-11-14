# Butler Mobile（U1）

Flutter 子项目，对应计划 `docs/mobile-u1-technical-plan.md`（v2.4.4）。
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
| 3 架构与分层 | `lib/core`、`lib/domain`、`lib/data/mock`、`lib/features`、`lib/shell` |
| 4 领域模型与仓库接口 | `lib/domain/models`、`lib/domain/repositories` |
| 4.17 同步规则 | `lib/core/sync/conversation_sync_engine.dart` |
| 5 设计系统 | `lib/core/theme` |
| 6 导航外壳与路由 | `lib/shell` |
| 7-9 Chat 与专题 | `lib/features/chat` |
| 8 Today 页 | `lib/features/today` |
| 10 全局紧急提醒 | `lib/shell/urgent_alert` |
| 11 调试面板 | `lib/features/debug` |

## 调试面板

debug 构建下长按 Today 页标题进入。支持模拟时间、网络状态、数据集、主题、文字缩放、紧急提醒、邀请与发送失败。

## 截图

存放于 `mobile/screenshots/`，使用虚构数据，按计划 13.3 提交。
