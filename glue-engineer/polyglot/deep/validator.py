"""polyglot/deep/validator.py — Validate subagent architecture outputs."""

import json
import os
import sys


def validate_reuse_map(workspace_dir: str, slug: str) -> list:
    """Validate reuse-map.json for a single repo if it exists.

    Returns:
        List of (status, message) tuples
    """
    from polyglot.deep.outputs import repo_dir

    rd = repo_dir(workspace_dir, slug)
    reuse_json_path = os.path.join(rd, "reuse-map.json")
    reuse_md_path = os.path.join(rd, "reuse-map.md")
    results = []

    # Check if reuse-map exists at all (optional artifact)
    if not os.path.exists(reuse_json_path):
        results.append(("-", "reuse-map.json not present (optional)"))
        return results  # Skip further checks — it's optional

    results.append(("v", "reuse-map.json present"))

    # Parse JSON
    try:
        with open(reuse_json_path, "r", encoding="utf-8") as f:
            reuse = json.load(f)
        results.append(("v", "reuse-map.json is valid JSON"))
    except json.JSONDecodeError as e:
        results.append(("x", f"reuse-map.json is invalid JSON: {e}"))
        return results

    # Required top-level fields
    required = ["repo", "slug", "candidates"]
    missing = [f for f in required if f not in reuse]
    if missing:
        results.append(("x", f"reuse-map.json missing fields: {', '.join(missing)}"))
        return results
    results.append(("v", "reuse-map.json has all required fields"))

    # Check candidates
    candidates = reuse.get("candidates", [])
    if not candidates:
        results.append(("!", "reuse-map.json candidates is empty"))
        return results

    valid_modes = {"copy", "port", "wrap", "reference_only", "avoid"}
    for i, c in enumerate(candidates):
        cid = f"candidate[{i}]"

        # Required fields
        required_candidate = ["file", "line_start", "line_end", "symbol", "purpose",
                              "reuse_mode", "license_note", "confidence", "evidence"]
        missing_c = [f for f in required_candidate if f not in c]
        if missing_c:
            results.append(("x", f"{cid}: missing fields: {', '.join(missing_c)}"))
            continue

        # reuse_mode enum check
        if c.get("reuse_mode") not in valid_modes:
            results.append(("!", f"{cid}: invalid reuse_mode '{c.get('reuse_mode')}'"))

        # confidence range
        conf = c.get("confidence", -1)
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            results.append(("!", f"{cid}: confidence out of range (0-1): {conf}"))

        # line range validity
        ls = c.get("line_start", 0)
        le = c.get("line_end", 0)
        if ls <= 0 or le <= 0 or le < ls:
            results.append(("!", f"{cid}: invalid line range ({ls}-{le})"))

    results.append(("v", f"{len(candidates)} candidates validated"))

    # Check reuse-map.md exists alongside
    if os.path.exists(reuse_md_path):
        results.append(("v", "reuse-map.md present"))
    else:
        results.append(("!", "reuse-map.md missing"))

    return results


def validate_repo_artifacts(workspace_dir: str, slug: str, include_reuse_map: bool = False) -> list:
    """Validate all required artifacts for a single repo.

    Returns:
        List of (status, message) tuples:
          status: 'v' (valid), '!' (warning), 'x' (error)
    """
    from polyglot.deep.outputs import artifact_paths, load_session

    session = load_session(workspace_dir)
    paths = artifact_paths(workspace_dir, slug)
    results = []

    # 1. architecture.md exists
    if os.path.exists(paths["architecture_md"]):
        size = os.path.getsize(paths["architecture_md"])
        results.append(("v", f"architecture.md exists ({size} bytes)"))
    else:
        results.append(("x", "architecture.md missing"))

    # 2. architecture.json exists and is valid JSON
    if os.path.exists(paths["architecture_json"]):
        try:
            with open(paths["architecture_json"], "r", encoding="utf-8") as f:
                arch = json.load(f)
            results.append(("v", "architecture.json is valid JSON"))
        except json.JSONDecodeError as e:
            results.append(("x", f"architecture.json is invalid JSON: {e}"))
            arch = {}
    else:
        results.append(("x", "architecture.json missing"))
        arch = {}

    # 3. Required fields in architecture.json
    required_fields = [
        "repo", "slug", "source_path", "commit", "one_line_summary",
        "core_modules", "key_types", "platform_apis", "known_gaps",
        "confidence", "evidence",
    ]
    missing = [f for f in required_fields if f not in arch]
    if missing:
        results.append(("x", f"architecture.json missing fields: {', '.join(missing)}"))
    else:
        results.append(("v", "architecture.json has all required fields"))

    # 4. confidence in 0-1
    conf = arch.get("confidence", -1)
    if isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0:
        results.append(("v", f"confidence = {conf}"))
    else:
        results.append(("x", f"confidence missing or out of range (0-1): {conf}"))

    # 5. evidence non-empty
    evidence = arch.get("evidence", [])
    if evidence and len(evidence) > 0:
        # Check each evidence has required fields
        bad_evidence = [e for e in evidence if not all(k in e for k in ("claim", "file", "line_start", "line_end"))]
        if bad_evidence:
            results.append(("!", f"{len(bad_evidence)} evidence entries missing required fields"))
        else:
            results.append(("v", f"{len(evidence)} evidence entries with complete fields"))
    else:
        results.append(("x", "evidence array is empty or missing"))

    # 6. source_manifest.json exists
    if os.path.exists(paths["source_manifest"]):
        try:
            with open(paths["source_manifest"], "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if "files_read" in manifest and len(manifest["files_read"]) > 0:
                results.append(("v", f"source_manifest.json: {len(manifest['files_read'])} files read"))
            else:
                results.append(("!", "source_manifest.json exists but files_read is empty"))
        except json.JSONDecodeError:
            results.append(("x", "source_manifest.json is invalid JSON"))
    else:
        results.append(("x", "source_manifest.json missing"))

    # 7. unresolved.md exists
    if os.path.exists(paths["unresolved"]):
        size = os.path.getsize(paths["unresolved"])
        results.append(("v", f"unresolved.md exists ({size} bytes)"))
    else:
        results.append(("x", "unresolved.md missing"))

    # 8. Optional: reuse-map artifacts (Phase 3)
    if include_reuse_map:
        reuse_results = validate_reuse_map(workspace_dir, slug)
        results.extend(reuse_results)

    return results


def validate_all(workspace_dir: str, include_reuse_map: bool = False) -> dict:
    """Validate artifacts for all repos in the session.

    Args:
        workspace_dir: Path to deep-output/
        include_reuse_map: If True, also validate reuse-map artifacts (Phase 3)

    Returns:
        dict with keys: summary (list), all_pass (bool), exit_code (int)
    """
    from polyglot.deep.outputs import load_session

    session = load_session(workspace_dir)
    if not session:
        return {
            "summary": [("x", "No session.json found in workspace")],
            "all_pass": False,
            "exit_code": 1,
        }

    repos = session.get("candidate_repos", [])
    if not repos:
        return {
            "summary": [("!", "No candidate repos in session.json")],
            "all_pass": True,
            "exit_code": 0,
        }

    all_results = []
    all_pass = True

    for repo in repos:
        slug = repo["slug"]
        all_results.append((f"\n[{slug}]", ""))
        repo_results = validate_repo_artifacts(workspace_dir, slug, include_reuse_map=include_reuse_map)
        for status, msg in repo_results:
            all_results.append((f"  [{status}] {msg}",))
            if status == "x":
                all_pass = False

    return {
        "summary": all_results,
        "all_pass": all_pass,
        "exit_code": 0 if all_pass else 1,
    }


def main(workspace_dir: str, include_reuse_map: bool = False):
    """CLI entry point for deep-validate."""
    report = validate_all(workspace_dir, include_reuse_map=include_reuse_map)

    for line in report["summary"]:
        print(line[0])

    if report["all_pass"]:
        print("\n[v] All checks passed.")
    else:
        print("\n[x] Some checks failed.")

    return report["exit_code"]