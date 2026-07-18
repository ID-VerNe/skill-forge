"""polyglot/deep/repo_resolver.py — Repository URL parsing, cloning, slug resolution."""

import os
import subprocess
import re
import json


# @lat: [[deep#Workspace Structure]]
def url_to_slug(url: str) -> str:
    """Derive a filesystem-safe slug from a repo URL or local path.

    Examples:
        https://github.com/jtroo/kanata → kanata
        https://github.com/org/repo.git → repo
        git@github.com:user/project.git → project
        /path/to/my-repo → my-repo
        C:\\Users\\me\\project → project
    """
    # Strip trailing .git
    url = url.strip()
    if url.endswith(".git"):
        url = url[:-4]

    # Handle Windows paths
    if "://" not in url and (url.startswith("/") or re.match(r"^[A-Za-z]:\\", url)):
        return os.path.basename(os.path.normpath(url))

    # Handle SSH-style: git@github.com:user/repo
    if "@" in url and ":" in url:
        url = url.split(":")[-1]

    # Extract last path component
    slug = os.path.basename(url)
    # Sanitize: keep only alphanumeric, dash, underscore
    slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug)
    if not slug:
        slug = "repo"
    return slug


def resolve_repo_url(url: str) -> str:
    """Normalize a GitHub URL to cloneable form."""
    url = url.strip()
    # Already a git URL
    if url.endswith(".git") or url.startswith("git@"):
        return url
    # GitHub shorthand: jtroo/kanata
    if "/" in url and not url.startswith("http") and not url.startswith("git@"):
        return f"https://github.com/{url}.git"
    # Full HTTPS URL — ensure .git suffix
    if url.startswith("https://"):
        if not url.endswith(".git"):
            url = url + ".git"
        return url
    # Assume it's already cloneable
    return url


def clone_repo(url: str, target_dir: str) -> dict:
    """Shallow clone a repo to target_dir. Returns commit hash and metadata.

    Args:
        url: Repository URL
        target_dir: Absolute path to clone into

    Returns:
        dict with keys: commit, success, error (if failed)
    """
    os.makedirs(target_dir, exist_ok=True)

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, target_dir],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip()[:500], "commit": ""}

        # Get commit hash
        hash_result = subprocess.run(
            ["git", "-C", target_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30
        )
        commit = hash_result.stdout.strip() if hash_result.returncode == 0 else ""

        return {"success": True, "commit": commit, "error": ""}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "git clone timed out after 120s", "commit": ""}
    except FileNotFoundError:
        return {"success": False, "error": "git not found in PATH", "commit": ""}
    except Exception as e:
        return {"success": False, "error": str(e)[:500], "commit": ""}


def get_commit_hash(repo_dir: str) -> str:
    """Get the current HEAD commit hash of a local repo."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""