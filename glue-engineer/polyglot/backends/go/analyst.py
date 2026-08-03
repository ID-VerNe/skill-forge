"""
polyglot/backends/go/analyst.py — Go source code analyst backend.

Parses a single Go source file and extracts exported symbols
(functions, types, structs, interfaces, constants, variables)
using regex-based analysis.
"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def analyze(filepath: str) -> list:
    """Analyze a Go source file and return a list of ExportSymbol-like dicts."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except FileNotFoundError:
        return [{"error": f"File not found: {filepath}"}]
    except Exception as e:
        return [{"error": f"Read error: {e}"}]

    filename = os.path.basename(filepath)
    exports = []
    lines = source.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            i += 1
            continue

        # Exported function
        func_match = re.match(r"^func\s+([A-Z]\w*)\s*\(", stripped)
        if func_match:
            exports.append({
                "name": func_match.group(1),
                "kind": "function",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported method on a type
        method_match = re.match(r"^func\s+\([^)]+\)\s+([A-Z]\w*)\s*\(", stripped)
        if method_match:
            exports.append({
                "name": method_match.group(1),
                "kind": "method",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported type
        type_match = re.match(r"^type\s+([A-Z]\w*)\s+", stripped)
        if type_match:
            kind = "type"
            if "interface" in stripped:
                kind = "interface"
            elif "struct" in stripped:
                kind = "struct"
            exports.append({
                "name": type_match.group(1),
                "kind": kind,
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported const
        const_match = re.match(r"^const\s+([A-Z]\w*)\s*=", stripped)
        if const_match:
            exports.append({
                "name": const_match.group(1),
                "kind": "constant",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        # Exported var
        var_match = re.match(r"^var\s+([A-Z]\w*)\s*=", stripped)
        if var_match:
            exports.append({
                "name": var_match.group(1),
                "kind": "variable",
                "signature": stripped,
                "source": f"{filename}:{i + 1}",
                "doc_available": _has_doc_comment(lines, i),
                "probed": False,
            })
            i += 1
            continue

        i += 1

    return exports


def _has_doc_comment(lines: list, idx: int) -> bool:
    """Check if the preceding lines contain a doc comment."""
    if idx > 0:
        prev = lines[idx - 1].strip()
        if prev.startswith("//"):
            return True
        # Check for multi-line doc comment
        if prev.startswith("/*"):
            return True
    return False


# ── Minimal smoke test ──
if __name__ == "__main__":
    import tempfile
    sample = '''package main

import "fmt"

// Hello greets the world.
func Hello() string {
    return "Hello, world"
}

type Greeter struct {
    Name string
}

type Stringer interface {
    String() string
}

func (g *Greeter) Greet() string {
    return "Hello, " + g.Name
}

const MaxRetries = 3

var DefaultGreeter = &Greeter{Name: "World"}
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
        f.write(sample)
        tmp = f.name
    result = analyze(tmp)
    print(f"Found {len(result)} symbols:")
    for r in result:
        print(f"  {r['kind']}: {r['name']} ({r['signature'][:50]})")
    os.unlink(tmp)