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


VCPKG_CODE_SEARCH_URL = "https://api.github.com/search/code"
VCPKG_RAW_BASE = "https://raw.githubusercontent.com/microsoft/vcpkg/master/ports"
REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = "polyglot/1.0"


def search(query: str, limit: int = 5) -> dict:
    """Search vcpkg ports. Returns dict matching SearchOutput schema."""
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

    try:
        resp = requests.get(
            VCPKG_CODE_SEARCH_URL,
            params={
                "q": f"{query}+repo:microsoft/vcpkg+path:ports",
            },
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": USER_AGENT,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            output["errors"].append(
                "GitHub API rate limited. Returning empty results."
            )
            output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
            return output

        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        output["errors"].append(
            f"Request to GitHub API timed out after {REQUEST_TIMEOUT}s"
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

    items = data.get("items", [])
    total_count = data.get("total_count", 0)

    # Deduplicate by port directory name
    seen_ports: set = set()
    port_results: list = []
    version_map: dict = {}

    for item in items:
        path: str = item.get("path", "")
        # Extract port directory name from path like "ports/<port-name>/..."
        match = re.match(r"^ports/([^/]+)/", path)
        if not match:
            continue
        port_name = match.group(1)
        if port_name in seen_ports:
            continue
        seen_ports.add(port_name)

        html_url = item.get("html_url", "")
        # Rewrite to the port directory URL on GitHub
        port_url = f"https://github.com/microsoft/vcpkg/tree/master/ports/{port_name}"

        # Try to fetch vcpkg.json for version info (non-blocking if it fails)
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
                # Fallback: try CONTROL file format (older vcpkg ports)
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
            "score": 0.5,  # neutral default
        })

        if len(port_results) >= limit:
            break

    output["results"] = port_results
    output["metadata"]["has_more"] = int(total_count) > len(port_results)
    output["metadata"]["duration_ms"] = int((time.time() - start) * 1000)

    if not output["results"] and not output["errors"]:
        output["errors"].append(f"No results found for query '{query}'")

    return output


if __name__ == "__main__":
    import json
    import sys as _sys

    q = " ".join(_sys.argv[1:]) or "fmt"
    result = search(q)
    print(json.dumps(result, indent=2, ensure_ascii=False))