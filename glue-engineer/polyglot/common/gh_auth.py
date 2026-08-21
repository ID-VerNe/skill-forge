"""
polyglot/common/gh_auth.py — GitHub token resolution.

Resolution order:
  1. GITHUB_TOKEN / GH_TOKEN env var (preferred — no subprocess, testable)
  2. `gh auth token` shell-out (inherits the gh CLI's OAuth session)

Returns None if no token is available. Callers degrade to unauthenticated
requests (lower rate limits). Never raises — token acquisition is optional.
"""

import os
import subprocess


def resolve_token() -> str | None:
    """Resolve a GitHub API token for authenticated requests.

    Returns None if no token is available. Never raises.
    """
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        tok = os.environ.get(var, "").strip()
        if tok:
            return tok
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            tok = result.stdout.strip()
            if tok and tok.startswith("gho_") or tok.startswith("ghp_") or tok.startswith("github_pat_"):
                return tok
            if tok:
                return tok
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


# Resolved once at import; re-resolution on token expiry is out of scope for a CLI.
TOKEN = resolve_token()


def is_authenticated() -> bool:
    """Whether a GitHub token is active for this session."""
    return TOKEN is not None
