# Phase 4 Eval Checklist — Integration Plan + Final Synthesis

**Goal**: After Phase 1-3 reports exist, run glue-integration-planner → glue-synthesizer → enhanced deep-summarize

## Prerequisites

- [ ] Phase 1-3 pass (architecture + comparison + reuse-map exist)
- [ ] `polyglot/deep/schemas/integration-plan.schema.json` exists and is valid

## Step 1: Spawn glue-integration-planner

_In Claude Code: spawn one glue-integration-planner subagent_

**Checklist:**

- [ ] Subagent reads from `deep-output/` only (does NOT read source)
- [ ] Subagent reads: architecture.json, reuse-map.json, comparison.md
- [ ] Outputs `deep-output/integration-plan.json`
- [ ] Outputs `deep-output/integration-plan.md`
- [ ] Integration plan includes: `recommended_route` (direct_use/fork/compose/build)
- [ ] Includes route rationale explaining the choice
- [ ] Includes decision matrix with criteria, scores, weights, evidence
- [ ] Includes implementation roadmap with ordered steps
- [ ] Each roadmap step has: effort (low/medium/high), confidence (0-1), dependencies
- [ ] Includes first PR plan (smallest meaningful integration)
- [ ] First PR plan lists files to change with action (create/modify/delete)
- [ ] Includes risks with likelihood, impact, mitigation
- [ ] Includes validation checklist with categories (functional/build/license/etc.)
- [ ] Subagent returns short summary to main agent

## Step 2: deep-summarize (integration section)

```bash
python -m polyglot deep-summarize deep-output/
```

**Checklist:**

- [ ] `final-report-draft.md` contains "Integration Plans" section
- [ ] Integration section shows: recommended route per repo
- [ ] Shows decision matrix (criteria + scores)
- [ ] Shows roadmap (top 3 steps)
- [ ] Shows first PR plan
- [ ] Shows risks
- [ ] Exit code is 0

## Step 3: Spawn glue-synthesizer

_In Claude Code: spawn one glue-synthesizer subagent_

**Checklist:**

- [ ] Subagent reads from `deep-output/` only
- [ ] Reads: session.json, final-report-draft.md, comparison.json, integration-plan.json
- [ ] Reads: architecture.json for each repo
- [ ] Does NOT read repository source code
- [ ] Outputs `deep-output/final-recommendation.md`
- [ ] Final recommendation includes: executive summary (1 paragraph)
- [ ] Includes: decision summary table with scores
- [ ] Includes: requirements coverage matrix
- [ ] Includes: recommended route with what to take from each repo
- [ ] Includes: implementation roadmap (high-level, 3-5 steps)
- [ ] Includes: risks and mitigations (top 3)
- [ ] Includes: concrete next steps for the user
- [ ] Subagent returns short summary to main agent

## Step 4: Validate integration-plan JSON schema

```bash
python -c "
import json
from polyglot.deep.validator import validate_reuse_map  # integration schema check
# Manual validation:
plan = json.load(open('deep-output/integration-plan.json'))
assert plan['recommended_route'] in ('direct_use', 'fork', 'compose', 'build')
assert len(plan['decision_matrix']) > 0
assert len(plan['implementation_roadmap']) > 0
assert 'first_pr_plan' in plan
print('[v] Integration plan schema valid')
"
```

**Checklist:**

- [ ] JSON validates against schema
- [ ] All required fields present

## Final Score

**Pass:** ___ / ___ checks  **Fail:** ___ failures

**Notes:** _________________________________________________________________