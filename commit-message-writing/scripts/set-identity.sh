#!/bin/bash
# set-identity.sh — Set git identity for commits (source, don't execute).
# Reads identity from identity.env (single source of truth) and applies:
#   1. `git config` — persistent identity for this repo
#   2. Exported env vars — per-invocation override for THIS shell process
#
# Usage: source set-identity.sh
# Must be sourced (not executed) so `export`'d vars persist into the
# current shell. If you run `bash set-identity.sh`, the env vars vanish
# as soon as the subprocess exits.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IDENTITY_FILE="$SCRIPT_DIR/identity.env"

if [ ! -f "$IDENTITY_FILE" ]; then
  echo "[x] identity.env not found: $IDENTITY_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$IDENTITY_FILE"

# Persist to git config (per-repo)
git config user.name    "$GIT_AUTHOR_NAME"
git config user.email   "$GIT_AUTHOR_EMAIL"

# Export env overrides for this shell process
# (git reads GIT_AUTHOR_* / GIT_COMMITTER_* directly from env)
export GIT_AUTHOR_NAME
export GIT_AUTHOR_EMAIL
export GIT_COMMITTER_NAME
export GIT_COMMITTER_EMAIL

echo "[v] Git identity: $GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>"
