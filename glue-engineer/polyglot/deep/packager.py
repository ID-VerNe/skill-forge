"""polyglot/deep/packager.py — Generate subagent task prompt files from session."""

import os
import json


def build_architect_task(session: dict, repo_entry: dict, workspace_dir: str) -> str:
    """Build a .architect.task.md prompt string for glue-repo-architect.

    Args:
        session: Loaded session dict
        repo_entry: Single repo entry from session['candidate_repos']
        workspace_dir: Absolute path to .glue/deep/

    Returns:
        Markdown task prompt string
    """
    slug = repo_entry["slug"]
    requirements = session.get("requirements", [])
    req_list = "\n".join(f"{i+1}. {r}" for i, r in enumerate(requirements))

    return f"""---
task: glue-repo-architect
project: {session['project']}
repo: {repo_entry['name']}
slug: {slug}
---

## Analysis Target

**Repository**: {repo_entry['name']} ({repo_entry['url']})
**Local source path**: {repo_entry['local_path']}
**Commit**: {repo_entry.get('commit', 'unknown')}

## Requirements

{req_list}

## Output Paths

Write all outputs to: {os.path.join(workspace_dir, 'repos', slug)}

| Artifact | Path |
|----------|------|
| Architecture narrative | {os.path.join(workspace_dir, 'repos', slug, 'architecture.md')} |
| Structured summary | {os.path.join(workspace_dir, 'repos', slug, 'architecture.json')} |
| Source manifest | {os.path.join(workspace_dir, 'repos', slug, 'source_manifest.json')} |
| Unresolved questions | {os.path.join(workspace_dir, 'repos', slug, 'unresolved.md')} |

## Rules

1. Read as many relevant files as needed — no artificial limits.
2. Do NOT install dependencies, build, or run the project.
3. Do NOT modify files under the source directory.
4. **Write permission is ONLY for `.glue/deep/`**.
5. Every claim must cite file paths and line numbers.
6. **`architecture.json` MUST populate all required fields** (no need to open the schema file — they are listed here, and the schema is enforced strictly):
   - `repo` (string) — repository name
   - `slug` (string) — filesystem-safe slug
   - `source_path` (string) — local path to the cloned source
   - `commit` (string) — HEAD commit hash at analysis time
   - `one_line_summary` (string) — one sentence describing the project
   - `language` (string) — primary implementation language (e.g. "Python", "Rust", "Go", "TypeScript")
   - `core_modules` (array) — 3 to 10 major modules, each {{`name`, `path`, `purpose`}}
   - `key_types` (array, non-empty) — key structs/enums/traits/interfaces, each {{`name`, `kind`, `file`, `line`, `purpose`}}
   - `platform_apis` (array) — OS-specific API usage, each {{`api`, `purpose`, `file`, `line`}} (use `[]` if genuinely none)
   - `known_gaps` (array, non-empty) — **for EVERY requirement in the Requirements section above**, one entry {{`requirement`, `status`, `details`, `effort`}}. MUST use the exact field names `requirement` and `status` — NOT custom names like `gap`, `severity`, or `requirement_id`. `status` ∈ `supported`/`partial`/`missing`, `effort` ∈ `low`/`medium`/`high`/`unknown`
   - `confidence` (number 0.0-1.0) — MUST be a plain number (e.g. `0.9`), NOT an object with `overall`/`notes` keys
   - `evidence` (array, non-empty) — every entry MUST have `claim` (string), `file` (string), `line_start` (integer), `line_end` (integer) — NOT a `lines` string like "1808,1824,1841"
7. `confidence` must be in range 0.0-1.0.
8. `evidence` array must be non-empty.
9. If unsure about anything, write it in `unresolved.md`.
10. Final response to main agent must be SHORT — do not paste full report.
11. **File size awareness**: Before reading a file, check its size with `ls -la` or Glob. Files > 5000 lines or > 100KB MUST be read selectively: use Grep to locate key symbols first, then Read with `offset`/`limit`. Skip test files (`*_test.go`, `test_*.py`, `tests/`, `*_test.rs`), generated files, vendor directories, and lockfiles.

## Final Response Format

```
Done: analyzed {repo_entry['name']}.
Files written:
- .glue/deep/repos/{slug}/architecture.md
- .glue/deep/repos/{slug}/architecture.json
- .glue/deep/repos/{slug}/source_manifest.json
- .glue/deep/repos/{slug}/unresolved.md

Confidence: <0-1>
Key gaps: <brief summary>
```
"""


def generate_tasks(workspace_dir: str) -> list:
    """Read session.json and generate .architect.task.md for each repo.

    Args:
        workspace_dir: Absolute path to .glue/deep/

    Returns:
        List of (slug, task_path) tuples
    """
    from polyglot.deep.outputs import load_session, task_dir

    session = load_session(workspace_dir)
    if not session:
        raise FileNotFoundError(f"No session.json found in {workspace_dir}")

    tdir = task_dir(workspace_dir)
    os.makedirs(tdir, exist_ok=True)

    generated = []
    for repo in session.get("candidate_repos", []):
        slug = repo["slug"]
        task_content = build_architect_task(session, repo, workspace_dir)
        task_path = os.path.join(tdir, f"{slug}.architect.task.md")
        with open(task_path, "w", encoding="utf-8") as f:
            f.write(task_content)
        generated.append((slug, task_path))

    return generated