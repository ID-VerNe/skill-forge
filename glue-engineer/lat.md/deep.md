# deep

v4 Deep Mode 源码级深度分析模块。提供通过并行子 agent 对候选仓库做代码级分析的工作流，包括工作区管理、仓库克隆、子 agent 任务生成、产物验证、对比分析和报告生成。

## Responsibilities

- 工作区创建和管理（`.glue/deep/` 目录结构）
- 仓库 URL 解析、克隆和提交信息获取
- 子 agent（glue-repo-architect）任务 prompt 生成
- 产物验证（架构报告、JSON Schema、证据完整性）
- 结构化对比（覆盖率矩阵 + 排名）
- 报告草稿生成（确定性模板填充，无 LLM 调用）
- 许可证兼容性分析（确定性的规则引擎）

## Key Concepts

### 5 阶段管道

| 阶段 | CLI 命令 | 产出 |
|------|---------|------|
| Phase 1 | `deep-init` → `deep-pack` → 子 agent → `deep-validate` | 架构报告 |
| Phase 2 | `deep-compare` → `deep-summarize` | 对比矩阵 + 报告草稿 |
| Phase 3 | `glue-reuse-mapper` → `deep-validate --include-reuse-map` | 复用分析 |
| Phase 4 | `glue-integration-planner` → `glue-synthesizer` | 集成计划 |
| Phase 5 | `deep-clean` | 清理克隆仓库 |

### 工作区结构

```
.glue/deep/
├── session.json          # 会话状态
├── repos/                # 仓库目录
│   └── <slug>/
│       ├── source/       # 克隆的源码
│       ├── architecture.md  # 架构叙述
│       ├── architecture.json  # 结构化摘要
│       ├── source_manifest.json  # 阅读文件清单
│       └── unresolved.md  # 未解决的问题
├── tasks/                # 子 agent 任务 prompts
├── logs/                 # 日志
├── comparison.json       # 对比结果
├── comparison.md         # 对比 Markdown 报告
└── final-report-draft.md  # 最终报告草稿
```

### 产物验证

`validator.py` 对每个仓库验证 7 项必检项：
1. architecture.md 存在
2. architecture.json 存在且有效 JSON
3. 所有必需字段存在（repo, slug, source_path, commit, one_line_summary, core_modules, key_types, platform_apis, known_gaps, confidence, evidence）
4. confidence 在 0-1 范围内
5. evidence 非空且包含完整字段（claim, file, line_start, line_end）
6. source_manifest.json 存在且 files_read 非空
7. unresolved.md 存在

可选验证：reuse-map.json（Phase 3），检查 candidate 结构、reuse_mode 枚举、confidence 范围、行号有效性。

Reference: [[polyglot/deep/validator.py]]

### 对比分析

`comparer.py` 纯 Python 实现，无 LLM 调用。构建需求覆盖率矩阵和仓库排名。排名公式：`score = confidence * 0.6 + min(evidence_count / 20, 1.0) * 0.4`。

Reference: [[polyglot/deep/comparer.py]]

### 报告生成

`summarizer.py` 通过模板填充生成 `final-report-draft.md`，包含：需求列表、覆盖率矩阵、排名、逐仓库分析、集成计划（如果存在）、下一步建议。纯 Python，无 LLM 调用。

Reference: [[polyglot/deep/summarizer.py]]

### 许可证兼容性引擎

`license.py` 提供确定性的许可证检查（无需 LLM）。基于 SPDX 标识符分类为 permissive/weak_copyleft/strong_copyleft/proprietary，生成 5 种复用模式（copy/port/wrap/reference_only/avoid）。

Reference: [[polyglot/deep/license.py]]

### 子 agent 任务

`packager.py` 从 `session.json` 读取仓库列表，为每个仓库生成 `.architect.task.md` 文件，包含：分析目标、需求、输出路径、10 条执行规则、最终回复格式模板。

Reference: [[polyglot/deep/packager.py]]

## Dependencies

- 无内部模块依赖。deep 模块所有功能（git 克隆、文件操作等）使用 Python 标准库实现，不依赖 polyglot 其他模块。

## Consumed By

- [[polyglot-router]] — v4 命令（deep-init/pack/validate/compare/summarize/clean）

## Error Conditions

- 克隆超时（120s）→ 标记为 failed，继续处理其他仓库
- 产物缺失 → 验证报告中显示 `[x]`，不影响其他仓库
- 许可证冲突 → 标记为 `avoid`，在报告中给出解释
- 交互式确认（deep-clean）→ 使用 `--force` 跳过确认提示；`EOFError` 作为非交互式环境的后备处理