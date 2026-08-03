"""
polyglot/common/github.py — GitHub API helpers for polyglot backends.

Provides batched star-count lookups via the GitHub REST API with
local caching, rate-limit awareness, and graceful degradation.
"""

import sys
import os
import time
import re
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from polyglot.common.cache import cache_get, cache_set


GITHUB_API_BASE = "https://api.github.com"

# How many repos to batch-fetch concurrently
_BATCH_SIZE = 10

# Cache stars for 24 hours (stars don't change rapidly)
_STARS_TTL = 86400

# Reusable session with connection pooling + auto retry on transient errors
_session = requests.Session()
_session.headers.update({
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "polyglot-scout/1.0",
})
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
    """Fetch star counts for a batch of slugs serially with pacing.

    Serializes requests with a 1-second delay between each to stay well
    under GitHub's unauthenticated rate limit (60 req/hr = 1 req/60s).
    """
    result: dict[str, int] = {}
    for slug in slugs:
        stars = _fetch_repo_stars(slug)
        result[slug] = stars
        if len(slugs) > 1:
            time.sleep(1.0)
    return result


def _fetch_repo_stars(slug: str) -> int:
    """Fetch star count for a single 'owner/repo' via GitHub REST API.

    Uses a shared Session with connection pooling and urllib3 Retry
    for transparent retries on transient SSL/connection errors.
    Returns 0 on all failures.
    """
    url = f"{GITHUB_API_BASE}/repos/{slug}"

    try:
        resp = _session.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("stargazers_count", 0)
        if resp.status_code in (403, 429):
            return 0  # Rate limited
        if resp.status_code == 404:
            return 0  # Not found
        return 0
    except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError):
        # urllib3 Retry handles the retry; if we get here, all retries failed
        return 0
    except Exception:
        return 0


def parse_github_slug(module_path: str) -> str | None:
    """Extract 'owner/repo' from a Go module path if it's on GitHub.

    Examples:
      github.com/gin-gonic/gin              -> gin-gonic/gin
      github.com/gin-gonic/gin/binding      -> gin-gonic/gin
      github.com/gin-gonic/gin/v2           -> gin-gonic/gin
      gopkg.in/gin-gonic/gin.v1             -> gin-gonic/gin
      go.opentelemetry.io/...               -> None
      gitlab.com/...                         -> None
    """
    # Direct github.com path
    m = re.match(r"^github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:/|$|v\d+)", module_path)
    if m:
        slug = m.group(1)
        slug = re.sub(r"\.git$", "", slug)
        return slug

    # gopkg.in -> maps to github.com for many packages
    m = re.match(r"^gopkg\.in/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.v\d+)?$", module_path)
    if m:
        return m.group(1)

    return None


# ── Minimal smoke test ──
if __name__ == "__main__":
    slugs = [
        "gin-gonic/gin",
        "gin-contrib/cors",
        "swaggo/gin-swagger",
        "nonexistent-user-12345/nonexistent-repo-67890",
    ]
    stars = batch_stars(slugs)
    for slug, count in stars.items():
        print(f"  {slug}: {count} stars")
    print()

    test_paths = [
        "github.com/gin-gonic/gin",
        "github.com/gin-gonic/gin/binding",
        "github.com/gin-gonic/gin/v2",
        "gopkg.in/gin-gonic/gin.v1",
        "go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin",
        "github.com/WeidiDeng/ttyd-go",
    ]
    for p in test_paths:
        s = parse_github_slug(p)
        print(f"  {p:70s} -> {s}")