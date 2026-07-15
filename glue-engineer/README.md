# glue-engineer v4 — Claude Code-native Deep Mode

> **From "Know What" to "Know How"** — Automatically discover, deeply analyze, and build integration plans for open-source libraries across 6 ecosystems (Python/JS/Rust/Java/Kotlin/C/C++).

## Overview

glue-engineer v4 is a Claude Code skill that orchestrates a multi-phase pipeline:

| Phase | What happens | Output |
|:-----:|-------------|--------|
| **1** | `deep-init` → `deep-pack` → **parallel subagents** → `deep-validate` | Per-repo architecture reports (`architecture.json`, `architecture.md`, `source_manifest.json`, `unresolved.md`) |
| **2** | `deep-compare` → `deep-summarize` | Coverage matrix, repo ranking, `comparison.json`, `final-report-draft.md` |
| **3** | **glue-reuse-mapper** subagent → `deep-validate --include-reuse-map` | Reuse candidates with license compatibility (`reuse-map.json`, `reuse-map.md`) |
| **4** | **glue-integration-planner** → **glue-synthesizer** → `deep-summarize` | Integration plan (`integration-plan.json`), final recommendation (`final-recommendation.md`) |
| **5** | `deep-clean` | Clean cloned repos, keep reports |

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User (Claude Code session)                │
│                                                              │
│   Main agent ← SKILL.md rules ← ASK user ← schedule v3/v4  │
└───────────────────────┬─────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌──────────────┐ ┌───────────┐ ┌───────────────┐
│ Claude Code  │ │ polyglot  │ │ .claude/      │
│ Subagents    │ │ CLI       │ │ settings.json │
│              │ │           │ │               │
│ glue-repo-   │ │ deep-init │ │ permissions   │
│ architect    │ │ deep-pack │ │ allow/ask/    │
│              │ │ deep-vali │ │ deny          │
│ glue-reuse-  │ │ date      │ │               │
│ mapper       │ │ deep-comp │ │               │
│              │ │ are       │ │               │
│ glue-integra │ │ deep-summ │ │               │
│ tion-planner │ │ arize     │ │               │
│              │ │ deep-clean│ │               │
│ glue-synthe- │ │           │ │               │
│ sizer        │ │           │ │               │
└──────────────┘ └───────────┘ └───────────────┘
```

---

## Installation

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
- Python 3.10+
- Git

### 1. Install the Skill

Clone or copy the `glue-engineer` skill directory into your Claude Code skills path:

```bash
# Default skills location
cp -r glue-engineer ~/.claude/skills/
```

### 2. Install Subagent Definitions

Copy the subagent definitions so Claude Code can spawn them:

```bash
mkdir -p ~/.claude/agents/
cp agents/*.md ~/.claude/agents/
```

After installation, you should see 4 agents when you run `/agents` in Claude Code:
- `glue-repo-architect` — Deep repository architecture analysis
- `glue-reuse-mapper` — Code reuse candidate extraction with license checks
- `glue-integration-planner` — Integration route planning
- `glue-synthesizer` — Final report synthesis

### 3. (Optional) Install Permissions

Copy the permissions settings to avoid repetitive prompts:

```bash
cp .claude/settings.json ~/.claude/settings.json
```

Or merge the permissions into your existing settings.

### 4. Verify Installation

```bash
# Check polyglot CLI works (from any directory — no need to cd to glue-engineer)
python <path-to-glue-engineer>/polyglot/__main__.py --help
# Or: PYTHONPATH=<path-to-glue-engineer> python -m polyglot --help

# Subcommands should include:
#   deep-init      Create workspace + clone repos
#   deep-pack      Generate subagent task prompts
#   deep-validate  Validate subagent outputs
#   deep-compare   Compare repo architecture reports
#   deep-summarize Generate report draft
#   deep-clean     Clean cloned repos
```

---

## Quick Start

### End-to-End v4 Flow

```bash
# 1. Create workspace and clone candidate repos
python -m polyglot deep-init \
  --project "keyboard-remapper" \
  --requirements "device detection,cycle layer switching,macro support" \
  --target-license MIT \
  --repos https://github.com/jtroo/kanata https://github.com/qmk/qsk

# 2. Generate task prompts for subagents
python -m polyglot deep-pack .glue/deep/

# 3. (In Claude Code) Spawn subagents in parallel
#    Spawn one glue-repo-architect per repo
#    → They read source code, write architecture reports
#    → They return only short summaries

# 4. Validate subagent outputs
python -m polyglot deep-validate .glue/deep/

# 5. Generate comparison matrix
python -m polyglot deep-compare .glue/deep/

# 6. Generate report draft
python -m polyglot deep-summarize .glue/deep/

# 7. (In Claude Code) Spawn glue-reuse-mapper for reuse analysis
#    → Spawn glue-integration-planner for integration plans
#    → Spawn glue-synthesizer for final recommendation

# 8. Validate including reuse maps
python -m polyglot deep-validate .glue/deep/ --include-reuse-map

# 9. Clean up cloned repos when done
python -m polyglot deep-clean .glue/deep/
python -m polyglot deep-clean .glue/deep/ --all   # also clean tasks/ and logs/
```

### Session File

All state is tracked in `.glue/deep/session.json`:

```json
{
  "project": "keyboard-remapper",
  "requirements": ["device detection", "cycle layer switching"],
  "target_license": "MIT",
  "candidate_repos": [
    { "name": "kanata", "url": "https://github.com/jtroo/kanata", "slug": "kanata",
      "local_path": ".glue/deep/repos/kanata/source", "commit": "40a8b17" }
  ],
  "workflow": "glue-engineer-v4"
}
```

---

## CLI Reference

### `deep-init`

Create workspace and clone candidate repos.

```bash
python -m polyglot deep-init \
  --project <name> \
  --requirements "<req1>,<req2>" \
  --target-license <SPDX> \
  --repos <url1> <url2>
```

**Args:**
- `dir` — Workspace directory (default: `.glue/deep`)
- `--project` — Project name (required)
- `--requirements` — Comma-separated list (required)
- `--target-license` — SPDX identifier (default: `""`)
- `--repos` — GitHub URL(s) to clone

### `deep-pack`

Generate task prompt files for subagents.

```bash
python -m polyglot deep-pack [dir]
```

### `deep-validate`

Validate subagent architecture outputs.

```bash
python -m polyglot deep-validate [dir]
python -m polyglot deep-validate [dir] --include-reuse-map   # also check reuse maps
```

**Checks:**
- `architecture.md` exists
- `architecture.json` is valid JSON with all required fields
- `confidence` in range 0-1
- `evidence` non-empty with file/line references
- `source_manifest.json` exists
- `unresolved.md` exists
- With `--include-reuse-map`: also validates `reuse-map.json` (candidate structure, reuse_mode enum, confidence range)

### `deep-compare`

Generate structured comparison between repos.

```bash
python -m polyglot deep-compare [dir]
```

**Outputs:** `comparison.json` + `comparison.md` with coverage matrix and ranking.

### `deep-summarize`

Generate draft report from all available artifacts.

```bash
python -m polyglot deep-summarize [dir]
```

**Output:** `final-report-draft.md`

### `deep-clean`

Clean cloned repos but keep architecture reports.

```bash
python -m polyglot deep-clean [dir]
python -m polyglot deep-clean [dir] --all   # also clean tasks/ and logs/
```

### v3 Commands (still available)

```bash
python -m polyglot scout python "pdf parser"
python -m polyglot scout rust "serialization"
python -m polyglot cross-search "json parser" --languages python,rust
python -m polyglot cap-list
python -m polyglot cap-match python orjson rust serde_json
python -m polyglot bridge python orjson rust serde_json
```

---

## Subagent Definitions

All subagents are defined in `agents/*.md`. Each has:

| Agent | Max Turns | Color | Purpose |
|-------|:---------:|:-----:|---------|
| `glue-repo-architect` | 25 | cyan | Deep single-repo architecture analysis |
| `glue-reuse-mapper` | 20 | green | Extract reusable code with license checks |
| `glue-integration-planner` | 15 | purple | Integration route planning (fork vs compose vs build) |
| `glue-synthesizer` | 10 | orange | Final user-facing recommendation |

### Output Protocol

Every subagent must:
1. **Write full reports to disk** (under `.glue/deep/`)
2. **Return only a short summary** to the main agent (< 10 lines)
3. **Never** paste full reports into the main conversation context

---

## Directory Structure

```
glue-engineer/
├── SKILL.md                              # Skill definition
├── README.md                             # This file
├── agents/                               # Claude Code subagent definitions
│   ├── glue-repo-architect.md            # Phase 1
│   ├── glue-reuse-mapper.md              # Phase 3
│   ├── glue-integration-planner.md       # Phase 4
│   └── glue-synthesizer.md               # Phase 4
├── polyglot/
│   ├── __main__.py
│   ├── router.py                         # CLI dispatcher
│   ├── deep/                             # v4 deep mode module
│   │   ├── outputs.py                    # Workspace management
│   │   ├── repo_resolver.py              # URL parsing + git clone
│   │   ├── packager.py                   # Task prompt generation
│   │   ├── validator.py                  # Artifact validation
│   │   ├── comparer.py                   # Coverage matrix + ranking
│   │   ├── summarizer.py                 # Report draft generation
│   │   ├── license.py                    # License compatibility engine
│   │   └── schemas/
│   │       ├── session.schema.json
│   │       ├── architecture.schema.json
│   │       ├── source-manifest.schema.json
│   │       ├── comparison.schema.json
│   │       ├── reuse-map.schema.json
│   │       └── integration-plan.schema.json
│   ├── glue/                             # v3 glue engine
│   ├── common/                           # Shared infrastructure
│   ├── backends/                         # 6 language backends
│   └── ...
├── .claude/settings.json                 # Permission whitelist
├── evals/                                # Eval checklists
│   ├── phase-1-checklist.md
│   ├── phase-2-checklist.md
│   ├── phase-3-checklist.md
│   ├── phase-4-checklist.md
│   └── phase-5-checklist.md
└── scripts/                              # Setup hooks
    ├── setup.sh
    └── setup.ps1
```

---

## License Compatibility Engine

The `polyglot/deep/license.py` module provides deterministic license checks (no LLM needed):

| Category | Identifiers | Compatible With |
|----------|------------|----------------|
| **Permissive** | MIT, Apache-2.0, BSD, CC0-1.0, Unlicense, ISC | Everything (copy) |
| **Weak Copyleft** | LGPL-2.1, LGPL-3.0, MPL-2.0 | Permissive (port), Strong Copyleft (copy) |
| **Strong Copyleft** | GPL-2.0, GPL-3.0, AGPL-3.0 | Only same-license (copy) |
| **Proprietary** | Unrecognized SPDX | Avoid |

**Reuse modes:**
- `copy` — Safe to copy verbatim (with attribution)
- `port` — Adapt to target language, keep notices
- `wrap` — Use as dependency
- `reference_only` — Study design only, don't copy
- `avoid` — License conflict, do not reuse

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `deep-init` clones fail | Ensure GitHub is reachable. Use shorter repo list. |
| Subagent has no Write permission | Verify `permissionMode: default` in the agent definition |
| `deep-validate` shows all `x` | Subagents haven't run yet — this is expected |
| Permission prompts during flow | Install `.claude/settings.json` to whitelist common commands |
| `deep-compare` has no data | Run `deep-validate` first to confirm reports exist |
| GBK encoding errors | Run `set PYTHONIOENCODING=utf-8` before Python commands |

---

## Development

### Running Tests

```bash
cd polyglot
python -m pytest tests/
```

### Adding a New Schema

1. Create `polyglot/deep/schemas/<name>.schema.json`
2. Add validation to `polyglot/deep/validator.py`
3. Update relevant subagent definition to reference the schema

### File Naming Convention

- Schema files: `kebab-case.schema.json` (e.g., `reuse-map.schema.json`)
- Python modules: `snake_case.py` (e.g., `reuse_map` → `license.py`)
- Agent definitions: `kebab-case.md` (e.g., `glue-repo-architect.md`)
- JSON keys: `snake_case` (e.g., `"reuse_mode"`)

---

*glue-engineer v4 — From "Know What" to "Know How"*
*See [glue-engineer-v4-plan.md](./glue-engineer-v4-plan.md) for the full design document.*