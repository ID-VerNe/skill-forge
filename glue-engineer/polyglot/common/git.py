"""polyglot/common/git.py — Shared shallow-clone utilities."""

import subprocess
import os
import sys


def clone_repo(url: str, dest: str, depth: int = 1) -> tuple[bool, str]:
    """Shallow-clone repo. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", str(depth), url, dest],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return True, f"Cloned to {dest}"
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Clone timed out (120s)"
    except FileNotFoundError:
        return False, "git not found — install git or check PATH"


def repo_exists(url: str) -> bool:
    """Check if repo URL is accessible (no clone)."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--quiet", url],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_languages(repo_path: str) -> list[str]:
    """Detect languages used in a cloned repo."""
    detected = []
    for root, dirs, files in os.walk(repo_path):
        if ".git" in dirs:
            dirs.remove(".git")
        for f in files:
            ext = os.path.splitext(f)[1]
            if ext == ".py" and "python" not in detected:
                detected.append("python")
            elif ext in (".js", ".ts", ".tsx", ".jsx") and "javascript" not in detected:
                detected.append("javascript")
            elif ext == ".rs" and "rust" not in detected:
                detected.append("rust")
            elif ext in (".java",) and "java" not in detected:
                detected.append("java")
            elif ext in (".kt", ".kts") and "kotlin" not in detected:
                detected.append("kotlin")
            elif ext in (".c", ".cpp", ".h", ".hpp") and "c_cpp" not in detected:
                detected.append("c_cpp")
    return detected
