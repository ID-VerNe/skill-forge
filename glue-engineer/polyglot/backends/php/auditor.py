"""PHP package auditor (Packagist)."""
import sys, os, json, time, re, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def audit(name: str, version: str = "") -> dict:
    """Audit a Packagist package. Returns dict matching AuditOutput schema."""
    from common.schema import now_iso
    result = {
        "schema": "polyglot-output-v1",
        "tool": "auditor",
        "language": "php",
        "candidate_name": name,
        "repo_url": "",
        "timestamp": now_iso(),
        "data": None,
        "errors": [],
        "metadata": {},
    }

    # Packagist API: https://packagist.org/packages/{vendor}/{package}.json
    try:
        # Encode name for URL (it's already vendor/package format)
        api_url = f"https://packagist.org/packages/{name}.json"
        resp = requests.get(api_url, timeout=15)
        if resp.status_code == 200:
            pkg = resp.json()
            pkg_data = pkg.get("package", {})

            # Repository URL
            repo_data = pkg_data.get("repository", "")
            result["repo_url"] = repo_data if isinstance(repo_data, str) else ""

            # Get latest version
            versions = pkg_data.get("versions", {})
            latest = version or pkg_data.get("highest", "")
            ver_data = versions.get(latest, versions.get("dev-master", {}))

            # Try to fetch dist tarball and extract
            dist_url = ver_data.get("dist", {}).get("url", "") if ver_data else ""
            if dist_url:
                import tempfile, tarfile
                tmp = tempfile.mkdtemp()
                try:
                    r = requests.get(dist_url, timeout=30)
                    r.raise_for_status()
                    tarball_path = os.path.join(tmp, "pkg.tar")
                    with open(tarball_path, "wb") as f:
                        f.write(r.content)
                    # Extract (might be gzipped)
                    with tarfile.open(tarball_path, "r:*") as tar:
                        tar.extractall(path=tmp)

                    # Find the package directory (usually named after the package)
                    pkg_dir = None
                    for entry in os.listdir(tmp):
                        full = os.path.join(tmp, entry)
                        if os.path.isdir(full) and entry != "__pycache__":
                            pkg_dir = full
                            break

                    exports = []
                    keywords = []
                    if pkg_dir:
                        for root, dirs, files in os.walk(pkg_dir):
                            for f in files:
                                if f.endswith(".php"):
                                    path = os.path.join(root, f)
                                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                                        content = fh.read()
                                    # Extract class declarations
                                    for m in re.finditer(
                                        r'(?:abstract\s+)?(?:final\s+)?class\s+(\w+)',
                                        content,
                                    ):
                                        exports.append({
                                            "name": m.group(1),
                                            "kind": "class",
                                            "signature": f"class {m.group(1)}",
                                            "source": path,
                                            "doc_available": False,
                                            "probed": False,
                                        })
                                        keywords.append(m.group(1))
                                    # Extract function declarations
                                    for m in re.finditer(
                                        r'(?:public|protected|private|static)?\s*function\s+(\w+)\s*\(',
                                        content,
                                    ):
                                        exports.append({
                                            "name": m.group(1),
                                            "kind": "method",
                                            "signature": f"function {m.group(1)}(...)",
                                            "source": path,
                                            "doc_available": False,
                                            "probed": False,
                                        })
                                    # Extract interface declarations
                                    for m in re.finditer(
                                        r'interface\s+(\w+)',
                                        content,
                                    ):
                                        exports.append({
                                            "name": m.group(1),
                                            "kind": "interface",
                                            "signature": f"interface {m.group(1)}",
                                            "source": path,
                                            "doc_available": False,
                                            "probed": False,
                                        })
                                    # Extract trait declarations
                                    for m in re.finditer(
                                        r'trait\s+(\w+)',
                                        content,
                                    ):
                                        exports.append({
                                            "name": m.group(1),
                                            "kind": "trait",
                                            "signature": f"trait {m.group(1)}",
                                            "source": path,
                                            "doc_available": False,
                                            "probed": False,
                                        })

                    result["data"] = {
                        "files_scanned": len(exports),
                        "files_skipped": 0,
                        "exports": exports[:30],
                        "keywords_found": list(set(keywords))[:15],
                        "test_ratio": 0.0,
                        "complexity": "medium" if len(exports) > 10 else "low",
                        "community_health": None,
                        "security": None,
                        "verdict": "",
                    }
                    import shutil
                    shutil.rmtree(tmp, ignore_errors=True)
                except Exception as e:
                    import shutil
                    shutil.rmtree(tmp, ignore_errors=True)
                    raise e
            else:
                # No dist URL available — return minimal data
                result["data"] = {
                    "files_scanned": 0,
                    "files_skipped": 0,
                    "exports": [],
                    "keywords_found": [],
                    "test_ratio": 0.0,
                    "complexity": "unknown",
                    "community_health": None,
                    "security": None,
                    "verdict": "",
                }
        else:
            result["errors"].append(f"Packagist API returned {resp.status_code} for {name}")
            result["data"] = {
                "files_scanned": 0,
                "files_skipped": 0,
                "exports": [],
                "keywords_found": [],
                "test_ratio": 0.0,
                "complexity": "unknown",
                "community_health": None,
                "security": None,
                "verdict": "",
            }
    except Exception as e:
        result["errors"].append(f"Packagist audit failed: {e}")
        result["data"] = {
            "files_scanned": 0,
            "files_skipped": 0,
            "exports": [],
            "keywords_found": [],
            "test_ratio": 0.0,
            "complexity": "unknown",
            "community_health": None,
            "security": None,
            "verdict": "",
        }

    return result