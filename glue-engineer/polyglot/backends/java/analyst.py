"""Java analyst — regex-based method/class extraction."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def analyze(filepath: str) -> list:
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Class/interface declarations
        for m in re.finditer(r'(?:public\s+)?(?:abstract\s+)?(?:final\s+)?(?:class|interface|enum|@interface)\s+(\w+)', content):
            kind = "class"
            if "interface" in m.group(0): kind = "interface"
            elif "enum" in m.group(0): kind = "enum"
            result.append({"name": m.group(1), "kind": kind, "signature": m.group(0).strip(), "source": f"{filepath}", "doc_available": False, "probed": False})

        # Method declarations
        for m in re.finditer(r'(?:public|protected|private|static|final|abstract|synchronized|native)\s+(?:static\s+)?(?:final\s+)?(?:abstract\s+)?(?:[\w<>\[\],\s]+)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w,\s]+)?\s*(?:\{|;)', content):
            result.append({"name": m.group(1), "kind": "method", "signature": m.group(0).strip()[:80], "source": f"{filepath}", "doc_available": False, "probed": False})

        # Field declarations
        for m in re.finditer(r'(?:public|protected|private|static|final)\s+(?:static\s+)?(?:final\s+)?([\w<>[\]]+)\s+(\w+)\s*(?:=|\s*;)', content):
            if m.group(2)[0].isupper() and len(m.group(2)) > 1:
                result.append({"name": m.group(2), "kind": "field", "signature": f"{m.group(1)} {m.group(2)}", "source": f"{filepath}", "doc_available": False, "probed": False})

    except Exception as e:
        return [{"name": "PARSE_ERROR", "kind": "error", "signature": str(e), "source": filepath, "doc_available": False, "probed": False}]
    return result
