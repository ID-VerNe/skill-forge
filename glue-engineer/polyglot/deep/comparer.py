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


def _normalize_status(val) -> str:
    """Normalize a gap status to supported/partial/missing."""
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("supported", "yes", "✅", "full"):
            return "supported"
        if v in ("partial", "⚠️", "partially"):
            return "partial"
    return "missing"


def build_coverage_matrix(workspace_dir: str, session: dict) -> dict:
    """Build a requirements-coverage matrix from all architecture reports.

    Returns:
        dict with keys: requirements, repos, matrix (list of rows),
        where each row is {requirement, repo_1: status, repo_2: status, ...}
    """
    repos = session.get("candidate_repos", [])
    requirements = session.get("requirements", [])

    if not repos or not requirements:
        return {"requirements": [], "repos": [], "matrix": []}

    # Load all architecture reports
    archs = {}
    for repo in repos:
        slug = repo["slug"]
        arch = _load_architecture(workspace_dir, slug)
        archs[slug] = arch

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


def build_repo_comparisons(workspace_dir: str, session: dict) -> list:
    """Build side-by-side comparison of all repos.

    Returns:
        List of dicts, one per repo, with comparison fields.
    """
    repos = session.get("candidate_repos", [])
    comparisons = []

    for repo in repos:
        slug = repo["slug"]
        arch = _load_architecture(workspace_dir, slug)

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
        })

    # Sort by confidence descending
    comparisons.sort(key=lambda c: c["confidence"], reverse=True)
    return comparisons


def build_ranking(comparisons: list) -> list:
    """Build a simple ranking based on confidence and evidence depth."""
    ranked = []
    for i, c in enumerate(comparisons):
        score = c["confidence"] * 0.6 + min(c["evidence_count"] / 20, 1.0) * 0.4
        ranked.append({
            "rank": i + 1,
            "slug": c["slug"],
            "score": round(score, 2),
            "confidence": c["confidence"],
            "evidence_count": c["evidence_count"],
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    return ranked


# @lat: [[deep#Structured Comparison]]
def compare_all(workspace_dir: str) -> dict:
    """Run full comparison and return structured result.

    Returns:
        dict with keys: project, matrix, comparisons, ranking
    """
    from polyglot.deep.outputs import load_session

    session = load_session(workspace_dir)
    if not session:
        return {"error": "No session.json found"}

    matrix = build_coverage_matrix(workspace_dir, session)
    comparisons = build_repo_comparisons(workspace_dir, session)
    ranking = build_ranking(comparisons)

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
        lines.append("| Rank | Repo | Score | Confidence | Evidence |")
        lines.append("|------|------|-------|------------|----------|")
        for r in ranking:
            lines.append(f"| {r['rank']} | {r['slug']} | {r['score']} | {r['confidence']} | {r['evidence_count']} |")
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
    print(f"\n[v] Compared {repo_count} repos across {req_count} requirements")
    ranking = result.get("ranking", [])
    if ranking:
        print(f"    Top: {ranking[0]['slug']} (score={ranking[0]['score']})")

    return 0