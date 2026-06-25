export const meta = {
	  name: 'glue-engineer',
	  description: 'CRITICAL: This skill REQUIRES running polyglot CLI tools for ALL design/architecture tasks. When user says "使用胶水程序员skill" or "帮我设计/构建/评估一个系统", you MUST: (1) run `polyglot scout <lang> <keyword>` to search libraries, (2) run `polyglot mvp-scope` for prioritization, (3) run `polyglot cap-list`/`cap-match` for license checks. NEVER answer from internal knowledge alone. Multi-language, multi-agent pipeline. Builds solutions by composing existing open-source libraries across Python/JS/Rust/Java/Kotlin/C/C++. v3 adds cross-language search, capability ontology matching, scaffold glue code generation, and MVP scoping.',
	  metadata: { requires: [python, git] },
	};

	# Glue Engineer v3 — Multi-Language Glue Code Generation Engine

	> **核心理念**: 自动完成"找库→比库→测库→接库→验库"的全流程。v3 新增跨语言搜索、能力本体匹配、自动胶水代码生成。
	>
	> 借鉴 [multi-lens-research](skills/multi-lens-research) 的 STORM 方法论：并行独立 Agent → 文件通信 → 分阶段用户确认。

	---

	## 触发词 / When to Use

	| 你想干什么 | 怎么说 |
	|-----------|--------|
	| 🔍 跨生态搜索库 | `帮我找一个[语言]的[功能]库` |
	| 🌐 多语言同时搜索 | `同时搜索 Rust 的序列化库和 Python 的 HTTP 客户端` |
	| ⚖️ 对比几个库 | `对比一下[A]和[B]` |
	| 🔬 审计一个包 | `审计一下这个[语言]的[包名]` |
	| 🔗 跨语言连接两个库 | `帮我生成 Python 的 orjson 和 Rust 的 serde_json 之间的胶水代码` |
	| 🧩 能力匹配 | `看看 orjson 和 serde_json 能不能配对` |
	| 🏗️ **设计/构建项目** | **`帮我设计一个[项目]`, `我想做一个[系统]`, `使用胶水程序员skill`** |
	| 📐 **架构方案** | **`评估一下[项目]的架构`, `给我一个[系统]的可行plan`** |
	| 🎯 **MVP 分级** | **`给[项目]做P0/P1/P2分级`, `帮我排优先级`** |

	**不记得命令?** 说人话就行——我会自动理解你的需求并启动合适的管道。

	---

	## ⚠️ 关键执行规则（违反 = 没有执行此 Skill）

	### 规则 1：必须用 CLI 工具获取真实数据

	**当你收到"设计/构建/评估一个[项目或系统]"的任务时，必须使用 polyglot CLI 命令获取真实数据，禁止仅凭内部知识回答。**

	正确的执行流程：
	```
	用户说：我想做一个文献浏览器
	  → 步骤1 [强制] python -m polyglot scout python "pdf to markdown"
	  → 步骤2 [强制] python -m polyglot scout python "bibtex"
	  → 步骤3 [强制] python -m polyglot cross-search "data extraction" --languages python
	  → 步骤4 [强制] python -m polyglot mvp-scope <project> --features ...
	  → 步骤5 [建议] python -m polyglot cap-list
	  → 步骤6 [建议] python -m polyglot strategies
	```

	**绝对不要：** 只靠内部知识列出库名。**必须跑 CLI 命令**来获取版本号、许可证、下载量等真实数据。

	### 规则 2：多语言项目必须用 cross-search

	如果项目涉及多种语言（如 Python + Rust + JS），必须使用：
	```bash
	python -m polyglot cross-search "<关键词>" --languages python,rust,javascript
	```

	### 规则 3：库组合必须检查许可证兼容性

	涉及跨库组合时，必须查许可证：
	```bash
	python -m polyglot cap-list                              # 查看已录入的库
	python -m polyglot cap-match python <lib_a> python <lib_b>  # 匹配能力+许可证
	```

	### 规则 4：输出方案时必须标注数据来源

	生成的方案中每个库推荐必须标注：
	- 来源于 polyglot CLI 工具（scout / cross-search）
	- 版本号、许可证、下载量等关键数据

	### 规则 5：子 agent 场景必须传递 CLI 指令

	如果主 agent 将设计/评估任务委托给子 agent，**必须在子 agent prompt 中包含**：
	```
	这是 glue-engineer 胶水程序员技能的工作。你必须执行以下步骤：
	1. 用 python -m polyglot scout <lang> <keyword> 搜索所需库
	2. 用 python -m polyglot cross-search <keyword> --languages <langs> 做跨语言搜索
	3. 用 python -m polyglot mvp-scope <project> --features ... 做 MVP 分级
	4. 用 python -m polyglot cap-list 检查能力注册表
	5. 基于 CLI 获取的真实数据生成方案，每个库标注版本/许可证/下载量
	```
	如果不包含这些指令，子 agent 会只靠知识库回答，无法调用胶水工具。

	---

	## v3 新增能力

	v3 在 v2 的多语言后端基础上新增 4 大能力：

	### 1. 跨语言同时搜索 (Cross-Language Search)
	不再逐个语言搜索。一次查询同时扫 PyPI / npm / crates.io / Maven Central / vcpkg，自动去重：
	```bash
	python -m polyglot cross-search "json parser" --languages python,rust,javascript
	```

	### 2. 能力本体匹配 (Capability Ontology)
	将库按语义能力分类（I/O 模式、数据格式、错误模型、运行时要求），自动计算兼容性分数：
	```bash
	python -m polyglot cap-list
	python -m polyglot cap-match python orjson rust serde_json
	```

	### 3. 自动胶水代码生成 (Glue Code Generator)
	4 种桥接策略自动选择，生成 scaffold 胶水代码：
	- **import**: 同语言桥接（最高置信度）
	- **subprocess_json**: 跨语言桥接（通用方案）
	- **pyo3**: Python→Rust 原生扩展
	- **ffi_cffi**: Python↔C/C++
	```bash
	python -m polyglot bridge python orjson rust serde_json
	python -m polyglot bridge --dry-run python requests python httpx
	python -m polyglot strategies
	```

	### 4. MVP 范围分级 (MVP Scoping)
	将功能按 P0(必需)/P1(推荐)/P2(未来) 分级，帮助排优先级：
	```bash
	python -m polyglot mvp-scope <project> --features "功能名,分类"
	```

	### 5. 渐进式验证 (Verification Ladder)
	6 级验证管道：Schema → 文件完整性 → 依赖检查 → 映射一致性 → 语法检查 → 边缘用例
	验证结果附带清晰免责声明：这是 scaffold 级验证，不保证生产就绪。

	---

	## CLI 命令参考 (v3)

	### 搜索类
	```bash
	# 单语言搜索 (v2)
	python -m polyglot scout python "pdf parser"
	python -m polyglot scout rust "serialization"

	# 跨语言同时搜索 (v3)
	python -m polyglot cross-search "json parser" --languages python,rust,javascript --limit 3
	python -m polyglot cross-search "HTTP client" --languages python,javascript
	```

	### 能力匹配类
	```bash
	# 查看能力注册表
	python -m polyglot cap-list
	python -m polyglot cap-list --format json

	# 匹配两个库的能力
	python -m polyglot cap-match python orjson rust serde_json
	python -m polyglot cap-match python requests rust reqwest
	```

	### 胶水代码生成类
	```bash
	# 查看可用桥接策略
	python -m polyglot strategies

	# Dry-run: 只看 schema 不生成
	python -m polyglot bridge --dry-run python orjson rust serde_json

	# 生成胶水代码 + 自动验证
	python -m polyglot bridge python orjson rust serde_json

	# 跳过验证（只生成）
	python -m polyglot bridge python requests python httpx --skip-verify

	# 指定输出目录
	python -m polyglot bridge python pandas python polars --output-dir ./my-bridges
	```

	### MVP 分级类
	```bash
	# 对项目功能做 P0/P1/P2 分级
	python -m polyglot mvp-scope <project> --features "PDF导入,import" "LLM提取,pipeline" "BibTeX导出,export"

	# JSON 格式输出
	python -m polyglot mvp-scope <project> --features "功能1,分类1" --format json
	```

	### 审计类 (v2)
	```bash
	python -m polyglot audit python requests
	python -m polyglot audit rust serde --version 1.0
	python -m polyglot analyze python src/main.py
	```

	---

	## 架构概览 (v2 + v3)

	```
	polyglot/
	├── __init__.py
	├── __main__.py              # python -m polyglot entry point
	├── router.py                # CLI dispatcher (v2 + v3 commands)
	│
	├── common/                  # Shared infrastructure (v2)
	│   ├── schema.py            # Unified output schema (polyglot-output-v1)
	│   ├── cache.py             # 24h TTL disk cache
	│   ├── git.py               # Shallow clone + language detection
	│   ├── platform.py          # OS/ecosystem detection
	│   └── reporters.py         # JSON -> Markdown reporters
	│
	├── backends/                # 6 language backends (v2, unchanged)
	│   ├── python/              # PyPI JSON API + AST
	│   ├── javascript/          # npm registry + regex
	│   ├── rust/                # crates.io + regex
	│   ├── java/                # Maven Central + regex
	│   ├── kotlin/              # Maven Central + regex
	│   └── c_cpp/               # GitHub search + vcpkg
	│
	├── vtree/                   # Tree-sitter integration (optional)
	├── probe/                   # 4 probe templates
	│
	└── glue/                    # NEW v3: Cross-language glue engine
	    ├── __init__.py
	    ├── glue_schema.py       # GlueSchema, LibraryEndpoint, FunctionMapping, etc.
	    ├── aggregator.py        # CrossLangScoutEngine (threaded parallel search)
	    ├── capability_ontology.py  # LibraryCapability registry + matching
	    ├── function_matcher.py  # Semantic role classification + parameter mapping
	    ├── strategy_selector.py # Bridge strategy selection (6x6 language matrix)
	    ├── verifier.py          # 6-level progressive verification ladder
	    ├── mvp_scoper.py        # P0/P1/P2 MVP scope engine
	    ├── output_package.py    # GlueOutputPackage dataclass
	    └── generators/          # 4 bridge strategy generators (plugin architecture)
	        ├── plugin.py        # PluginInterface ABC + PluginRegistry
	        ├── import_gen.py    # Same-language import wrappers
	        ├── subprocess_gen.py # Cross-language subprocess+JSON
	        ├── pyo3_gen.py      # Python->Rust PyO3 native
	        └── ffi_gen.py       # Python<->C/C++ cffi
	```

	---

	## 桥接策略矩阵

	| src \\ dst | Python | JS | Rust | Java | Kotlin | C/C++ |
	|-----------|--------|-----|------|------|--------|-------|
	| Python | import | subprocess | subprocess | subprocess | subprocess | **ffi** |
	| JS | subprocess | import | subprocess | subprocess | subprocess | subprocess |
	| Rust | **pyo3** | subprocess | import | subprocess | subprocess | subprocess |
	| Java | subprocess | subprocess | subprocess | import | import | subprocess |
	| Kotlin | subprocess | subprocess | subprocess | import | import | subprocess |
	| C/C++ | **ffi** | subprocess | subprocess | subprocess | subprocess | import |

	- **import**: 同语言最高置信度
	- **subprocess_json**: JSON/stdio 协议，通用方案
	- **pyo3**: Python→Rust 原生扩展 (Scaffold)
	- **ffi_cffi**: Python↔C/C++ (Scaffold)

	---

	## 生成代码示例

	### 同语言桥接 (Python → Python: requests → httpx)
	```
	glue-outputs/requests_httpx/
	├── generated/
	│   ├── glue.py              # 包装函数 + try/except
	│   └── __init__.py
	├── requirements.txt
	├── README.md                # 审查清单
	└── schema.json              # 机器可读接口合约
	```

	### 跨语言桥接 (Python → Rust: orjson → serde_json)
	```
	glue-outputs/orjson_serde_json/
	├── generated/
	│   ├── glue.py              # Python 端 BridgeClient
	│   ├── bridge.rs             # Rust 端 stdin/stdout CLI
	│   └── __init__.py
	├── requirements.txt
	├── build.sh                 # Rust 编译脚本
	├── README.md                 # 跨语言审查清单
	└── schema.json
	```

	---

	## 关键设计决策 (v3)

	1. **Scaffold-only 代码生成** — 生成的代码始终带 "# TODO" 标记和免责声明。不生产就绪代码。
	2. **能力本体 (Capability Ontology)** — 取代 FEATURES.json 的布尔标志。按语义匹配库，而非按工具能力。
	3. **逐映射置信度** — 每个函数映射有自己的分数 (0.0-1.0) 和审查标签。高分映射可跳过审查。
	4. **不自愈 (v3.0)** — 验证失败直接向用户报告，附带诊断信息。不自愈循环。
	5. **诚实验证标签** — 所有验证结果附带 "这是 scaffold 级验证，非生产就绪" 的声明。

	---

## 向后兼容

	旧版命令和脚本仍可使用:
	```bash
	python -m polyglot scout python "requests"      # v2 不变
	python scripts/scout.py pypi "requests"          # 弃用警告，路由到 v2
	python scripts/analyst.py src/main.py            # 自动检测语言
	python -m polyglot bridge python orjson rust serde_json  # v3 新
	```

	---

	## 错误处理

	1. **Phase 1 超时**: 单个 scout agent 60s 超时 → 标记为 timeout，用部分结果继续
	2. **Phase 2 克隆失败**: 标记为 failed → 对比表中显示 "clone failed"
	3. **Phase 3 探测失败**: 显示 "probe unavailable" → 用户决定是否跳过
	4. **Phase 5 自愈**: 最多 2 次自动修复 → 如果仍失败则向用户上报
	5. **速率限制**: GitHub API 被限时 → 使用缓存 (24h TTL) → 显示提示
	6. **v3 生成失败**: Schema 验证错误 → 失败详情 + 建议修复方向
	7. **v3 验证失败**: 具体失败级别 + 文件/行号提示 → 用户决定修复或重新生成

	---

	## 参考资料

	- STORM paper: "Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking" — NAACL 2024, Stanford OVAL Lab
	- multi-lens-research skill: 多视角 STORM 工作流模式
	- Tree-sitter: github.com/tree-sitter/py-tree-sitter
	- 多视角 v3 方案合成: upgrade-analysis/glue-v3-outputs/synthesis-plan.md