"""
polyglot/backends/go/auditor.py — Go module auditor backend.

Fetches module metadata via the Go module proxy (proxy.golang.org/@latest)
and attempts to extract exported symbols from the module's source on GitHub.
"""

import sys
import os
import time
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests

from polyglot.common.cache import cache_get, cache_set, cache_get_stale
from polyglot.common.retry import retry_call


def audit(name: str, version: str = "") -> dict:
    """Audit a Go module. Returns dict matching AuditOutput schema."""
    cache_key = f"audit:go:{name}:{version or 'latest'}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["metadata"]["cache_hit"] = True
        return cached

    start = time.monotonic()
    errors = []

    # Resolve the latest version + commit time via the module proxy.
    ver = version or "latest"
    mod_info = _fetch_module_info(name, ver)
    if isinstance(mod_info, str) and mod_info.startswith("error:"):
        errors.append(mod_info[6:].strip()[:200])
        mod_info = None

    exports = []
    repo_url = ""

    if mod_info:
        resolved_version = mod_info.get("version", ver)
        repo_url = _path_to_repo_url(name)

        # Attempt to fetch source from GitHub raw
        if repo_url and "github.com" in repo_url:
            gh_exports = _fetch_github_exports(repo_url, name, resolved_version)
            if gh_exports:
                exports.extend(gh_exports)
            else:
                # Fallback: try proxy.golang.org for source
                gh_exports = _fetch_proxy_exports(name, resolved_version)
                if gh_exports:
                    exports.extend(gh_exports)

    duration_ms = int((time.monotonic() - start) * 1000)

    result = {
        "schema": "polyglot-output-v1",
        "tool": "auditor",
        "language": "go",
        "candidate_name": name,
        "repo_url": repo_url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "files_scanned": 0,
            "files_skipped": 0,
            "exports": exports,
            "keywords_found": [],
            "test_ratio": 0.0,
            "complexity": "medium",
            "community_health": None,
            "security": None,
            "verdict": "",
        },
        "errors": errors,
        "metadata": {
            "duration_ms": duration_ms,
            "cache_hit": False,
        },
    }

    cache_set(cache_key, result)
    return result


def _fetch_module_info(name: str, version: str) -> dict | None:
    """Fetch module version info via the Go module proxy.

    Uses ``https://proxy.golang.org/{module}/@latest`` (the authoritative
    "latest version" endpoint) and returns ``{"version":..., "last_commit":...}``.
    Returns None on 404 or network failure; an "error: ..." string on the
    "latest" sentinel being requested but the proxy yielding a non-200.
    """
    from polyglot.backends.go.scout import lookup

    # If the caller asked for a pinned version we can still get the latest
    # commit time via the @latest endpoint — version pinning for symbol
    # extraction is best-effort here.
    result = lookup(name)
    if result is None:
        return "error: module not found on proxy.golang.org (404 or network error)"
    return {
        "version": result.get("version", version if version != "latest" else ""),
        "last_commit": result.get("last_commit", ""),
    }


def _path_to_repo_url(path: str) -> str:
    """Convert a Go module path to a GitHub repo URL."""
    m = re.match(r"^(github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", path)
    if m:
        return f"https://{m.group(1)}"
    return ""


def _fetch_github_exports(repo_url: str, module_name: str, version: str) -> list:
    """Fetch Go source files from GitHub raw and extract exports."""
    exports = []
    # Normalize version to a branch or tag
    ref = version if version and version != "latest" else "master"

    # Try to fetch common Go files from GitHub raw
    import_path = repo_url.replace("https://", "")
    # Strip trailing path
    parts = import_path.split("/")
    org_repo = "/".join(parts[:2]) if len(parts) >= 2 else import_path
    subdir = "/".join(parts[2:]) if len(parts) > 2 else ""
    full_org_repo = org_repo
    gh_api_base = f"https://raw.githubusercontent.com/{full_org_repo}/{ref}"

    if subdir:
        gh_api_base = f"{gh_api_base}/{subdir}"

    # Fetch main Go files
    go_files = ["main.go", "go.mod"]
    fetched_files = set()

    for fname in go_files:
        url = f"{gh_api_base}/{fname}" if subdir else f"{gh_api_base}/{fname}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                fetched_files.add(fname)
                file_exports = _extract_exports_from_go(content, fname)
                exports.extend(file_exports)
        except Exception:
            pass

    # If no standard files found, try fetching directory listing via GitHub API
    if not fetched_files:
        try:
            gh_api = f"https://api.github.com/repos/{full_org_repo}/contents"
            if subdir:
                gh_api = f"{gh_api}/{subdir}"
            resp = requests.get(gh_api, timeout=10)
            if resp.status_code == 200:
                items = resp.json()
                for item in items:
                    if item.get("type") == "file" and item["name"].endswith(".go"):
                        dl_url = item.get("download_url")
                        if dl_url:
                            try:
                                resp2 = requests.get(dl_url, timeout=10)
                                if resp2.status_code == 200:
                                    file_exports = _extract_exports_from_go(resp2.text, item["name"])
                                    exports.extend(file_exports)
                            except Exception:
                                pass
        except Exception:
            pass

    return exports


def _fetch_proxy_exports(name: str, version: str) -> list:
    """Fallback: try fetching module source via proxy.golang.org."""
    exports = []
    ver = version or "latest"
    url = f"https://proxy.golang.org/{name}/@v/{ver}.mod"

    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            # .mod files have module directives, not source code
            # Try to at least get the module path
            for line in resp.text.splitlines():
                if line.startswith("module "):
                    exports.append({
                        "name": line[7:].strip(),
                        "kind": "module",
                        "signature": "",
                        "source": f"{name}@{ver}:go.mod",
                        "doc_available": False,
                        "probed": False,
                    })
    except Exception:
        pass

    return exports


def _extract_exports_from_go(source: str, filename: str) -> list:
    """Extract exported Go symbols (exported functions, types, structs, interfaces) from source."""
    exports = []
    lines = source.split("\n")

    # Package declaration
    pkg_match = re.search(r"^package\s+(\w+)", source, re.MULTILINE)
    pkg_name = pkg_match.group(1) if pkg_match else ""

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip comments and blank lines
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            i += 1
            continue

        # Exported function: func Foo(...)
        func_match = re.match(r"^func\s+([A-Z]\w*)\s*\(", stripped)
        if func_match:
            exports.append({
                "name": func_match.group(1),
                "kind": "function",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported method: func (r *Receiver) Foo(...)
        method_match = re.match(r"^func\s+\([^)]+\)\s+([A-Z]\w*)\s*\(", stripped)
        if method_match:
            exports.append({
                "name": method_match.group(1),
                "kind": "method",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported type: type Foo ...
        type_match = re.match(r"^type\s+([A-Z]\w*)\s+", stripped)
        if type_match:
            kind = "type"
            if "interface" in stripped:
                kind = "interface"
            elif "struct" in stripped:
                kind = "struct"
            exports.append({
                "name": type_match.group(1),
                "kind": kind,
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported const: const Foo = ...
        const_match = re.match(r"^const\s+([A-Z]\w*)\s*=", stripped)
        if const_match:
            exports.append({
                "name": const_match.group(1),
                "kind": "constant",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported var: var Foo = ...
        var_match = re.match(r"^var\s+([A-Z]\w*)\s*=", stripped)
        if var_match:
            exports.append({
                "name": var_match.group(1),
                "kind": "variable",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        i += 1

    return exports


def _has_doc_comment(lines: list, idx: int) -> bool:
    """Check if the preceding lines contain a doc comment (//-style)."""
    if idx > 0:
        prev = lines[idx - 1].strip()
        if prev.startswith("//"):
            return True
    return False


# ── Minimal smoke test ──
if __name__ == "__main__":
    out = audit("github.com/gin-gonic/gin")
    print(f"Audited {out['candidate_name']}, {len(out['data']['exports'])} exports, {len(out['errors'])} errors")
    for e in out["data"]["exports"][:10]:
        print(f"  {e['kind']}: {e['name']}")