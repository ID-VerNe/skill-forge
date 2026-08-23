"""polyglot/deep/comparer.py — Structured comparison of multiple architecture reports.

Pure Python, no LLM calls. Reads all architecture.json files from the session
and produces a comparison matrix.
"""

import json
import os


def _load_architecture(workspace_dir: str, slug: str) -> dict:
    """Load a single architecture.json, return empty dict on failure."""
    path = os.path.join(workspace_dir, "repos", slug, "architecture.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _load_all_architectures(workspace_dir: str, session: dict) -> dict:
    """Load architecture.json for every repo, emitting one warning per failure.

    Returns:
        dict[str, dict] — slug -> arch dict (empty dict on failure)
    """
    archs = {}
    for repo in session.get("candidate_repos", []):
        slug = repo["slug"]
        arch = _load_architecture(workspace_dir, slug)
        if not arch:
            print(f"[!] {slug}: architecture.json missing or corrupt — treating as unanalyzed")
        archs[slug] = arch
    return archs


def _normalize_status(val) -> str:
    """Normalize a gap status to supported/partial/missing."""
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("supported", "yes", "✅", "full"):
            return "supported"
        if v in ("partial", "⚠️", "partially"):
            return "partial"
    return "missing"


def build_coverage_matrix(workspace_dir: str, session: dict, archs: dict = None) -> dict:
    """Build a requirements-coverage matrix from all architecture reports.

    Returns:
        dict with keys: requirements, repos, matrix (list of rows),
        where each row is {requirement, repo_1: status, repo_2: status, ...}
    """
    repos = session.get("candidate_repos", [])
    requirements = session.get("requirements", [])

    if not repos or not requirements:
        return {"requirements": [], "repos": [], "matrix": []}

    # Load all architecture reports once
    if archs is None:
        archs = _load_all_architectures(workspace_dir, session)

    # Build matrix rows
    matrix = []
    for req in requirements:
        row = {"requirement": req}
        for repo in repos:
            slug = repo["slug"]
            arch = archs.get(slug, {})
            gaps = arch.get("known_gaps", [])
            # Find matching gap
            status = "missing"
            for gap in gaps:
                if req.lower() in gap.get("requirement", "").lower() or gap.get("requirement", "").lower() in req.lower():
                    status = _normalize_status(gap.get("status", "missing"))
                    break
            row[slug] = status
        matrix.append(row)

    return {
        "requirements": requirements,
        "repos": [r["slug"] for r in repos],
        "matrix": matrix,
    }


def _count_source_lines(source_path: str) -> int:
    """Count total non-blank source lines under a path (fast estimation).

    Skips vendor/.git/node_modules/__pycache__/target dirs. Used to surface
    large-repo size in the comparison (a proxy for subagent context risk).
    """
    if not source_path or not os.path.isdir(source_path):
        return 0
    total = 0
    source_exts = (".py", ".rs", ".go", ".js", ".ts", ".java", ".kt", ".c", ".cpp", ".h", ".hpp")
    for root, dirs, files in os.walk(source_path):
        dirs[:] = [d for d in dirs if d not in (".git", "vendor", "node_modules", "__pycache__", "target")]
        for f in files:
            if f.endswith(source_exts):
                path = os.path.join(root, f)
                try:
                    with open(path, "rb") as fh:
                        total += sum(1 for line in fh if line != b"\n")
                except Exception:
                    pass
    return total


def build_repo_comparisons(workspace_dir: str, session: dict, archs: dict = None) -> list:
    """Build side-by-side comparison of all repos.

    Returns:
        List of dicts, one per repo, with comparison fields.
    """
    repos = session.get("candidate_repos", [])

    if archs is None:
        archs = _load_all_architectures(workspace_dir, session)

    comparisons = []

    for repo in repos:
        slug = repo["slug"]
        arch = archs.get(slug, {})

        gaps = arch.get("known_gaps", [])
        gap_summary = ", ".join(
            f"{g.get('requirement', '?')}={g.get('status', '?')}"
            for g in gaps
        ) if gaps else "no gap data"

        evidence = arch.get("evidence", [])
        evidence_count = len(evidence)

        comparisons.append({
            "slug": slug,
            "name": arch.get("repo", slug),
            "language": arch.get("language", "unknown"),
            "one_line_summary": arch.get("one_line_summary", ""),
            "confidence": arch.get("confidence", 0),
            "known_gaps_summary": gap_summary,
            "evidence_count": evidence_count,
            "core_module_count": len(arch.get("core_modules", [])),
            "key_type_count": len(arch.get("key_types", [])),
            "platform_api_count": len(arch.get("platform_apis", [])),
            "commit": arch.get("commit", repo.get("commit", "")),
            "source_files": {
                "total_lines": _count_source_lines(arch.get("source_path", "")),
                "files_read": len(arch.get("core_modules", [])),
            },
        })

    # Sort by confidence descending
    comparisons.sort(key=lambda c: c["confidence"], reverse=True)
    return comparisons


def build_ranking(comparisons: list, matrix: dict) -> list:
    """Build a ranking based on coverage, confidence, and evidence depth."""
    requirements = matrix.get("requirements", [])
    req_count = max(len(requirements), 1)
    ranked = []
    for c in comparisons:
        supported = 0
        partial = 0
        for row in matrix.get("matrix", []):
            status = row.get(c["slug"], "missing")
            if status == "supported":
                supported += 1
            elif status == "partial":
                partial += 1
        coverage_ratio = (supported * 1.0 + partial * 0.5) / req_count

        score = coverage_ratio * 0.4 + c["confidence"] * 0.3 + min(c["evidence_count"] / 20, 1.0) * 0.3
        ranked.append({
            "rank": 0,
            "slug": c["slug"],
            "score": round(score, 2),
            "coverage_ratio": round(coverage_ratio, 2),
            "supported": supported,
            "partial": partial,
            "missing": req_count - supported - partial,
            "confidence": c["confidence"],
            "evidence_count": c["evidence_count"],
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    return ranked


def compare_all(workspace_dir: str) -> dict:
    """Run full comparison and return structured result.

    Runs validation first. If any repo is missing required fields, returns
    a result with `validation_failed: True` and an empty ranking instead of
    producing a misleading score-based ranking.

    Returns:
        dict with keys: project, matrix, comparisons, ranking,
        and optionally validation_failed / validation_errors / warning
    """
    from polyglot.deep.outputs import load_session
    from polyglot.deep.validator import validate_all

    session = load_session(workspace_dir)
    if not session:
        return {"error": "No session.json found"}

    # Validation gate: refuse to rank if architecture data is incomplete.
    validation = validate_all(workspace_dir)
    if not validation["all_pass"]:
        errors = [entry[0] for entry in validation["summary"]
                  if isinstance(entry, tuple) and entry and "[x]" in entry[0]]
        return {
            "project": session.get("project", ""),
            "matrix": {"requirements": [], "repos": [], "matrix": []},
            "comparisons": [],
            "ranking": [],
            "validation_failed": True,
            "validation_errors": errors,
            "warning": (
                "DATA INCOMPLETE: architecture reports are missing required fields. "
                "Ranking is unreliable and has been suppressed. "
                "Run subagents first, then `deep-validate` to confirm all checks pass."
            ),
        }

    archs = _load_all_architectures(workspace_dir, session)
    matrix = build_coverage_matrix(workspace_dir, session, archs)
    comparisons = build_repo_comparisons(workspace_dir, session, archs)
    ranking = build_ranking(comparisons, matrix)

    return {
        "project": session.get("project", ""),
        "matrix": matrix,
        "comparisons": comparisons,
        "ranking": ranking,
    }


def format_matrix_markdown(result: dict) -> str:
    """Format comparison result as Markdown."""
    lines = []
    lines.append(f"# Comparison Matrix: {result.get('project', 'Unnamed')}")
    lines.append("")

    # Validation gate banner: surface incomplete data before any numbers.
    if result.get("validation_failed"):
        lines.append("> **DATA INCOMPLETE**: architecture reports are missing required fields.")
        lines.append("> Ranking has been suppressed — it would be unreliable.")
        lines.append("> Run subagents first, then `deep-validate` to confirm all checks pass.")
        lines.append("")
        errors = result.get("validation_errors", [])
        if errors:
            lines.append("**Validation errors:**")
            for err in errors[:10]:
                lines.append(f"- {err}")
            lines.append("")

    matrix = result.get("matrix", {})
    requirements = matrix.get("requirements", [])
    repo_slugs = matrix.get("repos", [])
    matrix_rows = matrix.get("matrix", [])

    if not requirements or not repo_slugs:
        lines.append("*No comparison data available.*")
        lines.append("")
        return "\n".join(lines)

    # Coverage matrix
    lines.append("## Requirements Coverage Matrix")
    lines.append("")
    header = "| Requirement | " + " | ".join(f"**{s}**" for s in repo_slugs) + " |"
    sep = "|" + "---|" * (len(repo_slugs) + 1)
    lines.append(header)
    lines.append(sep)
    status_icons = {"supported": "✅", "partial": "⚠️", "missing": "❌"}
    for row in matrix_rows:
        cells = [row.get("requirement", "?")]
        for s in repo_slugs:
            st = row.get(s, "missing")
            cells.append(status_icons.get(st, "❌"))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # Ranking
    lines.append("## Ranking")
    lines.append("")
    ranking = result.get("ranking", [])
    if ranking:
        lines.append("| Rank | Repo | Score | Coverage | Confidence | Evidence |")
        lines.append("|------|------|-------|----------|------------|----------|")
        for r in ranking:
            lines.append(
                f"| {r['rank']} | {r['slug']} | {r['score']} | "
                f"{r.get('coverage_ratio', '?')} | {r['confidence']} | {r['evidence_count']} |"
            )
    elif result.get("validation_failed"):
        lines.append("*Ranking suppressed — see DATA INCOMPLETE banner above.*")
    lines.append("")

    # Repo comparisons
    lines.append("## Repo Details")
    lines.append("")
    for c in result.get("comparisons", []):
        lines.append(f"### {c['slug']}")
        lines.append(f"- **Language**: {c['language']}")
        lines.append(f"- **Summary**: {c['one_line_summary']}")
        lines.append(f"- **Confidence**: {c['confidence']}")
        lines.append(f"- **Evidence items**: {c['evidence_count']}")
        lines.append(f"- **Core modules**: {c['core_module_count']}")
        lines.append(f"- **Key types**: {c['key_type_count']}")
        lines.append(f"- **Platform APIs**: {c['platform_api_count']}")
        lines.append(f"- **Known gaps**: {c['known_gaps_summary']}")
        sf = c.get("source_files", {})
        lines.append(f"- **Source size**: {sf.get('total_lines', '?')} lines ({sf.get('files_read', '?')} modules read)")
        lines.append("")

    return "\n".join(lines)


def main(workspace_dir: str, output_dir: str = None):
    """CLI entry point for deep-compare."""
    if output_dir is None:
        output_dir = workspace_dir

    result = compare_all(workspace_dir)

    if "error" in result:
        print(f"[x] {result['error']}")
        return 1

    # Write JSON
    json_path = os.path.join(output_dir, "comparison.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[v] comparison.json written to {json_path}")

    # Write Markdown
    md = format_matrix_markdown(result)
    md_path = os.path.join(output_dir, "comparison.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[v] comparison.md written to {md_path}")

    # Print summary
    matrix = result.get("matrix", {})
    req_count = len(matrix.get("requirements", []))
    repo_count = len(matrix.get("repos", []))
    ranking = result.get("ranking", [])
    if result.get("validation_failed"):
        print(f"\n[!] DATA INCOMPLETE — ranking suppressed.")
        print(f"    Run subagents first, then `deep-validate` to confirm all checks pass.")
        errors = result.get("validation_errors", [])
        if errors:
            print(f"    {len(errors)} validation error(s) — see comparison.md for details.")
        return 0

    print(f"\n[v] Compared {repo_count} repos across {req_count} requirements")
    if ranking:
        print(f"    Top: {ranking[0]['slug']} (score={ranking[0]['score']}, "
              f"coverage={ranking[0].get('coverage_ratio', '?')})")

    return 0