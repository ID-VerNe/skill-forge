"""
polyglot/backends/rust/scout.py — crates.io ecosystem scout.

Searches crates.io for Rust packages matching the query.
Returns a SearchOutput dict matching the unified polyglot schema.
"""

import os
import sys
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from polyglot.common.cache import cache_get, cache_set, cache_get_stale
from polyglot.common.retry import retry_call


CRATES_API = "https://crates.io/api/v1/crates"
USER_AGENT = "polyglot-glue-engineer/1.0"
REQUEST_TIMEOUT = 15  # seconds


def search(query: str, limit: int = 5) -> dict:
    """Search crates.io. Returns dict matching SearchOutput schema."""
    cache_key = f"scout:rust:{query}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["metadata"]["cache_hit"] = True
        return cached

    start = time.time()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    output: dict = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "rust",
        "query": query,
        "timestamp": timestamp,
        "results": [],
        "errors": [],
        "metadata": {
            "duration_ms": 0,
            "cache_hit": False,
            "has_more": False,
        },
    }

    if requests is None:
        output["errors"].append(
            "The 'requests' library is not installed. Run: pip install requests"
        )
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output

    def _http_get():
        resp = requests.get(
            CRATES_API,
            params={"q": query, "per_page": limit},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    data, attempts, http_error = retry_call(
        _http_get,
        max_retries=3,
        retryable_exceptions=(
            requests.ConnectionError, requests.Timeout, requests.RequestException,
        ),
    )

    if http_error is not None:
        stale = cache_get_stale(cache_key)
        if stale is not None:
            stale["metadata"]["cache_hit"] = True
            return stale
        output["errors"].append(str(http_error)[:200])
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        cache_set(cache_key, output)
        return output

    try:
        crates = data.get("crates", [])
        meta = data.get("meta", {})
        output["metadata"]["has_more"] = meta.get("total", 0) > len(crates)

        for crate in crates:
            name = crate.get("name", "")
            max_version = crate.get("max_version", "")
            description = crate.get("description") or ""

            docs = crate.get("documentation", "")
            homepage = crate.get("homepage", "")
            registry_url = docs or homepage or f"https://crates.io/crates/{name}"

            repository = crate.get("repository", "")
            downloads = crate.get("downloads", 0) or 0
            recent_downloads = crate.get("recent_downloads", 0) or 0

            score = min(
                float(downloads) / 1_000_000 * 0.5 + float(recent_downloads) / 10_000 * 0.5,
                1.0,
            )

            output["results"].append(
                {
                    "name": name,
                    "version": max_version,
                    "description": description[:500] if description else "",
                    "registry_url": registry_url,
                    "stars": 0,
                    "downloads": downloads,
                    "last_commit": "",
                    "license_name": crate.get("license", ""),
                    "dependencies": [],
                    "score": round(score, 4),
                }
            )
    except (KeyError, ValueError, TypeError) as exc:
        output["errors"].append(f"Parse error: {exc}")

    output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)

    if not output["results"] and not output["errors"]:
        output["errors"].append(f"No results found for query '{query}'")

    cache_set(cache_key, output)
    return output


if __name__ == "__main__":
    import json
    import sys as _sys

    q = " ".join(_sys.argv[1:]) or "serde"
    result = search(q)
    print(json.dumps(result, indent=2, ensure_ascii=False))