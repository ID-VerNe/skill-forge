"""polyglot/deep/repo_resolver.py — Repository URL parsing, cloning, slug resolution."""

import os
import subprocess
import re
import hashlib
from urllib.parse import urlparse


def url_to_slug(url: str) -> str:
    """Derive a filesystem-safe slug from a repo URL or local path.

    Examples:
        https://github.com/jtroo/kanata → kanata
        https://github.com/org/repo.git → repo
        git@github.com:user/project.git → project
        /path/to/my-repo → my-repo
        C:\\Users\\me\\project → project
    """
    original = url.strip()

    # Local paths retain their original final component and don't collide merely
    # because they aren't URL-shaped.
    if "://" not in original and (original.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", original)):
        name = os.path.basename(os.path.normpath(original))
        return _safe_slug(name) or "repo"

    value = original
    owner = ""
    if value.startswith("git@") and ":" in value:
        host, path = value.split(":", 1)
        owner = path.rsplit("/", 1)[0].split("/")[-1]
        name = path.rsplit("/", 1)[-1]
    elif "://" in value:
        parsed = urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            owner, name = parts[-2], parts[-1]
        else:
            name = parts[-1] if parts else "repo"
    else:
        parts = [part for part in value.split("/") if part]
        if len(parts) >= 2:
            owner, name = parts[-2], parts[-1]
        else:
            name = parts[-1] if parts else "repo"

    if name.endswith(".git"):
        name = name[:-4]
    safe_name = _safe_slug(name) or "repo"
    safe_owner = _safe_slug(owner)
    if safe_owner:
        identity = f"{owner.lower()}/{name.lower()}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
        return f"{safe_owner}-{safe_name}-{digest}"
    return safe_name


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value).strip("-_")


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
