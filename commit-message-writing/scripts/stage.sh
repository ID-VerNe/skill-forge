#!/bin/bash
# stage.sh — Stage files one by one (no batch add).
# Usage: bash stage.sh <file1> [file2 ...]
#
# Rules enforced:
#   - Every argument must be an existing regular file (or symlink to one).
#   - Directories are REJECTED — `git add <dir>` would recurse and silently
#     stage everything under it, defeating the explicit-per-file contract
#     this skill exists to enforce.
#
# Exits non-zero on any missing or directory argument (before running git add).

set -eu

if [ $# -eq 0 ]; then
  echo "Usage: bash stage.sh <file1> [file2 ...]" >&2
  echo "Tip: run 'git status' first to see what's available." >&2
  exit 1
fi

for f in "$@"; do
  if [ ! -e "$f" ]; then
    echo "[x] Not found: $f" >&2
    exit 1
  fi
  if [ -d "$f" ]; then
    echo "[x] Refusing to stage a directory: $f" >&2
    echo "    'git add <dir>' would recurse and stage every file inside it." >&2
    echo "    Stage individual files instead — see 'git status' for the list." >&2
    exit 1
  fi
  git add -- "$f"
  echo "[v] Staged: $f"
done

echo "[v] All files staged successfully."
