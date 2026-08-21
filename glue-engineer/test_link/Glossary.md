# Glossary

glue-engineer 项目中使用的关键术语和概念定义。

## AI Agent
指 Claude Code 会话中的主 agent 或子 agent。glue-engineer 通过 subagent 并行执行仓库分析、方案生成等任务。

## Backend
按语言分类的后端模块，每个后端实现 scout（搜索）、auditor（审计）、installer（安装）三个工具。支持 6 种语言：Python、JavaScript/TypeScript、Rust、Java、Kotlin、C/C++。

## Capability Ontology
能力本体论，定义功能的语义分类体系，用于跨语言功能匹配。每个功能有名称、描述、输入/输出参数、配置项等属性。

## Deep Mode
v4 引入的源码级深度分析模式。克隆候选仓库后，并行派出 subagent 进行架构分析，生成覆盖率矩阵和集成方案。

## Glue Code
胶水代码，连接不同语言/生态库之间的桥接代码。glue-engineer 的 generators 模块支持多种桥接策略：FFI（外部函数接口）、子进程调用、Python 绑定（PyO3）等。

## MVP Scoping
最小可行产品范围划分，将功能需求按 P0（必需）、P1（重要）、P2（可选）分级，指导集成优先级。

## Polyglot CLI
glue-engineer 的核心命令行工具，支持所有搜索、分析、匹配、生成操作的统一入口。通过 `python -m polyglot <subcommand>` 调用。

## Reuse Mode
许可证兼容性框架下的代码复用模式：copy（直接复制）、port（适配移植）、wrap（作为依赖使用）、reference_only（仅参考设计）、avoid（许可证冲突，禁止复用）。

## Search Mode
v3 默认模式，通过 CLI 自动链完成库搜索、跨语言查询、MVP 分级和能力匹配。

## Subagent
Claude Code 子 agent，定义为 `agents/*.md`。glue-engineer 定义 4 个子 agent：glue-repo-architect、glue-reuse-mapper、glue-integration-planner、glue-synthesizer。

## vtree
一种树形输出格式，用于结构化呈现搜索结果和分析报告。`polyglot/vtree/parser.py` 解析 vtree 格式数据。

## Workspace
Deep Mode 的工作空间目录（默认 `.glue/deep/`），包含 session.json、克隆的仓库、subagent 生成的报告和最终输出。由 `outputs.py` 管理。