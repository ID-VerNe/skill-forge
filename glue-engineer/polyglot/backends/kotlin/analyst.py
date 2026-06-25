"""Kotlin analyst — regex-based extraction."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def analyze(filepath: str) -> list:
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        for m in re.finditer(r'(?:suspend\s+)?fun\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*([^{]+))?', content):
            sig = f"fun {m.group(1)}({m.group(2).strip()})"
            if m.group(3):
                sig += f": {m.group(3).strip()}"
            result.append({"name": m.group(1), "kind": "function", "signature": sig[:100], "source": f"{filepath}", "doc_available": False, "probed": False})

        for m in re.finditer(r'(?:data\s+|sealed\s+|open\s+)?(?:class|object|enum class)\s+(\w+)', content):
            result.append({"name": m.group(1), "kind": "class", "signature": re.sub(r'\s+', ' ', m.group(0)).strip(), "source": f"{filepath}", "doc_available": False, "probed": False})

        for m in re.finditer(r'interface\s+(\w+)', content):
            result.append({"name": m.group(1), "kind": "interface", "signature": f"interface {m.group(1)}", "source": f"{filepath}", "doc_available": False, "probed": False})

        for m in re.finditer(r'(?:val|var)\s+(\w+)\s*(?::\s*([^=]+))?\s*=', content):
            result.append({"name": m.group(1), "kind": "property", "signature": f"val {m.group(1)}" + (f": {m.group(2).strip()}" if m.group(2) else ""), "source": f"{filepath}", "doc_available": False, "probed": False})

    except Exception as e:
        return [{"name": "PARSE_ERROR", "kind": "error", "signature": str(e), "source": filepath, "doc_available": False, "probed": False}]
    return result
