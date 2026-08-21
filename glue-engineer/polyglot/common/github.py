"""
polyglot/common/github.py — GitHub API session + batched star-count lookups.

Provides a shared requests Session with auth, connection pooling, and retry,
plus batch_stars() for fetching star counts of many 'owner/repo' slugs.

Consumers wanting token resolution alone should import from gh_auth directly.
Consumers wanting Go module slug parsing should import from gh_slug directly.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from polyglot.common.cache import cache_get, cache_set
from polyglot.common.gh_auth import TOKEN, is_authenticated


GITHUB_API_BASE = "https://api.github.com"

# How many repos to batch-fetch concurrently
_BATCH_SIZE = 10

# Cache stars for 24 hours (stars don't change rapidly)
_STARS_TTL = 86400


# Reusable session with connection pooling + auto retry on transient errors
_session = requests.Session()
_headers = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "polyglot-scout/1.0",
}
if TOKEN:
    _headers["Authorization"] = f"Bearer {TOKEN}"
_session.headers.update(_headers)
_retry_adapter = HTTPAdapter(
    max_retries=Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
)
_session.mount("https://", _retry_adapter)


def batch_stars(repo_slugs: list[str]) -> dict[str, int]:
    """Fetch star counts for a list of 'owner/repo' slugs.

    Returns a dict mapping slug -> star count (0 on failure/rate-limit).
    Results are cached locally for 24h.
    """
    if not repo_slugs:
        return {}

    # Deduplicate
    slugs = sorted(set(s.strip() for s in repo_slugs if s and "/" in s))
    result: dict[str, int] = {}

    # Check cache first
    uncached: list[str] = []
    for slug in slugs:
        cached = cache_get(f"github:stars:{slug}")
        if cached is not None and isinstance(cached, dict) and "stars" in cached:
            result[slug] = cached["stars"]
        else:
            uncached.append(slug)

    if not uncached:
        return result

    # Fetch uncached in batches
    for i in range(0, len(uncached), _BATCH_SIZE):
        batch = uncached[i : i + _BATCH_SIZE]
        batch_stars = _fetch_batch(batch)
        for slug, stars in batch_stars.items():
            result[slug] = stars
            cache_set(f"github:stars:{slug}", {"stars": stars}, ttl_seconds=_STARS_TTL)

        # Brief pause between batches to avoid hammering the API
        if i + _BATCH_SIZE < len(uncached):
            time.sleep(0.5)

    return result


def _fetch_batch(slugs: list[str]) -> dict[str, int]:
    """Fetch star counts for a batch of slugs serially with pacing."""
    result: dict[str, int] = {}
    for slug in slugs:
        stars = _fetch_repo_stars(slug)
        result[slug] = stars
        if len(slugs) > 1:
            time.sleep(1.0)
    return result


def _fetch_repo_stars(slug: str) -> int:
    """Fetch star count for a single 'owner/repo' via GitHub REST API.

    Returns 0 on all failures. Distinguishes 401 (auth required) from
    403 (rate limited) — 401 is logged because it signals a misconfigured
    token, but the function still degrades to 0 stars.
    """
    url = f"{GITHUB_API_BASE}/repos/{slug}"

    try:
        resp = _session.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("stargazers_count", 0)
        if resp.status_code == 401:
            sys.stderr.write(
                f"[github] 401 Unauthorized for {slug} — token invalid or missing. "
                f"Set GITHUB_TOKEN or run `gh auth login`.\n"
            )
            return 0
        if resp.status_code in (403, 429):
            return 0  # Rate limited
        if resp.status_code == 404:
            return 0  # Not found
        return 0
    except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError):
        return 0
    except Exception:
        return 0