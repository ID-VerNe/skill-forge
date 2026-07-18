# probe

探针模板层。提供可复用的源码结构探查模板，用于子 agent 分析源码时的结构化查询。

## Responsibilities

- 提供标准化的源码探针模板
- 当前支持 Python 探针模板

## Key Concepts

探针模板为子 agent 提供了预定义的源码探查模式，包括函数符号解析、返回值类型推断、错误处理检测等。当前提供 `template_python.py` 探针。

Reference: [[src/polyglot/probe/template_python.py]]

## Dependencies

- 无内部模块依赖

## Consumed By

- [[deep]] — 子 agent 可选择性使用探针模板进行源码分析