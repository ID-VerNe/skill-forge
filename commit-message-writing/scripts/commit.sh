#!/bin/bash
# commit.sh — Commit with identity enforcement
# Usage: bash commit.sh <message_file>
# Reads commit message from file (avoids shell escaping issues),
# sets identity, checks for Co-Authored-By, then commits.

set -e

if [ $# -lt 1 ]; then
  echo "Usage: bash commit.sh <message_file>" >&2
  exit 1
fi

MSG_FILE="$1"
if [ ! -f "$MSG_FILE" ]; then
  echo "[x] Message file not found: $MSG_FILE" >&2
  exit 1
fi

# Set identity
git config user.name "ID-VerNe"
git config user.email "yuu_seeing@foxmail.com"
export GIT_COMMITTER_NAME="ID-VerNe"
export GIT_COMMITTER_EMAIL="yuu_seeing@foxmail.com"

# Check for Co-Authored-By in the message file
if grep -qi "Co-Authored-By" "$MSG_FILE"; then
  echo "[x] Commit message contains Co-Authored-By line! Remove it first." >&2
  exit 1
fi

# Commit using -F to read from file (no shell escaping issues)
git commit -F "$MSG_FILE"
echo "[v] Commit successful."