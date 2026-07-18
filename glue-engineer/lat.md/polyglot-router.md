# polyglot-router

CLI 命令分发器，所有 16 个子命令的入口。通过 argparse 解析命令，动态导入对应后端模块执行。

## Responsibilities

- 解析用户输入的 CLI 命令和参数
- 通过 `importlib` 动态导入语言后端模块
- 分发到 v2（scout/audit/analyze/list）、v3（cross-search/cap-match/bridge/mvp-scope）和 v4（deep-*）子系统
- 提供语言别名解析（如 `py` → `python`，`rs` → `rust`）
- 路径无关入口：`__main__.py` 自动解析 glue-engineer 根目录，可从任意 CWD 运行

## Key Concepts

### 动态后端导入

每个后端模块在 `polyglot/backends/<language>/<tool>.py` 路径下，通过 `importlib.util.spec_from_file_location` 动态加载。不依赖硬编码导入。

注意：后端文件名与 CLI 命令名存在映射关系。例如 `audit` 命令对应 `auditor.py`，`analyze` 命令对应 `analyst.py`，这三个工具的导入代码共享相同的模式。

Reference: [[polyglot/router.py#import_backend]]

### 语言别名映射

`LANGUAGES` 字典将用户输入的别名（`py`、`js`、`ts`、`rs`、`kt`、`crates` 等）映射到标准语言名。支持 npm、crates、vcpkg 等生态别名的直接输入。TypeScript/ts 映射到 javascript 后端（npm 生态）。

Reference: [[polyglot/router.py#LANGUAGES]]

### 子命令概览

| 类别 | 命令 | 功能 |
|------|------|------|
| v2 | `scout <lang> <keyword>` | 单语言包搜索 |
| v2 | `audit <lang> <name>` | 包审计 |
| v2 | `analyze <lang> <path>` | 源码分析 |
| v2 | `list` | 列出可用后端 |
| v3 | `cross-search <keyword>` | 跨语言同时搜索 |
| v3 | `cap-list` | 能力注册表列表 |
| v3 | `cap-match <src_lang> <src> <dst_lang> <dst>` | 能力匹配 |
| v3 | `bridge <src_lang> <src> <dst_lang> <dst>` | 胶水代码生成 |
| v3 | `strategies` | 桥接策略列表 |
| v3 | `mvp-scope <project>` | MVP 功能分级 |
| v4 | `deep-init` | 创建工作区+克隆仓库 |
| v4 | `deep-pack` | 生成子 agent 任务 |
| v4 | `deep-validate` | 验证产物 |
| v4 | `deep-compare` | 仓库对比 |
| v4 | `deep-summarize` | 报告草稿生成 |
| v4 | `deep-clean` | 清理克隆仓库 |

## Dependencies

- [[common]] — 使用 `common.reporters` 生成 Markdown 报告
- [[backends]] — 动态导入后端模块
- [[glue]] — v3 命令使用 glue 模块的聚合器、本体、策略选择器、验证器
- [[deep]] — v4 命令使用 deep 模块的工作区、打包、验证、比较、总结

## Consumed By

- `__main__.py` — 入口文件，调用 `router.main()`
- 用户 CLI 交互

## Error Conditions

- `ImportError` — 找不到对应语言的后端模块 → 输出错误信息并退出码 1
- 未知命令 — 打印帮助信息
- 通过 `sys.stdout.reconfigure(encoding='utf-8')` 避免 GBK 编码错误