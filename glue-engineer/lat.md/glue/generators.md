# glue/generators

4 种桥接策略生成器，采用插件架构。所有生成器遵循 `PluginInterface` 抽象基类，通过 `PluginRegistry` 注册。

## Responsibilities

- 实现 4 种桥接策略的代码生成
- 保持统一的插件接口（`generate()` + `validate()`）
- 生成 scaffold 级代码（始终带 TODO 标记和免责声明）

## Key Concepts

### Plugin Architecture

基础抽象类 `PluginInterface` 定义 `generate()` 和 `validate()` 方法。`PluginRegistry` 管理所有注册的生成器，支持按策略模式查找。

Reference: [[src/polyglot/glue/generators/plugin.py]]

### 4 种桥接策略

| 生成器 | 策略模式 | 适用场景 | 输出 |
|--------|---------|---------|------|
| [[glue/generators#import_gen]] | import | 同语言桥接 | 包装函数 + try/except |
| [[glue/generators#subprocess_gen]] | subprocess_json | 跨语言通用 | Python 端 BridgeClient + 目标语言 CLI |
| [[glue/generators#pyo3_gen]] | pyo3 | Python→Rust | Rust 扩展 + pyproject.toml |
| [[glue/generators#ffi_gen]] | ffi_cffi | Python↔C/C++ | CFFI 绑定 + C 源码 |

### 输出结构

```
.glue/search/<pair_id>/
├── generated/
│   ├── glue.py              # 桥接代码
│   └── __init__.py
├── requirements.txt
├── README.md                # 审查清单
└── schema.json              # 机器可读接口合约
```

## Dependencies

- [[glue]] — 使用 GlueSchema、FunctionMapping 等数据模型

## Consumed By

- [[glue]] — 通过 `generate_glue()` 函数调用