"""
polyglot/backends/go/installer.py — Go module installer backend.

Installs Go packages via `go get` in a subprocess.
"""

import sys
import os
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def install(package: str, version: str = "") -> tuple:
    """Install a Go package via go get. Returns (success, message)."""
    if version:
        spec = f"{package}@{version}"
    else:
        spec = f"{package}@latest"

    try:
        result = subprocess.run(
            ["go", "get", spec],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, f"Installed {spec}"
        else:
            err = result.stderr.strip() or result.stdout.strip() or "unknown error"
            return False, f"go get failed: {err}"
    except FileNotFoundError:
        return False, "Go is not installed (go not found in PATH)"
    except subprocess.TimeoutExpired:
        return False, f"go get timed out after 120s"
    except Exception as e:
        return False, f"Install error: {e}"


# ── Minimal smoke test ──
if __name__ == "__main__":
    success, msg = install("github.com/gin-gonic/gin")
    print(f"Install: {success} — {msg}")