# Phase 3 Eval Checklist — Reuse Map + License Checks

**Goal**: After Phase 1-2 reports exist, run glue-reuse-mapper and validate with `--include-reuse-map`

## Prerequisites

- [ ] Phase 1-2 pass (architecture reports + comparison exist)
- [ ] `polyglot/deep/license.py` module is importable

## Step 1: License Module Verification

```bash
python -c "from polyglot.deep.license import get_category, reuse_mode_for_license"
```

**Checklist:**

- [ ] `get_category("MIT")` returns `"permissive"`
- [ ] `get_category("GPL-3.0")` returns `"strong_copyleft"`
- [ ] `get_category("LGPL-3.0")` returns `"weak_copyleft"`
- [ ] `get_category("")` returns `"unknown"`
- [ ] `get_category("Unrecognized")` returns `"proprietary"`
- [ ] `reuse_mode_for_license("MIT", "GPL-3.0")` returns `"copy"`
- [ ] `reuse_mode_for_license("LGPL-3.0", "MIT")` returns `"port"`
- [ ] `reuse_mode_for_license("GPL-3.0", "MIT")` returns `"reference_only"`
- [ ] `reuse_mode_for_license("GPL-3.0", "proprietary")` returns `"avoid"`
- [ ] `is_copyleft("LGPL-3.0")` returns `True`
- [ ] `is_strong_copyleft("LGPL-3.0")` returns `False`
- [ ] `is_strong_copyleft("GPL-3.0")` returns `True`

## Step 2: Spawn glue-reuse-mapper

_In Claude Code: spawn one glue-reuse-mapper subagent per repo (parallel)_

**Checklist:**

- [ ] Subagent reads architecture reports first (does NOT re-analyze source)
- [ ] For each candidate, records: file, line_start, line_end, symbol, purpose
- [ ] For each candidate, records: reuse_mode (copy/port/wrap/reference_only/avoid)
- [ ] For each candidate, records: source_license, license_note
- [ ] For each candidate, records: adaptation_steps, confidence, evidence
- [ ] GPL/AGPL candidates not marked as `copy` unless target is also GPL
- [ ] MIT candidates marked as `copy` for MIT target
- [ ] License usage is explained (not just SPDX identifier)
- [ ] Subagent returns short summary to main agent

## Step 3: deep-validate --include-reuse-map

```bash
python -m polyglot deep-validate deep-output/ --include-reuse-map
```

**Checklist:**

- [ ] `reuse-map.json` present for at least one repo
- [ ] `reuse-map.json` contains: repo, slug, candidates
- [ ] Each candidate has valid `reuse_mode` enum value
- [ ] Each candidate has `confidence` in 0.0-1.0 range
- [ ] Each candidate has valid line range (line_start ≤ line_end, both > 0)
- [ ] Each candidate has source_license (even if empty string)
- [ ] `reuse-map.md` present alongside JSON
- [ ] Repos without reuse-map show `[-]` (not `[x]`)
- [ ] Invalid reuse_mode shows `[!]` warning
- [ ] Exit code is 0

## Step 4: License Edge Cases

**Checklist:**

- [ ] Empty/missing license field → `unknown` category
- [ ] `"Proprietary"` text → `proprietary` category → `avoid` for all targets
- [ ] All 5 reuse modes are represented in the output across all repos

## Final Score

**Pass:** ___ / ___ checks  **Fail:** ___ failures

**Notes:** _________________________________________________________________