"""Python AST analyst — enhanced signature extraction."""
import sys, os, ast
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def analyze(filepath: str) -> list:
    """Analyze a Python file. Returns list of ExportSymbol-like dicts."""
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = []
                for a in node.args.args:
                    ann = ast.unparse(a.annotation) if a.annotation else ""
                    args.append(f"{a.arg}: {ann}" if ann else a.arg)
                sig = f"def {node.name}({', '.join(args)})"
                if node.returns:
                    sig += f" -> {ast.unparse(node.returns)}"
                result.append({"name": node.name, "kind": "function", "signature": sig, "source": f"{filepath}:{node.lineno}", "doc_available": bool(ast.get_docstring(node)), "probed": False})
            elif isinstance(node, ast.AsyncFunctionDef):
                args = [a.arg for a in node.args.args]
                result.append({"name": node.name, "kind": "async_function", "signature": f"async def {node.name}({', '.join(args)})", "source": f"{filepath}:{node.lineno}", "doc_available": bool(ast.get_docstring(node)), "probed": False})
            elif isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b) for b in node.bases]
                base_str = f"({', '.join(bases)})" if bases else ""
                result.append({"name": node.name, "kind": "class", "signature": f"class {node.name}{base_str}", "source": f"{filepath}:{node.lineno}", "doc_available": bool(ast.get_docstring(node)), "probed": False})
    except SyntaxError as e:
        return [{"name": f"PARSE_ERROR", "kind": "error", "signature": str(e), "source": filepath, "doc_available": False, "probed": False}]
    return result