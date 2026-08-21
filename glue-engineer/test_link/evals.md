# evals

Evaluation checklists (`evals/`) for validating each phase of the glue-engineer pipeline. Used during development and testing to ensure completeness.

## Phase Checklists

各个阶段的评估清单，覆盖 glue-engineer 管道的所有环节。

### Phase 1: Search
Checklist: `phase-1-checklist.md`
Verifies that scout and cross-search return correct results with proper format.

### Phase 2: Analysis
Checklist: `phase-2-checklist.md`
Verifies that analysis results are complete and accurate.

### Phase 3: Reuse Mapping
Checklist: `phase-3-checklist.md`
Verifies that reuse candidates are correctly identified with license compatibility.

### Phase 4: Integration Planning
Checklist: `phase-4-checklist.md`
Verifies that integration plans are complete and realistic.

### Phase 5: Synthesis
Checklist: `phase-5-checklist.md`
Verifies that final recommendations are comprehensive and actionable.

## Dependencies

evals 模块依赖的 polyglot 模块。

- [[polyglot]] — All checklists reference polyglot CLI commands
- [[agents]] — Deep Mode checklists reference subagent outputs