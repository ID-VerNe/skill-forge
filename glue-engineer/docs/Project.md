# Project

**Tech Stack**: Python 3.10+ CLI, multi-language backends (Python/JS/TS/Rust/Java/Kotlin/C/C++/PHP/Go)
**Architecture Pattern**: Modular CLI with subagent orchestration
**Project Type**: Claude Code Skill — multi-language library search and analysis

## Modules

glue-engineer 的核心模块列表。

- [[polyglot]] — 核心 CLI 包，包含所有子命令和管道逻辑
- [[deep]] — v4 Deep Mode：源码级仓库分析管道（deep-init → deep-pack → 并行 subagent → deep-validate → deep-compare → deep-summarize → deep-clean），新增 jsonschema 严格校验与 coverage 排名
- [[glue]] — v3 Glue Engine：跨语言能力本体匹配、功能匹配、策略选择、MVP 分级、胶水代码生成
- [[backends]] — 8 语言后端实现：scout/audit/analyze 三工具
- [[skill]] — Skill 操作文档：路由/流程/命令参考/排障
- [[scripts]] — 辅助脚本
- [[tests]] — 端到端测试

## Dependency Graph

依赖关系见 [[lat.md/Architecture#Module Dependencies]]。

## Key Design Decisions

glue-engineer 的关键设计决策。

### 路径无关性
`__main__.py` 自动解析 glue-engineer 根目录并注入 sys.path，使所有 CLI 命令可从任意工作目录运行，无需先 `cd` 到项目目录。所有 `.glue/` 输出自动放在用户项目目录（CWD）下。

### 双模式入口
Search Mode（v3 CLI 自动链）和 Deep Mode（v4 subagent 源码分析）构成完整管道。Search Mode 默认进入，Deep Mode 可选进入。

### 子 agent 输出协议
所有子 agent 必须写完整报告到磁盘（`.glue/deep/`），只返回简短摘要（< 10 行）到主对话上下文，避免上下文膨胀。

### Schema 严格校验
deep-validate 接入 jsonschema，architecture.json 的类型/结构/枚举违规一次性全部报出，对比阶段数据不完整则抑制排名（DATA INCOMPLETE 横幅）。

### 覆盖率主导排名
deep-compare 排名公式 score = coverage×0.4 + confidence×0.3 + evidence×0.3，覆盖率优先。

### 子 agent 大文件指引
subagent 分析超 5000 行/100KB 文件必须选择性读取（Grep+offset/limit），跳过测试/生成文件。