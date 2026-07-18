#!/bin/bash
# stage.sh — Stage files one by one (no batch add)
# Usage: bash stage.sh <file1> [file2 ...]
# Exits with error if any file doesn't exist.

set -e

if [ $# -eq 0 ]; then
  echo "Usage: bash stage.sh <file1> [file2 ...]" >&2
  echo "Tip: run 'git status' first to see what's available." >&2
  exit 1
fi

for f in "$@"; do
  if [ -f "$f" ] || [ -d "$f" ]; then
    git add "$f"
    echo "[v] Staged: $f"
  else
    echo "[x] Not found: $f" >&2
    exit 1
  fi
done

echo "[v] All files staged successfully."