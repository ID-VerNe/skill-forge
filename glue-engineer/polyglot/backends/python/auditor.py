"""Python package auditor: clones repo, extracts API surface."""
import sys, os, json, re, time, subprocess, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def audit(name: str, version: str = "") -> dict:
    """Audit a Python package. Returns dict matching AuditOutput schema."""
    from common.schema import AuditOutput, AuditData, ExportSymbol, CommunityHealth, now_iso
    from common.git import clone_repo, get_languages

    result = {
        "schema": "polyglot-output-v1",
        "tool": "auditor",
        "language": "python",
        "candidate_name": name,
        "repo_url": "",
        "timestamp": now_iso(),
        "data": None,
        "errors": [],
        "metadata": {},
    }

    # Try to get repo URL from PyPI JSON API
    import requests
    try:
        resp = requests.get(f"https://pypi.org/pypi/{name}/json", timeout=15)
        if resp.status_code == 200:
            info = resp.json()["info"]
            repo_url = info.get("project_urls", {}).get("Source", "") or info.get("project_url", "") or info.get("home_page", "")
            result["repo_url"] = repo_url
    except Exception as e:
        result["errors"].append(f"PyPI lookup failed: {e}")

    exports = []
    keywords = []
    files_scanned = 0
    files_skipped = 0

    # If no repo URL, try to audit via pip download + source extraction
    if not result["repo_url"]:
        try:
            import tempfile, subprocess
            tmp = tempfile.mkdtemp()
            subprocess.run(
                [sys.executable, "-m", "pip", "download", "--no-deps", "--dest", tmp, f"{name}=={version}" if version else name],
                capture_output=True, text=True, timeout=60
            )
            for root, dirs, files in os.walk(tmp):
                for f in files:
                    if f.endswith(".py"):
                        path = os.path.join(root, f)
                        sigs, kvs = _extract_python(path)
                        exports.extend(sigs)
                        keywords.extend(kvs)
                        files_scanned += 1
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            result["errors"].append(f"pip download audit failed: {e}")
            return result

    if exports:
        data = AuditData(
            files_scanned=files_scanned,
            files_skipped=files_skipped,
            exports=[ExportSymbol(**s) if isinstance(s, dict) else s for s in exports],
            keywords_found=list(set(keywords)),
            complexity="medium",
        )
        result["data"] = {
            "files_scanned": data.files_scanned,
            "files_skipped": data.files_skipped,
            "exports": [vars(e) for e in data.exports],
            "keywords_found": data.keywords_found,
            "test_ratio": data.test_ratio,
            "complexity": data.complexity,
            "community_health": None,
            "security": None,
            "verdict": data.verdict,
        }

    return result


def _extract_python(filepath: str) -> tuple:
    """Extract function/class signatures and keywords from a .py file."""
    sigs = []
    kws = []
    import ast
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                sigs.append({"name": node.name, "kind": "function", "signature": f"def {node.name}({', '.join(args)})", "source": f"{filepath}:{node.lineno}", "doc_available": bool(ast.get_docstring(node)), "probed": False})
                kws.append(node.name)
            elif isinstance(node, ast.AsyncFunctionDef):
                args = [a.arg for a in node.args.args]
                sigs.append({"name": node.name, "kind": "async_function", "signature": f"async def {node.name}({', '.join(args)})", "source": f"{filepath}:{node.lineno}", "doc_available": bool(ast.get_docstring(node)), "probed": False})
            elif isinstance(node, ast.ClassDef):
                bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                base_str = f"({', '.join(bases)})" if bases else ""
                sigs.append({"name": node.name, "kind": "class", "signature": f"class {node.name}{base_str}", "source": f"{filepath}:{node.lineno}", "doc_available": bool(ast.get_docstring(node)), "probed": False})
                kws.append(node.name)
    except SyntaxError:
        pass
    return sigs[:20], kws[:10]