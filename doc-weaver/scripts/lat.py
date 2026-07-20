#!/usr/bin/env python3
"""lat — Bidirectional documentation ↔ source code navigation CLI.

Usage:
    lat index                    Scan and rebuild bidirectional index
    lat lookup <file>[:<line>]   Source file → doc sections
    lat locate <section-id>      Doc section → source code locations
    lat context <file>           Read full module docs for a source file
    lat check                    Validate all @lat annotations
    lat suggest <file>           Suggest @lat annotations for a source file

The index is stored at docs/schema/lat-index.json.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_INDEX_PATH = "docs/schema/lat-index.json"
DEFAULT_MANIFEST_PATH = "docs/schema/manifest.json"
DOCS_DIR = "docs"
MODULES_DIR = f"{DOCS_DIR}/modules"

# Patterns for @lat annotations in source files
LAT_PATTERN = re.compile(r"""
    [#/]{1,2}\s*@lat:\s*\[\[
    (?P<section_id>[^\]]+)
    \]\]
""", re.VERBOSE)

# Patterns for section IDs in markdown files (headings)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Wiki link pattern in docs
WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

# Available source comment styles per language
LANG_COMMENT_MAP = {
    ".py": "#",
    ".js": "//",
    ".ts": "//",
    ".tsx": "//",
    ".jsx": "//",
    ".rs": "//",
    ".go": "//",
    ".java": "//",
    ".kt": "//",
    ".php": "//",
    ".rb": "#",
    ".swift": "//",
    ".c": "//",
    ".cpp": "//",
    ".h": "//",
    ".hpp": "//",
    ".sh": "#",
    ".yaml": "#",
    ".yml": "#",
    ".toml": "#",
    ".json": "//",  # Not really, but some JSONC variants
}


# ── Helpers ────────────────────────────────────────────────────────────────

def find_project_root() -> str:
    """Walk up from cwd to find project root (where docs/ lives)."""
    cwd = os.getcwd()
    for parent in [cwd] + [os.path.dirname(cwd)] * 5:
        docs_dir = os.path.join(parent, DOCS_DIR)
        if os.path.isdir(docs_dir):
            return parent
    return cwd


def find_source_files(project_root: str) -> list[str]:
    """Find all source files that could have @lat annotations."""
    src_dirs = []
    # Common source directories
    for d in ["src", "polyglot", "lib", "app", "api", "core", "utils", "services"]:
        p = os.path.join(project_root, d)
        if os.path.isdir(p):
            src_dirs.append(p)
    # Also scan root-level files
    src_dirs.append(project_root)

    source_files = []
    extensions = tuple(LANG_COMMENT_MAP.keys())
    for src_dir in src_dirs:
        for root, dirs, files in os.walk(src_dir):
            # Skip common non-source dirs
            dirs[:] = [d for d in dirs if not d.startswith((".", "node_modules", "venv",
                                                             "__pycache__", "target", "build",
                                                             "dist", "vendor", ".git"))]
            # Skip if we're already inside docs/
            if DOCS_DIR in root.split(os.sep):
                continue
            for f in files:
                if f.endswith(extensions) and not f.startswith("."):
                    source_files.append(os.path.join(root, f))

    return source_files


def find_doc_files(project_root: str) -> list[str]:
    """Find all markdown doc files from docs/ or lat.md/."""
    doc_files = []

    # Primary: docs/
    docs_dir = os.path.join(project_root, "docs")
    if os.path.isdir(docs_dir):
        for root, dirs, files in os.walk(docs_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.endswith(".md"):
                    doc_files.append(os.path.join(root, f))

    # Fallback: lat.md/ (legacy format)
    lat_dir = os.path.join(project_root, "lat.md")
    if os.path.isdir(lat_dir):
        for root, dirs, files in os.walk(lat_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.endswith(".md"):
                    doc_files.append(os.path.join(root, f))

    return doc_files


def extract_section_ids(file_path: str) -> list[dict]:
    """Extract all section IDs from a markdown file."""
    sections = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, OSError):
        return sections

    # Build relative path for section ID
    rel_path = os.path.relpath(file_path, os.getcwd()).replace("\\", "/")
    # Remove .md extension for section ID format
    section_base = re.sub(r"\.md$", "", rel_path)

    # Also extract short base (module name only, for legacy @lat format)
    # e.g. "lat.md/polyglot-router" → "polyglot-router"
    # e.g. "docs/modules/polyglot-router" → "polyglot-router"
    short_base = os.path.basename(section_base)

    # Track heading chain
    heading_chain = []
    heading_levels = []

    for match in HEADING_PATTERN.finditer(content):
        level = len(match.group(1))
        text = match.group(2).strip()

        # Remove leading/trailing markers from template placeholders
        text = re.sub(r"^<!--.*?-->$", "", text).strip()
        if not text:
            continue

        # Build heading chain
        while heading_levels and heading_levels[-1] >= level:
            heading_levels.pop()
            heading_chain.pop()
        heading_levels.append(level)
        heading_chain.append(text)

        # Full section ID (new format)
        section_id = section_base + "#" + "#".join(heading_chain)
        # Short section ID (legacy format: just module#subheading)
        short_id = short_base + "#" + "#".join(heading_chain)

        sections.append({
            "section_id": section_id,
            "short_id": short_id,
            "heading_chain": list(heading_chain),
            "level": level,
            "line": match.start(),
        })

    return sections


def extract_lat_annotations(file_path: str) -> list[dict]:
    """Extract all @lat annotations from a source file."""
    annotations = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (UnicodeDecodeError, OSError):
        return annotations

    for i, line in enumerate(lines, 1):
        m = LAT_PATTERN.search(line)
        if m:
            annotations.append({
                "line": i,
                "section_id": m.group("section_id").strip(),
                "annotation": f"# @lat: [[{m.group('section_id').strip()}]]",
            })

    return annotations


def get_module_name_from_file(file_path: str, manifest: dict | None) -> str | None:
    """Given a source file path, find its module name from manifest."""
    if not manifest:
        return None
    rel_path = os.path.relpath(file_path, os.getcwd()).replace("\\", "/")
    for name, mod in manifest.get("modules", {}).items():
        for sp in mod.get("source_paths", []):
            if sp == rel_path or sp in rel_path or rel_path == sp:
                return name
    return None


def get_file_hash(file_path: str) -> str:
    """Quick file hash (first 4KB + file size + mtime)."""
    try:
        stat = os.stat(file_path)
        size = stat.st_size
        mtime = stat.st_mtime
        with open(file_path, "rb") as f:
            head = f.read(4096)
        return f"{hash((head, size, mtime)):016x}"
    except OSError:
        return ""


def infer_doc_from_section_id(section_id: str, index: dict) -> str | None:
    """Infer the doc file path from a section ID by matching the module prefix."""
    # Extract the module prefix (everything before the first #)
    module_prefix = section_id.split("#")[0] if "#" in section_id else section_id
    # Remove legacy dir prefix if present
    for prefix in ["lat.md/", "docs/modules/", "docs/project/", "docs/"]:
        if module_prefix.startswith(prefix):
            module_prefix = module_prefix[len(prefix):]
            break

    # Now look for any section whose ID contains this module prefix
    for sid, sec in index.get("sections", {}).items():
        if module_prefix in sid:
            return sec.get("doc_path", "?")

    return None


# ── Commands ───────────────────────────────────────────────────────────────

def cmd_index(args: argparse.Namespace) -> int:
    """Scan all @lat annotations + doc section IDs, rebuild index."""
    project_root = args.project_root
    index_path = os.path.join(project_root, args.index)

    # Load manifest if available
    manifest_path = os.path.join(project_root, DEFAULT_MANIFEST_PATH)
    manifest = None
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

    # Scan docs for section IDs
    doc_files = find_doc_files(project_root)
    sections: dict[str, dict] = {}
    for df in doc_files:
        extracted = extract_section_ids(df)
        for s in extracted:
            sid = s["section_id"]
            short_id = s["short_id"]
            # Register under both full and short ID
            for reg_id in [sid, short_id]:
                if reg_id not in sections:
                    sections[reg_id] = {
                        "doc_path": os.path.relpath(df, os.getcwd()).replace("\\", "/"),
                        "heading_chain": s["heading_chain"],
                        "code_refs": [],
                    }

    # Scan source files for @lat annotations
    source_files = find_source_files(project_root)
    files_index: dict[str, dict] = {}

    for sf in source_files:
        annotations = extract_lat_annotations(sf)
        if not annotations:
            continue

        rel_path = os.path.relpath(sf, os.getcwd()).replace("\\", "/")
        module_name = get_module_name_from_file(sf, manifest)

        file_entry = {
            "module": module_name or "unknown",
            "annotations": [],
        }

        for a in annotations:
            section_id = a["section_id"]
            file_entry["annotations"].append({
                "line": a["line"],
                "section_id": section_id,
            })

            # Build the reverse link
            if section_id in sections:
                # Check if this code_ref already exists (dedup)
                existing = [r for r in sections[section_id]["code_refs"]
                            if r["file"] == rel_path and r["line"] == a["line"]]
                if not existing:
                    sections[section_id]["code_refs"].append({
                        "file": rel_path,
                        "line": a["line"],
                        "annotation": a["annotation"],
                    })

        files_index[rel_path] = file_entry

    # Build the index
    index = {
        "version": "1.0.0",
        "indexed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections": sections,
        "files": files_index,
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f"[lat] Indexed {len(sections)} sections, {len(files_index)} files with @lat annotations")
    print(f"[lat] Index saved to {index_path}")
    return 0


def cmd_lookup(args: argparse.Namespace) -> int:
    """Source file → doc sections."""
    index = load_index(args)
    if index is None:
        return 1

    file_arg = args.file
    line = None
    if ":" in file_arg:
        file_arg, line_str = file_arg.split(":", 1)
        try:
            line = int(line_str)
        except ValueError:
            pass

    # Normalize path
    file_arg = file_arg.replace("\\", "/")

    # Find matching file entry
    entry = index.get("files", {}).get(file_arg)
    if not entry:
        # Try relative path matching
        cwd = os.getcwd().replace("\\", "/")
        for key, val in index.get("files", {}).items():
            if key.endswith(file_arg) or file_arg in key:
                entry = val
                file_arg = key
                break

    if not entry:
        print(f"[lat] No @lat annotations found for '{file_arg}'")
        return 1

    annotations = entry["annotations"]
    if line is not None:
        annotations = [a for a in annotations if a["line"] == line]

    if not annotations:
        print(f"[lat] No @lat annotations at '{file_arg}:{line}'" if line
              else f"[lat] No @lat annotations in '{file_arg}'")
        return 0

    print(f"[lat] {len(annotations)} annotation(s) in '{file_arg}':\n")
    for a in annotations:
        section_id = a["section_id"]
        sec = index.get("sections", {}).get(section_id)
        # Try partial match
        if not sec:
            for sid, s in index.get("sections", {}).items():
                if section_id in sid or sid.endswith(section_id):
                    sec = s
                    break
        doc_path = sec.get("doc_path", "?") if sec else "?"
        heading = " → ".join(sec.get("heading_chain", [])) if sec else "?"

        # If we still have "?" for doc_path, try to infer it from the module name prefix
        if doc_path == "?":
            inferred_doc = infer_doc_from_section_id(section_id, index)
            if inferred_doc:
                doc_path = inferred_doc

        # If heading is still "?" but we found a doc, show the annotation's section_id as the heading hint
        if heading == "?" and doc_path != "?":
            heading = section_id

        print(f"  Line {a['line']}: {section_id}")
        print(f"    Doc: {doc_path}")
        print(f"    Heading: {heading}")
        print()

    return 0


def cmd_locate(args: argparse.Namespace) -> int:
    """Doc section → source code locations."""
    index = load_index(args)
    if index is None:
        return 1

    section_id = args.section_id
    # Try exact match first
    sec = index.get("sections", {}).get(section_id)

    # If not found, try partial match
    if not sec:
        matches = []
        for sid, s in index.get("sections", {}).items():
            if section_id in sid or section_id in sid.replace("#", "/"):
                matches.append((sid, s))
        if len(matches) == 1:
            sec = matches[0][1]
            section_id = matches[0][0]
        elif len(matches) > 1:
            print(f"[lat] Multiple sections match '{section_id}':\n")
            for sid, s in matches:
                code_refs = s.get("code_refs", [])
                print(f"  {sid}")
                print(f"    Doc: {s['doc_path']}")
                print(f"    Code refs: {len(code_refs)}")
                print()
            return 0

    if not sec:
        # Try infer_doc_from_section_id fallback
        inferred_doc = infer_doc_from_section_id(section_id, index)
        if inferred_doc:
            print(f"[lat] Section '{section_id}' not found in index")
            print(f"   Inferred doc: {inferred_doc}")
            print(f"   (The @lat annotation references a section that doesn't exist in the index.)")
            # Show the closest matching sections from the same module
            module_prefix = section_id.split("#")[0] if "#" in section_id else section_id
            for prefix in ["lat.md/", "docs/modules/", "docs/project/", "docs/"]:
                if module_prefix.startswith(prefix):
                    module_prefix = module_prefix[len(prefix):]
                    break
            similar = []
            for sid in index.get("sections", {}):
                if module_prefix in sid:
                    similar.append(sid)
            if similar:
                print(f"\n   Available sections in same module ({len(similar)} total):")
                for sid in similar[:5]:
                    print(f"     {sid}")
                if len(similar) > 5:
                    print(f"     ... and {len(similar) - 5} more")
            return 1

        print(f"[lat] Section '{section_id}' not found in index")
        return 1

    code_refs = sec.get("code_refs", [])
    print(f"[lat] Section: {section_id}")
    print(f"   Doc: {sec['doc_path']}")
    print(f"   Heading: {' → '.join(sec['heading_chain'])}\n")

    if not code_refs:
        print("   No source code references found.")
        return 0

    print(f"   {len(code_refs)} source code reference(s):\n")
    for ref in code_refs:
        print(f"     {ref['file']}:{ref['line']}")
        print(f"       {ref['annotation']}")
        print()

    return 0


def cmd_context(args: argparse.Namespace) -> int:
    """Read full module docs for a source file."""
    index = load_index(args)
    if index is None:
        return 1

    file_arg = args.file.replace("\\", "/")

    # Try to find which module this file belongs to
    entry = index.get("files", {}).get(file_arg)
    if not entry:
        # try partial match
        for key, val in index.get("files", {}).items():
            if key.endswith(file_arg) or file_arg in key:
                entry = val
                file_arg = key
                break

    if not entry:
        print(f"[lat] No @lat annotations found for '{file_arg}'")
        print(f"[lat] Try running 'lat index' first, or check the file path.")
        return 1

    module_name = entry.get("module", "unknown")

    # Find the doc file for this module
    doc_path = None
    for sid, sec in index.get("sections", {}).items():
        doc_file = sec.get("doc_path", "")
        if module_name != "unknown" and module_name in doc_file:
            doc_path = doc_file
            break

    if not doc_path and entry.get("annotations"):
        # Try by looking at the first annotation's section_id with partial match
        first_sid = entry["annotations"][0]["section_id"]
        for sid, sec in index.get("sections", {}).items():
            if first_sid in sid or sid.endswith(first_sid):
                doc_path = sec["doc_path"]
                break

    if not doc_path and entry.get("annotations"):
        # Try infer_doc_from_section_id fallback
        first_sid = entry["annotations"][0]["section_id"]
        doc_path = infer_doc_from_section_id(first_sid, index)

    if not doc_path:
        print(f"[lat] Could not find doc file for module '{module_name}'")
        return 1

    # Read the doc file
    full_path = os.path.join(os.getcwd(), doc_path)
    if not os.path.isfile(full_path):
        print(f"[lat] Doc file not found: {doc_path}")
        return 1

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        print(f"[lat] Error reading {doc_path}: {e}")
        return 1

    print(f"[lat] Context for '{file_arg}' (module: {module_name}):\n")
    print(f"   Doc: {doc_path}\n")
    print("─" * 60)
    print(content)
    print("─" * 60)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Validate all @lat annotations."""
    index = load_index(args)
    if index is None:
        return 1

    issues = []

    # Check 1: Every section in index should have at least one code_ref
    for sid, sec in index.get("sections", {}).items():
        if not sec.get("code_refs"):
            issues.append({
                "severity": "warning",
                "type": "orphan_section",
                "message": f"Section '{sid}' has no source code @lat references",
                "location": sec["doc_path"],
            })

    # Check 2: Every file annotation should point to a real section
    for file_path, entry in index.get("files", {}).items():
        for a in entry.get("annotations", []):
            sid = a["section_id"]
            if sid not in index.get("sections", {}):
                issues.append({
                    "severity": "error",
                    "type": "broken_ref",
                    "message": f"@lat annotation at {file_path}:{a['line']} references non-existent section '{sid}'",
                    "location": f"{file_path}:{a['line']}",
                })

    # Check 3: Check wiki links in doc files point to existing files
    doc_files = find_doc_files(args.project_root)
    for df in doc_files:
        try:
            with open(df, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue

        rel_path = os.path.relpath(df, os.getcwd()).replace("\\", "/")
        for wm in WIKI_LINK_PATTERN.finditer(content):
            target = wm.group(1).strip()
            # Skip external links (http://, https://)
            if target.startswith("http"):
                continue
            # Skip src/ links (they point to source code)
            if target.startswith("src/"):
                continue
            # Skip schema/ links (they point to JSON files)
            if target.startswith("schema/"):
                continue

            # Convert wiki link to file path
            # [[modules/xxx]] → docs/modules/xxx.md
            # [[project/index]] → docs/project/index.md
            wiki_path = os.path.join(DOCS_DIR, f"{target}.md")
            full_wiki_path = os.path.join(args.project_root, wiki_path)
            if not os.path.isfile(full_wiki_path):
                issues.append({
                    "severity": "warning",
                    "type": "broken_wiki_link",
                    "message": f"Wiki link '[[{target}]]' in {rel_path} points to non-existent file {wiki_path}",
                    "location": rel_path,
                })

    # Summary
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    print(f"[lat] Check complete: {len(errors)} errors, {len(warnings)} warnings\n")

    for issue in issues:
        sev = "✗" if issue["severity"] == "error" else "△"
        print(f"  {sev} [{issue['type']}] {issue['message']}")

    if not issues:
        print("  All checks passed! ✓")

    return 1 if errors else 0


def cmd_suggest(args: argparse.Namespace) -> int:
    """Suggest @lat annotations for a source file based on function/class names."""
    file_path = os.path.join(args.project_root, args.file)

    if not os.path.isfile(file_path):
        print(f"[lat] File not found: {file_path}")
        return 1

    # Load index for existing sections
    index = load_index(args)
    if index is None:
        return 1

    # Try to find matching doc sections
    rel_path = os.path.relpath(file_path, os.getcwd()).replace("\\", "/")
    module_name = rel_path.split("/")[0] if "/" in rel_path else os.path.splitext(rel_path)[0]

    # Find sections that match this module
    matching_sections = []
    for sid, sec in index.get("sections", {}).items():
        if module_name in sid:
            matching_sections.append(sid)

    if not matching_sections:
        print(f"[lat] No matching doc sections found for '{rel_path}'")
        print(f"[lat] Try running 'lat index' first, or check if docs exist for this module.")
        return 0

    # Extract function/class names from source
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        print(f"[lat] Error reading {file_path}: {e}")
        return 1

    # Simple regex for function/class definitions (language-agnostic)
    def_pattern = re.compile(r"^(?:def\s+|function\s+|fn\s+|func\s+|public\s+\w+\s+function\s+)?(\w+)\s*\(|^(?:class\s+|struct\s+|interface\s+|trait\s+)?(\w+)", re.MULTILINE)
    symbols = set()
    for m in def_pattern.finditer(content):
        symbol = m.group(1) or m.group(2)
        if symbol and symbol not in ("if", "for", "while", "return", "import"):
            symbols.add(symbol)

    # Suggest annotations
    print(f"[lat] Suggestions for '{rel_path}':\n")
    comment_style = LANG_COMMENT_MAP.get(os.path.splitext(file_path)[1], "#")

    # Find sections that match by symbol name
    suggested = []
    for sid in matching_sections:
        for sym in symbols:
            if sym.lower() in sid.lower():
                comment = f"{comment_style} @lat: [[{sid}]]"
                suggested.append((sym, sid, comment))

    if suggested:
        print(f"  Found {len(suggested)} potential matches by symbol name:\n")
        for sym, sid, comment in suggested[:20]:
            print(f"    {sym} → {comment}")
        print()

    # List all matching sections
    print(f"  All {len(matching_sections)} matching sections for module '{module_name}':\n")
    for sid in matching_sections:
        comment = f"{comment_style} @lat: [[{sid}]]"
        print(f"    {comment}")
    print()

    return 0


# ── Index loader ───────────────────────────────────────────────────────────

def load_index(args: argparse.Namespace) -> dict | None:
    """Load the lat-index.json, rebuild if missing."""
    index_path = os.path.join(args.project_root, args.index)
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="lat — Bidirectional doc ↔ code navigation")
    parser.add_argument("--project-root", "-r", default=None,
                        help="Project root directory (default: auto-detect)")
    parser.add_argument("--index", "-i", default=DEFAULT_INDEX_PATH,
                        help=f"Index path (default: {DEFAULT_INDEX_PATH})")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # index
    p_index = subparsers.add_parser("index", help="Rebuild the bidirectional index")

    # lookup
    p_lookup = subparsers.add_parser("lookup", help="Source file → doc sections")
    p_lookup.add_argument("file", help="Source file path (optionally: file:line)")

    # locate
    p_locate = subparsers.add_parser("locate", help="Doc section → source code locations")
    p_locate.add_argument("section_id", help="Section ID (e.g. 'docs/modules/router#Key Concepts')")

    # context
    p_context = subparsers.add_parser("context", help="Read full module docs for a source file")
    p_context.add_argument("file", help="Source file path")

    # check
    p_check = subparsers.add_parser("check", help="Validate all @lat annotations")

    # suggest
    p_suggest = subparsers.add_parser("suggest", help="Suggest @lat annotations for a file")
    p_suggest.add_argument("file", help="Source file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Resolve project root
    if args.project_root:
        args.project_root = os.path.abspath(args.project_root)
    else:
        args.project_root = find_project_root()

    # Resolve index path relative to project root
    if not os.path.isabs(args.index):
        args.index = os.path.join(args.project_root, args.index)

    # Dispatch
    cmd_map = {
        "index": cmd_index,
        "lookup": cmd_lookup,
        "locate": cmd_locate,
        "context": cmd_context,
        "check": cmd_check,
        "suggest": cmd_suggest,
    }

    return cmd_map[args.command](args)


if __name__ == "__main__":
    sys.exit(main())