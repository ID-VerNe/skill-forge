# -*- coding: utf-8 -*-
"""
Python/PyPI scout backend.

Returns structured search results following the unified polyglot schema.
"""

import json
import os
import re
import sys
import time
import traceback

# Ensure project root is importable so "from common.schema import ..." works
_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import requests
from common.schema import compute_score, now_iso

# Fix GBK encoding crash on Chinese Windows (emoji/Unicode in terminal output)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ───── Helpers ─────


def _parse_snippet(snippet_html: str) -> dict:
    """Extract name, version, description from a single PyPI search-result snippet."""
    info = {"name": None, "version": None, "description": None}

    m = re.search(r'class="package-snippet__name">(.+?)</span>', snippet_html)
    if m:
        info["name"] = m.group(1).strip()

    m = re.search(r'class="package-snippet__version">(.+?)</span>', snippet_html)
    if m:
        info["version"] = m.group(1).strip()

    m = re.search(
        r'class="package-snippet__description">(.+?)</p>', snippet_html, re.DOTALL
    )
    if m:
        desc = m.group(1).strip()
        desc = re.sub(r"<[^>]+>", "", desc)  # strip any nested HTML tags
        info["description"] = desc.strip()

    return info


def _fetch_download_stats(package: str) -> int:
    """Best-effort fetch of monthly download count via PyPI Stats API."""
    try:
        url = f"https://pypistats.org/api/packages/{package}/recent"
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("last_month", 0)
    except Exception:
        pass
    return 0


def _fetch_exact(query: str) -> dict | None:
    """Fetch exact package info via PyPI JSON API.

    Returns the full JSON response body or None on failure/404.
    """
    url = f"https://pypi.org/pypi/{query}/json"
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _extract_registry_url(info: dict) -> str:
    """Extract repository URL from project_urls dict."""
    urls = info.get("project_urls") or {}
    if not urls:
        return ""
    # Try common URL-name keys in priority order
    for key in ("Repository", "Source", "Source Code", "Homepage", "Home Page"):
        val = urls.get(key)
        if val:
            return val.strip()
    # Fallback: take any non-empty value
    for val in urls.values():
        if val:
            return val.strip()
    return ""


def _fetch_html_search(query: str, limit: int) -> list[dict]:
    """Broad PyPI search via HTML scraping.

    Returns a list of raw package names found (for further detail lookup).
    """
    names = []
    try:
        html_url = "https://pypi.org/search/"
        resp = requests.get(
            html_url, params={"q": query}, headers=_BROWSER_HEADERS, timeout=15
        )
        if resp.status_code != 200:
            return names

        # If Cloudflare is blocking, bail out
        if "cf-browser-verification" in resp.text:
            return names

        snippets = resp.text.split('class="package-snippet"')[1:]
        for snippet in snippets[:limit]:
            parsed = _parse_snippet(snippet)
            if parsed["name"]:
                names.append(parsed)
    except Exception:
        pass
    return names


def _build_result(
    raw_data: dict | None,
    *,
    name: str,
    version: str = "",
    description: str = "",
) -> dict:
    """Build a SearchResult-compatible dict from available data.

    ``raw_data`` is the full PyPI JSON response (or None if only HTML snippet
    data is available).
    """
    info = (raw_data or {}).get("info", {}) if raw_data else {}

    registry_url = ""
    license_name = ""
    dependencies = []
    last_commit = ""
    days_since_commit = 9999
    downloads = 0

    if info:
        registry_url = _extract_registry_url(info)
        license_name = info.get("license", "") or ""
        raw_deps = info.get("requires_dist") or []
        dependencies = list(raw_deps) if isinstance(raw_deps, (list, tuple)) else []

    # Download stats (best-effort)
    downloads = _fetch_download_stats(name)

    # Last-commit proxy: latest release upload time
    if raw_data and "releases" in raw_data:
        releases = raw_data["releases"]
        all_times = []
        for _ver, files in releases.items():
            if isinstance(files, list):
                for f in files:
                    if isinstance(f, dict) and f.get("upload_time"):
                        all_times.append(f["upload_time"])
        if all_times:
            all_times.sort(reverse=True)
            last_commit = all_times[0][:10]  # "2024-01-01"
            try:
                parsed = time.strptime(last_commit, "%Y-%m-%d")
                days_since_commit = int((time.time() - time.mktime(parsed)) / 86400)
            except (ValueError, OverflowError, OSError):
                pass

    score = compute_score(stars=0, downloads=downloads, days_since_commit=days_since_commit)

    return {
        "name": name,
        "version": version or "",
        "description": description or "",
        "registry_url": registry_url,
        "stars": 0,
        "downloads": downloads,
        "last_commit": last_commit,
        "license_name": license_name,
        "dependencies": dependencies,
        "score": round(score, 4),
    }


# ───── Public API ─────


def search(query: str, limit: int = 5) -> dict:
    """Search PyPI via JSON API. Returns dict matching SearchOutput schema.

    Primary path: exact-match via ``https://pypi.org/pypi/<query>/json``.
    Fallback path: broad search via ``https://pypi.org/search/?q=<query>``
    with HTML snippet parsing.

    Returns a plain dict (not a dataclass instance) matching SearchOutput.
    """
    start = time.time()
    errors: list[str] = []
    results: list[dict] = []

    # ── 1. Exact match via JSON API ──
    try:
        raw = _fetch_exact(query)
        if raw:
            info = raw.get("info", {})
            result = _build_result(
                raw,
                name=info.get("name", query),
                version=info.get("version", ""),
                description=info.get("summary", ""),
            )
            results.append(result)
    except requests.exceptions.ConnectionError as e:
        errors.append(f"ConnectionError during exact lookup: {e}")
    except requests.exceptions.Timeout as e:
        errors.append(f"Timeout during exact lookup: {e}")
    except Exception as e:
        errors.append(f"Exact-lookup error: {e}")

    # ── 2. Fallback / broad search via HTML ──
    if len(results) < limit:
        try:
            snippets = _fetch_html_search(query, limit)
            for parsed in snippets:
                pkg_name = parsed["name"]
                # Skip duplicate (already have exact match for this name)
                if any(r["name"] == pkg_name for r in results):
                    continue

                # Try to enrich with JSON API detail
                detail = _fetch_exact(pkg_name)
                result = _build_result(
                    detail,
                    name=pkg_name,
                    version=parsed.get("version", ""),
                    description=parsed.get("description", ""),
                )
                results.append(result)
                if len(results) >= limit:
                    break
        except requests.exceptions.ConnectionError as e:
            errors.append(f"ConnectionError during HTML search: {e}")
        except requests.exceptions.Timeout as e:
            errors.append(f"Timeout during HTML search: {e}")
        except Exception as e:
            errors.append(f"HTML-search error: {e}")

    duration_ms = int((time.time() - start) * 1000)

    return {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "python",
        "query": query,
        "timestamp": now_iso(),
        "results": results[:limit],
        "errors": errors,
        "metadata": {
            "duration_ms": duration_ms,
            "cache_hit": False,
            "has_more": len(results) > limit,
        },
    }


# ───── CLI Entry Point ─────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PyPI scout backend")
    parser.add_argument("query", help="Package name or search term")
    parser.add_argument("--limit", type=int, default=5, help="Max results")
    args = parser.parse_args()

    output = search(args.query, limit=args.limit)
    print(json.dumps(output, indent=2, ensure_ascii=False))