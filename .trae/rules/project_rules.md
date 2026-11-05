# 项目背景
我们在做一个 AI 原生的时间管理与陪伴后端（代号 Butler）。系统由两个智能体组成：
- Friday：快通道，负责日常事项、意图路由、提醒与简报文案，强调低延迟。
- Jarvis：慢通道，负责长期任务立项、重规划、周复盘，异步运行，使用显式状态机。
首个渠道是飞书机器人（长连接），但后端必须与渠道无关。当前处于 P0 阶段：只验证机制，不追求规模和性能。

# 技术栈（不得擅自更换）
- Python 3.12、FastAPI、SQLAlchemy 2.x（异步）、Alembic、Pydantic v2、httpx
- PostgreSQL 16 + pgvector：同一个库承担事件日志、业务状态、向量、任务队列与调度表
- 不引入 Redis、Celery、Temporal；不使用 LangChain、LangGraph、LlamaIndex，Agent 循环与状态机手写
- Worker 使用 Postgres 的 FOR UPDATE SKIP LOCKED 领取任务
- 工具链：uv、ruff、mypy、pytest
- 部署：Docker Compose（运行在 WSL2），所有配置来自环境变量

# 架构原则（违反即视为错误）
1. 状态与叙事分离。业务状态用强 schema 表并在事务内写入；对话与事件写入 append-only 的 event_log。向量、摘要、抽取出的事实都是可重建的派生物，必须带 source_event_ids。
2. LLM 只通过工具调用读写状态，不依赖回忆。能用确定性代码完成的逻辑（时间计算、重复规则、校验、统计）一律不交给 LLM。
3. 渠道无关。核心代码不得 import 任何飞书 SDK，渠道细节只存在于 adapters 目录。出站消息用意图（text、confirm_card、choice、nudge）表达，由 adapter 渲染。
4. 所有模型调用经 LLM 网关。业务代码只引用档位别名（friday_fast、memory_extract、mini_plan、jarvis_deep、vision_extract），禁止出现模型名字符串。
5. 每次模型调用都写入 llm_call 表：别名、实际模型 id、参数、输入输出、input/cached/output/reasoning 四类 token、延迟、错误。
6. 所有时间通过可注入的 Clock 读取，禁止直接调用 datetime.now() 或 time.time()。存储统一 timestamptz（UTC），同时保存用户时区。
7. 所有写操作幂等（idempotency key）。外部回调先验签、去重、落库、快速应答，处理异步进行。
8. 记忆只 supersede，不原地更新；每条记忆有 provenance；推断类记忆不得驱动日程、计划变更或主动触达的时机。
9. 主动消息只产出候选，唯一发送出口是仲裁器（gate）；发送前重新校验前提；每个决策写入决策日志。
10. 外部内容（网页、文档、OCR 结果）视为数据而非指令，也不能作为记忆来源。

# 目录结构
app/
  api/            FastAPI 路由
  adapters/       渠道适配（feishu、console）
  agents/         friday、jarvis
  engine/         triggers、gate、delivery
  memory/         记忆写入与检索
  tools/          工具定义与实现
  llm/            LLM 网关与 provider
  embeddings/     嵌入服务封装
  db/             models、migrations
  core/           clock、config、logging、ids
tests/  scripts/  docs/

# 编码规范
- 全面类型标注，公共函数写简短 docstring 说明意图而不是复述代码
- 禁止吞异常；所有外部调用必须设置超时与重试上限
- 不硬编码配置与密钥，示例放 .env.example
- 结构化日志（JSON），带 trace_id 与 user_id
- 数据库变更只通过 Alembic 迁移，禁止手工改表

# 工作方式
- 先给出简短计划（文件清单、实现顺序、疑问），等我确认后再改代码
- 一次只做我指定阶段的内容，不要提前实现后续阶段；不确定就提问，不要猜
- 契约见 docs/contracts.md。涉及数据模型、工具 schema、adapter 接口时必须先阅读它；不得擅自修改其中字段的含义，需要变更时先说明理由并等我确认
- 每个阶段结束时运行测试与静态检查，汇报结果、已知问题与未做事项
- 不创建与当前任务无关的文件、示例代码或额外功能