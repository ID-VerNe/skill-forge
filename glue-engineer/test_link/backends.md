# backends

Language-specific backend modules (`polyglot/backends/`), each implementing scout, auditor, and installer tools for one language ecosystem. Backends are dynamically loaded by `router.py` based on language name resolution.

## Supported Languages

6 种语言后端的具体实现：Python、JavaScript/TypeScript、Rust、Java、Kotlin、C/C++。

### Python
Backend directory: `polyglot/backends/python/`
- `scout.py` — Search PyPI for libraries matching requirements
- `auditor.py` — Audit a Python package for license, dependencies, and metrics
- `installer.py` — Package installation support

### JavaScript/TypeScript
Backend directory: `polyglot/backends/javascript/`
- `scout.py` — Search npm for libraries
- `auditor.py` — Audit npm package metadata
- `installer.py` — Package installation support

### Rust
Backend directory: `polyglot/backends/rust/`
- `scout.py` — Search crates.io for libraries
- `auditor.py` — Audit crate metadata
- `installer.py` — Package installation support

### Java
Backend directory: `polyglot/backends/java/`
- `scout.py` — Search Maven Central for libraries
- `auditor.py` — Audit Maven package metadata
- `installer.py` — Package installation support

### Kotlin
Backend directory: `polyglot/backends/kotlin/`
- `scout.py` — Search Maven Central for Kotlin libraries
- `auditor.py` — Audit Kotlin package metadata
- `installer.py` — Package installation support

### C/C++
Backend directory: `polyglot/backends/c_cpp/`
- `scout.py` — Search vcpkg/conan for C/C++ libraries
- `auditor.py` — Audit C/C++ package metadata
- `installer.py` — Package installation support

## Key Concepts

后端模块的核心概念：动态加载和共享输出格式。

### Dynamic Loading

Backend modules are not imported at startup. `router.py` uses `importlib.util.spec_from_file_location()` to load the specific backend when a language + tool is requested. This keeps startup fast and avoids import errors for unused backends.

Reference: [[polyglot/router.py]]

### Shared Output Format

All scout backends return a standardized list of candidate libraries with: name, version, license, description, download count, and source URL. All auditor backends return license, dependencies, and metrics.

## Dependencies

backends 模块依赖的其他模块。

- [[common]] — Shared utilities for HTTP requests, caching, platform detection
- [[polyglot]] — CLI dispatcher that loads backends dynamically

## Consumed By

哪些模块使用 backends 模块。

- [[polyglot]] — CLI commands that invoke scout/audit/analyze
- [[glue]] — Capability matching uses backend metadata