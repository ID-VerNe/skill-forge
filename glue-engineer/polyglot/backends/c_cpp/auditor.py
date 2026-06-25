"""C/C++ package auditor (limited: GitHub source analysis)."""
import sys, os, json, time, re, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def audit(name: str, version: str = "") -> dict:
    from common.schema import now_iso
    result = {"schema": "polyglot-output-v1", "tool": "auditor", "language": "c_cpp", "candidate_name": name, "repo_url": "", "timestamp": now_iso(), "data": None, "errors": [], "metadata": {}}
    exports = []
    keywords = []
    try:
        # Try GitHub search
        resp = requests.get(f"https://api.github.com/search/repositories?q={name}+language:c&sort=stars&per_page=1", headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "polyglot/1.0"}, timeout=15)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                result["repo_url"] = item.get("html_url", "")
                # Try to fetch a header file
                repo_path = item.get("full_name", "")
                for branch in ["master", "main"]:
                    for header in [f"{name}.h", f"{name.lower()}.h", "include/{name}/{name}.h".format(name=name.lower())]:
                        url = f"https://raw.githubusercontent.com/{repo_path}/{branch}/{header}"
                        r = requests.get(url, timeout=10)
                        if r.status_code == 200:
                            for m in re.finditer(r'(?:extern\s+)?(?:void|int|char|size_t|bool|float|double|uint\d+_t|int\d+_t|char\*|const\s+\w+)\s+(\w+)\s*\(', r.text):
                                exports.append({"name": m.group(1), "kind": "function", "signature": m.group(0).strip()[:80], "source": header, "doc_available": False, "probed": False})
                                keywords.append(m.group(1))
                            break
                    if exports: break
    except Exception as e:
        result["errors"].append(f"C/C++ audit failed: {e}")
    result["data"] = {"files_scanned": len(exports), "files_skipped": 0, "exports": exports[:30], "keywords_found": list(set(keywords))[:15], "test_ratio": 0.0, "complexity": "low", "community_health": None, "security": None, "verdict": ""}
    return result

def _extract_c(content: str) -> tuple:
    sigs = []
    kws = []
    for m in re.finditer(r'(?:extern\s+)?(?:void|int|char|size_t|bool|float|double|uint\d+_t|int\d+_t|char\*|const\s+\w+|\w+\s+\*+)\s+(\w+)\s*\(([^)]*)\)', content):
        sigs.append({"name": m.group(1), "kind": "function", "signature": m.group(0).strip()[:80], "source": "src", "doc_available": False, "probed": False})
    return sigs[:20], kws[:10]
