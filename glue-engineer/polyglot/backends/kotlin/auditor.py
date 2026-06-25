"""Kotlin package auditor."""
import sys, os, json, time, re, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def audit(name: str, version: str = "") -> dict:
    from common.schema import now_iso

    result = {
        "schema": "polyglot-output-v1",
        "tool": "auditor",
        "language": "kotlin",
        "candidate_name": name,
        "repo_url": "",
        "timestamp": now_iso(),
        "data": None,
        "errors": [],
        "metadata": {},
    }

    parts = name.split(":")
    group_id = parts[0] if len(parts) > 1 else name
    artifact_id = parts[-1]

    try:
        search_url = f"https://search.maven.org/solrsearch/select?q=g:{group_id}+AND+a:{artifact_id}&rows=1&wt=json"
        resp = requests.get(search_url, timeout=15)
        if resp.status_code == 200:
            docs = resp.json().get("response", {}).get("docs", [])
            if docs:
                doc = docs[0]
                result["repo_url"] = doc.get("s", [""])[0] if doc.get("s") else ""
    except Exception as e:
        result["errors"].append(f"Maven lookup failed: {e}")

    exports = []
    keywords = []

    repo = result.get("repo_url", "")
    if repo and "github.com" in repo:
        try:
            repo_path = repo.replace("https://github.com/", "").replace(".git", "").rstrip("/")
            for branch in ["master", "main"]:
                url = f"https://raw.githubusercontent.com/{repo_path}/{branch}/src/main/kotlin/"
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    # List directory and find .kt files (simplified: try common entry)
                    break
            # Try direct main file
            for entry in [f"{artifact_id.capitalize()}.kt", f"{artifact_id}.kt"]:
                for branch in ["master", "main"]:
                    url = f"https://raw.githubusercontent.com/{repo_path}/{branch}/src/main/kotlin/{entry}"
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        sigs, kws = _extract_kotlin(r.text)
                        exports.extend(sigs)
                        keywords.extend(kws)
                        break
        except Exception:
            pass

    result["data"] = {
        "files_scanned": max(len(exports), 1),
        "files_skipped": 0,
        "exports": exports[:30],
        "keywords_found": list(set(keywords))[:15],
        "test_ratio": 0.0,
        "complexity": "medium" if len(exports) > 10 else "low",
        "community_health": None,
        "security": None,
        "verdict": "",
    }

    return result


def _extract_kotlin(content: str) -> tuple:
    sigs = []
    kws = []
    for m in re.finditer(r'(?:fun|suspend fun)\s+(\w+)\s*\(', content):
        sigs.append({"name": m.group(1), "kind": "function", "signature": f"{m.group(0).strip()}...", "source": "src/main/kotlin", "doc_available": False, "probed": False})
    for m in re.finditer(r'(?:data\s+)?(?:class|object|enum class|sealed class|interface)\s+(\w+)', content):
        kind = "class" if "class" in m.group(0) else ("object" if "object" in m.group(0) else "interface")
        sigs.append({"name": m.group(1), "kind": kind, "signature": re.sub(r'\s+', ' ', m.group(0)).strip(), "source": "src/main/kotlin", "doc_available": False, "probed": False})
    return sigs[:20], kws[:10]
