"""JavaScript/npm package auditor."""
import sys, os, json, time, re, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def audit(name: str, version: str = "") -> dict:
    from common.schema import now_iso
    result = {"schema": "polyglot-output-v1", "tool": "auditor", "language": "javascript", "candidate_name": name, "repo_url": "", "timestamp": now_iso(), "data": None, "errors": [], "metadata": {}}
    try:
        resp = requests.get(f"https://registry.npmjs.org/{name}", timeout=15)
        if resp.status_code == 200:
            pkg = resp.json()
            latest = pkg.get("dist-tags", {}).get("latest", "")
            ver_data = pkg.get("versions", {}).get(version or latest, {})
            repo = pkg.get("repository", {})
            result["repo_url"] = (repo.get("url", "") if isinstance(repo, dict) else repo).replace("git+","").replace(".git","")
            # Try tarball extraction
            tarball_url = ver_data.get("dist", {}).get("tarball", "")
            if tarball_url:
                import tempfile, subprocess, tarfile
                tmp = tempfile.mkdtemp()
                r = requests.get(tarball_url, timeout=30)
                with open(os.path.join(tmp, "pkg.tgz"), "wb") as f: f.write(r.content)
                with tarfile.open(os.path.join(tmp, "pkg.tgz")) as tar: tar.extractall(path=tmp)
                pkg_dir = os.path.join(tmp, "package")
                exports = []; keywords = []
                if os.path.exists(pkg_dir):
                    for root, dirs, files in os.walk(pkg_dir):
                        for f in files:
                            if f.endswith((".js", ".mjs", ".cjs", ".ts")):
                                path = os.path.join(root, f)
                                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                                    content = fh.read()
                                for m in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(', content):
                                    exports.append({"name": m.group(1), "kind": "function", "signature": f"function {m.group(1)}(...)", "source": path, "doc_available": False, "probed": False})
                                    keywords.append(m.group(1))
                                for m in re.finditer(r'(?:export\s+)?class\s+(\w+)', content):
                                    exports.append({"name": m.group(1), "kind": "class", "signature": f"class {m.group(1)}", "source": path, "doc_available": False, "probed": False})
                                for m in re.finditer(r'module\.exports\s*=\s*(\w+)', content):
                                    exports.append({"name": f"exports.{m.group(1)}", "kind": "export", "signature": f"module.exports = {m.group(1)}", "source": path, "doc_available": False, "probed": False})
                import shutil; shutil.rmtree(tmp, ignore_errors=True)
                result["data"] = {"files_scanned": len(exports), "files_skipped": 0, "exports": exports[:30], "keywords_found": list(set(keywords))[:15], "test_ratio": 0.0, "complexity": "medium" if len(exports) > 10 else "low", "community_health": None, "security": None, "verdict": ""}
    except Exception as e:
        result["errors"].append(f"npm audit failed: {e}")
    if not result.get("data"):
        result["data"] = {"files_scanned": 0, "files_skipped": 0, "exports": [], "keywords_found": [], "test_ratio": 0.0, "complexity": "unknown", "community_health": None, "security": None, "verdict": ""}
    return result
