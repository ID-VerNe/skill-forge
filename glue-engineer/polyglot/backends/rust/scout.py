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


CRATES_API = "https://crates.io/api/v1/crates"
USER_AGENT = "polyglot-glue-engineer/1.0"
REQUEST_TIMEOUT = 15  # seconds


def search(query: str, limit: int = 5) -> dict:
    """Search crates.io. Returns dict matching SearchOutput schema."""
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

    try:
        resp = requests.get(
            CRATES_API,
            params={"q": query, "per_page": limit},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        output["errors"].append(
            f"Request to crates.io timed out after {REQUEST_TIMEOUT}s"
        )
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output
    except requests.exceptions.ConnectionError as exc:
        output["errors"].append(f"Connection error: {exc}")
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output
    except requests.exceptions.RequestException as exc:
        output["errors"].append(f"HTTP request failed: {exc}")
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output
    except ValueError as exc:
        output["errors"].append(f"Failed to parse JSON response: {exc}")
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output

    crates = data.get("crates", [])
    meta = data.get("meta", {})
    output["metadata"]["has_more"] = meta.get("total", 0) > len(crates)

    for crate in crates:
        name = crate.get("name", "")
        max_version = crate.get("max_version", "")
        description = crate.get("description") or ""

        # Build registry_url preferring documented links
        docs = crate.get("documentation", "")
        homepage = crate.get("homepage", "")
        registry_url = docs or homepage or f"https://crates.io/crates/{name}"

        repository = crate.get("repository", "")
        downloads = crate.get("downloads", 0) or 0
        recent_downloads = crate.get("recent_downloads", 0) or 0

        # Compute score: downloads + recent_downloads weighted components, capped at 1.0
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

    output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)

    if not output["results"] and not output["errors"]:
        output["errors"].append(f"No results found for query '{query}'")

    return output


if __name__ == "__main__":
    import json
    import sys as _sys

    q = " ".join(_sys.argv[1:]) or "serde"
    result = search(q)
    print(json.dumps(result, indent=2, ensure_ascii=False))