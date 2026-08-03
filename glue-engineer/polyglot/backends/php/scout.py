"""
polyglot/backends/php/scout.py — Packagist registry scout backend.

Searches Packagist via its public search.json endpoint and returns
results shaped to match the SearchOutput schema (plain dict, not dataclass).
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests

from polyglot.common.cache import cache_get, cache_set, cache_get_stale
from polyglot.common.retry import retry_call


PACKAGIST_SEARCH_URL = "https://packagist.org/search.json"


def search(query: str, limit: int = 5) -> dict:
    """Search Packagist registry. Returns dict matching SearchOutput schema."""
    cache_key = f"scout:php:{query}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["metadata"]["cache_hit"] = True
        return cached

    start = time.monotonic()
    errors = []
    results = []

    def _http_get():
        resp = requests.get(
            PACKAGIST_SEARCH_URL,
            params={"q": query, "per_page": limit},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    data, attempts, http_error = retry_call(
        _http_get,
        max_retries=3,
        retryable_exceptions=(requests.ConnectionError, requests.Timeout, requests.RequestException),
    )

    if http_error is None:
        try:
            for pkg in data.get("results", []):
                name = pkg.get("name", "")
                description = pkg.get("description", "")
                url = pkg.get("url", "")
                repo_url = _extract_repo_url(pkg)

                if "/" in name:
                    vendor, package = name.split("/", 1)
                else:
                    vendor, package = "", name

                stars = pkg.get("favers", 0) or 0
                downloads = pkg.get("downloads", 0) or 0
                abandoned = pkg.get("abandoned", False)
                date_str = ""

                results.append({
                    "name": name,
                    "version": "",
                    "description": description,
                    "registry_url": url,
                    "stars": stars,
                    "downloads": downloads,
                    "last_commit": date_str,
                    "license_name": pkg.get("license", ""),
                    "dependencies": [],
                    "score": _compute_score(stars, downloads, abandoned),
                })

            has_more = len(results) >= limit
        except (KeyError, ValueError, TypeError) as e:
            errors.append(f"Parse error: {e}")
            has_more = False
    else:
        errors.append(str(http_error)[:200])
        has_more = False

    duration_ms = int((time.monotonic() - start) * 1000)

    result = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "php",
        "query": query,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
        "errors": errors,
        "metadata": {
            "duration_ms": duration_ms,
            "cache_hit": False,
            "has_more": has_more,
        },
    }

    if http_error is None:
        cache_set(cache_key, result)
        return result

    stale = cache_get_stale(cache_key)
    if stale is not None:
        stale["metadata"]["cache_hit"] = True
        return stale

    # Cache the error result so subsequent calls don't re-hit the network
    cache_set(cache_key, result)
    return result


def _extract_repo_url(pkg: dict) -> str:
    """Extract repository URL from Packagist search result."""
    url = pkg.get("repository", "") or ""
    if url.startswith("git@"):
        url = url.replace(":", "/").replace("git@", "https://").replace(".git", "")
    return url


def _compute_score(stars: int, downloads: int, abandoned: bool) -> float:
    """0.0 - 1.0 composite quality score for Packagist packages."""
    s = 0.0
    if stars > 1000:
        s += 0.4
    elif stars > 100:
        s += 0.3
    elif stars > 10:
        s += 0.2
    elif stars > 1:
        s += 0.1

    if downloads > 10_000_000:
        s += 0.3
    elif downloads > 1_000_000:
        s += 0.25
    elif downloads > 100_000:
        s += 0.2
    elif downloads > 1_000:
        s += 0.1

    if not abandoned:
        s += 0.3
    else:
        s += 0.0

    return min(s, 1.0)


# ── Minimal smoke test ──
if __name__ == "__main__":
    out = search("monolog", limit=3)
    print(f"Found {len(out['results'])} results, errors={len(out['errors'])}")
    for r in out["results"]:
        print(f"  {r['name']} — stars={r['stars']}, score={r['score']:.3f}")