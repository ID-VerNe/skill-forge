#!/bin/bash
# commit.sh — Commit with identity enforcement.
# Usage: bash commit.sh <message_file>
# Reads commit message from file (avoids shell escaping issues),
# loads identity from identity.env via set-identity.sh,
# rejects Co-Authored-By trailers, then commits.
#
# Exits non-zero on ANY failure (missing file, forbidden trailer,
# failed git commit, missing identity) — the caller can rely on
# the exit code to decide what to do next.

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -lt 1 ]; then
  echo "Usage: bash commit.sh <message_file>" >&2
  exit 1
fi

MSG_FILE="$1"
if [ ! -f "$MSG_FILE" ]; then
  echo "[x] Message file not found: $MSG_FILE" >&2
  exit 1
fi

# Reject Co-Authored-By (before setting identity — fail fast)
if grep -qi "Co-Authored-By" "$MSG_FILE"; then
  echo "[x] Commit message contains Co-Authored-By line! Remove it first." >&2
  exit 1
fi

# Load identity (sources identity.env, sets git config, exports env vars)
# shellcheck disable=SC1090
source "$SCRIPT_DIR/set-identity.sh"

# Commit using -F to read from file (no shell escaping issues)
git commit -F "$MSG_FILE"
echo "[v] Commit successful."
