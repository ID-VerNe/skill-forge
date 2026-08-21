"""polyglot/router.py — CLI dispatcher for polyglot tools.

Thin dispatcher: holds the language registry, backend loader, and shared
helpers.  Command handler logic lives in polyglot/commands/.
"""

import argparse
import importlib.util
import json
import os
import sys

# ═══════════════════════════════════════════════════════════════════
# Path bootstrap (so `python -m polyglot` works from any CWD)
# ═══════════════════════════════════════════════════════════════════

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # skill root
# Also add polyglot/ subdir for common/ module access when not run via -m
_poly_dir = os.path.dirname(__file__)
if _poly_dir not in sys.path and os.path.isdir(_poly_dir):
    sys.path.insert(0, _poly_dir)

BACKENDS_DIR = os.path.join(os.path.dirname(__file__), "backends")

LANGUAGES = {
    "python": "python",
    "py": "python",
    "pypi": "python",
    "javascript": "javascript",
    "js": "javascript",
    "node": "javascript",
    "npm": "javascript",
    "rust": "rust",
    "rs": "rust",
    "crates": "rust",
    "java": "java",
    "kotlin": "kotlin",
    "kt": "kotlin",
    "c": "c_cpp",
    "cpp": "c_cpp",
    "c_cpp": "c_cpp",
    "vcpkg": "c_cpp",
    "php": "php",
    "composer": "php",
    "packagist": "php",
    "go": "go",
    "golang": "go",
    "golang.org": "go",
    "pkg.go.dev": "go",
}


def resolve_language(lang: str) -> str:
    return LANGUAGES.get(lang, lang)


def import_backend(language: str, tool: str):
    """Dynamically import a backend module."""
    path = os.path.join(BACKENDS_DIR, language, f"{tool}.py")
    if not os.path.exists(path):
        raise ImportError(f"No {tool} backend for '{language}' (expected {path})")
    spec = importlib.util.spec_from_file_location(f"{language}.{tool}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dict_to_obj(d):
    """Convert a nested dict to a simple object with attribute access."""
    if isinstance(d, dict):
        o = type("Obj", (), {})()
        for k, v in d.items():
            setattr(o, k, _dict_to_obj(v))
        return o
    elif isinstance(d, list):
        return [_dict_to_obj(i) for i in d]
    return d


# ═══════════════════════════════════════════════════════════════════
# Dispatch
# ═══════════════════════════════════════════════════════════════════

# command name -> (handler_module, function_name)
_DISPATCH = {
    # scout group
    "scout":       ("polyglot.commands.scout", "cmd_scout"),
    "audit":       ("polyglot.commands.scout", "cmd_audit"),
    "analyze":     ("polyglot.commands.scout", "cmd_analyze"),
    "list":        ("polyglot.commands.scout", "cmd_list"),
    # glue group
    "cross-search":("polyglot.commands.glue",  "cmd_cross_search"),
    "cap-list":    ("polyglot.commands.glue",  "cmd_cap_list"),
    "cap-match":   ("polyglot.commands.glue",  "cmd_cap_match"),
    "bridge":      ("polyglot.commands.glue",  "cmd_bridge"),
    "strategies":  ("polyglot.commands.glue",  "cmd_strategies"),
    "mvp-scope":   ("polyglot.commands.glue",  "cmd_mvp_scope"),
    # discover group
    "discover":    ("polyglot.commands.discover", "cmd_discover"),
    # deep group
    "deep-init":     ("polyglot.commands.deep", "cmd_deep_init"),
    "deep-pack":     ("polyglot.commands.deep", "cmd_deep_pack"),
    "deep-validate": ("polyglot.commands.deep", "cmd_deep_validate"),
    "deep-compare":   ("polyglot.commands.deep", "cmd_deep_compare"),
    "deep-summarize": ("polyglot.commands.deep", "cmd_deep_summarize"),
    "deep-clean":     ("polyglot.commands.deep", "cmd_deep_clean"),
}


def _build_parser():
    """Build the argparse parser and register all subcommands."""
    parser = argparse.ArgumentParser(
        description="polyglot — multi-language glue engineer toolkit", add_help=True)
    sub = parser.add_subparsers(dest="command")

    from polyglot.commands import scout, glue, discover, deep
    scout.add_args(sub)
    glue.add_args(sub)
    discover.add_args(sub)
    deep.add_args(sub)

    return parser


def main():
    parser = _build_parser()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    entry = _DISPATCH.get(args.command)
    if entry is None:
        parser.print_help()
        return

    # Lazy import: only load the command module actually being invoked.
    module_name, func_name = entry
    module = __import__(module_name, fromlist=[func_name])
    handler = getattr(module, func_name)
    handler(args)


if __name__ == "__main__":
    main()