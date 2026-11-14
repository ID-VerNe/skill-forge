"""polyglot/deep/summarizer.py — Deterministic report draft generation.

Reads all architecture reports + comparison.json and produces
a final-report-draft.md using template filling. No LLM calls.
"""

import json
import os
import re
from datetime import datetime, timezone


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def _load_json_with_status(path: str):
    """Load a JSON object and preserve missing/corrupt-file diagnostics."""
    if not os.path.exists(path):
        return {}, f"{os.path.basename(path)} is missing"
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return {}, f"{os.path.basename(path)} is invalid: {exc}"
    if not isinstance(value, dict):
        return {}, f"{os.path.basename(path)} must contain a JSON object"
    return value, ""


def _load_architecture(workspace_dir: str, slug: str) -> dict:
    return _load_json(os.path.join(workspace_dir, "repos", slug, "architecture.json"))


def _generate_draft(workspace_dir: str) -> tuple[str, int]:
    """Generate the draft and its CLI status from all available artifacts.

    Args:
        workspace_dir: Path to .glue/deep/

    Returns:
        (Markdown report draft, CLI exit code: 0 complete, nonzero incomplete).
    """
    from polyglot.deep.outputs import load_session

    session = load_session(workspace_dir)
    if not session:
        session_path = os.path.join(workspace_dir, "session.json")
        reason = (
            "session.json is missing" if not os.path.exists(session_path)
            else "session.json is invalid or unreadable"
        )
        comparison, comparison_error = _load_json_with_status(
            os.path.join(workspace_dir, "comparison.json")
        )
        lines = [
            "# Deep Analysis: Unavailable",
            "",
            "> **DATA INCOMPLETE — ranking suppressed.**",
            "",
            "## Completeness issues",
            "",
            f"- {reason}",
        ]
        if comparison_error:
            lines.append(f"- {comparison_error}")
        failures = comparison.get("clone_failures", [])
        for item in failures if isinstance(failures, list) else []:
            if isinstance(item, dict):
                lines.append(
                    f"- Clone failed: `{item.get('url', item.get('slug', 'unknown'))}` — "
                    f"{item.get('error') or 'unknown error'}"
                )
        lines.extend(["", "## Summary", "", "*Ranking suppressed because session data is unavailable.*", ""])
        return "\n".join(lines), 1

    project = session.get("project", "Unnamed")
    requirements = session.get("requirements", [])
    requirements = requirements if isinstance(requirements, list) else []
    repos = session.get("candidate_repos", [])
    repos = [
        repo for repo in repos
        if isinstance(repo, dict)
        and isinstance(repo.get("slug"), str)
        and re.fullmatch(r"[A-Za-z0-9_-]+", repo["slug"])
    ] if isinstance(repos, list) else []

    # The report must not trust a stale or hand-edited comparison gate. Validate
    # current artifacts again and only expose ranking for a complete result.
    from polyglot.deep.validator import validate_all

    comparison, comparison_error = _load_json_with_status(
        os.path.join(workspace_dir, "comparison.json")
    )
    validation = validate_all(workspace_dir)
    incomplete_reasons = list(validation.get("errors", []))
    if comparison_error:
        incomplete_reasons.append(comparison_error)
    if comparison.get("status") != "complete" or comparison.get("validation_failed"):
        validation_errors = comparison.get("validation_errors", [])
        if isinstance(validation_errors, list):
            incomplete_reasons.extend(str(error) for error in validation_errors if error)
        if comparison.get("validation_failed") and not validation_errors:
            incomplete_reasons.append("comparison is marked validation_failed")
        if comparison.get("status") != "complete" and not validation_errors:
            incomplete_reasons.append(
                f"comparison status is {comparison.get('status', 'missing or unknown')}, not complete"
            )

    if not comparison_error and comparison.get("status") == "complete":
        expected_count = session.get("candidate_count", len(repos))
        if comparison.get("candidate_count") != expected_count:
            incomplete_reasons.append(
                f"comparison candidate_count ({comparison.get('candidate_count')}) does not match session ({expected_count})"
            )
        if comparison.get("cloned_count") != len(repos):
            incomplete_reasons.append(
                f"comparison cloned_count ({comparison.get('cloned_count')}) does not match session ({len(repos)})"
            )
        expected_slugs = {repo["slug"] for repo in repos}
        matrix = comparison.get("matrix")
        matrix_repos = matrix.get("repos", []) if isinstance(matrix, dict) else []
        matrix_slugs = {
            slug for slug in matrix_repos if isinstance(slug, str)
        } if isinstance(matrix_repos, list) else set()
        reported_comparisons = comparison.get("comparisons")
        comparison_slugs = {
            item.get("slug") for item in reported_comparisons
            if isinstance(item, dict) and isinstance(item.get("slug"), str)
        } if isinstance(reported_comparisons, list) else set()
        if (matrix_slugs != expected_slugs or comparison_slugs != expected_slugs
                or len(matrix_repos) != len(expected_slugs)
                or not isinstance(comparison.get("matrix"), dict)
                or not isinstance(matrix.get("matrix"), list)
                or not isinstance(reported_comparisons, list)
                or len(reported_comparisons) != len(expected_slugs)):
            incomplete_reasons.append("comparison candidate details do not match the current session")

        persisted_ranking = comparison.get("ranking")
        persisted_clone_failures = comparison.get("clone_failures")
        if not isinstance(persisted_ranking, list) or not isinstance(persisted_clone_failures, list):
            incomplete_reasons.append("comparison ranking or clone_failures has an invalid shape")
        elif persisted_clone_failures:
            incomplete_reasons.append("complete comparison contains clone failures")

        # A status flag alone is not evidence that a saved comparison is sound.
        # Recompute deterministic coverage and scores from the validated session
        # and architecture artifacts; stale or hand-edited ranking data blocks
        # selection even when its status still says `complete`.
        if not incomplete_reasons:
            from polyglot.deep.comparer import compare_all

            canonical = compare_all(workspace_dir)
            if (canonical.get("status") != "complete"
                    or comparison.get("matrix") != canonical.get("matrix")
                    or comparison.get("ranking") != canonical.get("ranking")):
                incomplete_reasons.append("comparison matrix or ranking does not match current architecture data")

    # Preserve order while removing duplicate messages.
    incomplete_reasons = list(dict.fromkeys(incomplete_reasons))
    data_incomplete = bool(incomplete_reasons)
    comparison_available = (
        not data_incomplete
        and comparison.get("status") == "complete"
        and isinstance(comparison.get("comparisons"), list)
        and bool(comparison.get("comparisons"))
        and isinstance(comparison.get("ranking"), list)
        and isinstance(comparison.get("matrix"), dict)
    )
    clone_results = session.get("clone_results")
    clone_failures = [
        item for item in (clone_results if isinstance(clone_results, list) else [])
        if isinstance(item, dict) and item.get("status") != "cloned"
    ]

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append(f"# Deep Analysis: {project}")
    lines.append("")
    lines.append(f"**Generated**: {date_str}")
    lines.append(f"**Repos analyzed**: {len(repos)}")
    lines.append(f"**Candidates requested**: {session.get('candidate_count', len(repos))}")
    lines.append(f"**Requirements**: {len(requirements)}")
    lines.append("")

    if data_incomplete:
        lines.append("> **DATA INCOMPLETE — ranking suppressed.** Do not use this report to select a top candidate.")
        lines.append("")
        lines.append("### Completeness issues")
        lines.append("")
        for reason in incomplete_reasons:
            lines.append(f"- {reason}")
        reported_failures = set()
        failures = comparison.get("clone_failures", [])
        for item in failures if isinstance(failures, list) else []:
            if not isinstance(item, dict):
                continue
            reported_failures.add(item.get("slug"))
            lines.append(
                f"- Clone failed: `{item.get('url', item.get('slug', 'unknown'))}` — "
                f"{item.get('error') or 'unknown error'}"
            )
        for item in clone_failures:
            if item.get("slug") in reported_failures:
                continue
            lines.append(
                f"- Clone failed: `{item.get('url', item.get('slug', 'unknown'))}` — "
                f"{item.get('error') or 'unknown error'}"
            )
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
            top = ranking[0]
            lines.append(
                f"1. **{top['slug']}** — score {top['score']} "
                f"(coverage {top.get('coverage_ratio', '?')}, "
                f"confidence {top['confidence']})"
            )
            for r in ranking[1:]:
                lines.append(
                    f"{r['rank']}. {r['slug']} — score {r['score']} "
                    f"(coverage {r.get('coverage_ratio', '?')}, "
                    f"confidence {r['confidence']})"
                )
            lines.append("")
        else:
            lines.append("### Ranking")
            lines.append("")
            lines.append("*Ranking suppressed because candidate or architecture data is incomplete.*")
            lines.append("")

    # Section 3: Repo-by-repo summaries
    lines.append("## Repository Analysis")
    lines.append("")

    for repo in repos:
        slug = repo["slug"]
        arch = _load_architecture(workspace_dir, slug)
        if not arch:
            print(f"[!] {slug}: architecture.json missing or corrupt — skipping detailed analysis")

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
        key_types = [item for item in key_types if isinstance(item, dict)] if isinstance(key_types, list) else []
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
        apis = [item for item in apis if isinstance(item, dict)] if isinstance(apis, list) else []
        if apis:
            lines.append("**Platform APIs:**")
            for api in apis[:5]:
                lines.append(f"- {api.get('api', '?')}: {api.get('purpose', '')}")
            if len(apis) > 5:
                lines.append(f"  *+{len(apis) - 5} more*")
            lines.append("")

        # Known gaps
        gaps = arch.get("known_gaps", [])
        gaps = [item for item in gaps if isinstance(item, dict)] if isinstance(gaps, list) else []
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
        evidence = evidence if isinstance(evidence, list) else []
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
    elif data_incomplete:
        lines.append("*Ranking suppressed because candidate or architecture data is incomplete.*")
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

    return "\n".join(lines), 2 if data_incomplete else 0


def generate_draft(workspace_dir: str) -> str:
    """Generate a report draft while preserving the public string result."""
    draft, _ = _generate_draft(workspace_dir)
    return draft


def main(workspace_dir: str) -> int:
    """CLI entry point for deep-summarize."""
    draft, exit_code = _generate_draft(workspace_dir)

    md_path = os.path.join(workspace_dir, "final-report-draft.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(draft)
    print(f"[v] final-report-draft.md written to {md_path}")

    # Print a brief summary
    if exit_code:
        print("\n[!] Draft report generated with incomplete data — ranking suppressed")
    else:
        print("\n[v] Draft report generated")
    section_count = draft.count("## ")
    print(f"    {section_count} sections, {len(draft)} chars")

    return exit_code
