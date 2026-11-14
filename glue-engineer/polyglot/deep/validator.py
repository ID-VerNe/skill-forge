"""polyglot/deep/validator.py — Validate subagent architecture outputs."""

import json
import os
import re


def validate_architecture_schema(arch: dict) -> list:
    """Validate architecture.json against the JSON Schema using jsonschema.

    Catches type/structure/enum violations that field-presence checks miss:
    e.g. `confidence` as an object instead of a number, `evidence` entries using
    a `lines` string instead of `line_start`/`line_end` ints, `known_gaps`
    entries using custom field names instead of `requirement`/`status`.

    Returns:
        List of (status, message) tuples — each violation is a hard error ('x').
    """
    try:
        import jsonschema
    except ImportError:
        return [(
            "x",
            "jsonschema is required for architecture validation; "
            'install it with `python -m pip install "jsonschema>=4.18"`.',
        )]

    schema_path = os.path.join(os.path.dirname(__file__), "schemas", "architecture.schema.json")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    errors = []
    try:
        # Use Draft202012Validator to collect ALL violations, not just the first.
        cls = jsonschema.validators.validator_for(schema)
        validator = cls(schema)
        for err in validator.iter_errors(arch):
            path = " → ".join(str(p) for p in err.absolute_path) if err.absolute_path else "root"
            errors.append(("x", f"schema violation at '{path}': {err.message}"))
    except jsonschema.SchemaError as e:
        errors.append(("x", f"schema file itself is invalid: {e.message}"))
    return errors


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
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            results.append(("x", f"architecture.json is invalid JSON: {e}"))
            arch = {}
        if not isinstance(arch, dict):
            results.append(("x", "architecture.json root must be an object"))
            arch = {}
    else:
        results.append(("x", "architecture.json missing"))
        arch = {}

    # 3. Required fields in architecture.json
    required_fields = [
        "repo", "slug", "source_path", "commit", "one_line_summary",
        "language", "core_modules", "key_types", "platform_apis",
        "known_gaps", "confidence", "evidence",
    ]
    missing = [f for f in required_fields if f not in arch]
    if missing:
        results.append(("x", f"architecture.json missing fields: {', '.join(missing)}"))
    else:
        results.append(("v", "architecture.json has all required fields"))
        # 3b. Strict schema validation (type/structure/enum) via jsonschema
        results.extend(validate_architecture_schema(arch))

        repos = session.get("candidate_repos", []) if isinstance(session, dict) else []
        repo = next(
            (entry for entry in repos if isinstance(entry, dict) and entry.get("slug") == slug),
            None,
        ) if isinstance(repos, list) else None
        if arch.get("slug") != slug:
            results.append(("x", f"architecture.json slug does not match candidate slug: {slug}"))
        if repo and arch.get("commit") != repo.get("commit"):
            results.append(("x", f"architecture.json commit does not match cloned candidate commit: {slug}"))

        # 3c. Every user requirement must have exactly one explicit coverage entry.
        requirements = session.get("requirements", []) if isinstance(session, dict) else []
        results.extend(validate_requirement_coverage(arch, requirements))

    # 4. confidence in 0-1
    conf = arch.get("confidence", -1)
    if isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0:
        results.append(("v", f"confidence = {conf}"))
    else:
        results.append(("x", f"confidence missing or out of range (0-1): {conf}"))

    # 5. evidence non-empty
    evidence = arch.get("evidence", [])
    if isinstance(evidence, list) and evidence:
        # Check each evidence has required fields
        bad_evidence = [
            e for e in evidence
            if not isinstance(e, dict) or not all(k in e for k in ("claim", "file", "line_start", "line_end"))
        ]
        if bad_evidence:
            results.append(("x", f"{len(bad_evidence)} evidence entries missing required fields"))
        else:
            results.append(("v", f"{len(evidence)} evidence entries with complete fields"))
    else:
        results.append(("x", "evidence must be a non-empty array"))

    # 6. source_manifest.json exists
    if os.path.exists(paths["source_manifest"]):
        try:
            with open(paths["source_manifest"], "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if not isinstance(manifest, dict):
                results.append(("x", "source_manifest.json root must be an object"))
            elif isinstance(manifest.get("files_read"), list) and manifest["files_read"]:
                results.append(("v", f"source_manifest.json: {len(manifest['files_read'])} files read"))
            else:
                results.append(("x", "source_manifest.json files_read must be a non-empty array"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
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


def validate_requirement_coverage(arch: dict, requirements: list) -> list:
    """Require exactly one well-formed known-gap row for each session requirement."""
    results = []
    if not isinstance(requirements, list) or not requirements:
        return [("x", "session requirements must contain at least one requirement")]
    if not isinstance(arch, dict):
        return [("x", "architecture report must be a JSON object")]

    gaps = arch.get("known_gaps")
    if not isinstance(gaps, list):
        return [("x", "known_gaps must be an array to validate requirement coverage")]

    def normalize(value):
        return " ".join(value.split()).casefold() if isinstance(value, str) else ""

    normalized_gaps = {}
    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            results.append(("x", f"known_gaps[{index}] must be an object"))
            continue
        key = normalize(gap.get("requirement"))
        if not key:
            results.append(("x", f"known_gaps[{index}].requirement must be a non-empty string"))
            continue
        normalized_gaps.setdefault(key, []).append(index)

    seen_requirements = set()
    for index, requirement in enumerate(requirements):
        key = normalize(requirement)
        if not key:
            results.append(("x", f"session requirements[{index}] must be a non-empty string"))
            continue
        if key in seen_requirements:
            results.append(("x", f"duplicate session requirement: {requirement}"))
            continue
        seen_requirements.add(key)
        matches = normalized_gaps.get(key, [])
        if not matches:
            results.append(("x", f"known_gaps has no entry for requirement: {requirement}"))
        elif len(matches) > 1:
            results.append(("x", f"known_gaps has duplicate entries for requirement: {requirement}"))

    required_keys = {normalize(requirement) for requirement in requirements if normalize(requirement)}
    for key, indexes in normalized_gaps.items():
        if key not in required_keys:
            results.append(("x", f"known_gaps[{indexes[0]}] does not match any session requirement: {key}"))

    if not results:
        results.append(("v", f"known_gaps covers all {len(requirements)} session requirements exactly once"))
    return results


def validate_session_completeness(session: dict) -> list:
    """Validate candidate accounting and reject empty/incomplete sessions."""
    results = []
    if not isinstance(session, dict):
        return [("x", "session.json must contain a JSON object")]
    repos = session.get("candidate_repos", [])
    clone_results = session.get("clone_results")
    candidate_count = session.get("candidate_count")

    if not isinstance(repos, list) or not repos:
        results.append(("x", "session has no successfully cloned candidate repositories"))
        repos = []
    repo_slugs = []
    for index, repo in enumerate(repos):
        if not isinstance(repo, dict):
            results.append(("x", f"candidate_repos[{index}] must be an object"))
            continue
        slug = repo.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
            results.append(("x", f"candidate_repos[{index}].slug must be a non-empty filesystem-safe string"))
        else:
            repo_slugs.append(slug)
        for field in ("name", "url", "local_path", "commit"):
            value = repo.get(field)
            if not isinstance(value, str) or not value.strip():
                results.append(("x", f"candidate_repos[{index}].{field} must be a non-empty string"))
    if len(repo_slugs) != len(set(repo_slugs)):
        results.append(("x", "candidate_repos contains duplicate slugs"))
    requirements = session.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        results.append(("x", "session has no requirements; coverage ranking is undefined"))
    elif any(not isinstance(requirement, str) or not requirement.strip()
             for requirement in requirements):
        results.append(("x", "session requirements must be non-empty strings"))
    else:
        normalized_requirements = [" ".join(requirement.split()).casefold() for requirement in requirements]
        if len(normalized_requirements) != len(set(normalized_requirements)):
            results.append(("x", "session requirements contain duplicates after normalization"))

    for field in ("project", "created_at", "workflow"):
        if not isinstance(session.get(field), str) or not session[field].strip():
            results.append(("x", f"session {field} must be a non-empty string"))

    if not isinstance(clone_results, list):
        results.append(("x", "session clone_results must be an array recording every requested candidate"))
        clone_results = []

    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool) or candidate_count < 1:
        results.append(("x", "candidate_count must be a positive integer"))
    if candidate_count != len(clone_results):
        results.append(("x", f"candidate_count ({candidate_count}) does not match recorded clone results ({len(clone_results)})"))

    if len(clone_results) != len(repos) and not any(
        isinstance(item, dict) and item.get("status") == "failed" for item in clone_results
    ):
        results.append(("x", f"recorded candidate count ({len(clone_results)}) does not match cloned candidates ({len(repos)})"))

    seen_slugs = set()
    clone_results_by_slug = {}
    for index, item in enumerate(clone_results):
        if not isinstance(item, dict):
            results.append(("x", f"clone_results[{index}] must be an object"))
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
            results.append(("x", f"clone_results[{index}].slug must be a non-empty filesystem-safe string"))
            slug = None
        elif slug in seen_slugs:
            results.append(("x", f"duplicate candidate slug in clone_results: {slug}"))
        if slug is not None:
            seen_slugs.add(slug)
            clone_results_by_slug[slug] = item
        for field in ("name", "url", "commit", "error"):
            value = item.get(field)
            must_be_non_empty = field in ("name", "url")
            if not isinstance(value, str) or (must_be_non_empty and not value.strip()):
                qualifier = "non-empty " if must_be_non_empty else ""
                results.append(("x", f"clone_results[{index}].{field} must be a {qualifier}string"))

        if item.get("status") not in ("cloned", "failed"):
            results.append(("x", f"clone_results[{index}].status must be 'cloned' or 'failed'"))
            continue
        if item["status"] == "failed":
            error = item.get("error")
            if not isinstance(error, str) or not error.strip():
                error = "unknown error"
            results.append(("x", f"clone failed for {item.get('url') or slug or 'unknown candidate'}: {error}"))
        elif not isinstance(item.get("commit"), str) or not item["commit"].strip():
            results.append(("x", f"successful clone has no commit hash: {slug or 'unknown candidate'}"))

    cloned_slugs = {
        item.get("slug") for item in clone_results
        if isinstance(item, dict) and item.get("status") == "cloned"
        and isinstance(item.get("slug"), str)
    }
    if cloned_slugs != set(repo_slugs):
        results.append(("x", "recorded successful clone slugs do not match candidate_repos slugs"))
    for repo in repos:
        if not isinstance(repo, dict) or not isinstance(repo.get("slug"), str):
            continue
        if repo["slug"] not in clone_results_by_slug:
            continue
        clone = clone_results_by_slug[repo["slug"]]
        if clone.get("status") != "cloned":
            continue
        for field in ("name", "url", "commit"):
            if repo.get(field) != clone.get(field):
                results.append(("x", f"candidate_repos {field} does not match clone result for {repo['slug']}"))

    return results


# @lat: [[deep#Key Concepts#Validation]]
def validate_all(workspace_dir: str, include_reuse_map: bool = False) -> dict:
    """Validate artifacts for all repos in the session.

    Args:
        workspace_dir: Path to .glue/deep/
        include_reuse_map: If True, also validate reuse-map artifacts (Phase 3)

    Returns:
        dict with keys: summary (list), all_pass (bool), exit_code (int)
    """
    from polyglot.deep.outputs import load_session

    session = load_session(workspace_dir)
    if not session:
        session_path = os.path.join(workspace_dir, "session.json")
        reason = (
            "session.json is missing" if not os.path.exists(session_path)
            else "session.json is invalid or unreadable"
        )
        return {
            "summary": [(f"[x] {reason}",)],
            "all_pass": False,
            "exit_code": 1,
            "errors": [reason],
        }

    all_results = []
    all_pass = True
    session_results = validate_session_completeness(session)
    for status, msg in session_results:
        all_results.append((f"[ {status} ] {msg}",))
        if status == "x":
            all_pass = False

    repos = session.get("candidate_repos", [])
    if not isinstance(repos, list):
        repos = []

    for repo in repos:
        if not isinstance(repo, dict) or not isinstance(repo.get("slug"), str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", repo["slug"]):
            continue
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
        "errors": [
            entry[0] for entry in all_results
            if entry and ("[ x ]" in entry[0] or "[x]" in entry[0])
        ],
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
