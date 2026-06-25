"""C/C++ analyst — regex-based function extraction."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def analyze(filepath: str) -> list:
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for m in re.finditer(r'(?:static\s+)?(?:inline\s+)?(?:void|int|char|size_t|bool|float|double|uint\d+_t|int\d+_t|char\*|const\s+[\w\s]+\*?)\s+(\w+)\s*\(([^)]*)\)\s*{', content):
            result.append({"name": m.group(1), "kind": "function", "signature": m.group(0).split('{')[0].strip()[:80], "source": f"{filepath}", "doc_available": False, "probed": False})
        for m in re.finditer(r'typedef\s+(?:struct|union|enum)\s+\w+\s*\{[^}]*\}\s*(\w+);', content):
            result.append({"name": m.group(1), "kind": "typedef", "signature": f"typedef ... {m.group(1)}", "source": f"{filepath}", "doc_available": False, "probed": False})
        for m in re.finditer(r'struct\s+(\w+)\s*\{', content):
            result.append({"name": m.group(1), "kind": "struct", "signature": f"struct {m.group(1)}", "source": f"{filepath}", "doc_available": False, "probed": False})
    except Exception as e:
        return [{"name": "PARSE_ERROR", "kind": "error", "signature": str(e), "source": filepath, "doc_available": False, "probed": False}]
    return result
