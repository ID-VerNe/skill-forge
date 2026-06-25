"""polyglot/common/reporters.py — JSON-to-Markdown conversion."""

import json
import sys
import os

# Allow import from parent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.schema import SearchOutput, AuditOutput, ProbeOutput


def search_to_md(output) -> str:
    lines = [
        f"## Search Results: {output.language}",
        f"Query: `{output.query}` | {len(output.results)} results",
        "",
    ]
    for i, r in enumerate(output.results[:10], 1):
        score = f" (score: {r.score:.2f})" if r.score else ""
        stars = f" *{r.stars}" if r.stars else ""
        desc = r.description[:120] if r.description else "No description"
        lines.append(f"### {i}. {r.name} `{r.version}`{stars}{score}")
        lines.append(f"{desc}")
        lines.append(f"URL: {r.registry_url or 'N/A'}")
        if r.license_name:
            lines.append(f"License: {r.license_name}")
        lines.append("")
    if output.errors:
        lines.append("### Errors")
        for e in output.errors:
            lines.append(f"- ERROR: {e}")
    return "\n".join(lines)


def audit_to_md(output: AuditOutput) -> str:
    lines = [
        f"## Audit Report: {output.candidate_name}",
        f"Language: {output.language} | Repo: {output.repo_url}",
        "",
    ]
    if output.errors:
        lines.append("### Errors")
        for e in output.errors:
            lines.append(f"- {e}")
        lines.append("")

    d = output.data
    if d:
        lines.append(f"Files scanned: {d.files_scanned} (skipped: {d.files_skipped})")
        lines.append(f"Complexity: {d.complexity}")
        lines.append(f"Test ratio: {d.test_ratio:.0%}")
        if d.verdict:
            lines.append(f"Verdict: **{d.verdict}**")
        if d.keywords_found:
            lines.append(f"Keywords: {', '.join(d.keywords_found)}")
        lines.append("")

        if d.exports:
            lines.append(f"### API Surface ({len(d.exports)} exports)")
            for sym in d.exports[:30]:
                check = "✅" if sym.probed else "○"
                lines.append(f"- {check} `{sym.name}` ({sym.kind}) {sym.signature[:80]}")
            if len(d.exports) > 30:
                lines.append(f"  ... and {len(d.exports) - 30} more")
            lines.append("")

        if d.community_health:
            ch = d.community_health
            lines.append("### Community Health")
            lines.append(f"- Stars: {ch.stars}")
            lines.append(f"- Last commit: {ch.last_commit_days_ago}d ago")
            lines.append(f"- Open issues: {ch.open_issues}")
            lines.append(f"- README: {'✅' if ch.has_readme else '❌'} | Tests: {'✅' if ch.has_tests else '❌'} | Docs: {'✅' if ch.has_docs else '❌'}")
            lines.append("")

        if d.security and d.security.vulnerabilities:
            lines.append("### Security")
            for v in d.security.vulnerabilities:
                lines.append(f"- ⚠️ {v}")

    return "\n".join(lines)


def probe_to_md(output: ProbeOutput) -> str:
    lines = [
        f"## Probe Results: {output.package}",
        f"Language: {output.language}",
        "",
    ]
    passed = [s for s in output.probed_symbols if s.get("resolved")]
    failed = [s for s in output.probed_symbols if not s.get("resolved")]
    lines.append(f"Symbols probed: {len(output.probed_symbols)} ({len(passed)} resolved, {len(failed)} failed)")
    if output.discrepancies:
        lines.append("")
        lines.append("### ⚠️ Discrepancies (static vs dynamic mismatch)")
        for d in output.discrepancies:
            lines.append(f"- {d}")
    if output.errors:
        lines.append("")
        lines.append("### Errors")
        for e in output.errors:
            lines.append(f"- ❌ {e}")
    return "\n".join(lines)


def output_from_file(path: str) -> SearchOutput | AuditOutput | ProbeOutput | None:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    tool = data.get("tool", "")
    if tool == "scout":
        return SearchOutput.from_json(data) if isinstance(data, dict) else SearchOutput(**data)
    elif tool == "auditor":
        return AuditOutput.from_json(data)
    elif tool == "probe":
        return ProbeOutput(**data)
    return None
