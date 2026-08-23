# 架构概览（参考）

本文档是 glue-engineer 的架构参考,包含代码结构、桥接策略矩阵和 Deep Mode 产物结构。纯参考,不影响执行。

> 何时读：纯参考，不影响执行。了解代码结构、桥接策略矩阵、生成代码示例时。

## 代码结构

polyglot 包的目录树和模块职责说明,含 8 个语言后端。

```
polyglot/
├── __init__.py
├── __main__.py              # python -m polyglot entry point
├── router.py                # CLI dispatcher (scout/glue/discover/deep commands)
│
├── common/                  # Shared infrastructure (v2)
│   ├── schema.py            # Unified output schema (polyglot-output-v1)
│   ├── cache.py             # 24h TTL disk cache
│   ├── git.py               # Shallow clone + language detection
│   ├── platform.py          # OS/ecosystem detection
│   ├── proxy_fallback.py    # proxy 回退 GET
│   └── reporters.py         # JSON -> Markdown reporters
│
├── backends/                # Language backends
│   ├── python/              # PyPI JSON API + AST
│   ├── javascript/          # npm registry + regex
│   ├── rust/                # crates.io + regex
│   ├── java/                # Maven Central + regex
│   ├── kotlin/              # Maven Central + regex
│   ├── c_cpp/               # GitHub search + vcpkg
│   ├── go/                  # pkg.go.dev + proxy.golang.org
│   └── php/                 # Packagist
│
├── vtree/                   # Tree-sitter integration (optional)
├── probe/                   # 4 probe templates
│
├── commands/                # CLI 命令处理
│   ├── scout.py             # scout / audit / analyze / list
│   ├── glue.py              # cross-search / cap-list / cap-match / bridge / strategies / mvp-scope
│   ├── discover.py          # GitHub 仓库检索
│   └── deep.py              # deep-init / deep-pack / deep-validate / deep-compare / deep-summarize / deep-clean
│
└── glue/                    # v3: Cross-language glue engine
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

## 桥接策略矩阵

6×6 语言组合的桥接方案选择表:同语言用 import,跨语言用 subprocess_json,Python↔Rust 用 pyo3,Python↔C/C++ 用 ffi_cffi。

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

## 生成代码示例

gen 产物目录结构,分同语言和跨语言两种场景。

### 同语言桥接 (Python → Python: requests → httpx)

同语言 import 桥接的产物布局:包装函数 glue.py + schema.json 接口合约。

```
.glue/search/requests_httpx/
├── generated/
│   ├── glue.py              # 包装函数 + try/except
│   └── __init__.py
├── requirements.txt
├── README.md                # 审查清单
└── schema.json              # 机器可读接口合约
```

### 跨语言桥接 (Python → Rust: orjson → serde_json)

跨语言 subprocess 桥接的产物布局:Python BridgeClient + Rust CLI + build.sh 编译脚本。

```
.glue/search/orjson_serde_json/
├── generated/
│   ├── glue.py              # Python 端 BridgeClient
│   ├── bridge.rs             # Rust 端 stdin/stdout CLI
│   └── __init__.py
├── requirements.txt
├── build.sh                 # Rust 编译脚本
├── README.md                 # 跨语言审查清单
└── schema.json
```

## 关键设计决策

5 项核心架构原则:scaffold-only 生成、能力本体、逐映射置信度、不自愈、诚实验证标签。

1. **Scaffold-only 代码生成** — 生成的代码始终带 "# TODO" 标记和免责声明。不生产就绪代码。
2. **能力本体 (Capability Ontology)** — 取代 FEATURES.json 的布尔标志。按语义匹配库，而非按工具能力。
3. **逐映射置信度** — 每个函数映射有自己的分数 (0.0-1.0) 和审查标签。高分映射可跳过审查。
4. **不自愈 (v3.0)** — 验证失败直接向用户报告，附带诊断信息。不自愈循环。
5. **诚实验证标签** — 所有验证结果附带 "这是 scaffold 级验证，非生产就绪" 的声明。

## Deep Mode 产物结构

deep workspace 目录布局,覆盖 session/manifest/architecture/ranking 等全部产物。

```
.glue/deep/
├── session.json              # 项目元数据 + 候选 repo 列表
├── comparison.json           # 覆盖矩阵 + ranking（deep-compare 输出）
├── comparison.md             # 可读的对比报告
├── final-report-draft.md     # deep-summarize 输出
├── tasks/                    # 子 agent task prompt（deep-pack 生成）
│   └── <slug>.architect.task.md
├── logs/
└── repos/
    └── <slug>/
        ├── source/           # 克隆的源码
        ├── architecture.md   # 架构叙述
        ├── architecture.json # 结构化架构报告（12 必填字段）
        ├── source_manifest.json
        ├── unresolved.md
        ├── reuse-map.json    # （Phase 3，可选）
        └── integration-plan.json  # （Phase 4）
```