# vtree

Tree-sitter 语法解析集成层。可选依赖（`tree-sitter>=0.20`），提供 AST 解析能力。

## Responsibilities

- 封装 tree-sitter 的 Python 绑定
- 提供源码语法树解析功能
- 为 deep mode 子 agent 提供结构化源码分析支持

## Key Concepts

Tree-sitter 是一个增量解析库，可为多种编程语言生成精确的语法树。vtree 层将其包装为 glue-engineer 可用的工具，当前主要用于解析 Python 源码。

Reference: [[src/polyglot/vtree/parser.py]]

## Dependencies

- 外部：`tree-sitter>=0.20`（可选依赖）

## Consumed By

- [[deep]] — 子 agent 可选择性使用 vtree 进行源码分析