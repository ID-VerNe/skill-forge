# deep

v4 Deep Mode module (`polyglot/deep/`), implementing the end-to-end deep analysis pipeline: workspace creation, repo cloning, subagent task generation, validation, comparison, and summary.

## Key Concepts

Deep Mode 的核心概念：管道阶段、工作空间、验证、比较、许可证兼容性。

### Pipeline Stages

The Deep Mode pipeline follows a fixed sequence of stages, each implemented by a dedicated module:

1. **deep-init** (`outputs.py`) — Create workspace directory, clone candidate repos, write session.json
2. **deep-pack** (`packager.py`) — Generate task prompt files for each subagent
3. **Subagent Execution** (outside `polyglot/`) — Claude Code subagents read task prompts, write architecture reports
4. **deep-validate** (`validator.py`) — Validate subagent outputs against JSON Schema requirements
5. **deep-compare** (`comparer.py`) — Generate coverage matrix and repo ranking
6. **deep-summarize** (`summarizer.py`) — Generate final report draft
7. **deep-clean** (`outputs.py`) — Clean cloned repos, keep reports

### Workspace

All Deep Mode state is tracked in `.glue/deep/session.json`. The workspace contains cloned repos (under `repos/`), subagent task prompts (under `tasks/`), and generated reports.

Reference: [[polyglot/deep/outputs.py]]

### Validation

`validator.py` checks that subagent outputs meet minimum requirements:
- `architecture.md` exists
- `architecture.json` is valid JSON with required fields (confidence, evidence)
- `source_manifest.json` exists
- `unresolved.md` exists

With `--include-reuse-map`, also validates `reuse-map.json` structure.

Reference: [[polyglot/deep/validator.py]]

### Comparison

`comparer.py` generates a coverage matrix comparing all repos across dimensions (architecture, features, API surface, etc.), then ranks repos by coverage score.

Reference: [[polyglot/deep/comparer.py]]

### License Compatibility

`license.py` provides deterministic license checks without LLM calls. Uses a pre-defined compatibility matrix mapping SPDX identifiers to reuse modes (copy/port/wrap/reference_only/avoid).

Reference: [[polyglot/deep/license.py]]

## Dependencies

deep 模块依赖的其他模块。

- [[common]] — Schema validation, git operations, platform detection
- [[polyglot]] — CLI subcommand registration

## Consumed By

哪些模块使用 deep 模块。

- [[Project]] — User-facing Deep Mode workflow
- [[scripts]] — Setup scripts that configure the environment

## Schemas

All JSON Schema files are in `polyglot/deep/schemas/`:
- `session.schema.json` — Workspace session validation
- `architecture.schema.json` — Architecture report validation
- `source-manifest.schema.json` — Source manifest validation
- `comparison.schema.json` — Comparison matrix validation
- `reuse-map.schema.json` — Reuse map validation
- `integration-plan.schema.json` — Integration plan validation

## Error Conditions

deep 模式可能遇到的错误条件。

- `CLONE_FAILED` — Git clone of a candidate repo failed. Resolution: check network connectivity and repo URL.
- `VALIDATION_FAILED` — Subagent output missing required fields. Resolution: re-run subagent with corrected prompt.
- `LICENSE_CONFLICT` — Target license incompatible with candidate repo. Resolution: choose different candidate or accept `reference_only` reuse mode.