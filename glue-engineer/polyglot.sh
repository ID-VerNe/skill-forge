#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# polyglot.sh — Glue Engineer polyglot CLI wrapper
# ═══════════════════════════════════════════════════════════════════════
# Usage:
#   ./polyglot.sh scout python "requests"
#   ./polyglot.sh deep-init --project "my-project" --repos <url>...
#   ./polyglot.sh bridge python orjson rust serde_json
#
# Runs from ANY directory; all .glue/ output goes to the current
# working directory (the project directory where Claude Code was launched).
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# Resolve the glue-engineer directory (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Add glue-engineer to PYTHONPATH so `python -m polyglot` works from any CWD
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

# Run the polyglot CLI — all paths are relative to the user's CWD, not to glue-engineer
exec python -m polyglot "$@"