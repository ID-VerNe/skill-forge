# backends

## 6 语言后端

每个后端位于 `polyglot/backends/<language>/` 目录下，提供统一的 API 接口：

### 公共接口

所有后端工具遵循相同的函数签名模式：

| 工具 | 函数 | 参数 | 返回 |
|------|------|------|------|
| scout | `search(keyword, limit)` | keyword: str, limit: int | `SearchOutput` JSON |
| auditor | `audit(name, version)` | name: str, version: str | `AuditOutput` JSON |
| analyst | `analyze(path)` | path: str | 分析结果 JSON |
| installer | `install(name, version, target)` | name, version, target | 安装结果 |

### 后端列表

- [[backends/python]] — PyPI JSON API + AST 源码分析
- [[backends/javascript]] — npm registry API + 正则匹配
- [[backends/rust]] — crates.io API + 正则匹配
- [[backends/java]] — Maven Central search API + 正则匹配
- [[backends/kotlin]] — Maven Central search API（与 Java 共享索引）
- [[backends/c_cpp]] — GitHub Code Search + vcpkg 注册表

### 数据来源

| 后端 | 包管理器 API | 备用数据源 |
|------|-------------|-----------|
| python | pypi.org/json | github.com |
| javascript | registry.npmjs.org | github.com |
| rust | crates.io/api/v1 | github.com |
| java | search.maven.org | github.com |
| kotlin | search.maven.org | github.com |
| c_cpp | github.com/search | vcpkg.io |

## Dependencies

- [[common]] — 使用 schema 定义输出格式
- [[polyglot-router]] — 通过 `importlib` 动态导入

## Consumed By

- [[polyglot-router]] — CLI 命令分发
- [[glue#aggregator]] — 跨语言搜索聚合器