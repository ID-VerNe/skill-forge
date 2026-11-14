# tests

End-to-end test specifications for glue-engineer. Located in `tests/`.

## Key Concepts

tests 模块的核心概念：端到端测试用例。

### End-to-End Test

`test_e2e.py` exercises the full polyglot pipeline: scout, cross-search, cap-list, cap-match, bridge, and mvp-scope commands. Validates CLI output format and basic functionality.

## Test Specifications

具体测试用例清单，验证 CLI 各命令的正确性。

### CLI dispatcher handles all subcommands
Verify that `python -m polyglot <subcommand>` dispatches correctly for all registered subcommands and returns expected exit codes.

### Scout returns correct format
Verify that `python -m polyglot scout <lang> <keyword>` returns a list of candidate libraries with name, version, license, and description fields.

### Cross-search aggregates results
Verify that `python -m polyglot cross-search` aggregates results from multiple language backends into a unified output.

### Deep-init creates workspace
Verify that `python -m polyglot deep-init` creates the `.glue/deep/` directory structure with session.json.

### Validation catches missing fields
Verify that `deep-validate` correctly reports missing required fields in subagent outputs.

## Issue 59 Phase 1

Regression tests for issue #59 phase 1 cover CLI failure behavior, documented Deep Mode argument parsing, and the required JSON Schema dependency.

### cap-match missing registry entry is a CLI error
Verify that a missing capability entry reports a readable error and exits non-zero instead of raising `NameError`.

### Deep Mode directory options parse
Verify that Deep Mode commands accept the documented `--dir` workspace option.

### Deep Mode requirements parse as separate values
Verify that `deep-init --requirements` preserves each independently supplied requirement.

### Missing jsonschema reports installation guidance
Verify that architecture validation gives a `jsonschema` install command that works regardless of the caller's current directory.

### jsonschema is declared as a runtime dependency
Verify that `jsonschema` is listed in the Polyglot runtime requirements.

### License compatibility engine
Verify that `license.py` correctly classifies SPDX identifiers into the right reuse mode categories.

## Issue 59 Phase 2

Regression tests for bridge mapping integrity and generator status live in `test_issue59_phase2.py`.

### Bridge requires reviewed mappings or explicit scaffold mode
Verify that an empty mapping set cannot generate files by default, while `--scaffold-only` emits an explicitly labeled scaffold.

### Only reviewed mappings reach generation
Verify that unreviewed candidates do not enter the serialized schema or generated wrapper, and reviewed Python mappings forward named parameters correctly.

### Bridge rejects invalid input and unsupported language pairs
Verify malformed mapping JSON and unsupported generator language combinations return machine-readable errors before creating output.

### Python mapping calls execute against fixture modules
Compile and execute generated Python glue against temporary source/destination fixture modules to verify the supported vertical slice.

### Verification distinguishes syntax from runtime checks
Verify Python syntax checks pass independently while runtime execution is reported as `not_run` by the structural verifier.

### MVP scoping produces P0/P1/P2
Verify that `mvp-scope` assigns priority levels to features and produces a sorted output.

## Dependencies

tests 模块依赖的 polyglot 子模块。

- [[backends]] — Tests call scout/audit commands
- [[deep]] — Tests call deep-init/validate commands
- [[glue]] — Tests call mvp-scope command
