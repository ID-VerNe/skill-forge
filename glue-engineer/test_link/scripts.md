# scripts

Auxiliary scripts (`scripts/`) for environment setup and quick operations. These are standalone Python scripts and shell setup scripts.

## Key Concepts

scripts 模块的主要功能：安装脚本和快速工具。

### Setup Scripts

`setup.sh` (Linux/macOS) and `setup.ps1` (Windows) automate the installation of glue-engineer dependencies and subagent definitions. Install the polyglot CLI, copy agent definitions to `~/.claude/agents/`, and configure permissions.

### Quick Tools

- `scout.py` — Quick library search wrapper
- `analyst.py` — Quick analysis wrapper
- `auditor.py` — Quick audit wrapper

These scripts provide a simpler interface for common operations without the full `python -m polyglot` invocation.

## Dependencies

scripts 模块依赖的 polyglot CLI。

- [[polyglot]] — All scripts call polyglot CLI commands internally

## Consumed By

哪些用户使用 scripts 模块。

- End users installing or quickly using glue-engineer