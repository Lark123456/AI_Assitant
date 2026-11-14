# 仓库结构与协作规则（Monorepo）

## 目录

- 根目录：Butler 后端（Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL）
- `mobile/`：Flutter 移动端子项目（阶段 U1 起）

## 命令执行位置

- 后端命令（uv、ruff、mypy、pytest、alembic、docker compose）在仓库根执行
- Flutter / Dart 命令必须在 `mobile/` 内执行；不要在仓库根运行 `flutter` 或 `dart pub`
- 仓库路径含 `&` 与空格，PowerShell 中所有路径必须加引号

## 边界

- `mobile/` 不得 import 后端 Python 代码，也不得读取后端配置
- 后端不得依赖 `mobile/`；U1 期间后端代码零改动
- 渠道与协议细节只存在于后端 adapters；移动端只通过 `ChatRepository`、`TodayRepository` 等接口访问数据

## 构建

- `mobile/android/gradlew.bat` 的三处路径赋值必须保留引号补丁；不要重新生成 `android/`
- Flutter 使用 `dart flutter_tools.dart` 调用，避免 `flutter.bat` 挂起；首次构建如遇网络失败，按 `mobile/README.md` 设置代理

## 提交

- 后端与移动端改动分开提交；提交前各自跑完对应检查
