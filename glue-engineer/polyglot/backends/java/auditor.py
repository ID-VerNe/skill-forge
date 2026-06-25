"""Java/Maven package auditor."""
import sys, os, json, time, re, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def audit(name: str, version: str = "") -> dict:
    from common.schema import now_iso

    result = {
        "schema": "polyglot-output-v1",
        "tool": "auditor",
        "language": "java",
        "candidate_name": name,
        "repo_url": "",
        "timestamp": now_iso(),
        "data": None,
        "errors": [],
        "metadata": {},
    }

    # Parse group:artifact
    parts = name.split(":")
    group_id = parts[0] if len(parts) > 1 else name
    artifact_id = parts[-1]

    # Try to get info from Maven Central
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

    # Attempt to fetch source from GitHub or Maven source jar
    repo = result.get("repo_url", "")
    if repo and "github.com" in repo:
        try:
            repo_path = repo.replace("https://github.com/", "").replace(".git", "").rstrip("/")
            raw_url = f"https://raw.githubusercontent.com/{repo_path}/master/src/main/java/"
            # Try listing common entry points
            for entry in [f"{artifact_id.capitalize()}.java", f"{artifact_id}.java", "Main.java"]:
                r = requests.get(raw_url + entry, timeout=10)
                if r.status_code == 200:
                    sigs, kws = _extract_java(r.text)
                    exports.extend(sigs)
                    keywords.extend(kws)
                    break
            if not exports:
                # Try main branch
                raw_url2 = raw_url.replace("/master/", "/main/")
                for entry in [f"{artifact_id.capitalize()}.java", f"{artifact_id}.java", "Main.java"]:
                    r = requests.get(raw_url2 + entry, timeout=10)
                    if r.status_code == 200:
                        sigs, kws = _extract_java(r.text)
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


def _extract_java(content: str) -> tuple:
    sigs = []
    kws = []
    for m in re.finditer(r'(?:public|protected|private|static|\s)+\s+([\w<>[\]]+)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+\w+)?\s*{', content):
        return_type = m.group(1)
        method_name = m.group(2)
        params = m.group(3).strip()
        sigs.append({"name": method_name, "kind": "method", "signature": f"{' '.join(m.group(0).split()[:1])} {return_type} {method_name}({params})", "source": "src/main/java", "doc_available": False, "probed": False})
        kws.append(method_name)
    for m in re.finditer(r'(?:public\s+)?(?:abstract\s+)?class\s+(\w+)', content):
        sigs.append({"name": m.group(1), "kind": "class", "signature": f"class {m.group(1)}", "source": "src/main/java", "doc_available": False, "probed": False})
    for m in re.finditer(r'(?:public\s+)?interface\s+(\w+)', content):
        sigs.append({"name": m.group(1), "kind": "interface", "signature": f"interface {m.group(1)}", "source": "src/main/java", "doc_available": False, "probed": False})
    return sigs[:20], kws[:10]
