# Project

**Tech Stack**: Python 3.10+ (scripts-based, no pyproject.toml)
**Architecture Pattern**: Plugin-based CLI with layered backend architecture
**External Dependencies**: requests>=2.28, tree-sitter>=0.20 (optional)

## One-Line Summary

glue-engineer 是一个 Claude Code skill，通过多语言后端搜索、能力本体匹配、胶水代码生成和源码级深度分析，自动完成"找库→比库→测库→接库→验库"的全流程。

## Modules

- [[polyglot-router]] — CLI 命令分发器，16 个子命令横跨 v2/v3/v4 三个子系统
- [[common]] — 共享基础设施：统一输出 Schema、24h TTL 缓存、Git 操作、平台检测、Markdown 报告
- [[backends]] — 6 语言后端，每语言 4 工具（scout/auditor/analyst/installer），动态导入
- [[glue]] — v3 跨语言胶水引擎：跨语言搜索、能力本体匹配、胶水代码生成、MVP 分级
- [[glue/generators]] — 4 种桥接策略（import/subprocess/pyo3/ffi），插件架构
- [[deep]] — v4 Deep Mode：子 agent 源码级深度分析工作流（5 阶段管道）
- [[vtree]] — Tree-sitter 集成层（可选依赖），提供 AST 解析能力
- [[probe]] — 4 种探测模板，用于子 agent 探查源码结构

## Dependency Graph

依赖关系见 [[Architecture#Module Dependencies]]。

## CLI Overview

所有命令通过 `python -m polyglot <command>` 执行，支持 16 个子命令：

| 命令 | 子系统 | 功能 |
|------|--------|------|
| `scout` | v2 | 单语言包搜索 |
| `audit` | v2 | 包审计 |
| `analyze` | v2 | 源码分析 |
| `list` | v2 | 列出可用后端 |
| `cross-search` | v3 | 跨语言同时搜索 |
| `cap-list` | v3 | 能力注册表列表 |
| `cap-match` | v3 | 能力匹配 |
| `bridge` | v3 | 胶水代码生成 |
| `strategies` | v3 | 桥接策略列表 |
| `mvp-scope` | v3 | MVP 功能分级 |
| `deep-init` | v4 | 创建工作区 + 克隆仓库 |
| `deep-pack` | v4 | 生成子 agent 任务 |
| `deep-validate` | v4 | 验证产物 |
| `deep-compare` | v4 | 仓库对比 |
| `deep-summarize` | v4 | 报告草稿生成 |
| `deep-clean` | v4 | 清理克隆仓库 |

## Key Design Decisions

1. **Scaffold-only 代码生成** — 生成的胶水代码始终带 TODO 标记和免责声明，不生产就绪代码
2. **Capability Ontology** — 取代 FEATURES.json 布尔标志，按语义匹配库
3. **逐映射置信度** — 每个函数映射有独立分数（0.0-1.0）和审查标签
4. **不自愈**（v3.0）— 验证失败直接报告，不自愈循环
5. **诚实验证标签** — 验证结果附带"scaffold 级验证，非生产就绪"声明
6. **入口无关性** — `python -m polyglot` 可从任意目录运行，自动解析路径。所有 `.glue/` 输出放在 CWD 下