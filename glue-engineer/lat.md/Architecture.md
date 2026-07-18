# Architecture

glue-engineer 采用分层架构，CLI 入口统一，后端按语言和功能分层组织。

## System Architecture

```
polyglot/
├── __main__.py              # python -m polyglot 入口，路径无关解析
├── router.py                # CLI 调度器（argparse 16 命令）
│
├── common/                  # 共享基础设施层
│   ├── schema.py            # 统一输出 Schema
│   ├── cache.py             # 24h TTL 磁盘缓存
│   ├── git.py               # Git 操作（浅克隆 + 语言检测）
│   ├── platform.py          # OS/生态检测
│   └── reporters.py         # JSON → Markdown 报告
│
├── backends/                # 6 语言动态后端层
│   ├── python/              # PyPI JSON API + AST
│   ├── javascript/          # npm registry + regex
│   ├── rust/                # crates.io + regex
│   ├── java/                # Maven Central + regex
│   ├── kotlin/              # Maven Central + regex
│   └── c_cpp/               # GitHub search + vcpkg
│
├── glue/                    # v3 胶水引擎层
│   ├── aggregator.py        # 跨语言并行搜索
│   ├── capability_ontology.py  # 能力本体注册 + 匹配
│   ├── function_matcher.py  # 语义角色分类 + 参数映射
│   ├── strategy_selector.py # 6x6 桥接策略矩阵
│   ├── glue_schema.py       # 胶水数据模型
│   ├── mvp_scoper.py        # P0/P1/P2 分级
│   ├── verifier.py          # 6 级验证管道
│   ├── output_package.py    # 输出包封装
│   └── generators/          # 4 桥接策略生成器
│
├── deep/                    # v4 Deep Mode 层
│   ├── outputs.py           # 工作区管理
│   ├── repo_resolver.py     # URL 解析 + Git 克隆
│   ├── packager.py          # 子 agent 任务生成
│   ├── validator.py         # 产物验证
│   ├── comparer.py          # 覆盖率矩阵 + 排名
│   ├── summarizer.py        # 报告草稿
│   ├── license.py           # 许可证兼容性引擎
│   └── schemas/             # 6 个 JSON Schema 定义
│
├── vtree/                   # Tree-sitter 集成层
│   └── parser.py            # 语法树解析器
│
└── probe/                   # 探针模板层
    └── template_python.py   # Python 结构探查
```

## Module Dependencies

| 模块 | 依赖 | 被依赖 |
|------|------|--------|
| [[polyglot-router]] | common, backends, glue, deep | —（入口） |
| [[common]] | — | router, backends |
| [[backends]] | common | router |
| [[glue]] | backends, glue/generators | router |
| [[glue/generators]] | glue | glue |
| [[deep]] | — | router |
| [[vtree]] | — | — |
| [[probe]] | — | — |

## Data Flow

### Search Mode（v2 + v3）

```
用户输入 → router.py → backends/<lang>/scout.py → 外部 API → 结果
                    → glue/aggregator.py → 多后端并行 → 聚合结果
                    → glue/capability_ontology.py → 能力匹配
                    → glue/mvp_scoper.py → 分级报告
```

### Deep Mode（v4）

```
deep-init → 克隆仓库 → deep-pack → 子 agent 分析 → 产物
    → deep-validate → deep-compare → deep-summarize → 最终报告
```

## Bridge Strategy Matrix

| src \\ dst | Python | JS | Rust | Java | Kotlin | C/C++ |
|-----------|--------|-----|------|------|--------|-------|
| Python | import | subprocess | subprocess | subprocess | subprocess | **ffi** |
| JS | subprocess | import | subprocess | subprocess | subprocess | subprocess |
| Rust | **pyo3** | subprocess | import | subprocess | subprocess | subprocess |
| Java | subprocess | subprocess | subprocess | import | import | subprocess |
| Kotlin | subprocess | subprocess | subprocess | import | import | subprocess |
| C/C++ | **ffi** | subprocess | subprocess | subprocess | subprocess | import |

## Technical Decisions

1. **动态导入后端** — 通过 `importlib.util.spec_from_file_location` 动态加载后端模块，避免硬编码导入
2. **路径无关入口** — `__main__.py` 解析自身路径设置 `sys.path` 和 `PYTHONPATH`，支持从任意目录运行
3. **24h TTL 缓存** — 所有外部 API 查询结果缓存到 `.glue/cache/`，减少重复请求
4. **6 级验证管道** — Schema → 文件完整性 → 依赖检查 → 映射一致性 → 语法检查 → 边缘用例