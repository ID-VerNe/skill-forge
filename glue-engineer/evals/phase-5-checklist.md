# Phase 5 Eval Checklist — UX Hardening

**Goal**: Verify install scripts, README, deep-clean, permissions, and overall UX

## Prerequisites

- [ ] Phase 1-4 pass
- [ ] README.md exists at skill root

## Step 1: README Verification

**Checklist:**

- [ ] README.md exists at `glue-engineer/README.md`
- [ ] Contains: description of what glue-engineer v4 is
- [ ] Contains: installation instructions
- [ ] Contains: quick start example with CLI commands
- [ ] Contains: full CLI reference for all 7 deep commands
- [ ] Contains: subagent reference table (4 agents)
- [ ] Contains: directory structure diagram
- [ ] Contains: license compatibility reference
- [ ] Contains: troubleshooting section
- [ ] All CLI commands in README match actual `python -m polyglot --help` output
- [ ] All agent names in README match actual `agents/*.md` files
- [ ] README references consistent paths (no stale references to old file locations)

## Step 2: deep-clean Verification

```bash
# Create test workspace
python -m polyglot deep-init --project "clean-test" --requirements "test" --repos https://github.com/jtroo/kanata
# Run clean
python -m polyglot deep-clean deep-output/ --force
# Verify
ls deep-output/repos/kanata/source/  # should fail (source removed)
ls deep-output/repos/kanata/architecture.json  # should exist (report preserved)
```

**Checklist:**

- [ ] `deep-clean` removes `source/` directory
- [ ] `deep-clean` preserves `architecture.json`, `architecture.md`, etc.
- [ ] `deep-clean --all` also removes `tasks/` and `logs/`
- [ ] `deep-clean --all` preserves `repos/<slug>/*.json` and `*.md`
- [ ] `deep-clean --force` skips confirmation prompt
- [ ] `deep-clean` on empty workspace shows helpful message (not crash)
- [ ] `deep-clean` on workspace without session.json still cleans repos/ dir

## Step 3: Permission Settings

**Checklist:**

- [ ] `.claude/settings.json` exists in skill root
- [ ] Permissions file is valid JSON
- [ ] `allow` includes: git clone, find, rg, mkdir -p deep-output*, python -m polyglot
- [ ] `allow` includes: Read, Grep, Glob, Write
- [ ] `deny` includes: cargo build, cargo run, npm install, pip install, docker
- [ ] `ask` includes: rm, mkdir (without -p deep-output)

## Step 4: Agent Definitions Consistency

**Checklist:**

- [ ] All 4 agent files exist in `agents/`:
  - `glue-repo-architect.md`
  - `glue-reuse-mapper.md`
  - `glue-integration-planner.md`
  - `glue-synthesizer.md`
- [ ] Each agent has valid YAML frontmatter
- [ ] Each agent has `name:` field matching filename (without .md)
- [ ] Each agent has `permissionMode: default`
- [ ] Each agent restricts Write to `deep-output/`
- [ ] Each agent has clear final response format (< 10 lines)
- [ ] No agent references paths that don't exist
- [ ] maxTurns are reasonable (25/20/15/10 descending)

## Step 5: polyglot CLI Completeness

```bash
python -m polyglot --help
```

**Checklist:**

- [ ] All 7 deep commands listed: init, pack, validate, compare, summarize, clean
- [ ] v3 commands also listed: scout, audit, analyze, cross-search, cap-list, cap-match, bridge, strategies
- [ ] No command has broken argparse definitions
- [ ] All default arguments work (e.g., `python -m polyglot deep-validate` defaults to `deep-output/`)

## Step 6: Error Message UX

**Checklist:**

- [ ] `deep-validate` on empty workspace shows clear error ("No session.json found")
- [ ] `deep-compare` on workspace without reports shows clear message
- [ ] `deep-summarize` on workspace without reports shows clear message
- [ ] `deep-clean` on empty workspace shows "nothing to clean" (not a traceback)
- [ ] No unhandled Python exceptions in normal error flows

## Final Score

**Pass:** ___ / ___ checks  **Fail:** ___ failures

**Notes:** _________________________________________________________________