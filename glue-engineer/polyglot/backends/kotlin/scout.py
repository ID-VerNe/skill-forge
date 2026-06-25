"""
polyglot/backends/kotlin/scout.py — Kotlin ecosystem scout via Maven Central.

Searches Maven Central via its Solr search API and filters results
to prefer or surface Kotlin-related artifacts. Returns results shaped
to match the SearchOutput schema (plain dict).
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


SOLR_SEARCH_URL = "https://search.maven.org/solrsearch/select"
REQUEST_TIMEOUT = 15  # seconds


def search(query: str, limit: int = 5) -> dict:
    """Search Maven Central, preferring Kotlin artifacts. Returns dict matching SearchOutput schema."""
    start = time.time()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    output: dict = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "kotlin",
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

    # Fetch extra results to account for filtering down to Kotlin-relevant ones
    fetch_limit = max(limit * 3, 15)

    try:
        resp = requests.get(
            SOLR_SEARCH_URL,
            params={"q": query, "rows": fetch_limit, "wt": "json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        output["errors"].append(
            f"Request to Maven Central timed out after {REQUEST_TIMEOUT}s"
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

    response_body = data.get("response", {})
    docs = response_body.get("docs", [])
    num_found = response_body.get("numFound", 0)
    output["metadata"]["has_more"] = int(num_found) > len(docs)

    now_epoch_ms = int(time.time() * 1000)

    # Separate Kotlin-relevant results from generic ones
    kotlin_results = []
    other_results = []

    for doc in docs:
        artifact_id = doc.get("id", "")
        group_id = doc.get("g", "")
        artifact_name = doc.get("a", "")
        latest_version = doc.get("latestVersion", "")
        version_count = int(doc.get("versionCount", 0) or 0)
        timestamp_ms = doc.get("timestamp", 0) or 0

        # Detect Kotlin relevance from artifact id, group id, or name
        artifact_lower = (artifact_id + " " + group_id + " " + artifact_name).lower()
        is_kotlin = "kotlin" in artifact_lower or "kt" in artifact_lower

        coord_path = artifact_id.replace(":", "/")
        registry_url = (
            f"https://search.maven.org/artifact/{coord_path}/{latest_version}/jar"
        )

        if timestamp_ms:
            days_since = max(0, (now_epoch_ms - int(timestamp_ms)) / 86_400_000)
            recency = 0.3 if days_since <= 30 else (0.2 if days_since <= 365 else 0.1)
        else:
            recency = 0.1

        # Score: version count + recency, with a bonus for Kotlin relevance
        score = min(version_count / 100 * 0.5 + recency * 0.5, 1.0)
        if is_kotlin:
            score = min(score + 0.2, 1.0)

        last_commit_str = ""
        if timestamp_ms:
            last_commit_str = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(timestamp_ms) / 1000)
            )

        result = {
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
        }

        if is_kotlin:
            kotlin_results.append(result)
        else:
            other_results.append(result)

    # Prefer Kotlin results, then fill remaining slots with generic results
    combined = kotlin_results + other_results
    output["results"] = combined[:limit]

    output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)

    if not output["results"] and not output["errors"]:
        output["errors"].append(f"No results found for query '{query}'")

    return output


if __name__ == "__main__":
    import json
    import sys as _sys

    q = " ".join(_sys.argv[1:]) or "kotlinx"
    result = search(q)
    print(json.dumps(result, indent=2, ensure_ascii=False))