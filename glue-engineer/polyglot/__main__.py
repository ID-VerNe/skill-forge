# python -m polyglot
import sys, os
# Add both skill root (for polyglot package) and polyglot/ itself (for common/) to path
_skill_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_polyglot_dir = os.path.dirname(__file__)
for p in [_skill_root, _polyglot_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)
from polyglot.router import main
main()