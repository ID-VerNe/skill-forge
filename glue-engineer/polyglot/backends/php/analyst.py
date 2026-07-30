"""PHP analyst — regex-based symbol extraction from PHP source files."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def analyze(filepath: str) -> list:
    """Analyze a PHP file and return extracted symbols."""
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Namespace
        ns_match = re.search(r'namespace\s+([\w\\\\]+)\s*;', content)
        namespace = ns_match.group(1) if ns_match else ""

        # Classes (abstract, final, or plain)
        for m in re.finditer(
            r'(?:abstract\s+|final\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?',
            content,
        ):
            fqcn = f"{namespace}\\{m.group(1)}" if namespace else m.group(1)
            result.append({
                "name": fqcn,
                "kind": "class",
                "signature": f"class {m.group(1)}",
                "source": f"{filepath}",
                "doc_available": bool(re.search(r'/\*\*.*?' + re.escape(m.group(1)), content, re.DOTALL)),
                "probed": False,
            })

        # Interfaces
        for m in re.finditer(r'interface\s+(\w+)(?:\s+extends\s+([\w,\s]+))?', content):
            fqcn = f"{namespace}\\{m.group(1)}" if namespace else m.group(1)
            result.append({
                "name": fqcn,
                "kind": "interface",
                "signature": f"interface {m.group(1)}",
                "source": f"{filepath}",
                "doc_available": bool(re.search(r'/\*\*.*?' + re.escape(m.group(1)), content, re.DOTALL)),
                "probed": False,
            })

        # Traits
        for m in re.finditer(r'trait\s+(\w+)', content):
            fqcn = f"{namespace}\\{m.group(1)}" if namespace else m.group(1)
            result.append({
                "name": fqcn,
                "kind": "trait",
                "signature": f"trait {m.group(1)}",
                "source": f"{filepath}",
                "doc_available": False,
                "probed": False,
            })

        # Functions (top-level only, not methods inside classes)
        # Strip class/trait/interface bodies first to avoid picking up methods
        stripped = re.sub(r'(?:abstract\s+|final\s+)?(?:class|trait|interface)\s+\w+.*?\{.*?\}(?=\s*$|\s*\n)', '', content, flags=re.DOTALL)
        # Also strip closure functions
        for m in re.finditer(r'^\s*function\s+(\w+)\s*\(', stripped, re.MULTILINE):
            result.append({
                "name": m.group(1),
                "kind": "function",
                "signature": f"function {m.group(1)}(...)",
                "source": f"{filepath}",
                "doc_available": False,
                "probed": False,
            })

        # Constants (define)
        for m in re.finditer(r'define\s*\(\s*[\'"]([\w_]+)[\'"]\s*,', content):
            result.append({
                "name": m.group(1),
                "kind": "constant",
                "signature": f"define('{m.group(1)}', ...)",
                "source": f"{filepath}",
                "doc_available": False,
                "probed": False,
            })

        # Class constants
        for m in re.finditer(r'const\s+(\w+)\s*=', content):
            result.append({
                "name": m.group(1),
                "kind": "class_constant",
                "signature": f"const {m.group(1)} =",
                "source": f"{filepath}",
                "doc_available": False,
                "probed": False,
            })

        # Enums (PHP 8.1+)
        for m in re.finditer(r'enum\s+(\w+)(?:\s*:\s*(\w+))?(?:\s+implements\s+([\w,\s]+))?', content):
            fqcn = f"{namespace}\\{m.group(1)}" if namespace else m.group(1)
            result.append({
                "name": fqcn,
                "kind": "enum",
                "signature": f"enum {m.group(1)}",
                "source": f"{filepath}",
                "doc_available": False,
                "probed": False,
            })

    except Exception as e:
        return [{
            "name": "PARSE_ERROR",
            "kind": "error",
            "signature": str(e),
            "source": filepath,
            "doc_available": False,
            "probed": False,
        }]

    return result