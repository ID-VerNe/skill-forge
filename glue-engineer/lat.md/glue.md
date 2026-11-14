# glue

v3 Glue Engine module (`polyglot/glue/`), implementing cross-language capability matching, strategy selection, MVP scoping, and glue code generation. This is the original Glue Engine (v3) that operates without source-level analysis.

## Key Concepts

Glue Engine 的核心概念：能力本体、功能匹配、策略选择、MVP 分级、代码生成。

### Capability Ontology

`capability_ontology.py` defines a semantic classification system for library capabilities. Each capability has a name, description, input/output parameters, and configuration options. Used for cross-language functional matching.

Reference: [[polyglot/glue/capability_ontology.py]]

### Function Matching

`function_matcher.py` compares capabilities across libraries and languages to find compatible functions. Determines whether two functions can be paired based on input/output type compatibility, parameter semantics, and side effects.

Reference: [[polyglot/glue/function_matcher.py]]

### Strategy Selection

`strategy_selector.py` determines the optimal integration strategy for a given pair of libraries: FFI bridge, subprocess invocation, Python binding (PyO3), or import-based composition.

Reference: [[polyglot/glue/strategy_selector.py]]

### MVP Scoping

`mvp_scoper.py` applies P0/P1/P2 priority classification to features based on dependency analysis, effort estimation, and risk assessment. Guides integration sequencing.

Reference: [[polyglot/glue/mvp_scoper.py]]

### Glue Code Generators

`generators/` directory contains code generators for different bridge strategies:
- `ffi_gen.py` — External Function Interface bridge code
- `import_gen.py` — Import-based composition (same-language integration)
- `pyo3_gen.py` — Python-Rust bridge via PyO3
- `subprocess_gen.py` — Subprocess-based bridge
- `plugin.py` — Plugin system generator

Reference: [[glue#Key Concepts#Glue Code Generators]]

### Schema

`glue_schema.py` defines the glue plan schema, including bridge type, mapping rules, and generated code structure.

Reference: [[polyglot/glue/glue_schema.py]]

### Verification

`verifier.py` validates schema/file integrity, mapping consistency, and Python syntax. It explicitly reports runtime behavior as `not_run`; a passing structural report is not evidence that generated bridge calls execute correctly.

Reference: [[polyglot/glue/verifier.py]]

### Reviewed mapping generation

Bridge generation consumes reviewed mappings only. Empty mappings require explicit scaffold mode.

`polyglot bridge --mappings <file.json>` accepts a top-level `mappings` array and sends only entries marked `review_status: "reviewed"` to the schema and generator. The currently functional vertical slice is Python-to-Python identity parameter mapping; the remaining generators are identified as scaffold through `GeneratorMetadata.implementation_status` and supported-language metadata.

Reference: [[polyglot/commands/glue.py]]

## Dependencies

glue 模块依赖的其他模块。

- [[common]] — Shared schema validation, reporting
- [[backends]] — Backend metadata for capability matching

## Consumed By

哪些模块使用 glue 模块。

- [[polyglot]] — CLI subcommand registration
- [[Project]] — User-facing Search Mode workflow
