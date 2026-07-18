# Glossary

## 核心概念

### Glue Code
跨语言桥接的胶水代码。由生成器自动生成 scaffold 代码，包含 TODO 标记和免责声明，不生产就绪代码。

### Capability Ontology
库的能力本体注册表。将库按语义能力分类（I/O 模式、数据格式、错误模型、运行时要求），取代传统的 FEATURES.json 布尔标志。

### Bridge Strategy
桥接策略。决定如何连接两个不同语言的库。有 4 种：import（同语言）、subprocess_json（跨语言通用）、pyo3（Python↔Rust）、ffi（Python↔C/C++）。

### MVP Scoping
将功能按 P0（必需）/ P1（推荐）/ P2（未来）三级分级，帮助排优先级。参考 [[glue#MVP Scoper]]。

### Deep Mode
v4 引入的源码级深度分析模式。通过并行子 agent 对候选仓库做代码级分析，输出架构报告、复用分析和集成计划。

### Scaffold-only
生成的代码始终带 `# TODO` 标记和免责声明，不生产就绪代码。这是 [[Project#Key Design Decisions]] 之一。

## 子系统

### v2
基础多语言后端。每个语言（Python/JS/Rust/Java/Kotlin/C/C++）提供 scout/auditor/analyst/installer 四个工具，通过动态导入加载。

### v3
跨语言胶水引擎。新增跨语言搜索、能力本体匹配、胶水代码生成、MVP 分级和渐进式验证。

### v4
Deep Mode。通过子 agent 对候选仓库做源码级深度分析，支持 5 阶段管道：初始化、并行分析、对比、总结、清理。

## 工具函数

### Scout
包搜索工具。通过各语言包管理器 API（PyPI/npm/crates.io/Maven Central/vcpkg）搜索库。

### Auditor
包审计工具。检查包的版本、许可证、下载量、依赖关系和安全性。

### Analyst
源码分析工具。分析本地源码文件的结构和依赖。

### Installer
安装工具。为各语言提供包安装功能。

## 验证

### Verification Ladder
6 级验证管道：Schema 验证 → 文件完整性 → 依赖检查 → 映射一致性 → 语法检查 → 边缘用例。验证结果附带「scaffold 级验证，非生产就绪」声明。

## 相关概念

### Tree-sitter
可选的语法解析库。vtree 层封装了 tree-sitter 的 Python 绑定，提供 AST 解析能力。

### Probe
探针模板。用于子 agent 探查源码结构，当前提供 Python 探针模板。