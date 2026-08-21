"""polyglot/commands/scout.py — scout / audit / analyze / list commands."""

import json
import os
import sys

from polyglot.router import resolve_language, import_backend, BACKENDS_DIR, _dict_to_obj


def add_args(sub):
    """Register scout-group subparsers."""
    p_scout = sub.add_parser("scout", help="Search for packages (single language)")
    p_scout.add_argument("language")
    p_scout.add_argument("keyword")
    p_scout.add_argument("--limit", type=int, default=5)
    p_scout.add_argument("--format", choices=["json", "markdown"], default="json")

    p_audit = sub.add_parser("audit", help="Audit a package")
    p_audit.add_argument("language")
    p_audit.add_argument("name")
    p_audit.add_argument("--version", default="")
    p_audit.add_argument("--format", choices=["json", "markdown"], default="json")

    p_analyze = sub.add_parser("analyze", help="Analyze source file")
    p_analyze.add_argument("language")
    p_analyze.add_argument("path")

    p_list = sub.add_parser("list", help="List available backends")
    p_list.add_argument("--format", choices=["json", "markdown"], default="markdown")


def cmd_scout(args):
    lang = resolve_language(args.language)
    try:
        mod = import_backend(lang, "scout")
        result = mod.search(args.keyword, limit=args.limit)
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            from common.reporters import search_to_md
            out = _dict_to_obj(result)
            print(search_to_md(out))
    except ImportError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


def cmd_audit(args):
    lang = resolve_language(args.language)
    try:
        mod = import_backend(lang, "auditor")
        result = mod.audit(args.name, args.version or "")
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            from common.reporters import audit_to_md
            out = _dict_to_obj(result)
            print(audit_to_md(out))
    except ImportError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


def cmd_analyze(args):
    lang = resolve_language(args.language)
    try:
        mod = import_backend(lang, "analyst")
        result = mod.analyze(args.path)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except ImportError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args):
    """List available backends and their capabilities."""
    available = []
    for lang in sorted(os.listdir(BACKENDS_DIR)):
        feat_path = os.path.join(BACKENDS_DIR, lang, "FEATURES.json")
        if os.path.exists(feat_path):
            with open(feat_path) as f:
                feats = json.load(f)
            available.append({"language": lang, **feats})
    if args.format == "json":
        print(json.dumps(available, indent=2, ensure_ascii=False))
    else:
        print("Available backends:")
        for a in available:
            caps = [k for k, v in a.items() if v is True and k != "language"]
            print(f"  {a['language']}: {', '.join(caps)}")