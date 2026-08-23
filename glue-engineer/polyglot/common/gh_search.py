"""
polyglot/common/gh_search.py — GitHub repository search via REST API.

Uses direct GitHub Search API with proxy_fallback (to handle flaky proxies)
and retry (to handle transient network failures).  Falls back to stale cache
when all attempts fail.

Token is resolved from environment or `gh auth token` via gh_auth.py.
Authenticated requests get 30 req/min; unauthenticated get 10 req/min.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polyglot.common.cache import cache_get, cache_set, cache_get_stale
from polyglot.common.schema import compute_score
from polyglot.common.gh_auth import TOKEN
from polyglot.common.proxy_fallback import get as proxy_get
from polyglot.common.retry import retry_call


# Cache TTL — hourly is fine for repo search results
_SEARCH_TTL = 3600

# Fields requested from GitHub Search API
_GH_FIELDS = "fullName,stargazersCount,forksCount,language,description,url,updatedAt,license"

# Default sort is gh's native relevance sorting (best match), which the
# `discover` command relies on — pass sort explicitly to change it.
_DEFAULT_SORT = ""


def search(query: str, limit: int = 5, qualifiers: str = "", sort: str = "") -> dict:
    """Search GitHub repositories by keyword.

    Uses direct GitHub REST API with proxy fallback + retry.
    Falls back to stale cache when all network attempts fail.

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

    # Build the search query
    search_query = query
    if qualifiers:
        search_query = f"{query} {qualifiers}"

    # GitHub Search API endpoint
    url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "polyglot-scout/1.0",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    params = {
        "q": search_query,
        "per_page": min(limit, 20),
        "page": 1,
    }
    if sort and sort not in ("best-match", ""):
        params["sort"] = sort

    # Build the fetch function for retry + proxy fallback
    def _fetch():
        resp, used_no_proxy = proxy_get(url, timeout=20, headers=headers, params=params)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 401:
            raise PermissionError("GitHub API token is invalid or expired")
        if resp.status_code == 403:
            # Rate limited — check if it's due to secondary rate limit
            raise RuntimeError(f"GitHub API rate limited (403): {resp.headers.get('X-RateLimit-Remaining', '?')} remaining")
        if resp.status_code == 422:
            data = resp.json()
            msg = data.get("message", "") or data.get("errors", [{}])[0].get("message", "")
            raise ValueError(f"GitHub API validation error (422): {msg}")
        raise RuntimeError(f"GitHub API returned {resp.status_code}")

    try:
        data, attempts, last_error = retry_call(
            _fetch,
            max_retries=2,
            base_delay=1.0,
            max_delay=10.0,
            retryable_exceptions=(
                TimeoutError,
                ConnectionError,
                RuntimeError,  # 403/other transient
                OSError,
            ),
        )
        if data is not None:
            items = data.get("items", [])
            results = _parse_results(items, limit)
        else:
            # All retries exhausted
            if last_error:
                errors.append(f"GitHub search failed after 3 attempts: {last_error}")
            else:
                errors.append("GitHub search failed after 3 attempts (unknown error)")
    except (PermissionError, ValueError) as e:
        # Non-retryable errors (bad token, bad query)
        errors.append(str(e))
    except Exception as e:
        errors.append(f"GitHub search failed: {e}")

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
    """Parse GitHub Search API response into SearchOutput-compatible result dicts."""
    results = []
    for item in items[:limit]:
        name = item.get("full_name", "")
        stars = item.get("stargazers_count", 0) or 0
        lang = item.get("language") or ""
        desc = item.get("description") or ""
        url = item.get("html_url", "")
        updated = item.get("updated_at", "")
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
            license_name = license_info.get("spdx_id") or license_info.get("name", "")

        results.append({
            "name": name,
            "version": "",
            "description": desc[:200] if desc else "",
            "registry_url": url,
            "stars": stars,
            "downloads": 0,
            "last_commit": updated,
            "license_name": license_name,
            "dependencies": [],
            "score": round(score, 2),
            "language": lang,
        })
    return results


def check_available() -> tuple[bool, str]:
    """Check if GitHub API is accessible.

    Makes a lightweight API call to verify connectivity and auth.
    Returns (available, message).
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "polyglot-scout/1.0",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    try:
        resp, _ = proxy_get(
            "https://api.github.com/rate_limit", timeout=10, headers=headers
        )
        if resp.status_code == 200:
            data = resp.json()
            remaining = data.get("resources", {}).get("search", {}).get("remaining", 0)
            return True, f"GitHub API accessible ({remaining} search requests remaining)"
        if resp.status_code == 401:
            return False, "GitHub API token is invalid"
        if resp.status_code == 403:
            return False, "GitHub API rate limited"
        return False, f"GitHub API returned {resp.status_code}"
    except Exception as e:
        return False, f"GitHub API unreachable: {e}"


# ── Minimal smoke test ──
if __name__ == "__main__":
    import json as _json
    q = " ".join(sys.argv[1:]) or "h264 decode"
    result = search(q, limit=3)
    print(_json.dumps(result, indent=2, ensure_ascii=False))