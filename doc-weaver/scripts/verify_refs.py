#!/usr/bin/env python3
"""verify_refs.py — CI 引用完整性检查（纯机械，无 AI 调用）

Checks:
1. [[modules/xxx]] wiki link → docs/modules/xxx.md 文件存在
2. [[project/xxx]] wiki link → docs/project/xxx.md 文件存在
3. [[schema/xxx]] wiki link → docs/schema/xxx.json 文件存在
4. [[src/path#symbol]] 格式是否正确
5. manifest 中声明的模块是否都有对应的文档文件
6. docs 中存在的模块文档是否在 manifest 中有声明

Usage:
    python verify_refs.py [--project-dir <path>] [--json] [--strict]

Exit codes:
    0 — all checks passed
    1 — warnings only (if not --strict)
    2 — errors found
"""

import argparse
import json
import os
import re
import sys


DOCS_DIR = "docs"
MANIFEST_PATH = "docs/schema/manifest.json"

# Wiki link pattern
WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

# Source link pattern (for [[src/path#symbol]] and [[path/to/file.ext]])
SRC_LINK_PATTERN = re.compile(r"^src/")
FILE_EXT_PATTERN = re.compile(r"\.(py|js|ts|tsx|jsx|php|rs|go|java|kt|c|cpp|h|hpp|rb|swift)$")


def find_md_files(docs_dir: str) -> list[str]:
    """Find all .md files under docs/."""
    md_files = []
    for root, dirs, files in os.walk(docs_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))
    return md_files


def find_json_files(docs_dir: str) -> list[str]:
    """Find all .json files under docs/schema/."""
    schema_dir = os.path.join(docs_dir, "schema")
    if not os.path.isdir(schema_dir):
        return []
    json_files = []
    for root, dirs, files in os.walk(schema_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".json"):
                json_files.append(os.path.join(root, f))
    return json_files


def load_manifest(project_dir: str) -> dict | None:
    """Load manifest.json from project directory."""
    path = os.path.join(project_dir, MANIFEST_PATH)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def check_wiki_links(project_dir: str, issues: list) -> None:
    """Check all wiki links in docs/*.md point to existing files."""
    docs_dir = os.path.join(project_dir, DOCS_DIR)
    md_files = find_md_files(docs_dir)

    for md_file in md_files:
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            continue

        rel_path = os.path.relpath(md_file, project_dir).replace("\\", "/")

        for wm in WIKI_LINK_PATTERN.finditer(content):
            target = wm.group(1).strip()

            # Skip external links
            if target.startswith("http"):
                continue

            # Skip src/ links (they point to source code symbols)
            if target.startswith("src/"):
                # Check format: src/path/to/file.ext#symbol or src/path/to/file.ext
                if "#" in target:
                    path_part, symbol = target.rsplit("#", 1)
                else:
                    path_part = target
                    symbol = None

                # Check the file part looks reasonable
                if not FILE_EXT_PATTERN.search(path_part):
                    issues.append({
                        "severity": "warning",
                        "category": "bad_src_link",
                        "location": rel_path,
                        "message": f"Source link '{target}' doesn't look like a valid source file path",
                    })
                continue

            # Check known prefixes
            if target.startswith("modules/"):
                expected_path = os.path.join(docs_dir, f"{target}.md")
                if not os.path.isfile(expected_path):
                    issues.append({
                        "severity": "error",
                        "category": "broken_wiki_link",
                        "location": rel_path,
                        "message": f"Wiki link '[[{target}]]' → {DOCS_DIR}/{target}.md not found",
                    })
                continue

            if target.startswith("project/"):
                expected_path = os.path.join(docs_dir, f"{target}.md")
                if not os.path.isfile(expected_path):
                    issues.append({
                        "severity": "error",
                        "category": "broken_wiki_link",
                        "location": rel_path,
                        "message": f"Wiki link '[[{target}]]' → {DOCS_DIR}/{target}.md not found",
                    })
                continue

            if target.startswith("schema/"):
                expected_path = os.path.join(docs_dir, f"{target}.json")
                if not os.path.isfile(expected_path):
                    issues.append({
                        "severity": "warning",
                        "category": "broken_schema_link",
                        "location": rel_path,
                        "message": f"Schema link '[[{target}]]' → {DOCS_DIR}/{target}.json not found",
                    })
                continue

            # Unrecognized prefix — could be an old-style link (e.g. [[polyglot-router]])
            # Check if it looks like a module name (no slashes, no dots)
            if "/" not in target and "." not in target:
                expected_path = os.path.join(docs_dir, "modules", f"{target}.md")
                if not os.path.isfile(expected_path):
                    expected_project = os.path.join(docs_dir, "project", f"{target}.md")
                    if not os.path.isfile(expected_project):
                        issues.append({
                            "severity": "warning",
                            "category": "unresolved_wiki_link",
                            "location": rel_path,
                            "message": f"Wiki link '[[{target}]]' — no matching file in {DOCS_DIR}/modules/ or {DOCS_DIR}/project/",
                        })


def check_manifest_module_docs(project_dir: str, manifest: dict, issues: list) -> None:
    """Check that every module in manifest has a corresponding doc file."""
    docs_dir = os.path.join(project_dir, DOCS_DIR)
    for name, mod in manifest.get("modules", {}).items():
        doc_path = mod.get("doc_path", f"docs/modules/{name}.md")
        full_path = os.path.join(project_dir, doc_path)
        doc_status = mod.get("doc_status", "")

        if doc_status == "needs_delete":
            continue  # Expected to be gone

        if not os.path.isfile(full_path):
            issues.append({
                "severity": "error" if doc_status == "up_to_date" else "warning",
                "category": "missing_module_doc",
                "location": doc_path,
                "message": f"Module '{name}' declared in manifest but doc file not found at {doc_path}",
            })

        # Check schema file
        schema_path = mod.get("schema_path", f"docs/schema/{name}.schema.json")
        full_schema_path = os.path.join(project_dir, schema_path)
        if not os.path.isfile(full_schema_path) and doc_status != "needs_delete":
            issues.append({
                "severity": "warning",
                "category": "missing_module_schema",
                "location": schema_path,
                "message": f"Module '{name}' has no schema file at {schema_path}",
            })


def check_orphan_docs(project_dir: str, manifest: dict, issues: list) -> None:
    """Check that every doc file under docs/modules/ is declared in manifest."""
    docs_dir = os.path.join(project_dir, DOCS_DIR)
    modules_dir = os.path.join(docs_dir, "modules")

    if not os.path.isdir(modules_dir):
        return

    manifest_modules = set(manifest.get("modules", {}).keys())

    for md_file in find_md_files(modules_dir):
        rel_path = os.path.relpath(md_file, project_dir).replace("\\", "/")
        # Extract module name from path
        # docs/modules/foo.md → foo
        # docs/modules/foo/bar.md → foo/bar
        name = rel_path.replace(f"{DOCS_DIR}/modules/", "").replace(".md", "")

        # Skip index files
        if name == "index" or name.endswith("/index"):
            continue

        # Check if module name is in manifest (with or without subdirectory)
        found = False
        for mod_name in manifest_modules:
            if name == mod_name or name.startswith(mod_name + "/") or mod_name.startswith(name):
                found = True
                break

        if not found:
            issues.append({
                "severity": "warning",
                "category": "orphan_doc",
                "location": rel_path,
                "message": f"Doc file {rel_path} exists but is not declared in manifest",
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify doc reference integrity (no AI calls)")
    parser.add_argument("--project-dir", "-p", default=".",
                        help="Project directory (default: current dir)")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--strict", "-s", action="store_true",
                        help="Treat warnings as errors (exit code 2 on any warning)")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    issues = []

    # Check 1: Wiki links in doc files
    check_wiki_links(project_dir, issues)

    # Check 2: Manifest module docs
    manifest = load_manifest(project_dir)
    if manifest:
        check_manifest_module_docs(project_dir, manifest, issues)
        check_orphan_docs(project_dir, manifest, issues)
    else:
        issues.append({
            "severity": "warning",
            "category": "missing_manifest",
            "location": MANIFEST_PATH,
            "message": f"No manifest.json found at {MANIFEST_PATH}",
        })

    # Categorize
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    if args.json:
        print(json.dumps({
            "passed": len(errors) == 0 and (len(warnings) == 0 if args.strict else True),
            "total": len(issues),
            "errors": len(errors),
            "warnings": len(warnings),
            "issues": issues,
        }, indent=2, ensure_ascii=False))
    else:
        print(f"[verify] Reference check complete: {len(errors)} errors, {len(warnings)} warnings\n")
        for issue in issues:
            icon = "✗" if issue["severity"] == "error" else "△"
            print(f"  {icon} [{issue['category']}] {issue['message']}")
            print(f"     at {issue['location']}")

    # Determine exit code
    if errors:
        return 2
    if args.strict and warnings:
        return 2
    if warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())