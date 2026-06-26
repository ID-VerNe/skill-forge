#!/usr/bin/env python3
"""Backward-compatible stub: routes to polyglot analyze subcommand."""
import sys, os, warnings
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
warnings.warn("scripts/analyst.py is deprecated. Use: python -m polyglot analyze <language> <path>", DeprecationWarning, stacklevel=2)

if len(sys.argv) < 2:
    print("Usage: python scripts/analyst.py <file_path>")
    sys.exit(1)

filepath = sys.argv[1]

# Detect language from extension
ext = os.path.splitext(filepath)[1].lower()
lang_map = {".py": "python", ".js": "javascript", ".ts": "javascript", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin"}
lang = lang_map.get(ext, "python")

from polyglot.router import main
sys.argv = ["polyglot", "analyze", lang, filepath]
main()