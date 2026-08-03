# common

Shared infrastructure modules (`polyglot/common/`) providing cross-cutting utilities used by all other modules.

## Key Concepts

common 模块提供的共享服务：schema 验证、git 操作、平台检测、缓存、报告格式化。

### Schema Validation

`schema.py` provides shared JSON Schema validation utilities. All structured data in the project (session, architecture reports, comparison results, reuse maps, integration plans) is validated against schemas.

Reference: [[polyglot/common/schema.py]]

### Git Operations

`git.py` wraps git CLI operations used by `deep-init` for cloning candidate repositories. Handles URL parsing, shallow clones, and commit hash capture.

Reference: [[polyglot/common/git.py]]

### Platform Detection

`platform.py` detects the operating system and platform characteristics. Used by backend installers to determine appropriate package manager and installation paths.

Reference: [[polyglot/common/platform.py]]

### Cache

`cache.py` provides a SQLite-backed disk cache at a fixed system-level location — not project-relative. Thread-safe via thread-local connections and WAL mode.

- **Path**: Windows `%LOCALAPPDATA%/polyglot/cache.db`, macOS `~/.cache/polyglot/cache.db`, Linux `$XDG_CACHE_HOME/polyglot/cache.db`
- **TTL**: Default 24-hour expiration
- **Stale fallback**: `cache_get_stale()` returns expired data when network is unreachable
- **Auto-cleanup**: Probabilistic (~1% chance per `cache_set`) to prevent unbounded growth
- **Functions**: `cache_get`, `cache_set`, `cache_get_stale`, `cache_clean`, `cache_stats`

Reference: [[polyglot/common/cache.py]]

### Retry

`retry.py` provides exponential backoff with jitter for transient network failures. Used by all scout backends when querying package registries.

`retry_call(fn, max_retries=3, base_delay=1.0, max_delay=30.0, retryable_exceptions=None)` calls `fn()` with exponential backoff on failure. Returns `(result, attempts, last_error)` — never raises. The caller controls which exceptions are retryable, enabling 404 errors to be distinguished from transient network errors.

Reference: [[polyglot/common/retry.py]]

### Reporters

`reporters.py` provides output formatting utilities for CLI results. Handles table rendering, JSON output, and vtree format generation.

Reference: [[polyglot/common/reporters.py]]

## Dependencies

common 模块无内部依赖，是所有其他模块的叶子节点。

- No internal dependencies — these are leaf modules used by all other modules.

## Consumed By

哪些模块使用 common 模块。

- [[polyglot]] — CLI dispatcher uses schema and reporters
- [[deep]] — Session validation, git operations
- [[glue]] — Schema validation
- [[backends]] — Cache, retry, platform detection (all scout backends use cache and retry)