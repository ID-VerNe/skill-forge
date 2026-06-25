# polyglot — Multi-Language Glue Engineer Toolkit

Language-specific backends for searching, auditing, analyzing, and installing packages
across 6 ecosystems: Python, JavaScript/TypeScript, Rust, Java, Kotlin, C/C++.

## Quick Start
```bash
python -m polyglot scout python "pdf parser"
python -m polyglot scout rust "serialization"
python -m polyglot list
```

## Structure
- `common/` — Schema, cache, git, platform, reporters
- `backends/<lang>/` — Per-language scout, auditor, analyst, installer
- `probe/` — Dynamic probe templates (anti-hallucination)
- `vtree/` — Tree-sitter abstraction layer
- `router.py` — CLI dispatcher