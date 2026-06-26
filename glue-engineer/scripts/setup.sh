#!/usr/bin/env bash
# glue-engineer v4 — Setup Script (bash/zsh)
#
# Copies subagent definitions and optionally installs permissions.
# Usage:
#   bash scripts/setup.sh                    # install agents only
#   bash scripts/setup.sh --with-permissions  # install agents + settings
#   bash scripts/setup.sh --dry-run           # show what would be done

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_DIR="${HOME}/.claude"
AGENTS_DIR="${CLAUDE_DIR}/agents"
SETTINGS_FILE="${CLAUDE_DIR}/settings.json"
DRY_RUN=false
WITH_PERMS=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --with-permissions) WITH_PERMS=true ;;
        --help)
            echo "Usage: bash scripts/setup.sh [--with-permissions] [--dry-run]"
            exit 0
            ;;
    esac
done

echo "=== glue-engineer v4 Setup ==="
echo "  Skill directory: ${SKILL_DIR}"
echo ""

# Step 1: Verify the skill looks complete
echo "[1/4] Validating skill structure..."
REQUIRED=(
    "${SKILL_DIR}/SKILL.md"
    "${SKILL_DIR}/polyglot/router.py"
    "${SKILL_DIR}/agents/glue-repo-architect.md"
    "${SKILL_DIR}/agents/glue-reuse-mapper.md"
    "${SKILL_DIR}/agents/glue-integration-planner.md"
    "${SKILL_DIR}/agents/glue-synthesizer.md"
)
MISSING=0
for f in "${REQUIRED[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  [x] Missing: ${f}"
        MISSING=$((MISSING + 1))
    fi
done
if [ "$MISSING" -gt 0 ]; then
    echo "  [x] ${MISSING} required file(s) missing — skill may be incomplete"
else
    echo "  [v] All required files present"
fi

# Step 2: Create agents directory
echo ""
echo "[2/4] Installing subagent definitions..."
if [ "$DRY_RUN" = true ]; then
    echo "  Would create: ${AGENTS_DIR}"
    echo "  Would copy: agents/*.md -> ${AGENTS_DIR}/"
else
    mkdir -p "${AGENTS_DIR}"
    cp "${SKILL_DIR}/agents/"*.md "${AGENTS_DIR}/"
    echo "  [v] Copied agents to ${AGENTS_DIR}"
fi

# Step 3: Verify polyglot CLI
echo ""
echo "[3/4] Verifying polyglot CLI..."
cd "${SKILL_DIR}"
if python -m polyglot --help > /dev/null 2>&1; then
    echo "  [v] polyglot CLI is importable"
else
    echo "  [x] polyglot CLI failed — check Python path"
fi

# Step 4: (Optional) Install permissions
if [ "$WITH_PERMS" = true ]; then
    echo ""
    echo "[4/4] Installing permissions..."
    if [ -f "${SETTINGS_FILE}" ]; then
        echo "  [!] ${SETTINGS_FILE} already exists — backing up to settings.json.bak"
        if [ "$DRY_RUN" = false ]; then
            cp "${SETTINGS_FILE}" "${SETTINGS_FILE}.bak"
        fi
    fi
    if [ "$DRY_RUN" = false ]; then
        cp "${SKILL_DIR}/.claude/settings.json" "${SETTINGS_FILE}"
        echo "  [v] Permissions installed to ${SETTINGS_FILE}"
    else
        echo "  Would copy: .claude/settings.json -> ${SETTINGS_FILE}"
    fi
else
    echo ""
    echo "[4/4] Skipped (use --with-permissions to install settings)"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "To verify:"
echo "  1. Run /agents in Claude Code — should show 4 glue-* agents"
echo "  2. Run 'python -m polyglot --help' — should show deep-* commands"
echo ""
echo "To install permissions as well:"
echo "  bash scripts/setup.sh --with-permissions"