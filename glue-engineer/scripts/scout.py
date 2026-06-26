#!/usr/bin/env python3
"""Backward-compatible stub: routes to polyglot router."""
import sys, os, warnings
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from polyglot.router import main
warnings.warn("scripts/scout.py is deprecated. Use: python -m polyglot scout <lang> <keyword>", DeprecationWarning, stacklevel=2)
sys.argv = [sys.argv[0], "scout"] + [a for a in sys.argv[1:]]
main()