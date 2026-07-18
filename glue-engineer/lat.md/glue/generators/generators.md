# generators

桥接策略生成器目录。包含 4 种生成器实现，遵循插件架构。

- [[glue/generators#import_gen]] — 同语言 import 包装生成器
- [[glue/generators#subprocess_gen]] — 跨语言 subprocess+JSON 生成器
- [[glue/generators#pyo3_gen]] — Python→Rust PyO3 原生扩展生成器
- [[glue/generators#ffi_gen]] — Python↔C/C++ CFFI 绑定生成器
- [[glue/generators#plugin]] — 插件接口抽象基类 + 注册表