"""polyglot/commands/glue.py — cross-search / cap-list / cap-match / bridge / strategies / mvp-scope."""

import json


def add_args(sub):
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