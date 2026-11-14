"""polyglot/commands/glue.py — cross-search / cap-list / cap-match / bridge / strategies / mvp-scope."""

import json
import keyword
import sys
import ast


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
    p_bridge.add_argument(
        "--mappings",
        help="JSON file with a top-level mappings array; only reviewed mappings are generated",
    )
    p_bridge.add_argument(
        "--scaffold-only",
        action="store_true",
        help="Allow an empty mapping set and explicitly generate scaffold-only files",
    )
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
        GlueSchema, LibraryEndpoint, CapabilityAlignment, build_pair_id, now_iso,
    )
    from polyglot.glue.generators import generate_glue, get_generator_for_schema
    from polyglot.glue.strategy_selector import select_strategy
    from polyglot.glue.capability_ontology import get_registry
    from polyglot.glue.verifier import verify_package

    def fail(status, message, **details):
        result = {"status": status, "message": message, **details}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        raise SystemExit(2)

    def valid_identifier(value):
        return isinstance(value, str) and value.isidentifier() and not keyword.iskeyword(value)

    def valid_default_expression(value):
        if not isinstance(value, str):
            return False
        if not value:
            return True
        try:
            ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return False
        return True

    def load_reviewed_mappings(path):
        if not path:
            return []
        try:
            with open(path, "r", encoding="utf-8") as mapping_file:
                data = json.load(mapping_file)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read mappings JSON: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("mappings"), list):
            raise ValueError("Mappings file must contain a top-level 'mappings' array")

        reviewed = []
        ids = set()
        source_functions = set()
        mapping_fields = {
            "mapping_id", "src_function", "dst_function", "confidence",
            "confidence_label", "review_status", "review_note", "param_mappings",
            "return_transform", "error_map", "code_snippet",
        }
        param_fields = {"src_name", "dst_name", "transform", "src_default", "dst_default"}
        transform_fields = {"kind", "expr", "params"}
        for index, raw in enumerate(data["mappings"]):
            if not isinstance(raw, dict):
                raise ValueError(f"Mapping at index {index} must be an object")
            review_status = raw.get("review_status", "unreviewed")
            if review_status not in ("reviewed", "unreviewed", "rejected"):
                raise ValueError(f"Mapping at index {index} has invalid review_status: {review_status}")
            if review_status != "reviewed":
                continue

            unknown_fields = set(raw) - mapping_fields
            if unknown_fields:
                raise ValueError(
                    f"Reviewed mapping at index {index} has unsupported fields: "
                    f"{', '.join(sorted(unknown_fields))}"
                )
            mapping_id = raw.get("mapping_id")
            src_function = raw.get("src_function")
            dst_function = raw.get("dst_function")
            if not isinstance(mapping_id, str) or not mapping_id.strip():
                raise ValueError(f"Mapping at index {index} must have a non-empty mapping_id")
            if mapping_id in ids:
                raise ValueError(f"Duplicate mapping_id: {mapping_id}")
            ids.add(mapping_id)
            if not valid_identifier(src_function) or not valid_identifier(dst_function):
                raise ValueError(f"Mapping {mapping_id} must use valid Python function identifiers")
            if src_function in source_functions:
                raise ValueError(f"Multiple reviewed mappings define source function: {src_function}")
            source_functions.add(src_function)
            confidence = raw.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError(f"Mapping {mapping_id} confidence must be a number from 0 to 1")
            confidence_label = raw.get("confidence_label")
            if confidence_label not in ("identical", "similar"):
                raise ValueError(f"Reviewed mapping {mapping_id} must provide confidence_label 'identical' or 'similar'")
            if not isinstance(raw.get("review_note", ""), str):
                raise ValueError(f"Mapping {mapping_id} review_note must be a string")
            if not isinstance(raw.get("error_map", {}), dict):
                raise ValueError(f"Mapping {mapping_id} error_map must be an object")
            if not isinstance(raw.get("code_snippet", ""), str):
                raise ValueError(f"Mapping {mapping_id} code_snippet must be a string")
            param_mappings = raw.get("param_mappings", [])
            if not isinstance(param_mappings, list):
                raise ValueError(f"Mapping {mapping_id} param_mappings must be an array")
            source_params = set()
            destination_params = set()
            for param_index, param in enumerate(param_mappings):
                if not isinstance(param, dict):
                    raise ValueError(f"Mapping {mapping_id} parameter {param_index} must be an object")
                unknown_param_fields = set(param) - param_fields
                if unknown_param_fields:
                    raise ValueError(
                        f"Mapping {mapping_id} parameter {param_index} has unsupported fields: "
                        f"{', '.join(sorted(unknown_param_fields))}"
                    )
                if not valid_identifier(param.get("src_name")) or not valid_identifier(param.get("dst_name")):
                    raise ValueError(f"Mapping {mapping_id} parameters must use valid Python identifiers")
                if param["src_name"] in source_params or param["dst_name"] in destination_params:
                    raise ValueError(f"Mapping {mapping_id} contains duplicate parameter mappings")
                source_params.add(param["src_name"])
                destination_params.add(param["dst_name"])
                if not valid_default_expression(param.get("src_default", "")) or not valid_default_expression(param.get("dst_default", "")):
                    raise ValueError(f"Mapping {mapping_id} parameter defaults must be valid Python expressions")
                transform = param.get("transform")
                if transform is not None:
                    if not isinstance(transform, dict):
                        raise ValueError(f"Mapping {mapping_id} parameter transform must be an object or null")
                    unknown_transform_fields = set(transform) - transform_fields
                    if unknown_transform_fields:
                        raise ValueError(f"Mapping {mapping_id} parameter transform has unsupported fields")
                    if transform.get("kind", "identity") != "identity":
                        raise ValueError(f"Mapping {mapping_id} uses an unsupported parameter transform")
                    if not isinstance(transform.get("expr", ""), str) or not isinstance(transform.get("params", {}), dict):
                        raise ValueError(f"Mapping {mapping_id} parameter transform fields are invalid")
            return_transform = raw.get("return_transform")
            if return_transform is not None:
                if not isinstance(return_transform, dict):
                    raise ValueError(f"Mapping {mapping_id} return_transform must be an object or null")
                unknown_transform_fields = set(return_transform) - transform_fields
                if unknown_transform_fields:
                    raise ValueError(f"Mapping {mapping_id} return transform has unsupported fields")
                if return_transform.get("kind", "identity") != "identity":
                    raise ValueError(f"Mapping {mapping_id} uses an unsupported return transform")
                if not isinstance(return_transform.get("expr", ""), str) or not isinstance(return_transform.get("params", {}), dict):
                    raise ValueError(f"Mapping {mapping_id} return transform fields are invalid")
            reviewed.append(dict(raw))
        return reviewed

    try:
        mappings = load_reviewed_mappings(getattr(args, "mappings", None))
    except ValueError as exc:
        fail("input_invalid", str(exc), mappings_path=getattr(args, "mappings", None))

    scaffold_requested = bool(getattr(args, "scaffold_only", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if not mappings and not scaffold_requested and not dry_run:
        fail(
            "mappings_required",
            "No reviewed function mappings were provided. Use --mappings <json>; "
            "use --scaffold-only only when you explicitly want an unmapped scaffold.",
            mappings_count=0,
        )

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

    schema = GlueSchema(
        src=src,
        dst=dst,
        pair_id=pair_id,
        strategy=strategy,
        mappings=mappings,
        scaffold_only=scaffold_requested and not mappings,
        capability_alignment=alignment,
        generated_at=now_iso(),
    )

    if dry_run:
        print(json.dumps({
            "status": "mappings_required" if not mappings and not scaffold_requested else "dry_run",
            "schema": json.loads(schema.to_json()),
            "mappings_count": len(mappings),
            "scaffold_only": schema.scaffold_only,
        }, indent=2, ensure_ascii=False))
        return

    # Resolve and validate the selected generator before creating any output.
    try:
        generator = get_generator_for_schema(schema)
    except ValueError as exc:
        fail("unsupported_strategy", str(exc), strategy=strategy.mode)

    # Only the reviewed, identity-mapped Python import slice is executable today.
    if strategy.mode == "import" and mappings:
        src_language = src.language
        dst_language = dst.language
        if src_language != "python" or dst_language != "python":
            fail(
                "unsupported_strategy",
                "The import generator currently implements only Python-to-Python mappings.",
                strategy=strategy.mode,
            )
        for mapping in mappings:
            if any(param.get("dst_name") == "#MISSING" for param in mapping.get("param_mappings", [])):
                fail("mapping_unsupported", f"Mapping {mapping['mapping_id']} has an unmapped parameter")

    schema.scaffold_only = schema.scaffold_only or generator.get_metadata().implementation_status != "functional"

    # Generate code
    output_dir = args.output_dir or ".glue/search"
    package = generate_glue(schema, output_dir)

    output_summary = {
        "status": "scaffold_only" if schema.scaffold_only else "generated",
        "pair_id": pair_id,
        "strategy": strategy.mode,
        "files_generated": len(package.output_paths),
        "output_dir": output_dir,
        "alignment_score": alignment.overall_score,
        "mappings_count": len(mappings),
        "reviewed_mappings_count": len(mappings),
        "scaffold_only": schema.scaffold_only,
        "generator_status": generator.get_metadata().implementation_status,
    }

    # Run verification
    if not args.skip_verify:
        report = verify_package(package)
        output_summary["verification"] = report

    if getattr(args, "format", "json") == "json":
        print(json.dumps(output_summary, indent=2, ensure_ascii=False))
    else:
        print(f"[{output_summary['status']}] {pair_id} via {strategy.mode}")
        print(f"  Mappings: {len(mappings)} reviewed; files: {len(package.output_paths)}")
        print(f"  Output: {output_dir}/{pair_id}/")
        if "verification" in output_summary:
            from polyglot.glue.verifier import VerificationReport, VerificationLevel

            report_data = output_summary["verification"]
            levels = {
                name: VerificationLevel(name=name, **details)
                for name, details in report_data["levels"].items()
            }
            print(VerificationReport(
                package_id=report_data["package_id"],
                verified_at=report_data["verified_at"],
                levels=levels,
                overall=report_data["overall"],
                disclaimer=report_data["disclaimer"],
            ).summary())


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
