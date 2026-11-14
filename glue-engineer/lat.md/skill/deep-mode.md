# Deep Mode — 详细流程

Deep Mode 的完整执行流程,含 6 个 CLI 命令链、subagent 并行策略、排名公式和 DATA INCOMPLETE 门禁规则。

> 何时读：用户确认进入 DEEP 模式（候选库源码级分析）时。

Deep Mode 是对候选库的源码级深度分析。

## 触发条件

如果用户直接要求深度分析，或满足以下条件，Search Mode 尾部会询问用户是否进入 Deep Mode：
- 候选库 ≥ 3 个
- 用户需求含 ≥ 3 条具体功能
- 用户提及 fork / modify / integrate / reuse / build on top
- 决策影响长期架构
- 用户要求"深度分析" / "深入了解" / "看看能不能改造"

## 执行流程

deep-init → deep-pack → 由调用环境启动并行 subagent → deep-validate（JSON Schema、候选账目和逐条需求覆盖校验）→ deep-compare（coverage×0.4+confidence×0.3+evidence×0.3, DATA INCOMPLETE 抑制排名）→ deep-summarize → deep-clean 的完整管道。CLI 只准备 workspace 并生成任务 prompt，不会自行启动或调度 subagent。

```bash
# 重要：polyglot CLI 可以从任何目录运行，所有输出都放在当前 CWD 的 .glue/ 下。
#    例如：在 C:\Users\VerNe\Downloads\Documents\my-project\ 下运行：
#    输出位置：C:\Users\VerNe\Downloads\Documents\my-project\.glue/deep/

# Phase 1: 初始化 + 克隆
# 必须包含 Search Mode 输出的所有候选库的 repo URL，不能主观跳过任何一个
#    （subagent 会做代码级分析来判断优劣，主 agent 不应先替用户过滤）
python -m polyglot deep-init --project <name> --requirements "req1" "req2" --repos <url1> <url2> <url3> <...>
python -m polyglot deep-pack --dir .glue/deep/

# 并行启动 glue-repo-architect subagent（每个 repo 一个）
# → Subagent prompt 必须包含 CLI 指令（见子 agent 规则）

# 验证产物
python -m polyglot deep-validate --dir .glue/deep/

# Phase 2: 对比 + 总结
python -m polyglot deep-compare --dir .glue/deep/
python -m polyglot deep-summarize --dir .glue/deep/

# Phase 3: 复用分析（可选）
# → 启动 glue-reuse-mapper subagent（如需要）

# Phase 4: 集成规划 + 综合
# → 启动 glue-integration-planner subagent
# → 启动 glue-synthesizer subagent

# Phase 5: 清理（使用 -f 跳过交互确认，因为 Bash 环境 input() 可能异常）
python -m polyglot deep-clean --dir .glue/deep/ --force

# --requirements 使用 nargs="+"：每条需求作为独立参数传入，不会自动拆分逗号分隔字符串。
```

## Subagent 规则

glue-repo-architect subagent 的权限和约束:源码只读、不 build/install、Write 限于 `.glue/deep/`、无需 worktree 隔离。

- 探索路径自由（不限制读取文件数）
- 源码只读，不 build，不 install
- Write 权限仅限于 `.glue/deep/`
- 只返回简短摘要给主 agent

## 并行策略

当有多 repo 时，用 `Agent` 工具并行启动 glue-repo-architect（每个 repo 一个实例）。所有 subagent 独立落盘，互不干扰。

**重要：不要使用 `isolation: "worktree"`。** subagent 需要写入共享的 `.glue/deep/` 目录，worktree 隔离会把 Write 落到隔离工作树副本，parent session 看不到产物（实测踩坑：agent 报告"文件已写"，但 `.glue/` 下是空的）。各 subagent 写不同的 `<slug>/` 子目录，不存在文件冲突，无需隔离。

## 排名机制（重要）

`deep-compare` 的排名公式：

```
score = coverage_ratio × 0.4 + confidence × 0.3 + min(evidence_count / 20, 1.0) × 0.3
```

其中 `coverage_ratio = (supported × 1.0 + partial × 0.5) / 需求总数`。

**覆盖率主导**：一个"自信但缺功能"的 repo（高 confidence、低 coverage）排名会低于"谦虚但全覆盖"的 repo。

**数据门禁**：只有完整候选集和有效报告都通过校验时才会生成排名。

- `deep-init` 会为每个请求候选记录一次 clone 结果（成功或失败）；即使部分 clone 失败，结果和错误原因也会保留在 `session.json`。候选集不完整时，`deep-compare` 退出非零并抑制排名，不能把成功 clone 的子集当成完整比较。
- 每个成功 clone 的 `architecture.json` 必须包含全部必填字段，并通过 JSON Schema 的类型、结构和枚举校验；架构报告中的 `slug`、`commit` 必须与 session 中克隆结果一致。
- 每条 session requirement 在每份架构报告的 `known_gaps` 中必须恰好出现一次。匹配规则是空格规范化后忽略大小写的精确匹配；缺项、重复项、额外项均阻止排名。
- session 的候选计数/clone 记录、唯一安全 slug、成功克隆列表和架构产物必须互相一致。损坏或形状错误的 session、架构 JSON、证据、manifest 等也会阻止排名，而不是被当成空数据继续计算。
- `deep-summarize` 会再次校验当前 session 和架构产物，并重算 coverage matrix 与 ranking；缺失/损坏/过期或被修改的 `comparison.json` 不能单靠 `status: complete` 通过门禁。任何不完整状态都会在总结中显示 `DATA INCOMPLETE`、失败原因并隐藏 top candidate。

遇到 `DATA INCOMPLETE` 时不要信任或引用任何排名数字；按 `comparison.md` / `final-report-draft.md` 中列出的错误修复 session 或重新生成架构报告，然后依次重跑 `deep-validate`、`deep-compare` 和 `deep-summarize`。
