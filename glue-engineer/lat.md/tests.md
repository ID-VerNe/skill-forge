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
Verify that architecture validation reports how to install `jsonschema` when it is unavailable.

### jsonschema is declared as a runtime dependency
Verify that `jsonschema` is listed in the Polyglot runtime requirements.

### License compatibility engine
Verify that `license.py` correctly classifies SPDX identifiers into the right reuse mode categories.

### MVP scoping produces P0/P1/P2
Verify that `mvp-scope` assigns priority levels to features and produces a sorted output.

## Dependencies

tests 模块依赖的 polyglot 子模块。

- [[backends]] — Tests call scout/audit commands
- [[deep]] — Tests call deep-init/validate commands
- [[glue]] — Tests call mvp-scope command
