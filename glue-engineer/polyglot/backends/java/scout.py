"""
polyglot/backends/java/scout.py — Maven Central ecosystem scout.

Searches Maven Central via its Solr search API and returns
results shaped to match the SearchOutput schema (plain dict).
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


SOLR_SEARCH_URL = "https://search.maven.org/solrsearch/select"
REQUEST_TIMEOUT = 15  # seconds


def search(query: str, limit: int = 5) -> dict:
    """Search Maven Central. Returns dict matching SearchOutput schema."""
    cache_key = f"scout:java:{query}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["metadata"]["cache_hit"] = True
        return cached

    start = time.time()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if requests is None:
        return _error_output(
            "The 'requests' library is not installed. Run: pip install requests",
            start, timestamp,
        )

    def _http_get():
        resp = requests.get(
            SOLR_SEARCH_URL,
            params={"q": query, "rows": limit, "wt": "json"},
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
        return _handle_fetch_error(cache_key, query, limit, http_error, start, timestamp)

    return _process_results(cache_key, data, query, limit, start, timestamp)


def _error_output(msg: str, start, timestamp) -> dict:
    return {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "java",
        "query": "",
        "timestamp": timestamp,
        "results": [],
        "errors": [msg],
        "metadata": {"duration_ms": int((time.time() - start) * 1000), "cache_hit": False, "has_more": False},
    }


def _handle_fetch_error(cache_key, query, limit, error, start, timestamp) -> dict:
    stale = cache_get_stale(cache_key)
    if stale is not None:
        stale["metadata"]["cache_hit"] = True
        return stale

    output = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "java",
        "query": query,
        "timestamp": timestamp,
        "results": [],
        "errors": [str(error)[:200]],
        "metadata": {},
    }

    output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
    cache_set(cache_key, output)
    return output


def _process_results(cache_key, data, query, limit, start, timestamp) -> dict:
    response_body = data.get("response", {})
    docs = response_body.get("docs", [])
    num_found = response_body.get("numFound", 0)
    now_epoch_ms = int(time.time() * 1000)

    results = []
    for doc in docs:
        artifact_id = doc.get("id", "")
        group_id = doc.get("g", "")
        artifact_name = doc.get("a", "")
        latest_version = doc.get("latestVersion", "")
        version_count = int(doc.get("versionCount", 0) or 0)
        timestamp_ms = doc.get("timestamp", 0) or 0

        coord_path = artifact_id.replace(":", "/")
        registry_url = (
            f"https://search.maven.org/artifact/{coord_path}/{latest_version}/jar"
        )

        if timestamp_ms:
            days_since = max(0, (now_epoch_ms - int(timestamp_ms)) / 86_400_000)
            recency = 0.3 if days_since <= 30 else (0.2 if days_since <= 365 else 0.1)
        else:
            recency = 0.1

        score = min(version_count / 100 * 0.5 + recency * 0.5, 1.0)

        last_commit_str = ""
        if timestamp_ms:
            last_commit_str = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(timestamp_ms) / 1000)
            )

        results.append({
            "name": artifact_id,
            "version": latest_version,
            "description": f"{group_id}:{artifact_name}" if group_id and artifact_name else artifact_id,
            "registry_url": registry_url,
            "stars": version_count,
            "downloads": 0,
            "last_commit": last_commit_str,
            "license_name": "",
            "dependencies": [],
            "score": round(score, 4),
        })

    output = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "java",
        "query": query,
        "timestamp": timestamp,
        "results": results,
        "errors": [],
        "metadata": {
            "duration_ms": int((time.time() - start) * 1000),
            "cache_hit": False,
            "has_more": int(num_found) > len(results),
        },
    }

    if not results:
        output["errors"].append(f"No results found for query '{query}'")

    cache_set(cache_key, output)
    return output


if __name__ == "__main__":
    import json
    import sys as _sys

    q = " ".join(_sys.argv[1:]) or "guava"
    result = search(q)
    print(json.dumps(result, indent=2, ensure_ascii=False))