"""
polyglot/common/gh_search.py — GitHub repository search via `gh search repos --json`.

Wraps the authenticated `gh` CLI for structured repo search.  This avoids:
- Direct REST API authentication plumbing (gh handles OAuth token management)
- Rate limit self-management (gh uses the authenticated 30 req/min budget)
- A 9th copy-paste backend directory (this is a shared module, not a backend)

The `gh` CLI must be installed and authenticated (`gh auth login`).  If either
condition is not met, the module returns empty results with a clear error.
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyglot.common.cache import cache_get, cache_set, cache_get_stale
from polyglot.common.schema import compute_score


# Cache TTL — hourly is fine for repo search results
_SEARCH_TTL = 3600

# Fields requested from `gh search repos --json`
_GH_FIELDS = "fullName,stargazersCount,forksCount,language,description,url,updatedAt,license"

# Default sort is gh's native relevance sorting (best match), which the
# `discover` command relies on — pass sort explicitly to change it.
_DEFAULT_SORT = ""


def search(query: str, limit: int = 5, qualifiers: str = "", sort: str = "") -> dict:
    """Search GitHub repositories by keyword.

    Args:
        query: The search keyword (e.g. "h264 decode", "pdf parser")
        limit: Max results to return (default 5, max 20)
        qualifiers: Extra GitHub search qualifiers (e.g. "stars:>100 language:rust")
        sort: Sort key (stars | updated | forks | best-match). Default: stars
              (gh's native default — best relevance for discovery).

    Returns a dict matching the SearchOutput schema (polyglot-output-v1).
    """
    cache_key = f"gh_search:{query}:{qualifiers}:{sort}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["metadata"]["cache_hit"] = True
        return cached

    start = time.time()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    errors = []
    results = []

    # Build the gh command
    search_query = query
    if qualifiers:
        search_query = f"{query} {qualifiers}"

    try:
        cmd = [
            "gh", "search", "repos", search_query,
            "--limit", str(min(limit, 20)),
            "--json", _GH_FIELDS,
        ]
        if sort and sort not in ("best-match", ""):
            cmd += ["--sort", sort]  # gh native: stars | updated | forks
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",  # gh outputs UTF-8; Windows defaults to gbk
            timeout=30,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            if "required" in stderr.lower() and ("auth" in stderr.lower() or "login" in stderr.lower()):
                errors.append(
                    "gh CLI is not authenticated. Run `gh auth login` first."
                )
            elif "not found" in stderr.lower() or "no such" in stderr.lower():
                errors.append("gh CLI is not installed. Install GitHub CLI and run `gh auth login`.")
            else:
                errors.append(f"gh search repos failed: {stderr[:200]}")
        else:
            items = json.loads(proc.stdout) if proc.stdout.strip() else []
            results = _parse_results(items, limit)
    except FileNotFoundError:
        errors.append("gh CLI not found on PATH. Install GitHub CLI and run `gh auth login`.")
    except subprocess.TimeoutExpired:
        errors.append("gh search repos timed out after 30s.")
    except json.JSONDecodeError as e:
        errors.append(f"Failed to parse gh output: {e}")
    except OSError as e:
        errors.append(f"Subprocess error: {e}")

    output = {
        "schema": "polyglot-output-v1",
        "tool": "gh_search",
        "language": "github",
        "query": query,
        "timestamp": timestamp,
        "results": results,
        "errors": errors,
        "metadata": {
            "duration_ms": int((time.time() - start) * 1000),
            "cache_hit": False,
            "has_more": len(results) >= limit,
        },
    }

    if errors and not results:
        stale = cache_get_stale(cache_key)
        if stale is not None:
            stale["metadata"]["cache_hit"] = True
            return stale

    if not results and not errors:
        errors.append(f"No results found for query '{query}'")

    cache_set(cache_key, output, ttl_seconds=_SEARCH_TTL)
    return output


def _parse_results(items: list, limit: int) -> list:
    """Parse gh --json output into SearchOutput-compatible result dicts."""
    results = []
    for item in items[:limit]:
        name = item.get("fullName", "")
        stars = item.get("stargazersCount", 0) or 0
        lang = item.get("language") or ""
        desc = item.get("description") or ""
        url = item.get("url", "")
        updated = item.get("updatedAt", "")
        license_info = item.get("license")

        # Compute a score from stars + recency
        days_since = 999
        if updated:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - dt).days
            except Exception:
                pass

        score = compute_score(stars, 0, days_since)

        # If the repo has no stars and no recent activity, score is near-zero
        if stars == 0 and days_since > 365:
            continue  # skip truly dead repos

        license_name = ""
        if isinstance(license_info, str):
            license_name = license_info
        elif isinstance(license_info, dict):
            license_name = license_info.get("spdxId") or license_info.get("name", "")

        results.append({
            "name": name,
            "version": "",  # No version info from repo search
            "description": desc[:200] if desc else "",
            "registry_url": url,
            "stars": stars,
            "downloads": 0,  # No download counts from repo search
            "last_commit": updated,
            "license_name": license_name,
            "dependencies": [],
            "score": round(score, 2),
            "language": lang,  # GitHub's detected language — used by discover routing
        })
    return results


def check_available() -> tuple[bool, str]:
    """Check if gh CLI is available and authenticated.

    Returns (available, message).
    """
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, encoding="utf-8", timeout=10,
        )
        if proc.returncode == 0:
            return True, "gh CLI authenticated"
        return False, proc.stderr.strip()[:200]
    except FileNotFoundError:
        return False, "gh CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "gh auth status timed out"
    except OSError as e:
        return False, str(e)[:200]


# ── Minimal smoke test ──
if __name__ == "__main__":
    import json as _json
    q = " ".join(sys.argv[1:]) or "h264 decode"
    result = search(q, limit=3)
    print(_json.dumps(result, indent=2, ensure_ascii=False))