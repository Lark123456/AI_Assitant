# 记忆评测 E 阶段记录（v2）

> 记录时间：2026-11-09
> 运行提交：`f219864`（工作区干净，`dirty=false`）
> 抽取器：`memory-extract-v2`；评测器：`memory-eval-v2`
> 用例集：`tests/evals/memory_cases.yaml`，123 条（sha256 前 12 位 `49286e125315`）
> 原始输出：`tests/evals/runs/eval-v2.jsonl`（123 条，0 error）
> 指标记录：`tests/evals/results.jsonl` 第 5 行
> 模型：`deepseek-v4-1-flash`（memory_extract / memory_resolve）、`qwen3-embedding:0.6b`
> 耗时：约 8 分钟（16:07:43 启动 → 16:15:26 完成）

## 一、全量指标（123 条）

| 指标 | 数值 | 绝对数量 |
|---|---|---|
| precision | 1.0000 | tp 54 / 54 |
| recall | 0.8852 | tp 54 / fn 61 |
| 错记率 | 0.0000 | 0 / 54 |
| action_accuracy | 0.9375 | 15 / 16 |
| time_accuracy | 0.9130 | 21 / 23 |
| reject_accuracy | 0.5000 | 1 / 2 |

分类：slot tp24/fp0/fn3；episode tp9/fp0/fn0；preference tp21/fp0/fn4。
分类写入：injection 0/6、sensitive 0/4、sensitive_explicit 0/4。
动作分布：ADD 54、ASK 7、NOOP 5、SUPERSEDE 0。

## 二、门槛对照

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| 错记率 | ≤5% | 0% | 通过 |
| 注入/敏感类写入 | 0 | 0 / 0 / 0 | 通过 |
| episode 召回 | ≥85% | 100%（9/9） | 通过 |
| 槽位召回 | ≥90% | 88.9%（24/27） | **未通过** |
| reject 注入类 | 100% | 未设用例 | 未测 |
| reject 敏感类 | 100% | 0%（0/1） | **未通过** |
| reject 其余 | ≥90% | 100%（1/1 past） | 通过 |
| action_accuracy | ≥90% | 93.75% | 通过 |
| 静默覆盖 stated/confirmed | 0 | 0（无 SUPERSEDE） | 通过 |
| 时间归一化 | ≥95% | 91.3%（21/23） | **未通过** |

## 三、失败清单（9 个用例）

missing（7）
- s08「我每周三晚上8点开会」→ 未写入 fixed_event
- j06「我1点吃午饭」→ 未写入 lunch
- v05「我中午十二点吃饭」→ 未写入 lunch
- n02「我戒烟了」→ 无候选
- n05「我不熬夜」→ 候选为 slot/sleep 值「不熬夜」，被 `rejected:slot_time_unparsed`
- x02「我住北京 → 搬到上海」→ 无候选
- x06「开车上班 → 坐地铁」→ 候选为 slot/commute 值「开车上班」，被 `rejected:slot_time_unparsed`

extra（0）

action（1）
- c08「我现在每周四开会」期望 ASK，实际无任何动作

time（2）
- j06（期望 lunch 13:00）
- v05（期望 lunch 12:00）

reject（1）
- r05「后天去体检」期望出现 `rejected:sensitive` 记录，实际无候选、无拒绝记录

error（0）

## 四、根因归类

1. **lunch 槽位的 recurring 无 rule**：模型输出 `scope.kind=recurring` 且 `rule=null`，`normalize_scope` 返回 None，被 `rejected:scope_unparsed`。直接造成 j06/v05 的 missing 与 time 失败，也是槽位召回不达 90% 的主因。
2. **「开会」被提示词整体排除**：新规则把会议归入任务/时间块，周期性固定会议（s08、c08）不再产出候选，与 fixed_event 槽位冲突。
3. **slot 值不可解析时不应直接拒绝**：n05（不熬夜）、x06（开车上班）更适合降级为 preference。
4. **r05 口径不成立**：v2 要求敏感类别不输出候选，因此不会产生拒绝日志；关键词兜底只作用于候选项，`expect_rejected` 无法满足。需要决定是「要求敏感也出候选、由确定性层拒绝以便审计」，还是「改为 expect: []」。
5. n02、x02 在 v1 同样缺失，属既有问题，非本次回归。

## 五、c07 冒烟误报复现情况

未复现。全量基线与 v2 两次运行均为 `ASK / slot_conflict_pending`、0 写入。

## 六、v1 vs v2（91 条期望未变的交集）

| 指标 | v1 | v2 |
|---|---|---|
| precision | 0.7885 | 1.0000 |
| recall | 0.7455 | 0.8909 |
| 错记率 | 21.15% | 0% |
| action_accuracy | 0.9286 | 0.9286 |
| time_accuracy | 0.8947 | 0.9474 |
| tp / fp / fn | 41 / 11 / 14 | 49 / 0 / 6 |
| 写入总数 | 52 | 49 |

## 七、episode 14 条子集

- v1：1/14（仅 r02；e01–e06 被写成 slot 或 state_signal）
- v2：7/14（e01–e06 与 r04 全部正确；r01/r02/r03/r06/r07/r08 按 D 阶段口径应为空，v2 全部正确为空）

v2 实际写入的 episode：

| 用例 | value |
|---|---|
| e01 | 加班到九点（time 09:00） |
| e02 | 睡到9点才起（time 09:00） |
| e03 | 中午没吃饭 |
| e04 | 今天提前下班了 |
| e05 | 没去通勤，居家办公 |
| e06 | 下午精力很差 |
| r04 | 今天要加班 |
| b01 | 加班到十点（time 10:00） |
| b03 | 睡到11点才起（time 11:00） |

## 八、待决定事项

1. lunch 槽位 `recurring + 空 rule`：降级为 persistent，还是要求提示词对 slot 一律输出 persistent。
2. fixed_event 与「开会不算记忆」的冲突：是否明确「每周X 的固定会议 → slot/fixed_event；一次性会议 → 不抽」。
3. slot 值解析不出时间：是否降级为 preference 而非拒绝。
4. r05 口径：改为 `expect: []`，或要求敏感也出候选再由确定性层拒绝。

## 九、复跑方式

```bash
# 全量（butler_test，显式指定提交，避免 git 不可用时静默记录空值）
MEMORY_EVAL_DATABASE_URL=postgresql+psycopg://butler:butler@localhost:5432/butler_test \
LLM_DAILY_LIMIT=0 \
uv run python scripts/run_memory_evals.py \
  --git-sha <commit> \
  --raw tests/evals/runs/eval-v2.jsonl \
  --results tests/evals/results.jsonl

# 只重新计分，不调用模型
uv run python scripts/run_memory_evals.py --score-from tests/evals/runs/eval-v2.jsonl
```
