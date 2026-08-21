# vtree

VTree parser module (`polyglot/vtree/`). Implements parsing of vtree format — a tree-structured output format used for presenting search results and analysis reports.

## Key Concepts

vtree 模块的核心概念：格式定义和解析器。

### VTree Format

A structured, tree-based output format designed for hierarchical data presentation. Used by reporters to format CLI output in a parseable tree structure.

### Parser

`parser.py` reads vtree format strings and produces a structured tree representation. Supports nested nodes, key-value pairs, and list items.

Reference: [[polyglot/vtree/parser.py]]

## Dependencies

vtree 模块依赖的 common 模块。

- [[common]] — Used by reporters for vtree output

## Consumed By

哪些模块使用 vtree 模块。

- [[common#Key Concepts#Reporters]] — VTree output formatting