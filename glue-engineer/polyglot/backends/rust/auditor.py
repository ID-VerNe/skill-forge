"""Rust crate auditor."""
import sys, os, json, time, re, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def audit(name: str, version: str = "") -> dict:
    from common.schema import now_iso

    result = {
        "schema": "polyglot-output-v1",
        "tool": "auditor",
        "language": "rust",
        "candidate_name": name,
        "repo_url": "",
        "timestamp": now_iso(),
        "data": None,
        "errors": [],
        "metadata": {},
    }

    # Get crate metadata from crates.io
    try:
        resp = requests.get(f"https://crates.io/api/v1/crates/{name}", headers={"User-Agent": "polyglot/1.0"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            crate_data = data.get("crate", {})
            result["repo_url"] = crate_data.get("repository", "")
    except Exception as e:
        result["errors"].append(f"crates.io lookup failed: {e}")

    exports = []
    keywords = []

    # Try to fetch the crate source from crates.io
    try:
        dl_url = f"https://crates.io/api/v1/crates/{name}/{version}/download" if version else f"https://crates.io/api/v1/crates/{name}/latest"
        # For source analysis, try the docs.rs source or GitHub
        repo = result.get("repo_url", "")
        if repo and "github.com" in repo:
            import tempfile, subprocess
            repo_path = repo.replace("https://github.com/", "").replace(".git", "")
            raw_url = f"https://raw.githubusercontent.com/{repo_path}/master/src/lib.rs"
            r = requests.get(raw_url, timeout=15)
            if r.status_code == 200:
                sigs, kws = _extract_rust_source(r.text)
                exports.extend(sigs)
                keywords.extend(kws)
            else:
                # Try main branch
                raw_url = raw_url.replace("/master/", "/main/")
                r = requests.get(raw_url, timeout=15)
                if r.status_code == 200:
                    sigs, kws = _extract_rust_source(r.text)
                    exports.extend(sigs)
                    keywords.extend(kws)
    except Exception as e:
        result["errors"].append(f"source fetch failed: {e}")

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

    return result


def _extract_rust_source(content: str) -> tuple:
    sigs = []
    kws = []
    for m in re.finditer(r'pub\s+(?:unsafe\s+)?fn\s+(\w+)\s*\(', content):
        sigs.append({"name": m.group(1), "kind": "function", "signature": f"pub fn {m.group(1)}(...)", "source": "src/lib.rs", "doc_available": False, "probed": False})
        kws.append(m.group(1))
    for m in re.finditer(r'pub\s+(?:unsafe\s+)?trait\s+(\w+)', content):
        sigs.append({"name": m.group(1), "kind": "trait", "signature": f"pub trait {m.group(1)}", "source": "src/lib.rs", "doc_available": False, "probed": False})
    for m in re.finditer(r'pub\s+(?:struct|enum)\s+(\w+)', content):
        sigs.append({"name": m.group(1), "kind": "struct", "signature": f"pub struct {m.group(1)}", "source": "src/lib.rs", "doc_available": False, "probed": False})
    for m in re.finditer(r'pub\s+(?:macro_rules!\s*|use\s+)', content):
        pass
    for m in re.finditer(r'#\[derive\(([^)]+)\)\]', content):
        kws.append(f"derive({m.group(1)})")
    return sigs[:20], kws[:10]