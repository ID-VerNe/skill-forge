"""Rust analyst — regex-based pub symbol extraction."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def analyze(filepath: str) -> list:
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        for m in re.finditer(r'pub\s+(?:unsafe\s+)?fn\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^{]+))?', content):
            sig = f"pub fn {m.group(1)}({m.group(2).strip()})" + (f" -> {m.group(3).strip()}" if m.group(3) else "")
            result.append({"name": m.group(1), "kind": "function", "signature": sig.strip(), "source": f"{filepath}", "doc_available": False, "probed": False})

        for m in re.finditer(r'pub\s+(?:struct|enum)\s+(\w+)\s*({|[;])', content):
            result.append({"name": m.group(1), "kind": "struct" if 'struct' in m.group(0) else "enum", "signature": m.group(0).split('{')[0].strip() + ";", "source": f"{filepath}", "doc_available": False, "probed": False})

        for m in re.finditer(r'pub\s+trait\s+(\w+)\s*(?::{)?', content):
            result.append({"name": m.group(1), "kind": "trait", "signature": f"pub trait {m.group(1)}", "source": f"{filepath}", "doc_available": False, "probed": False})

    except Exception as e:
        return [{"name": "PARSE_ERROR", "kind": "error", "signature": str(e), "source": filepath, "doc_available": False, "probed": False}]
    return result