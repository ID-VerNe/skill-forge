# polyglot

The core CLI package (`polyglot/`), providing the unified entry point for all glue-engineer operations. Dispatches to sub-modules based on subcommand.

## Key Concepts

核心模块概念：入口点、CLI 调度器、语言解析。

### Entry Point

`polyglot/__main__.py` resolves the root directory from its own file location, injects it into `sys.path` and `PYTHONPATH`, and calls `polyglot.router.main()`. Allows invocation from any working directory.

Reference: [[polyglot/__main__.py]]

### CLI Dispatcher

`polyglot/router.py` parses subcommands and dispatches to the appropriate module. Supports: `scout`, `cross-search`, `cap-list`, `cap-match`, `bridge`, `mvp-scope`, `deep-init`, `deep-validate`, `deep-compare`, `deep-summarize`, `deep-clean`.

Reference: [[polyglot/router.py]]

### Language Resolution

A mapping table (`LANGUAGES`) in `router.py` resolves user-facing language names (e.g., "py", "js", "rs") to backend directory names (e.g., "python", "javascript", "rust"). Backends are dynamically loaded.

## Dependencies

polyglot 模块调用的子模块列表。

- [[deep]] — v4 Deep Mode subcommands
- [[glue]] — v3 Glue Engine subcommands
- [[backends]] — Language-specific backend modules
- [[common]] — Shared utilities (schema, git, platform, cache)

## Consumed By

哪些模块使用 polyglot 模块。

- [[scripts]] — Wrapper scripts that call `polyglot` commands
- [[tests]] — End-to-end tests that exercise the CLI

## Error Conditions

CLI 命令可能遇到的错误条件。

- `UNKNOWN_LANGUAGE` — User specified a language not in the `LANGUAGES` mapping. Resolution: check supported languages with `python -m polyglot --help`.
- `MISSING_BACKEND` — A language is recognized but no backend module exists for the requested tool. Resolution: backend not yet implemented. See [[backends]] for supported tools.
- `MISSING_SUBCOMMAND` — No subcommand or unrecognized subcommand provided. Resolution: display help text.