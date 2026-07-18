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
6. `architecture.json` must follow the schema at `polyglot/deep/schemas/architecture.schema.json`.
7. Must include `confidence` (0.0-1.0) in `architecture.json`.
8. `evidence` array in `architecture.json` must be non-empty.
9. If unsure about anything, write it in `unresolved.md`.
10. Final response to main agent must be SHORT — do not paste full report.

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


# @lat: [[deep#Subagent Task Generation]]
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