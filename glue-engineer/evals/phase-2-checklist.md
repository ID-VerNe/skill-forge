# Phase 2 Eval Checklist — Multi-Repo Parallel + Comparison

**Goal**: Run 3 repos through full Phase 2 pipeline with parallel subagents

## Prerequisites

- [ ] Phase 1 checklist passes for at least one repo
- [ ] Python 3.10+, git

## Step 1: deep-init (3 repos)

```bash
python -m polyglot deep-init \
  --project "multi-repo-test" \
  --requirements "config parsing,device detection,cycle layer switching,macro support" \
  --target-license MIT \
  --repos https://github.com/jtroo/kanata https://github.com/qmk/qsk
```

**Checklist:**

- [ ] All 3 repo source directories exist
- [ ] All 3 repos recorded in session.json candidate_repos
- [ ] Commit hashes recorded
- [ ] `.glue/deep/tasks/` and `.glue/deep/logs/` created

## Step 2: deep-pack

```bash
python -m polyglot deep-pack .glue/deep/
```

**Checklist:**

- [ ] Task file exists for each repo (`<slug>.architect.task.md`)
- [ ] Each task file has correct local_path to its source

## Step 3: Parallel Subagents

_In Claude Code: spawn N glue-repo-architect subagents simultaneously (one per repo)_

**Checklist:**

- [ ] All subagents launched in same turn (parallel via Agent tool)
- [ ] Each subagent independently writes 4 artifacts
- [ ] Each subagent returns short summary to main agent
- [ ] No subagent accesses another repo's source
- [ ] All complete within reasonable time

## Step 4: deep-validate

```bash
python -m polyglot deep-validate .glue/deep/
```

**Checklist:**

- [ ] Each repo shows all `[v]` checks
- [ ] If a repo failed, `[x]` marker is present for the specific failure
- [ ] Exit code is 0 if all pass, 1 if any fail
- [ ] Validation output is per-repo, not a single blob

## Step 5: deep-compare

```bash
python -m polyglot deep-compare .glue/deep/
```

**Checklist:**

- [ ] `.glue/deep/comparison.json` created
- [ ] `.glue/deep/comparison.md` created
- [ ] Coverage matrix exists with all repos × all requirements
- [ ] Matrix shows each repo's status per requirement (supported/partial/missing)
- [ ] Ranking present (sorted by score)
- [ ] Scoring formula: 0.6×confidence + 0.4×evidence_coverage (roughly)
- [ ] Comparison includes: language comparison, license comparison

## Step 6: deep-summarize

```bash
python -m polyglot deep-summarize .glue/deep/
```

**Checklist:**

- [ ] `.glue/deep/final-report-draft.md` created
- [ ] Contains: requirements list, repo-by-repo summaries, coverage matrix
- [ ] Contains: ranking, evidence counts, known gaps
- [ ] Contains: summary section with top candidate
- [ ] Contains: next steps section
- [ ] Does NOT contain LLM-generated analysis (pure template filling)

## Final Score

**Pass:** ___ / ___ checks  **Fail:** ___ failures

**Notes:** _________________________________________________________________