"""polyglot/deep/summarizer.py — Deterministic report draft generation.

Reads all architecture reports + comparison.json and produces
a final-report-draft.md using template filling. No LLM calls.
"""

import json
import os
from datetime import datetime, timezone


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _load_architecture(workspace_dir: str, slug: str) -> dict:
    return _load_json(os.path.join(workspace_dir, "repos", slug, "architecture.json"))


def generate_draft(workspace_dir: str) -> str:
    """Generate a final-report-draft.md from all available artifacts.

    Args:
        workspace_dir: Path to .glue/deep/

    Returns:
        Markdown string with the report draft.
    """
    from polyglot.deep.outputs import load_session

    session = load_session(workspace_dir)
    if not session:
        return "# Error: No session.json found in workspace\n"

    project = session.get("project", "Unnamed")
    requirements = session.get("requirements", [])
    repos = session.get("candidate_repos", [])

    # Load comparison if available
    comparison = _load_json(os.path.join(workspace_dir, "comparison.json"))
    comparison_available = "error" not in comparison and comparison.get("comparisons")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append(f"# Deep Analysis: {project}")
    lines.append("")
    lines.append(f"**Generated**: {date_str}")
    lines.append(f"**Repos analyzed**: {len(repos)}")
    lines.append(f"**Requirements**: {len(requirements)}")
    lines.append("")

    # Section 1: Requirements
    lines.append("## Requirements")
    lines.append("")
    if requirements:
        for i, req in enumerate(requirements, 1):
            lines.append(f"{i}. {req}")
    else:
        lines.append("*No requirements specified.*")
    lines.append("")

    # Section 2: Coverage Matrix
    if comparison_available:
        matrix = comparison.get("matrix", {})
        matrix_rows = matrix.get("matrix", [])
        repo_slugs = matrix.get("repos", [])

        lines.append("## Requirements Coverage Matrix")
        lines.append("")
        if matrix_rows and repo_slugs:
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
        else:
            lines.append("*No coverage data.*")
        lines.append("")

        # Ranking
        ranking = comparison.get("ranking", [])
        if ranking:
            lines.append("### Ranking")
            lines.append("")
            lines.append(f"1. **{ranking[0]['slug']}** — score {ranking[0]['score']} (confidence {ranking[0]['confidence']})")
            for r in ranking[1:]:
                lines.append(f"{r['rank']}. {r['slug']} — score {r['score']} (confidence {r['confidence']})")
            lines.append("")

    # Section 3: Repo-by-repo summaries
    lines.append("## Repository Analysis")
    lines.append("")

    for repo in repos:
        slug = repo["slug"]
        arch = _load_architecture(workspace_dir, slug)

        lines.append(f"### {slug}")
        lines.append("")

        summary = arch.get("one_line_summary", "")
        if summary:
            lines.append(f"**Summary**: {summary}")
            lines.append("")

        confidence = arch.get("confidence", 0)
        lines.append(f"- **Language**: {arch.get('language', 'N/A')}")
        lines.append(f"- **Confidence**: {confidence}")
        lines.append(f"- **Commit**: {arch.get('commit', repo.get('commit', 'N/A')[:12])}")
        lines.append("")

        # Key types
        key_types = arch.get("key_types", [])
        if key_types:
            lines.append("**Key Types:**")
            for kt in key_types[:5]:
                name = kt.get("name", "?")
                kind = kt.get("kind", "")
                file = kt.get("file", "")
                line = kt.get("line", "")
                lines.append(f"- `{name}` ({kind}) — {file}:{line}")
            if len(key_types) > 5:
                lines.append(f"  *+{len(key_types) - 5} more*")
            lines.append("")

        # Platform APIs
        apis = arch.get("platform_apis", [])
        if apis:
            lines.append("**Platform APIs:**")
            for api in apis[:5]:
                lines.append(f"- {api.get('api', '?')}: {api.get('purpose', '')}")
            if len(apis) > 5:
                lines.append(f"  *+{len(apis) - 5} more*")
            lines.append("")

        # Known gaps
        gaps = arch.get("known_gaps", [])
        if gaps:
            lines.append("**Known Gaps:**")
            for gap in gaps:
                req = gap.get("requirement", "?")
                status = gap.get("status", "?")
                details = gap.get("details", "")
                status_icon = {"supported": "✅", "partial": "⚠️", "missing": "❌"}
                icon = status_icon.get(status, "❓")
                lines.append(f"- {icon} **{req}**: {status} — {details}")
            lines.append("")

        # Evidence count
        evidence = arch.get("evidence", [])
        lines.append(f"- **Evidence items**: {len(evidence)}")
        lines.append("")

        # Link to full report
        repo_url = repo.get("url", "")
        lines.append(f"[Full architecture report](./repos/{slug}/architecture.md)")
        lines.append("")

    # Section 3.5: Integration Plans (Phase 4)
    lines.append("## Integration Plans")
    lines.append("")

    any_integration = False
    for repo in repos:
        slug = repo["slug"]
        int_json = _load_json(os.path.join(workspace_dir, "repos", slug, "integration-plan.json"))
        if not int_json or "recommended_route" not in int_json:
            continue
        any_integration = True

        route = int_json.get("recommended_route", "unknown")
        route_icons = {"direct_use": "📦", "fork": "🔱", "compose": "🔗", "build": "🏗️"}
        icon = route_icons.get(route, "❓")

        lines.append(f"### {slug}")
        lines.append("")
        lines.append(f"{icon} **Recommended route**: {route}")
        lines.append("")

        rationale = int_json.get("route_rationale", "")
        if rationale:
            lines.append(f"> {rationale}")
            lines.append("")

        # Decision matrix
        matrix = int_json.get("decision_matrix", [])
        if matrix:
            lines.append("**Decision Matrix:**")
            for entry in matrix:
                c = entry.get("criterion", "?")
                s = entry.get("score", "?")
                w = entry.get("weight", "?")
                e = entry.get("evidence", "")
                lines.append(f"- **{c}**: score={s}, weight={w} — {e}")
            lines.append("")

        # Implementation roadmap (top 3)
        roadmap = int_json.get("implementation_roadmap", [])
        if roadmap:
            lines.append("**Implementation Roadmap (top 3):**")
            for step in roadmap[:3]:
                title = step.get("title", "?")
                effort = step.get("effort", "?")
                conf = step.get("confidence", "?")
                desc = step.get("description", "")
                lines.append(f"- **{step.get('step')}. {title}** (effort={effort}, confidence={conf})")
                if desc:
                    lines.append(f"  - {desc}")
            if len(roadmap) > 3:
                lines.append(f"  *+{len(roadmap) - 3} more steps*")
            lines.append("")

        # First PR plan
        first_pr = int_json.get("first_pr_plan", {})
        if first_pr:
            pr_title = first_pr.get("title", "")
            pr_desc = first_pr.get("description", "")
            files = first_pr.get("files_to_change", [])
            lines.append("**First PR:**")
            if pr_title:
                lines.append(f"- *{pr_title}*")
            if pr_desc:
                lines.append(f"- {pr_desc}")
            for f in files:
                action = f.get("action", "?")
                path = f.get("path", "?")
                summary = f.get("content_summary", "")
                lines.append(f"- `{action}` `{path}` — {summary}")
            lines.append("")

        # Risks
        risks = int_json.get("risks", [])
        if risks:
            lines.append("**Risks:**")
            for r in risks:
                risk = r.get("risk", "?")
                like = r.get("likelihood", "?")
                impact = r.get("impact", "?")
                mitigation = r.get("mitigation", "")
                lines.append(f"- ⚠️ **{risk}** (like={like}, impact={impact})")
                if mitigation:
                    lines.append(f"  - Mitigation: {mitigation}")
            lines.append("")

        # Validation checklist count
        checklist = int_json.get("validation_checklist", [])
        lines.append(f"- **Validation checks**: {len(checklist)}")
        lines.append("")

    if not any_integration:
        lines.append("*No integration plans available. Run `glue-integration-planner` first.*")
        lines.append("")

    # Section 4: Summary
    lines.append("## Summary")
    lines.append("")

    if comparison_available and ranking:
        best = ranking[0]
        lines.append(f"**Top candidate**: {best['slug']} (score {best['score']})")
        lines.append("")
        lines.append("**Coverage overview:**")
        for row in matrix_rows if comparison_available else []:
            supported_count = sum(1 for s in repo_slugs if row.get(s) == "supported")
            partial_count = sum(1 for s in repo_slugs if row.get(s) == "partial")
            lines.append(f"- {row['requirement']}: {supported_count} supported, {partial_count} partial")
    else:
        lines.append("*Comparison data not yet available. Run `deep-compare` first.*")
    lines.append("")

    # Section 5: Next Steps
    lines.append("## Next Steps")
    lines.append("")
    lines.append("1. Review individual architecture reports for detail")
    lines.append("2. Select the best-fit candidate based on coverage and confidence")
    lines.append("3. Run `deep-compare` for side-by-side comparison (if not already done)")
    lines.append("4. Consider running `glue-reuse-mapper` to extract reusable code (Phase 3)")
    lines.append("5. Consider running `glue-integration-planner` for a build plan (Phase 4)")
    lines.append("6. Run `glue-synthesizer` for a final user-facing recommendation (Phase 4)")
    lines.append("")

    lines.append("---")
    lines.append(f"*Report generated by glue-engineer v4 deep-summarize*")

    return "\n".join(lines)


def main(workspace_dir: str) -> int:
    """CLI entry point for deep-summarize."""
    draft = generate_draft(workspace_dir)

    md_path = os.path.join(workspace_dir, "final-report-draft.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(draft)
    print(f"[v] final-report-draft.md written to {md_path}")

    # Print a brief summary
    print(f"\n[v] Draft report generated")
    section_count = draft.count("## ")
    print(f"    {section_count} sections, {len(draft)} chars")

    return 0