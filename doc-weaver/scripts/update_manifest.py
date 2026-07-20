#!/usr/bin/env python3
"""update_manifest.py — Detect file changes and update manifest.json.

Usage:
    python update_manifest.py [--project-dir <path>] [--dry-run] [--force]

Reads docs/schema/manifest.json, compares each module's source file
hash + mtime against current filesystem state, and updates the manifest
with new doc_status values:

    up_to_date      — no changes detected
    needs_create    — new module not yet in manifest
    needs_update    — source file hash or mtime changed
    needs_delete    — source file no longer exists

Also scans for new source files not tracked by any existing module.

Change detection is based on file hash (first 4KB + size + mtime), NOT
git. Files that are un-staged, un-committed, or in a non-git repo are
all detected correctly.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone


MANIFEST_PATH = "docs/schema/manifest.json"

# Source file extensions to track
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".php", ".rs", ".go",
    ".java", ".kt", ".c", ".cpp", ".h", ".hpp", ".rb", ".swift",
    ".sh", ".bash", ".zsh", ".fish",
    ".yaml", ".yml", ".toml",
    ".html", ".css", ".scss", ".less", ".vue", ".svelte", ".astro",
}

# Directories to skip during scanning
SKIP_DIRS = {".git", "node_modules", "venv", "__pycache__", "target",
             "build", "dist", "vendor", ".venv", ".tox", ".eggs",
             "egg-info", ".mypy_cache", ".pytest_cache", ".ruff_cache",
             ".claude", "docs", "lat.md", "outputs", ".plan", "scripts",
             "references", "glue-engineer"}


def get_file_hash(file_path: str) -> str:
    """File hash (SHA256 of first 4KB + size + mtime)."""
    try:
        stat = os.stat(file_path)
        size = stat.st_size
        mtime = stat.st_mtime
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            sha.update(f.read(4096))
        sha.update(str(size).encode())
        sha.update(str(mtime).encode())
        return sha.hexdigest()
    except OSError:
        return ""


def get_file_mtime(file_path: str) -> str:
    """Get file mtime as ISO string."""
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def load_manifest(project_dir: str) -> dict | None:
    """Load manifest.json from project directory."""
    path = os.path.join(project_dir, MANIFEST_PATH)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_manifest(project_dir: str, manifest: dict) -> None:
    """Save manifest.json to project directory."""
    path = os.path.join(project_dir, MANIFEST_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  [save] {path}")


def scan_source_files(project_dir: str) -> list[str]:
    """Scan for source files not yet tracked."""
    source_files = []
    for root, dirs, files in os.walk(project_dir):
        # Skip common dirs
        rel = os.path.relpath(root, project_dir).replace("\\", "/")
        parts = rel.split("/")
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            continue

        for f in files:
            ext = os.path.splitext(f)[1]
            if ext in SOURCE_EXTENSIONS and not f.startswith("."):
                source_files.append(os.path.join(root, f))

    return source_files


def infer_module_name(file_path: str, project_dir: str) -> str:
    """Infer module name from file path."""
    rel = os.path.relpath(file_path, project_dir).replace("\\", "/")
    parts = rel.split("/")
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    elif len(parts) >= 2:
        return parts[0]
    return os.path.splitext(parts[0])[0]


def detect_changes(manifest: dict, project_dir: str) -> dict:
    """Compare manifest entries with current filesystem state.

    Returns:
        dict with 'changes' (list of change dicts) and 'updated_modules' (new modules dict)
    """
    modules = manifest.get("modules", {})
    changes = []
    updated_modules = {}

    # Track which source files are accounted for (to detect new files)
    accounted_files = set()

    for mod_name, mod_data in modules.items():
        source_paths = mod_data.get("source_paths", [])

        # Check if all source files still exist
        existing_paths = []
        all_exist = True
        for sp in source_paths:
            # Normalize path separators
            sp_norm = sp.replace("\\", "/")
            full_path = os.path.join(project_dir, sp_norm)
            if os.path.isfile(full_path):
                existing_paths.append(sp_norm)
                accounted_files.add(sp_norm)
            else:
                all_exist = False
                changes.append({
                    "module": mod_name,
                    "type": "file_missing",
                    "detail": f"Source file no longer exists: {sp_norm}",
                })

        if not all_exist and not existing_paths:
            # All files gone → needs_delete
            changes.append({
                "module": mod_name,
                "type": "needs_delete",
                "detail": "All source files removed",
            })
            updated_modules[mod_name] = dict(mod_data)
            updated_modules[mod_name]["doc_status"] = "needs_delete"
            continue

        # Check hash + mtime for each existing file
        # Compute current combined hash of all existing files
        current_hash_inputs = []
        current_mtimes = []
        for sp in existing_paths:
            full_path = os.path.join(project_dir, sp)
            current_hash_inputs.append(get_file_hash(full_path))
            current_mtimes.append(get_file_mtime(full_path))

        stored_hash = mod_data.get("hash", "")
        # Compute current combined hash
        if current_hash_inputs:
            combined = hashlib.sha256()
            for h in current_hash_inputs:
                combined.update(h.encode())
            current_combined = combined.hexdigest()
        else:
            current_combined = ""

        hash_changed = (current_combined != stored_hash)

        if hash_changed and current_hash_inputs:
            changes.append({
                "module": mod_name,
                "type": "file_changed",
                "detail": f"Hash changed: {stored_hash[:12]}... → {current_combined[:12]}...",
            })

        # Carry over existing data
        updated_modules[mod_name] = dict(mod_data)
        updated_modules[mod_name]["source_paths"] = existing_paths

        if hash_changed:
            updated_modules[mod_name]["doc_status"] = "needs_update"
            # Use already-computed hash inputs
            if current_hash_inputs:
                updated_modules[mod_name]["hash"] = current_combined
                # Use latest mtime
                updated_modules[mod_name]["mtime"] = max(current_mtimes)
        elif existing_paths == source_paths:
            # No changes at all
            updated_modules[mod_name]["doc_status"] = mod_data.get("doc_status", "up_to_date")
        else:
            # Some files were removed but not all → still needs_update
            updated_modules[mod_name]["doc_status"] = "needs_update"

    # Scan for new files not in any module
    all_source_files = scan_source_files(project_dir)
    new_files = []
    for sf in all_source_files:
        rel = os.path.relpath(sf, project_dir).replace("\\", "/")
        if rel not in accounted_files:
            # Check if it's already in a module
            found = False
            for mod_data in modules.values():
                if rel in mod_data.get("source_paths", []):
                    found = True
                    break
            if not found:
                new_files.append(rel)

    # Group new files by inferred module name
    new_modules: dict[str, list[str]] = {}
    for nf in new_files:
        mod_name = infer_module_name(nf, project_dir)
        if mod_name not in new_modules:
            new_modules[mod_name] = []
        new_modules[mod_name].append(nf)

    for mod_name, files in new_modules.items():
        changes.append({
            "module": mod_name,
            "type": "needs_create",
            "detail": f"New module detected ({len(files)} file(s)): {', '.join(files[:3])}{'...' if len(files) > 3 else ''}",
        })
        # Create entry for new module
        if mod_name not in updated_modules:
            updated_modules[mod_name] = {
                "source_paths": files,
                "hash": "",
                "mtime": "",
                "doc_status": "needs_create",
                "doc_path": f"docs/modules/{mod_name}.md",
                "schema_path": f"docs/schema/{mod_name}.schema.json",
                "exports": [],
                "dependencies": [],
                "consumers": [],
                "languages": [],
            }
            # Compute initial hash
            hash_inputs = []
            for f in files:
                full_path = os.path.join(project_dir, f)
                h = get_file_hash(full_path)
                m = get_file_mtime(full_path)
                hash_inputs.append((h, m))
            if hash_inputs:
                combined = hashlib.sha256()
                for h, _ in hash_inputs:
                    combined.update(h.encode())
                updated_modules[mod_name]["hash"] = combined.hexdigest()
                updated_modules[mod_name]["mtime"] = max(m for _, m in hash_inputs)

    return {
        "changes": changes,
        "updated_modules": updated_modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect file changes and update manifest.json")
    parser.add_argument("--project-dir", "-p", default=".",
                        help="Project directory (default: current dir)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show changes without writing")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Skip confirmation prompt")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)

    # Load existing manifest
    manifest = load_manifest(project_dir)
    if manifest is None:
        print(f"[update] No manifest.json found at {os.path.join(project_dir, MANIFEST_PATH)}")
        print(f"[update] Run 'init_manifest.py --project-dir <path>' first.")
        return 1

    print(f"[update] Checking file changes in {project_dir}\n")

    # Detect changes
    result = detect_changes(manifest, project_dir)
    changes = result["changes"]
    updated_modules = result["updated_modules"]

    # Summary
    needs_create = [c for c in changes if c["type"] == "needs_create"]
    needs_update = [c for c in changes if c["type"] == "file_changed"]
    needs_delete = [c for c in changes if c["type"] == "needs_delete"]
    unchanged = [c for c in changes if c["type"] == "file_missing"]

    print(f"  Modules in manifest: {len(manifest.get('modules', {}))}")
    print(f"  Modules after update: {len(updated_modules)}")
    print(f"  New modules: {len(needs_create)}")
    print(f"  Changed modules: {len(needs_update)}")
    print(f"  Deleted modules: {len(needs_delete)}")
    print(f"  Missing files: {len(unchanged)}")
    print()

    if not changes:
        print("  ✓ No changes detected. All modules up to date.")
        return 0

    # Print details
    for c in changes:
        icon = {"needs_create": "🆕", "file_changed": "✏️", "needs_delete": "🗑️",
                "file_missing": "⚠️"}.get(c["type"], "?")
        print(f"  {icon} [{c['type']}] {c['module']}: {c['detail']}")

    print()

    if args.dry_run:
        print("[update] Dry run — no changes written.")
        return 0

    if not args.force:
        print("[update] Use --force to apply changes, or --dry-run to preview.")
        return 0

    # Apply changes
    manifest["modules"] = updated_modules
    manifest["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_manifest(project_dir, manifest)

    print(f"\n[update] Done. {len(changes)} change(s) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())