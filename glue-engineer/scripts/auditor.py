#!/usr/bin/env python3
"""Backward-compatible stub: routes to polyglot auditor subcommand."""
import sys, os, warnings
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
warnings.warn("scripts/auditor.py is deprecated. Use: python -m polyglot audit <language> <name>", DeprecationWarning, stacklevel=2)

# Old: python scripts/auditor.py <url1> <url2> ...
# For now, just run the old logic but show message
print("[*] The new audit system uses: python -m polyglot audit <language> <package>")
print("[*] Example: python -m polyglot audit python requests")
print()
print("Running legacy parallel audit...")
from polyglot.router import main
sys.argv = [sys.argv[0]] + sys.argv[1:]
# Fallback: try old auditor.py logic
old_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "auditor.py")
if os.path.exists(old_path):
    exec(open(old_path).read())
else:
    print("Legacy auditor not found.")