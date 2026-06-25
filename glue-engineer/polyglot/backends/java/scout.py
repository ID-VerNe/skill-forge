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


SOLR_SEARCH_URL = "https://search.maven.org/solrsearch/select"
REQUEST_TIMEOUT = 15  # seconds


def search(query: str, limit: int = 5) -> dict:
    """Search Maven Central. Returns dict matching SearchOutput schema."""
    start = time.time()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    output: dict = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "java",
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
            SOLR_SEARCH_URL,
            params={"q": query, "rows": limit, "wt": "json"},
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

    for doc in docs:
        artifact_id = doc.get("id", "")
        group_id = doc.get("g", "")
        artifact_name = doc.get("a", "")
        latest_version = doc.get("latestVersion", "")
        version_count = int(doc.get("versionCount", 0) or 0)
        timestamp_ms = doc.get("timestamp", 0) or 0

        # Build the Maven-style coordinate: groupId:artifactId -> groupId/artifactId
        coord_path = artifact_id.replace(":", "/")
        registry_url = (
            f"https://search.maven.org/artifact/{coord_path}/{latest_version}/jar"
        )

        # Recency: timestamp from Solr is epoch in milliseconds
        if timestamp_ms:
            days_since = max(0, (now_epoch_ms - int(timestamp_ms)) / 86_400_000)
            recency = 0.3 if days_since <= 30 else (0.2 if days_since <= 365 else 0.1)
        else:
            recency = 0.1

        # Composite score: version count + recency
        score = min(version_count / 100 * 0.5 + recency * 0.5, 1.0)

        last_commit_str = ""
        if timestamp_ms:
            last_commit_str = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(timestamp_ms) / 1000)
            )

        output["results"].append({
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

    output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)

    if not output["results"] and not output["errors"]:
        output["errors"].append(f"No results found for query '{query}'")

    return output


if __name__ == "__main__":
    import json
    import sys as _sys

    q = " ".join(_sys.argv[1:]) or "guava"
    result = search(q)
    print(json.dumps(result, indent=2, ensure_ascii=False))