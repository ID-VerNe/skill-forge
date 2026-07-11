"""polyglot/router.py — CLI dispatcher for polyglot tools."""

import argparse
import json
import sys
import os
import time

# ═══════════════════════════════════════════════════════════════════
# v2-style backends (for scout / audit / analyze commands)
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
}


def resolve_language(lang: str) -> str:
    return LANGUAGES.get(lang, lang)


def import_backend(language: str, tool: str):
    """Dynamically import a backend module."""
    path = os.path.join(BACKENDS_DIR, language, f"{tool}.py")
    if not os.path.exists(path):
        raise ImportError(f"No {tool} backend for '{language}' (expected {path})")
    import importlib.util
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


# ═══════════════════════════════════════════════════════════════
# v3: Cross-language search + glue code generation
# ═══════════════════════════════════════════════════════════════

def cmd_cross_search(args):
    """Search across multiple ecosystems simultaneously."""
    from polyglot.glue.aggregator import CrossLangScoutEngine
    engine = CrossLangScoutEngine()
    languages = args.languages.split(",") if args.languages else None
    view = engine.batch_search(args.keyword, languages=languages, limit=args.limit)
    if args.format == "json":
        print(json.dumps({
            "tool": "cross_lang_scout",
            "query": view.query,
            "languages": view.targets,
            "coverage": view.coverage,
            "duration_ms": view.duration_ms,
            "candidates": [
                {"name": c.name, "language": c.language, "version": c.version,
                 "description": c.description[:100], "stars": c.stars, "score": c.score}
                for c in view.candidates
            ],
        }, indent=2, ensure_ascii=False))
    else:
        print(f"[v] Cross-language search for '{view.query}':")
        for lang, count in view.coverage.items():
            print(f"  [{lang}] {count} candidates")
        for c in view.candidates[:10]:
            print(f"  - {c.name} ({c.language}@{c.version}) — {c.description[:80]}")
        if view.errors:
            for lang, err in view.errors.items():
                print(f"  [!] {lang} error: {err[:60]}")


def cmd_cap_list(args):
    """List registered capability entries."""
    from polyglot.glue.capability_ontology import get_registry
    registry = get_registry()
    entries = registry.list_available()
    if args.format == "json":
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    else:
        print(f"Capability registry ({len(entries)} entries):")
        for e in entries:
            print(f"  {e['key']}: {', '.join(e['io_patterns'])}")


def cmd_cap_match(args):
    """Match capabilities between two libraries."""
    from polyglot.glue.capability_ontology import get_registry
    registry = get_registry()
    src_cap = registry.get(args.src, args.src_lang)
    dst_cap = registry.get(args.dst, args.dst_lang)
    if not src_cap:
        print(f"[x] No capability entry for {args.src_lang}:{args.src}", file=sys.stderr)
        sys.exit(1)
    if not dst_cap:
        print(f"[x] No capability entry for {args.dst_lang}:{args.dst}", file=sys.stderr)
        sys.exit(1)
    alignment = registry.match(src_cap, dst_cap)
    if args.format == "json":
        print(json.dumps(alignment.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"[v] Capability match: {args.src_lang}:{args.src} <-> {args.dst_lang}:{args.dst}")
        print(f"  Overall score: {alignment.overall_score:.2f}")
        print(f"  IO compatible: {alignment.io_compatible}")
        print(f"  Format compatible: {alignment.format_compatible}")
        print(f"  Error model compatible: {alignment.error_model_compatible}")
        print(f"  Runtime compatible: {alignment.runtime_compatible}")
        if alignment.warnings:
            for w in alignment.warnings:
                print(f"  [!] {w}")


def cmd_bridge(args):
    """Generate glue code between two libraries."""
    from polyglot.glue.glue_schema import (
        GlueSchema, LibraryEndpoint, FunctionMapping, ParamMapping,
        TransformRule, GlueStrategy, CapabilityAlignment, build_pair_id, now_iso,
    )
    from polyglot.glue.generators import generate_glue
    from polyglot.glue.strategy_selector import select_strategy
    from polyglot.glue.capability_ontology import get_registry
    from polyglot.glue.function_matcher import FunctionMatcher
    from polyglot.glue.verifier import verify_package

    # Build library endpoints
    src = LibraryEndpoint(name=args.src, language=args.src_lang, role="source")
    dst = LibraryEndpoint(name=args.dst, language=args.dst_lang, role="sink")
    pair_id = build_pair_id(args.src, args.dst)

    # Check capability ontology
    registry = get_registry()
    src_cap = registry.get(args.src, args.src_lang)
    dst_cap = registry.get(args.dst, args.dst_lang)
    if src_cap:
        src.capability = src_cap
    if dst_cap:
        dst.capability = dst_cap

    # Compute capability alignment
    alignment = CapabilityAlignment()
    if src_cap and dst_cap:
        alignment = registry.match(src_cap, dst_cap)

    # Select strategy
    strategy = select_strategy(src, dst, alignment)

    # Create empty mappings (user can augment with --mapping flags later)
    mappings = []

    schema = GlueSchema(
        src=src,
        dst=dst,
        pair_id=pair_id,
        strategy=strategy,
        mappings=mappings,
        capability_alignment=alignment,
        generated_at=now_iso(),
    )

    if args.dry_run:
        print(json.dumps(json.loads(schema.to_json()), indent=2, ensure_ascii=False))
        return

    # Generate code
    output_dir = args.output_dir or ".glue/search"
    package = generate_glue(schema, output_dir)

    output_summary = {
        "pair_id": pair_id,
        "strategy": strategy.mode,
        "files_generated": len(package.output_paths),
        "output_dir": output_dir,
        "alignment_score": alignment.overall_score,
    }
    print(json.dumps(output_summary, indent=2, ensure_ascii=False))
    print(f"\n[v] Generated {len(package.output_paths)} files in {output_dir}/{pair_id}/")

    # Run verification
    if not args.skip_verify:
        print(f"\n[*] Running verification...")
        report = verify_package(package)
        if args.format == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            from polyglot.glue.verifier import VerificationReport
            vr = VerificationReport(**report)
            print(vr.summary())


def cmd_mvp_scope(args):
    """Scope features into P0/P1/P2 tiers."""
    from polyglot.glue.mvp_scoper import MvpScoper

    scoper = MvpScoper(project=args.project)

    # Parse features from CLI: --feature name,category or from stdin
    decisions = []
    for feature_str in args.features:
        parts = feature_str.split(",", 1)
        name = parts[0].strip()
        cat = parts[1].strip() if len(parts) > 1 else "core"
        d = scoper.classify_item(name, cat, manual_tier=args.manual_tier)
        decisions.append(d)

    report = scoper.generate_report(decisions)
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.summary())


def cmd_strategies(args):
    """List available bridge strategies."""
    from polyglot.glue.strategy_selector import list_available_strategies
    strategies = list_available_strategies()
    if args.format == "json":
        print(json.dumps(strategies, indent=2, ensure_ascii=False))
    else:
        print("Available bridge strategies:")
        for s in strategies:
            print(f"  {s['from']:15s} -> {s['to']:15s}  [{s['mode']:15s}]  tools={s['tools']}")


# ═══════════════════════════════════════════════════════════════
# v4: Deep Mode — workspace init
# ═══════════════════════════════════════════════════════════════

def cmd_deep_init(args):
    """Create deep analysis workspace with cloned repos."""
    from polyglot.deep.outputs import create_workspace, create_session, add_repo_to_session, repo_dir
    from polyglot.deep.repo_resolver import url_to_slug, resolve_repo_url, clone_repo

    workspace = os.path.abspath(args.dir)
    create_workspace(workspace)

    session = create_session(
        workspace,
        project=args.project,
        requirements=args.requirements,
        target_license=args.target_license or "",
    )

    for url in args.repos:
        slug = url_to_slug(url)
        rd = repo_dir(workspace, slug)
        src = os.path.join(rd, "source")

        print(f"[v] Cloning {url} → {src}")
        result = clone_repo(resolve_repo_url(url), src)

        if result["success"]:
            add_repo_to_session(
                workspace, session,
                name=slug, url=url, slug=slug,
                local_path=src, commit=result["commit"],
            )
            print(f"    commit: {result['commit'][:12]}")
        else:
            print(f"    [!] Clone failed: {result['error'][:120]}")
            # Still add to session but with empty commit
            add_repo_to_session(
                workspace, session,
                name=slug, url=url, slug=slug,
                local_path=src, commit="",
            )

    print(f"\n[v] Workspace ready: {workspace}")
    print(f"    {len(session['candidate_repos'])} repos, {len(session['requirements'])} requirements")


def cmd_deep_pack(args):
    """Generate task prompt files for subagents."""
    from polyglot.deep.packager import generate_tasks
    workspace = os.path.abspath(args.dir)
    tasks = generate_tasks(workspace)
    if not tasks:
        print("[!] No tasks generated — check session.json has candidate_repos")
        return
    for slug, path in tasks:
        print(f"[v] {slug}: {path}")


def cmd_deep_validate(args):
    """Validate subagent architecture outputs."""
    from polyglot.deep.validator import main as validate_main
    workspace = os.path.abspath(args.dir)
    exit_code = validate_main(workspace, include_reuse_map=args.include_reuse_map)
    sys.exit(exit_code)


def cmd_deep_compare(args):
    """Structured comparison of multiple repo architecture reports."""
    from polyglot.deep.comparer import main as compare_main
    workspace = os.path.abspath(args.dir)
    exit_code = compare_main(workspace)
    sys.exit(exit_code)


def cmd_deep_summarize(args):
    """Generate final report draft from architecture reports."""
    from polyglot.deep.summarizer import main as summarize_main
    workspace = os.path.abspath(args.dir)
    exit_code = summarize_main(workspace)
    sys.exit(exit_code)


def cmd_deep_clean(args):
    """Clean cloned repos but keep reports."""
    import shutil
    from polyglot.deep.outputs import load_session, repo_dir

    workspace = os.path.abspath(args.dir)

    # Confirm before destructive action
    if not getattr(args, "force", False):
        print(f"[!] This will remove cloned source files from: {workspace}")
        print(f"    Architecture reports and JSON artifacts will be preserved.")
        try:
            confirm = input("    Continue? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print("[v] Cancelled.")
                return 0
        except EOFError:
            # Non-interactive mode — skip confirm
            pass

    session = load_session(workspace)

    if not session:
        # No session.json — try cleaning repos/ directory directly
        repos_dir = os.path.join(workspace, "repos")
        if os.path.exists(repos_dir):
            removed = 0
            for entry in os.listdir(repos_dir):
                src = os.path.join(repos_dir, entry, "source")
                if os.path.exists(src):
                    shutil.rmtree(src, ignore_errors=True)
                    removed += 1
                    print(f"[v] Removed source: {entry}")
            if removed == 0:
                print("[!] No source directories found under repos/")
            else:
                print(f"\n[v] Cleaned {removed} repo source directories")
        else:
            print("[x] No session.json and no repos/ directory found — nothing to clean")
        return

    removed = 0
    for repo in session.get("candidate_repos", []):
        slug = repo["slug"]
        src = os.path.join(repo_dir(workspace, slug), "source")
        if os.path.exists(src):
            shutil.rmtree(src, ignore_errors=True)
            removed += 1
            print(f"[v] Removed source: {slug}")

    print(f"\n[v] Cleaned {removed} repo source directories")
    if args.all:
        logs_dir = os.path.join(workspace, "logs")
        if os.path.exists(logs_dir):
            shutil.rmtree(logs_dir, ignore_errors=True)
            print("[v] Removed logs/")
        tasks_dir = os.path.join(workspace, "tasks")
        if os.path.exists(tasks_dir):
            shutil.rmtree(tasks_dir, ignore_errors=True)
            print("[v] Removed tasks/")


def main():
    parser = argparse.ArgumentParser(description="polyglot — multi-language glue engineer toolkit", add_help=True)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sub = parser.add_subparsers(dest="command")

    # v2 commands
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

    # v3 commands
    p_cross = sub.add_parser("cross-search", help="Search across multiple ecosystems")
    p_cross.add_argument("keyword", help="Search query")
    p_cross.add_argument("--languages", default="", help="Comma-separated (python,javascript,rust)")
    p_cross.add_argument("--limit", type=int, default=5)
    p_cross.add_argument("--format", choices=["json", "markdown"], default="markdown")

    p_cap = sub.add_parser("cap-list", help="List capability ontology entries")
    p_cap.add_argument("--format", choices=["json", "markdown"], default="markdown")

    p_cap_match = sub.add_parser("cap-match", help="Match capabilities between two libraries")
    p_cap_match.add_argument("src_lang", help="Source language")
    p_cap_match.add_argument("src", help="Source library name")
    p_cap_match.add_argument("dst_lang", help="Destination language")
    p_cap_match.add_argument("dst", help="Destination library name")
    p_cap_match.add_argument("--format", choices=["json", "markdown"], default="markdown")

    p_bridge = sub.add_parser("bridge", help="Generate glue code between two libraries")
    p_bridge.add_argument("src_lang")
    p_bridge.add_argument("src")
    p_bridge.add_argument("dst_lang")
    p_bridge.add_argument("dst")
    p_bridge.add_argument("--output-dir", default=".glue/search")
    p_bridge.add_argument("--dry-run", action="store_true", help="Print schema without generating")
    p_bridge.add_argument("--skip-verify", action="store_true", help="Skip verification step")
    p_bridge.add_argument("--format", choices=["json", "markdown"], default="json")

    p_strat = sub.add_parser("strategies", help="List available bridge strategies")
    p_strat.add_argument("--format", choices=["json", "markdown"], default="markdown")

    p_scope = sub.add_parser("mvp-scope", help="Scope features into P0/P1/P2 tiers")
    p_scope.add_argument("project", help="Project name")
    p_scope.add_argument("--features", nargs="+", default=[],
                        help="Features to scope, format: 'name,category' (e.g. 'PDF import,import')")
    p_scope.add_argument("--manual-tier", default="",
                        choices=["P0", "P1", "P2", ""],
                        help="Force a specific tier for all features")
    p_scope.add_argument("--format", choices=["json", "markdown"], default="markdown")

    # v4: Deep Mode commands
    p_deep_init = sub.add_parser("deep-init", help="Create deep analysis workspace")
    p_deep_init.add_argument("--dir", default=".glue/deep",
                            help="Workspace directory (default: .glue/deep)")
    p_deep_init.add_argument("--project", required=True, help="Project name")
    p_deep_init.add_argument("--requirements", nargs="+", default=[],
                            help="Structured requirement descriptions")
    p_deep_init.add_argument("--target-license", default="", help="Target license")
    p_deep_init.add_argument("repos", nargs="+", help="Repository URLs to analyze")

    p_deep_pack = sub.add_parser("deep-pack", help="Generate subagent task prompts")
    p_deep_pack.add_argument("dir", default=".glue/deep", nargs="?",
                            help="Workspace directory (default: .glue/deep)")

    p_deep_val = sub.add_parser("deep-validate", help="Validate subagent architecture outputs")
    p_deep_val.add_argument("dir", default=".glue/deep", nargs="?",
                           help="Workspace directory (default: .glue/deep)")
    p_deep_val.add_argument("--include-reuse-map", action="store_true",
                           help="Also validate reuse-map artifacts (Phase 3)")

    p_deep_comp = sub.add_parser("deep-compare", help="Compare multiple repo architecture reports")
    p_deep_comp.add_argument("dir", default=".glue/deep", nargs="?",
                            help="Workspace directory (default: .glue/deep)")

    p_deep_summ = sub.add_parser("deep-summarize", help="Generate final report draft")
    p_deep_summ.add_argument("dir", default=".glue/deep", nargs="?",
                            help="Workspace directory (default: .glue/deep)")

    p_deep_clean = sub.add_parser("deep-clean", help="Clean cloned repos but keep reports")
    p_deep_clean.add_argument("dir", default=".glue/deep", nargs="?",
                             help="Workspace directory (default: .glue/deep)")
    p_deep_clean.add_argument("--all", action="store_true",
                             help="Also clean logs/ and tasks/")
    p_deep_clean.add_argument("--force", "-f", action="store_true",
                             help="Skip confirmation prompt")

    args = parser.parse_args()

    if args.command == "scout":
        cmd_scout(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "cross-search":
        cmd_cross_search(args)
    elif args.command == "cap-list":
        cmd_cap_list(args)
    elif args.command == "cap-match":
        cmd_cap_match(args)
    elif args.command == "bridge":
        cmd_bridge(args)
    elif args.command == "strategies":
        cmd_strategies(args)
    elif args.command == "mvp-scope":
        cmd_mvp_scope(args)
    elif args.command == "deep-init":
        cmd_deep_init(args)
    elif args.command == "deep-pack":
        cmd_deep_pack(args)
    elif args.command == "deep-validate":
        cmd_deep_validate(args)
    elif args.command == "deep-compare":
        cmd_deep_compare(args)
    elif args.command == "deep-summarize":
        cmd_deep_summarize(args)
    elif args.command == "deep-clean":
        cmd_deep_clean(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()