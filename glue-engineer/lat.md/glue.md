# glue

v3 跨语言胶水引擎核心模块。提供跨语言包搜索、能力本体匹配、桥接策略选择、胶水代码生成、MVP 分级和 6 级渐进式验证。

## Responsibilities

- 跨语言并行搜索（threaded fan-out，使用 `threading.Thread` 逐线程并行），一次查询同时扫 6 个生态
- 能力本体（Capability Ontology）注册和语义匹配
- 桥接策略自动选择（6x6 语言矩阵）
- 胶水代码生成（scaffold-only，始终带 TODO 标记）
- MVP 功能分级（P0/P1/P2）
- 6 级渐进式验证管道
- 多层去重引擎（SHA256/DOI/Levenshtein/标题+作者）

## Key Concepts

### Cross-Language Search

`CrossLangScoutEngine` 使用 `threading.Thread` daemon 线程并行搜索多个语言生态，结果通过 `CrossLangSearchView` 统一呈现。支持去重、别名解析和跨语言项目标记。

Reference: [[polyglot/glue/aggregator.py#CrossLangScoutEngine]]

### Dedup Engine

多层去重引擎依次应用 4 层去重：SHA256 哈希精确匹配 → DOI 标识符去重 → Levenshtein 模糊标题匹配（阈值 0.85）→ 标题+作者联合模糊匹配（阈值 0.75）。

Reference: [[polyglot/glue/aggregator.py#DedupEngine]]

### Capability Ontology

取代 FEATURES.json 的布尔标志，按语义描述库的能力：I/O 模式、数据格式、错误模型、运行时要求、并发模型、许可证。匹配计算加权交集（IO 0.25 + 数据格式 0.25 + 错误模型 0.15 + 数据形状 0.15 + 运行时 0.10 + 许可证 0.10）。

Reference: [[polyglot/glue/capability_ontology.py#match_capabilities]]

### GlueSchema

胶水代码的完整接口契约。包含源和目标库端点、桥接策略、函数映射列表、能力对齐结果。每个 mapping 有独立的置信度分数（0.0-1.0）和审查标签。

Reference: [[polyglot/glue/glue_schema.py#GlueSchema]]

### 6 级验证管道

渐进的 6 级验证：Schema 验证 → 文件完整性 → 依赖检查 → 映射一致性 → 语法检查 → 边缘用例。所有验证结果附带"scaffold 级验证，非生产就绪"声明。

Reference: [[polyglot/glue/verifier.py]]

### 6 维度分析评分

`DimensionalScorer` 对生成的胶水方案进行多维度分析评分（非 pass/fail，而是 0.0-1.0 分析评分），帮助比较不同方案和发现盲点：

| 维度 | 权重 | 说明 |
|------|------|------|
| direction | 0.20 | 问题陈述与解决方案方向的清晰度 |
| architecture | 0.20 | 系统设计与组件分离的质量 |
| stack | 0.15 | 技术栈选择的合理性 |
| feasibility | 0.20 | 在给定约束下的实际可行性 |
| risk | 0.15 | 风险意识与缓解计划 |
| focus | 0.10 | 方案是否保持聚焦而非范围蔓延 |

评分通过 `DimensionalReport` 呈现，包含每个维度的分数、解释和警告，以及加权总分。

Reference: [[polyglot/glue/verifier.py#DimensionalScorer]]

### Strategy Selector

根据源和目标语言自动选择桥接策略。6x6 矩阵定义每条路径的推荐策略：

- **import** — 同语言桥接（最高置信度）
- **subprocess_json** — 跨语言通用方案（JSON/stdio 协议）
- **pyo3** — Python→Rust 原生扩展（scaffold）
- **ffi_cffi** — Python↔C/C++（scaffold）

Reference: [[polyglot/glue/strategy_selector.py]]

### MVP Scoper

将功能按 P0（必需）/ P1（推荐）/ P2（未来）三级分级，基于关键词分类和依赖风险评估，自动分配优先级。

Reference: [[polyglot/glue/mvp_scoper.py]]

### Failure State Machine

`StatusMachine` 支持 10 种状态（pending/queued/in_progress/retrying/succeeded/failed/failed_partial/cancelled/needs_review/skipped），严格的有向图状态转换规则，最多 3 次自动重试。

Reference: [[polyglot/glue/glue_schema.py#StatusMachine]]

## Dependencies

- [[backends]] — 通过 aggregator 动态导入后端 scout 模块
- [[glue/generators]] — 调用 4 种桥接策略生成器

## Consumed By

- [[polyglot-router]] — v3 命令（cross-search、cap-list、cap-match、bridge、strategies、mvp-scope）

## Submodules

- [[glue/generators]] — 4 种桥接策略生成器（插件架构）
- [[glue#aggregator]] — 跨语言并行搜索引擎
- [[glue#capability_ontology]] — 能力本体注册 + 匹配
- [[glue#function_matcher]] — 语义角色分类 + 参数映射
- [[glue#strategy_selector]] — 桥接策略选择
- [[glue#verifier]] — 6 级验证管道
- [[glue#mvp_scoper]] — MVP 分级引擎
- [[glue#output_package]] — 输出包封装
- [[glue#glue_schema]] — 数据模型定义

## Error Conditions

- Schema 验证错误 → 失败详情 + 建议修复方向
- 验证失败 → 具体失败级别 + 文件/行号提示
- 生成失败 → 用户决定修复或重新生成