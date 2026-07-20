# python -m polyglot
# ═══════════════════════════════════════════════════════════════════════
# Path-agnostic entry point.
# Resolves the glue-engineer directory from its own location, so it
# works from ANY working directory — no more cd <glue-engineer> needed.
# All .glue/ output goes to the user's project directory (CWD).
# ═══════════════════════════════════════════════════════════════════════
import sys, os

# Resolve the glue-engineer root (parent of polyglot/ package dir)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_skill_root = os.path.normpath(os.path.join(_script_dir, ".."))

# Add both to sys.path for import resolution
for p in [_skill_root, _script_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Also set PYTHONPATH env so subprocess calls (e.g. from subagents) work
os.environ.setdefault("PYTHONPATH", _skill_root)
_existing = os.environ.get("PYTHONPATH", "")
if _skill_root not in _existing.split(os.pathsep):
    os.environ["PYTHONPATH"] = _skill_root + os.pathsep + _existing

from polyglot.router import main
main()