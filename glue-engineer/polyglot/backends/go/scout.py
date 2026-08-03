"""
polyglot/backends/go/scout.py — Go module proxy (pkg.go.dev) scout backend.

Searches the Go ecosystem by scraping pkg.go.dev HTML search results,
then augments results with GitHub star counts via the GitHub REST API.
Returns results shaped to match the SearchOutput schema (plain dict).
"""

import sys
import os
import re
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests

from polyglot.common.cache import cache_get, cache_set, cache_get_stale
from polyglot.common.retry import retry_call
from polyglot.common.github import batch_stars, parse_github_slug

PKG_GO_DEV_SEARCH_URL = "https://pkg.go.dev/search"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def search(query: str, limit: int = 5) -> dict:
    """Search pkg.go.dev, then augment with GitHub stars.

    Returns dict matching SearchOutput schema.
    """
    cache_key = f"scout:go:{query}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["metadata"]["cache_hit"] = True
        return cached

    start = time.monotonic()
    errors = []
    results = []

    # Step 1: fetch and parse pkg.go.dev HTML
    def _http_get():
        resp = requests.get(
            PKG_GO_DEV_SEARCH_URL,
            params={"q": query},
            timeout=15,
            headers=_BROWSER_HEADERS,
        )
        resp.raise_for_status()
        return resp.text

    html, attempts, http_error = retry_call(
        _http_get,
        max_retries=3,
        retryable_exceptions=(requests.ConnectionError, requests.Timeout, requests.RequestException),
    )

    if http_error is None:
        try:
            results = _parse_search_results(html, limit)
            has_more = len(results) >= limit
        except (KeyError, ValueError, TypeError) as e:
            errors.append(f"Parse error: {e}")
            has_more = False
    else:
        errors.append(str(http_error)[:200])
        has_more = False

    # Step 2: augment with GitHub stars
    if results:
        try:
            _augment_with_stars(results)
        except Exception as e:
            errors.append(f"GitHub star lookup warning: {e}")

    duration_ms = int((time.monotonic() - start) * 1000)

    result = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "go",
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

    cache_set(cache_key, result)
    return result


def _augment_with_stars(results: list[dict]) -> None:
    """Fetch GitHub star counts for all results and update in-place."""
    # Build slug -> result index mapping
    slug_to_idx: dict[str, int] = {}
    for i, r in enumerate(results):
        slug = parse_github_slug(r["name"])
        if slug:
            slug_to_idx[slug] = i

    if not slug_to_idx:
        return

    # Batch fetch star counts
    stars = batch_stars(list(slug_to_idx.keys()))

    # Update results and recompute scores
    for slug, count in stars.items():
        idx = slug_to_idx.get(slug)
        if idx is None:
            continue
        results[idx]["stars"] = count
        # Recompute score with real stars
        results[idx]["score"] = _compute_score(
            count,
            results[idx].get("downloads", 0),
            results[idx].get("last_commit", ""),
        )


def _parse_search_results(html: str, limit: int) -> list:
    """Parse pkg.go.dev search results HTML into result dicts."""
    results = []

    snippet_pattern = re.compile(
        r'<div\s+class="SearchSnippet"[^>]*>(.*?)</div>\s*\n\s*</div>',
        re.DOTALL,
    )

    for match in snippet_pattern.finditer(html):
        if len(results) >= limit:
            break
        block = match.group(0)

        # Module path: <span class="SearchSnippet-header-path">(path)</span>
        path_match = re.search(
            r'<span\s+class="SearchSnippet-header-path">\(([^)]+)\)</span>', block
        )
        if not path_match:
            continue
        path = path_match.group(1).strip()

        # Description: <p class="SearchSnippet-synopsis">...</p>
        desc_match = re.search(
            r'class="SearchSnippet-synopsis"[^>]*>(.*?)</p>', block, re.DOTALL
        )
        description = desc_match.group(1).strip() if desc_match else ""

        # Import count: "Imported by ... <strong>183,243</strong>"
        import_count = 0
        import_match = re.search(
            r'Imported by.*?<strong>([\d,]+)</strong>', block, re.DOTALL
        )
        if import_match:
            import_count = int(import_match.group(1).replace(",", ""))

        # Version: <strong>v1.12.0</strong>
        version = ""
        for strong in re.finditer(r'<strong>([^<]+)</strong>', block):
            text = strong.group(1)
            if re.match(r'^v?[\d.]+(?:-[\w.]+)?$', text):
                version = text
                break

        # Published date: data-test-id="snippet-published"><strong>Feb 28, 2026</strong>
        published = ""
        date_match = re.search(
            r'data-test-id="snippet-published"[^>]*><strong>([^<]+)</strong>', block
        )
        if date_match:
            published = _parse_date(date_match.group(1).strip())

        # License
        license_name = ""
        lic_section = re.search(
            r'data-test-id="snippet-license"[^>]*>(.*?)</span>', block, re.DOTALL
        )
        if lic_section:
            lmatch = re.search(r'<a[^>]*>([^<]+)<', lic_section.group(1))
            if lmatch:
                license_name = lmatch.group(1).strip()

        registry_url = f"https://pkg.go.dev/{path}"
        # Score starts at 0 (stars not yet known — will be updated by _augment_with_stars)
        score = _compute_score(0, import_count, published)

        results.append({
            "name": path,
            "version": version,
            "description": description,
            "registry_url": registry_url,
            "stars": 0,
            "downloads": import_count,
            "last_commit": published,
            "license_name": license_name,
            "dependencies": [],
            "score": score,
        })

    return results


def _parse_date(date_str: str) -> str:
    """Parse date strings like 'Feb 28, 2026' into ISO format."""
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    m = re.match(r'(\w+)\s+(\d+),?\s+(\d{4})', date_str)
    if m:
        mon = months.get(m.group(1)[:3], "01")
        day = m.group(2).zfill(2)
        year = m.group(3)
        return f"{year}-{mon}-{day}T00:00:00Z"
    return date_str


def _compute_score(stars: int, downloads: int, commit_time: str) -> float:
    """0.0 - 1.0 composite quality score for Go modules.

    Uses stars (from GitHub) + import count (from pkg.go.dev) + recency.
    Mirrors the weights in common/schema.py:compute_score.
    """
    s = 0.0

    if stars > 10000:
        s += 0.4
    elif stars > 1000:
        s += 0.3
    elif stars > 100:
        s += 0.2
    elif stars > 10:
        s += 0.1

    if downloads > 100_000:
        s += 0.3
    elif downloads > 10_000:
        s += 0.25
    elif downloads > 1_000:
        s += 0.2
    elif downloads > 100:
        s += 0.1

    if commit_time:
        days_since = _days_since(commit_time)
        if days_since < 30:
            s += 0.3
        elif days_since < 365:
            s += 0.2
        else:
            s += 0.1
    else:
        s += 0.1

    return min(s, 1.0)


def _days_since(iso_date: str) -> int:
    """Return whole days elapsed between iso_date (UTC) and now."""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - dt).days
    except Exception:
        return 999


# ── Minimal smoke test ──
if __name__ == "__main__":
    out = search("gin", limit=3)
    print(f"Found {len(out['results'])} results, errors={len(out['errors'])}")
    for r in out["results"]:
        print(f"  {r['name']} ({r['version']}) — stars={r['stars']}, "
              f"downloads={r['downloads']}, score={r['score']:.3f}")