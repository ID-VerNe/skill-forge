# CLI 命令参考

本文档列出 glue-engineer 全部 CLI 命令,按功能分组:搜索、能力匹配、胶水生成、MVP 分级、审计、Deep Mode。

> 何时读：需要查具体命令（scout/discover/cross-search/cap-match/bridge/mvp-scope/audit/analyze）时。

## 命令速查

全部 CLI 入口一行速览,含搜索/匹配/生成/审计/深度分析类。

```bash
python -m polyglot scout <lang> "<keyword>"         # 包级：查生态注册表（要装的库）
python -m polyglot discover "<keyword>"              # 项目级：查 GitHub 仓库（有没有人做过）
python -m polyglot cross-search "<kw>" --languages python,rust,javascript   # 跨语言
python -m polyglot mvp-scope <project> --features "f,cat" "f2,cat"          # P0/P1/P2 分级
python -m polyglot cap-list                          # 能力注册表
python -m polyglot cap-match python orjson rust serde_json                  # 能力+许可证匹配
python -m polyglot bridge python orjson rust serde_json                     # 生成胶水代码
python -m polyglot audit <lang> <name>               # 审计包
python -m polyglot analyze <lang> <src>              # 分析源码
```

## scout vs discover 语义区分

scout 和 discover 的核心区别:包级检索 vs 项目级检索。

> `scout` = **包级**检索，查生态注册表（PyPI/npm/crates/Maven/pkg.go.dev），返回"要装的库"+ 版本/下载量。
> `discover` = **项目级**检索，查 GitHub 仓库（`gh search repos`），返回"有没有人做过"+ 星数/license，可选 enrichment 补生态数据。Go repo 通过 `proxy.golang.org/@latest` 精确补 version。

## 搜索类

三种搜索命令:scout(单语言)、cross-search(跨语言)、discover(GitHub 仓库)。

### 单语言搜索（scout）

查单一语言的生态注册表,返回库名+版本+下载量。用法: `python -m polyglot scout <lang> "<keyword>"`。

```bash
python -m polyglot scout python "pdf parser"
python -m polyglot scout rust "serialization"
```

### 跨语言同时搜索（cross-search）

一次跨多语言生态注册表搜索,返回汇总结果。用法: `python -m polyglot cross-search "<kw>" --languages <langs>`。

```bash
python -m polyglot cross-search "json parser" --languages python,rust,javascript --limit 3
python -m polyglot cross-search "HTTP client" --languages python,javascript
```

### GitHub 仓库检索（discover）

查 GitHub 仓库,返回星数/license/描述,可选 enrichment 补生态数据。用法: `python -m polyglot discover "<keyword>"`。

```bash
# 检索 GitHub 仓库（项目级：找"有没有人做过 X"）
python -m polyglot discover "byd remote monitor"
python -m polyglot discover "byd vehicle" --qualifiers "language:python" --sort stars
python -m polyglot discover "websocket library" --qualifiers "language:go" --sort stars --limit 5
python -m polyglot discover "ffmpeg" --limit 10 --no-enrich   # 跳过生态补全
```

## 能力匹配类

查看能力注册表,匹配两个库的功能和许可证兼容性。

```bash
# 查看能力注册表
python -m polyglot cap-list
python -m polyglot cap-list --format json

# 匹配两个库的能力
python -m polyglot cap-match python orjson rust serde_json
python -m polyglot cap-match python requests rust reqwest
```

## 胶水代码生成类

基于策略矩阵自动生成桥接代码,支持 dry-run 和跳过验证。

```bash
# 查看可用桥接策略
python -m polyglot strategies

# Dry-run：只看 schema 不生成
python -m polyglot bridge --dry-run python orjson rust serde_json

# 生成胶水代码 + 自动验证
python -m polyglot bridge python orjson rust serde_json

# 跳过验证（只生成）
python -m polyglot bridge python requests python httpx --skip-verify

# 指定输出目录
python -m polyglot bridge python pandas python polars --output-dir ./my-bridges
```

## MVP 分级类

对项目功能做 P0/P1/P2 优先级分级,支持 JSON 输出。

```bash
# 对项目功能做 P0/P1/P2 分级
python -m polyglot mvp-scope <project> --features "PDF导入,import" "LLM提取,pipeline" "BibTeX导出,export"

# JSON 格式输出
python -m polyglot mvp-scope <project> --features "功能1,分类1" --format json
```

## 审计类

审计包的安全/许可证/版本信息,或分析源码文件结构。

```bash
python -m polyglot audit python requests
python -m polyglot audit rust serde --version 1.0
python -m polyglot analyze python src/main.py
```

## Deep Mode 命令

6 个 deep pipeline 命令:deep-init → deep-pack → deep-validate → deep-compare → deep-summarize → deep-clean。

```bash
# 初始化 workspace + 克隆仓库
python -m polyglot deep-init --project <name> --requirements "req1,req2" --repos <url1> <url2>

# 生成子 agent task prompt
python -m polyglot deep-pack [dir]

# 验证子 agent 产物
python -m polyglot deep-validate [dir]
python -m polyglot deep-validate [dir] --include-reuse-map

# 对比架构报告
python -m polyglot deep-compare [dir]

# 生成报告草稿
python -m polyglot deep-summarize [dir]

# 清理克隆仓库
python -m polyglot deep-clean [dir]
python -m polyglot deep-clean [dir] --all
```