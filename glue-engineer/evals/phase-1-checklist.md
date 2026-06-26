# Phase 1 Eval Checklist — Single Repo Vertical Slice

**Goal**: Run one repo through `deep-init` → `deep-pack` → spawn glue-repo-architect → `deep-validate`

## Prerequisites

- [ ] Python 3.10+
- [ ] Git installed and GitHub accessible
- [ ] `python -m polyglot --help` shows all 7 deep commands

## Step 1: deep-init

```bash
python -m polyglot deep-init \
  --project "test-project" \
  --requirements "device detection,cycle layer switching" \
  --target-license MIT \
  --repos https://github.com/jtroo/kanata
```

**Checklist:**

- [ ] `deep-output/` directory created
- [ ] `deep-output/session.json` exists and is valid JSON
- [ ] `session.json` contains: `project`, `requirements`, `target_license`, `candidate_repos`
- [ ] `deep-output/repos/kanata/` directory created
- [ ] `deep-output/tasks/` directory created
- [ ] `deep-output/logs/` directory created
- [ ] commit hash recorded in session.json

## Step 2: deep-pack

```bash
python -m polyglot deep-pack deep-output/
```

**Checklist:**

- [ ] `deep-output/tasks/kanata.architect.task.md` exists
- [ ] Task file contains: project name, requirements, repo path
- [ ] Task file references output paths (architecture.md, architecture.json, etc.)

## Step 3: Spawn glue-repo-architect (simulated)

_In Claude Code: spawn one glue-repo-architect subagent for kanata_

**Checklist:**

- [ ] Subagent reads source code (no artificial file count limit)
- [ ] Subagent does NOT install/build/run
- [ ] Subagent does NOT modify source files
- [ ] Subagent writes to `deep-output/repos/kanata/` only
- [ ] Subagent returns short summary (< 10 lines) to main agent

## Step 4: deep-validate

```bash
python -m polyglot deep-validate deep-output/
```

**Checklist:**

- [ ] `architecture.md` exists and is non-empty
- [ ] `architecture.json` is valid JSON
- [ ] Architecture JSON has all required fields:
  - `repo`, `slug`, `source_path`, `commit`, `one_line_summary`
  - `core_modules`, `key_types`, `platform_apis`, `known_gaps`
  - `confidence` (0.0-1.0), `evidence` (non-empty)
- [ ] `confidence` is a number in 0.0-1.0 range
- [ ] `evidence` non-empty, each entry has `claim`, `file`, `line_start`, `line_end`
- [ ] `source_manifest.json` exists
- [ ] `unresolved.md` exists
- [ ] Exit code is 0
- [ ] Output shows `[v]` for all checks, no `[x]`

## Deep-Clean (verify cleanup)

```bash
python -m polyglot deep-clean deep-output/
```

- [ ] Source directories removed
- [ ] Reports preserved (architecture.json, architecture.md remain)
- [ ] Confirmation prompt shown

## Final Score

**Pass:** ___ / ___ checks  **Fail:** ___ failures

**Notes:** _________________________________________________________________