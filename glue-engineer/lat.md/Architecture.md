# Architecture

glue-engineer 是一个模块化 CLI 工具，通过多阶段管道实现多语言库的搜索、分析、匹配和集成方案生成。

## Module Dependencies

模块间的依赖关系图，展示从入口点到各子模块的数据流向。

```
polyglot/__main__.py  (入口点)
  └── polyglot/router.py  (CLI 调度器)
       ├── polyglot/deep/     (v4 Deep Mode)
       │   ├── outputs.py     — 工作空间管理
       │   ├── repo_resolver.py — URL 解析 + git clone
       │   ├── packager.py    — 子 agent 任务提示生成
       │   ├── validator.py   — 工件验证
       │   ├── comparer.py    — 覆盖率矩阵 + 排名
       │   ├── summarizer.py  — 报告草稿生成
       │   ├── license.py     — 许可证兼容性引擎
       │   └── schemas/       — JSON Schema 定义
       ├── polyglot/glue/     (v3 Glue Engine)
       │   ├── aggregator.py  — 聚合结果
       │   ├── capability_ontology.py — 能力本体
       │   ├── function_matcher.py   — 功能匹配
       │   ├── glue_schema.py — 胶水方案 schema
       │   ├── mvp_scoper.py  — MVP 分级
       │   ├── strategy_selector.py  — 策略选择
       │   ├── verifier.py    — 方案验证
       │   └── generators/    — 胶水代码生成器
       ├── polyglot/backends/   (6 语言后端)
       │   ├── {python, javascript, rust, java, kotlin, c_cpp}/
       │   │   ├── scout.py    — 库搜索
       │   │   ├── auditor.py  — 库审计
       │   │   └── installer.py — 安装支持
       ├── polyglot/common/     (共享基础设施)
       │   ├── schema.py    — 共享 schema 验证
       │   ├── git.py       — git 操作
       │   ├── platform.py  — 平台检测
       │   ├── cache.py     — 缓存
       │   └── reporters.py — 报告输出
       ├── polyglot/vtree/     (vtree 解析)
       │   └── parser.py    — vtree 格式解析器
       └── scripts/            (辅助脚本)
           ├── setup.sh / setup.ps1 — 安装脚本
           ├── scout.py      — 快速搜索
           ├── analyst.py    — 分析
           └── auditor.py    — 审计
```

## Data Flow

v3（Search Mode）和 v4（Deep Mode）两种模式的数据流路径。

### Search Mode (v3)

Search Mode 通过 CLI 自动链完成库搜索、跨语言查询、MVP 分级和能力匹配。

```
User Input → polyglot scout <lang> <keyword> → 候选库列表
          → polyglot cross-search → 跨语言覆盖
          → polyglot mvp-scope <project> → 优先级分级
          → polyglot cap-list / cap-match → 能力匹配
          → polyglot bridge <lang1> <lib1> <lang2> <lib2> → 胶水方案
```

### Deep Mode (v4)

Deep Mode 通过克隆仓库、派出 subagent 进行源码级分析，生成覆盖率矩阵和集成方案。

```
User Input → deep-init (创建 workspace + clone repos)
          → deep-pack (生成 subagent 任务提示)
          → 并行 subagent (glue-repo-architect 每 repo 一个)
          → deep-validate (验证 subagent 输出)
          → deep-compare (生成覆盖率矩阵 + 排名)
          → deep-summarize (生成报告草稿)
          → deep-clean (清理克隆的 repos)
```

## Technical Decisions

关键架构决策及其动机。

### 动态后端加载
`router.py` 使用 `importlib.util.spec_from_file_location()` 动态加载后端模块，避免了为每个语言注册 import 路径的维护成本。后端模块按 `backends/<language>/<tool>.py` 命名约定自动发现。

### 路径无关入口
`__main__.py` 通过 `os.path.dirname(os.path.abspath(__file__))` 解析自身位置，将 glue-engineer 根目录注入 `sys.path` 和 `PYTHONPATH` 环境变量。subprocess 调用（如 subagent 中的 CLI 命令）也能找到模块。

### 工作空间管理
所有 Deep Mode 状态保存在 `.glue/deep/session.json`，包含项目名称、需求、目标许可证、候选仓库列表和工作流版本。`outputs.py` 管理整个工作空间生命周期。

### 许可证兼容性引擎
`license.py` 提供确定性许可证检查（无需 LLM），基于预定义的兼容性矩阵判断 reuse mode（copy/port/wrap/reference_only/avoid）。