"""JavaScript/TypeScript analyst — regex-based symbol extraction."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def analyze(filepath: str) -> list:
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for m in re.finditer(r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?:\*\s+)?(\w+)\s*\(', content):
            result.append({"name": m.group(1), "kind": "function", "signature": content[m.start():m.start()+80].split('\n')[0].strip(), "source": f"{filepath}", "doc_available": False, "probed": False})
        for m in re.finditer(r'(?:export\s+)?(?:async\s+)?const\s+(\w+)\s*[=:]\s*(?:async\s+)?\(', content):
            result.append({"name": m.group(1), "kind": "arrow_function", "signature": f"const {m.group(1)} = (...) =>", "source": f"{filepath}", "doc_available": False, "probed": False})
        for m in re.finditer(r'(?:export\s+)?class\s+(\w+)\s*(?:extends\s+(\w+))?\s*(?:implements\s+(\w+))?', content):
            result.append({"name": m.group(1), "kind": "class", "signature": f"class {m.group(1)}", "source": f"{filepath}", "doc_available": False, "probed": False})
        for m in re.finditer(r'(?:export\s+)?interface\s+(\w+)\s*(?:extends\s+[\w,\s]+)?', content):
            result.append({"name": m.group(1), "kind": "interface", "signature": f"interface {m.group(1)}", "source": f"{filepath}", "doc_available": False, "probed": False})
        for m in re.finditer(r'(?:export\s+)?type\s+(\w+)\s*=', content):
            result.append({"name": m.group(1), "kind": "type", "signature": f"type {m.group(1)} =", "source": f"{filepath}", "doc_available": False, "probed": False})
    except Exception as e:
        return [{"name": "PARSE_ERROR", "kind": "error", "signature": str(e), "source": filepath, "doc_available": False, "probed": False}]
    return result