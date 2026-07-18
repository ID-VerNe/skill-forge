# backends

6 个语言后端的索引目录。每个后端提供 4 个工具（scout/auditor/analyst/installer），通过 polyglot-router 动态导入。

Supported Languages:

- [[backends/python]] — PyPI 搜索 + AST 分析
- [[backends/javascript]] — npm 注册表搜索
- [[backends/rust]] — crates.io 搜索
- [[backends/java]] — Maven Central 搜索
- [[backends/kotlin]] — Maven Central 搜索（与 Java 共享仓库）
- [[backends/c_cpp]] — GitHub 搜索 + vcpkg