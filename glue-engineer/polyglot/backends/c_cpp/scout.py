"""
polyglot/backends/c_cpp/scout.py — vcpkg ecosystem scout.

Searches the vcpkg port database via the GitHub code search API.
Falls back to empty results if the GitHub API rate-limits the request.
Returns results shaped to match the SearchOutput schema (plain dict).
"""

import os
import re
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
from polyglot.common.gh_auth import is_authenticated, resolve_token


VCPKG_CODE_SEARCH_URL = "https://api.github.com/search/code"
VCPKG_RAW_BASE = "https://raw.githubusercontent.com/microsoft/vcpkg/master/ports"
REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = "polyglot/1.0"


def search(query: str, limit: int = 5) -> dict:
    """Search vcpkg ports. Returns dict matching SearchOutput schema."""
    cache_key = f"scout:c_cpp:{query}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["metadata"]["cache_hit"] = True
        return cached

    start = time.time()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    output: dict = {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "c_cpp",
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

    # GitHub /search/code REQUIRES authentication — fail fast if no token.
    if not is_authenticated():
        output["errors"].append(
            "GitHub /search/code requires authentication. "
            "Set GITHUB_TOKEN or run `gh auth login`."
        )
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output

    def _http_get():
        tok = resolve_token()
        creds = {"Authorization": f"Bearer {tok}"} if tok else {}
        # Use raw URL to avoid requests percent-encoding `+` as `%2B`.
        # GitHub code search uses `+` as space separator (e.g., "fmt+repo:...").
        url = f"{VCPKG_CODE_SEARCH_URL}?q={query}+repo:microsoft/vcpkg+path:ports"
        resp = requests.get(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": USER_AGENT,
                **creds,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            # Auth required / bad token — not transient, won't self-resolve.
            # Signal via a special sentinel rather than retrying.
            return {"_auth_required": True}
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            # Rate limit — not a transient error, no retry will help.
            return {"_rate_limited": True}
        resp.raise_for_status()
        return resp.json()

    data, attempts, http_error = retry_call(
        _http_get,
        max_retries=2,  # fewer retries — GitHub rate limit won't clear quickly
        retryable_exceptions=(
            requests.ConnectionError, requests.Timeout, requests.RequestException,
        ),
    )

    # Check for rate-limit sentinel
    if isinstance(data, dict) and data.get("_rate_limited"):
        output["errors"].append("GitHub API rate limited. Returning empty results.")
        stale = cache_get_stale(cache_key)
        if stale is not None:
            stale["metadata"]["cache_hit"] = True
            return stale
        cache_set(cache_key, output)
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output

    # Check for auth-required sentinel — 401 won't self-resolve, don't retry
    if isinstance(data, dict) and data.get("_auth_required"):
        output["errors"].append(
            "GitHub /search/code requires authentication. "
            "Set GITHUB_TOKEN or run `gh auth login`."
        )
        cache_set(cache_key, output)
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output

    if http_error is not None:
        output["errors"].append(str(http_error)[:200])
        stale = cache_get_stale(cache_key)
        if stale is not None:
            stale["metadata"]["cache_hit"] = True
            return stale
        cache_set(cache_key, output)
        output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
        return output

    try:
        items = data.get("items", [])
        total_count = data.get("total_count", 0)

        seen_ports: set = set()
        port_results: list = []
        version_map: dict = {}

        for item in items:
            path: str = item.get("path", "")
            match = re.match(r"^ports/([^/]+)/", path)
            if not match:
                continue
            port_name = match.group(1)
            if port_name in seen_ports:
                continue
            seen_ports.add(port_name)

            port_url = f"https://github.com/microsoft/vcpkg/tree/master/ports/{port_name}"

            version = ""
            if port_name not in version_map:
                try:
                    vcpkg_resp = requests.get(
                        f"{VCPKG_RAW_BASE}/{port_name}/vcpkg.json",
                        headers={"User-Agent": USER_AGENT},
                        timeout=5,
                    )
                    if vcpkg_resp.status_code == 200:
                        vcpkg_data = vcpkg_resp.json()
                        version = vcpkg_data.get("version", "")
                        if not version:
                            version = vcpkg_data.get("version-string", "")
                except requests.RequestException:
                    try:
                        ctrl_resp = requests.get(
                            f"{VCPKG_RAW_BASE}/{port_name}/CONTROL",
                            headers={"User-Agent": USER_AGENT},
                            timeout=5,
                        )
                        if ctrl_resp.status_code == 200:
                            for line in ctrl_resp.text.splitlines():
                                if line.startswith("Version:"):
                                    version = line.split(":", 1)[1].strip()
                                    break
                    except requests.RequestException:
                        pass
                version_map[port_name] = version

            version = version_map.get(port_name, "")

            port_results.append({
                "name": port_name,
                "version": version,
                "description": "",
                "registry_url": port_url,
                "stars": 0,
                "downloads": 0,
                "last_commit": "",
                "license_name": "",
                "dependencies": [],
                "score": 0.5,
            })

            if len(port_results) >= limit:
                break

        output["results"] = port_results
        output["metadata"]["has_more"] = int(total_count) > len(port_results)
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

    q = " ".join(_sys.argv[1:]) or "fmt"
    result = search(q)
    print(json.dumps(result, indent=2, ensure_ascii=False))