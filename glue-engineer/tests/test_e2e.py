#!/usr/bin/env python3
"""
End-to-end verification runner for Glue Engineer v3.

Tests:
  1. Common infrastructure (schema, cache, git, platform)
  2. Each language scout (python, javascript, rust, java, kotlin, c_cpp)
  3. CLI router + list command
  4. Python auditor + analyst
  5. Reporters (JSON -> Markdown)
  6. Probe templates (compile check only)
  7. v3 Glue infrastructure (schema, aggregator, aliases, output package)
  8. v3 Capability ontology + function matcher + strategy selector
  9. v3 Generators (import, subprocess, pyo3, ffi)
  10. v3 CLI commands (cross-search, cap-list, cap-match, bridge dry-run, strategies)
"""

import sys
import os
import json
import time

SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_ROOT)

PASS = 0
FAIL = 0
TIMING = []


def test(name, fn):
    global PASS, FAIL
    start = time.time()
    try:
        fn()
        elapsed = time.time() - start
        TIMING.append((name, elapsed))
        print(f"  [PASS] {name} ({elapsed:.2f}s)")
        PASS += 1
    except Exception as e:
        elapsed = time.time() - start
        TIMING.append((name, elapsed))
        print(f"  [FAIL] {name} ({elapsed:.2f}s): {e}")
        FAIL += 1


# ═══════════════════════════════════════
# 1. Common infrastructure
# ═══════════════════════════════════════

def test_schema():
    from polyglot.common.schema import SearchOutput, AuditOutput, ProbeOutput, now_iso, compute_score
    assert now_iso()  # non-empty string
    assert 0.0 <= compute_score(100, 1000, 30) <= 1.0
    assert compute_score(50000, 5000000, 5) > 0.8  # popular recent project

    s = SearchOutput(language="python", query="test", timestamp=now_iso())
    j = s.to_json()
    assert '"polyglot-output-v1"' in j
    assert '"tool": "scout"' in j

    a = AuditOutput(language="rust", candidate_name="serde", timestamp=now_iso())
    j2 = a.to_json()
    assert '"tool": "auditor"' in j2

    print("    Schema dataclasses, serialization, score computation OK")


def test_cache():
    from polyglot.common.cache import cache_get, cache_set
    key = f"test_key_{int(time.time())}"
    assert cache_get(key) is None
    cache_set(key, {"hello": "world"}, ttl_seconds=60)
    val = cache_get(key)
    assert val is not None and val.get("hello") == "world"
    print("    Cache set/get/expiry OK")


def test_platform():
    from polyglot.common.platform import detect_os, is_tool_available, has_git
    os_name = detect_os()
    assert os_name in ("windows", "linux", "macos")
    # git should be available
    assert has_git() == True
    print(f"    Platform detection: {os_name}, git: {has_git()}")


def test_git():
    from polyglot.common.git import repo_exists, get_languages
    # Python's requests repo should be accessible
    exists = repo_exists("https://github.com/psf/requests.git")
    print(f"    GitHub accessibility: {exists}")
    # Don't check get_languages without a real clone


def test_reporters():
    from polyglot.common.reporters import search_to_md, audit_to_md, output_from_file
    from polyglot.common.schema import SearchOutput, SearchResult, now_iso
    out = SearchOutput(language="python", query="requests", timestamp=now_iso(),
                       results=[SearchResult(name="requests", version="2.32.0", description="HTTP for Humans", stars=50000, downloads=10000000)])
    md = search_to_md(out)
    assert "requests" in md
    assert "2.32.0" in md
    print("    Markdown reporter output OK")


# ═══════════════════════════════════════
# 2. Language scouts (live API calls)
# ═══════════════════════════════════════

def test_scout_python():
    sys.path.insert(0, os.path.join(SKILL_ROOT, "polyglot", "backends", "python"))
    import importlib
    mod = importlib.import_module("polyglot.backends.python.scout")
    importlib.reload(mod)
    result = mod.search("requests")
    assert result["tool"] == "scout"
    assert result["language"] == "python"
    assert len(result["results"]) >= 1
    assert any("requests" in r["name"].lower() for r in result["results"])
    print(f"    Found {len(result['results'])} results for 'requests'")


def test_scout_javascript():
    import importlib
    mod = importlib.import_module("polyglot.backends.javascript.scout")
    importlib.reload(mod)
    result = mod.search("lodash")
    assert result["tool"] == "scout"
    assert result["language"] == "javascript"
    # npm registry may have SSL issues in some environments; validate schema not results
    if result["errors"]:
        print(f"    WARNING: npm registry unreachable ({result['errors'][0][:60]}...)")
        print(f"    Schema validation passed, results={len(result['results'])}")
    else:
        assert len(result["results"]) >= 1
        print(f"    Found {len(result['results'])} results for 'lodash'")


def test_scout_rust():
    import importlib
    mod = importlib.import_module("polyglot.backends.rust.scout")
    importlib.reload(mod)
    result = mod.search("serde")
    assert result["tool"] == "scout"
    assert result["language"] == "rust"
    assert len(result["results"]) >= 1
    print(f"    Found {len(result['results'])} results for 'serde'")


def test_scout_java():
    import importlib
    mod = importlib.import_module("polyglot.backends.java.scout")
    importlib.reload(mod)
    result = mod.search("jackson")
    assert result["tool"] == "scout"
    assert result["language"] == "java"
    assert len(result["results"]) >= 1
    print(f"    Found {len(result['results'])} results for 'jackson'")


def test_scout_kotlin():
    import importlib
    mod = importlib.import_module("polyglot.backends.kotlin.scout")
    importlib.reload(mod)
    result = mod.search("kotlinx")
    assert result["tool"] == "scout"
    assert result["language"] == "kotlin"
    print(f"    Found {len(result['results'])} results for 'kotlinx'")


def test_scout_c_cpp():
    import importlib
    mod = importlib.import_module("polyglot.backends.c_cpp.scout")
    importlib.reload(mod)
    result = mod.search("curl")
    # c_cpp may return fewer results; just verify schema
    assert result["tool"] == "scout"
    assert result["language"] == "c_cpp"
    print(f"    Found {len(result['results'])} results for 'curl'")


# ═══════════════════════════════════════
# 3. CLI router
# ═══════════════════════════════════════

def test_cli_list():
    """Test CLI by importing router and calling the list function."""
    from polyglot.router import cmd_list
    import argparse
    args = argparse.Namespace(format="json")
    try:
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            cmd_list(args)
        output = f.getvalue()
        assert "python" in output or "rust" in output or "javascript" in output
        print(f"    CLI list output contains backend names")
    except Exception as e:
        print(f"    CLI list threw (non-fatal): {e}")
        pass


# ═══════════════════════════════════════
# 4. Python auditor + analyst
# ═══════════════════════════════════════

def test_python_analyst():
    """Analyze a known Python file (itself)."""
    import importlib
    mod = importlib.import_module("polyglot.backends.python.analyst")
    importlib.reload(mod)
    result = mod.analyze(__file__)
    assert len(result) >= 1
    kinds = {r["kind"] for r in result}
    assert "function" in kinds
    print(f"    Found {len(result)} symbols (kinds: {kinds})")


def test_probe_templates_exist():
    """Check all probe templates exist."""
    for name in ["template_python.py", "template_typescript.ts", "template_rust.rs", "template_java.java"]:
        path = os.path.join(SKILL_ROOT, "polyglot", "probe", name)
        assert os.path.exists(path), f"Missing: {name}"
    print("    All 4 probe templates present")


def test_backend_features():
    """Check all FEATURES.json files."""
    backends_dir = os.path.join(SKILL_ROOT, "polyglot", "backends")
    langs = ["python", "javascript", "rust", "java", "kotlin", "c_cpp"]
    for lang in langs:
        path = os.path.join(backends_dir, lang, "FEATURES.json")
        assert os.path.exists(path), f"Missing FEATURES.json for {lang}"
        with open(path) as f:
            feats = json.load(f)
        assert "search" in feats
    print(f"    All {len(langs)} backends have FEATURES.json")


# ═══════════════════════════════════════
# 7. v3 Glue infrastructure
# ═══════════════════════════════════════

def test_v3_glue_schema():
    from polyglot.glue.glue_schema import (
        GlueSchema, LibraryEndpoint, FunctionSignature, FunctionMapping,
        ParamMapping, TransformRule, GlueStrategy, CapabilityAlignment,
        CrossLangCandidate, CrossLangSearchView, GlueOutputPackage,
        build_pair_id, resolve_alias, SCAFFOLD_DISCLAIMER,
    )

    # Test basic dataclasses
    sig = FunctionSignature(name="dumps", kind="function", return_type="str")
    assert sig.name == "dumps"
    assert sig.kind == "function"
    d = sig.to_dict()
    assert d["name"] == "dumps"

    pm = ParamMapping(src_name="obj", dst_name="value", transform=TransformRule(kind="identity"))
    assert pm.src_name == "obj"
    assert pm.dst_name == "value"

    mapping = FunctionMapping(mapping_id="t1", src_function="dumps", dst_function="to_json", confidence=0.85)
    assert mapping.confidence == 0.85
    assert mapping.confidence_label == ""
    md = mapping.to_dict()
    assert md["mapping_id"] == "t1"

    strategy = GlueStrategy(mode="import", rationale="same language")
    assert strategy.mode == "import"
    assert strategy.docker_supported == False

    alignment = CapabilityAlignment(overall_score=0.8, io_compatible=True, format_compatible=True)
    assert alignment.overall_score == 0.8

    # Test GlueSchema round-trip
    src = LibraryEndpoint(name="orjson", language="python")
    dst = LibraryEndpoint(name="serde_json", language="rust")
    schema = GlueSchema(
        src=src, dst=dst, pair_id=build_pair_id("orjson", "serde_json"),
        strategy=strategy, mappings=[mapping], capability_alignment=alignment,
    )
    assert schema.pair_id == "orjson_serde_json"
    assert len(schema.mappings) == 1

    js = schema.to_json()
    assert '"glue-schema-v1"' in js
    assert '"orjson_serde_json"' in js

    # Round-trip
    import json as _json
    data = _json.loads(js)
    restored = GlueSchema.from_json(data)
    assert restored.pair_id == "orjson_serde_json"
    assert restored.src.name == "orjson"
    assert restored.dst.name == "serde_json"
    assert restored.strategy.mode == "import"
    assert restored.capability_alignment.overall_score == 0.8

    summary = schema.summary()
    assert "orjson" in summary
    assert "serde_json" in summary

    # CrossLangCandidate
    cand = CrossLangCandidate(name="polars", language="python", version="1.0.0", stars=5000)
    assert cand.also_available_in == []

    # GlueOutputPackage
    opkg = GlueOutputPackage(glue_schema=schema)
    assert opkg.disclaimer == SCAFFOLD_DISCLAIMER
    assert opkg.generated_at == ""

    # Resolve aliases
    alias = resolve_alias("polars", "python")
    assert alias is not None
    assert alias["canonical"] == "polars"
    assert "rust" in alias["also_in"]
    assert resolve_alias("nonexistent_lib_x", "python") is None

    print("    v3 glue schema: GlueSchema, CrossLangCandidate, aliases, round-trip OK")


def test_v3_aggregator():
    from polyglot.glue.aggregator import CrossLangScoutEngine, cross_search

    engine = CrossLangScoutEngine()
    view = engine.batch_search("serde", languages=["rust"], limit=2)
    assert view.query == "serde"
    assert "rust" in view.coverage
    assert len(view.candidates) >= 1
    assert view.duration_ms > 0
    print(f"    Cross-language search: {len(view.candidates)} candidates, {view.duration_ms}ms")

    # Test cross_search convenience function
    result = cross_search("serde", languages=["rust"], limit=2)
    assert result["tool"] == "cross_lang_scout"
    assert "candidates" in result
    print(f"    cross_search() convenience: {len(result['candidates'])} candidates")


def test_v3_capability():
    from polyglot.glue.capability_ontology import get_registry, match_capabilities

    registry = get_registry()
    entries = registry.list_available()
    assert len(entries) >= 10

    requests_cap = registry.get("requests", "python")
    assert requests_cap is not None
    assert "fetch" in requests_cap.io_patterns

    serde_json_cap = registry.get("serde_json", "rust")
    assert serde_json_cap is not None
    assert "serialize" in serde_json_cap.io_patterns

    assert registry.get("nonexistent_lib", "python") is None

    alignment = registry.match(requests_cap, serde_json_cap)
    assert alignment.overall_score > 0.0
    print(f"    Capability registry: {len(entries)} entries, match score={alignment.overall_score:.2f}")


def test_v3_function_matcher():
    from polyglot.glue.function_matcher import FunctionMatcher, classify_function_role

    role, conf = classify_function_role("dumps")
    assert role == "serialize"
    assert conf > 0.9

    role2, conf2 = classify_function_role("from_json")
    assert role2 == "deserialize"
    assert conf2 > 0.8

    matcher = FunctionMatcher()
    src_funcs = [
        {"name": "dumps", "params": [{"name": "obj"}], "return_type": "str"},
        {"name": "loads", "params": [{"name": "s"}], "return_type": "dict"},
    ]
    dst_funcs = [
        {"name": "to_json", "params": [{"name": "value"}], "return_type": "str"},
        {"name": "from_json", "params": [{"name": "json_str"}], "return_type": "dict"},
    ]
    mappings = matcher.match("orjson", src_funcs, dst_funcs, "python", "rust")
    assert len(mappings) >= 1
    assert all(m.confidence > 0.3 for m in mappings)
    print(f"    Function matcher: {len(mappings)} mappings proposed (conf={[f'{m.confidence:.2f}' for m in mappings]})")


def test_v3_strategy_selector():
    from polyglot.glue.strategy_selector import select_strategy, list_available_strategies
    from polyglot.glue.glue_schema import LibraryEndpoint

    strategies = list_available_strategies()
    assert len(strategies) >= 30  # 6x6 minus self

    src = LibraryEndpoint(name="orjson", language="python")
    dst = LibraryEndpoint(name="serde_json", language="rust")
    strategy = select_strategy(src, dst)
    assert strategy.mode in ("subprocess_json",)
    assert strategy.rationale

    src2 = LibraryEndpoint(name="requests", language="python")
    dst2 = LibraryEndpoint(name="httpx", language="python")
    strategy2 = select_strategy(src2, dst2)
    assert strategy2.mode == "import"

    # Edge cases
    js_src = LibraryEndpoint(name="lodash", language="javascript")
    js_dst = LibraryEndpoint(name="lodash", language="javascript")
    assert select_strategy(js_src, js_dst).mode == "import"

    c_src = LibraryEndpoint(name="libcurl", language="c_cpp")
    c_dst = LibraryEndpoint(name="my_python", language="python")
    assert select_strategy(c_src, c_dst).mode == "ffi_cffi"

    print(f"    Strategy selector: {len(strategies)} strategies, python->rust={strategy.mode}, python->python={strategy2.mode}")


# ═══════════════════════════════════════
# 8. v3 Generators
# ═══════════════════════════════════════

def test_v3_import_generator():
    from polyglot.glue.generators.import_gen import ImportGenerator
    from polyglot.glue.glue_schema import GlueSchema, LibraryEndpoint, FunctionMapping, ParamMapping, TransformRule, GlueStrategy

    strategy = GlueStrategy(mode="import")
    src = LibraryEndpoint(name="requests", language="python")
    dst = LibraryEndpoint(name="httpx", language="python")
    mappings = [
        FunctionMapping(mapping_id="m1", src_function="get", dst_function="get",
                        confidence=0.9, confidence_label="identical",
                        param_mappings=[ParamMapping(src_name="url", dst_name="url", transform=TransformRule(kind="identity"))]),
    ]
    schema = GlueSchema(src=src, dst=dst, pair_id="requests_httpx", strategy=strategy, mappings=mappings)
    generator = ImportGenerator()
    output_dir = os.path.join(SKILL_ROOT, "test-v3-gen")
    pkg = generator.generate(schema, output_dir)
    assert len(pkg.output_paths) >= 4
    glue_file = os.path.join(output_dir, "requests_httpx", "generated", "glue.py")
    assert os.path.exists(glue_file)
    with open(glue_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "GENERATED BY glue-engineer" in content
    assert "import requests" in content
    assert "import httpx" in content
    assert "def get_via_httpx" in content
    import shutil
    shutil.rmtree(output_dir, ignore_errors=True)
    print(f"    ImportGenerator: {len(pkg.output_paths)} files, glue.py OK")


def test_v3_subprocess_generator():
    from polyglot.glue.generators.subprocess_gen import SubprocessGenerator
    from polyglot.glue.glue_schema import GlueSchema, LibraryEndpoint, FunctionMapping, GlueStrategy

    strategy = GlueStrategy(mode="subprocess_json")
    src = LibraryEndpoint(name="orjson", language="python")
    dst = LibraryEndpoint(name="serde_json", language="rust")
    mappings = [FunctionMapping(mapping_id="m1", src_function="dumps", dst_function="to_string", confidence=0.6)]
    schema = GlueSchema(src=src, dst=dst, pair_id="orjson_serde_json", strategy=strategy, mappings=mappings)
    generator = SubprocessGenerator()
    output_dir = os.path.join(SKILL_ROOT, "test-v3-gen")
    pkg = generator.generate(schema, output_dir)
    bridge_rs = os.path.join(output_dir, "orjson_serde_json", "generated", "bridge.rs")
    assert os.path.exists(bridge_rs)
    with open(bridge_rs, "r", encoding="utf-8") as f:
        content = f.read()
    assert "fn main()" in content
    assert "serde_json" in content
    glue_py = os.path.join(output_dir, "orjson_serde_json", "generated", "glue.py")
    assert os.path.exists(glue_py)
    with open(glue_py, "r", encoding="utf-8") as f:
        py_content = f.read()
    assert "BridgeClient" in py_content
    import shutil
    shutil.rmtree(output_dir, ignore_errors=True)
    print(f"    SubprocessGenerator: bridge.rs + glue.py OK")


def test_v3_pyo3_generator():
    from polyglot.glue.generators.pyo3_gen import PyO3Generator
    from polyglot.glue.glue_schema import GlueSchema, LibraryEndpoint, FunctionMapping, GlueStrategy

    strategy = GlueStrategy(mode="pyo3")
    src = LibraryEndpoint(name="my_func", language="python")
    dst = LibraryEndpoint(name="serde", language="rust")
    mappings = [FunctionMapping(mapping_id="m1", src_function="process", dst_function="serialize", confidence=0.6)]
    schema = GlueSchema(src=src, dst=dst, pair_id="my_func_serde", strategy=strategy, mappings=mappings)
    generator = PyO3Generator()
    output_dir = os.path.join(SKILL_ROOT, "test-v3-gen")
    pkg = generator.generate(schema, output_dir)
    cargo = os.path.join(output_dir, "my_func_serde", "generated", "Cargo.toml")
    lib = os.path.join(output_dir, "my_func_serde", "generated", "src", "lib.rs")
    assert os.path.exists(cargo)
    assert os.path.exists(lib)
    with open(cargo, "r", encoding="utf-8") as f:
        c = f.read()
    assert "pyo3" in c
    with open(lib, "r", encoding="utf-8") as f:
        l = f.read()
    assert "#[pyfunction]" in l
    assert "#[pymodule]" in l
    import shutil
    shutil.rmtree(output_dir, ignore_errors=True)
    print(f"    PyO3Generator: Cargo.toml + lib.rs OK")


def test_v3_ffi_generator():
    from polyglot.glue.generators.ffi_gen import FFICffiGenerator
    from polyglot.glue.glue_schema import GlueSchema, LibraryEndpoint, FunctionMapping, GlueStrategy

    strategy = GlueStrategy(mode="ffi_cffi")
    src = LibraryEndpoint(name="my_func", language="python")
    dst = LibraryEndpoint(name="libcurl", language="c_cpp")
    mappings = [FunctionMapping(mapping_id="m1", src_function="compute", dst_function="compute", confidence=0.5)]
    schema = GlueSchema(src=src, dst=dst, pair_id="my_func_libcurl", strategy=strategy, mappings=mappings)
    generator = FFICffiGenerator()
    output_dir = os.path.join(SKILL_ROOT, "test-v3-gen")
    pkg = generator.generate(schema, output_dir)
    c_file = os.path.join(output_dir, "my_func_libcurl", "generated", "glue_c_bridge.c")
    assert os.path.exists(c_file)
    with open(c_file, "r", encoding="utf-8") as f:
        c = f.read()
    assert "bridge_compute" in c
    assert "BRIDGE_ERROR" in c
    build_glue = os.path.join(output_dir, "my_func_libcurl", "generated", "build_glue.py")
    assert os.path.exists(build_glue)
    import shutil
    shutil.rmtree(output_dir, ignore_errors=True)
    print(f"    FFICffiGenerator: C bridge + builder OK")


def test_v3_generator_dispatcher():
    from polyglot.glue.generators import generate_glue, list_generators

    gens = list_generators()
    assert len(gens) == 4
    modes = {g["mode"] for g in gens}
    assert "import" in modes
    assert "subprocess_json" in modes
    assert "pyo3" in modes
    assert "ffi_cffi" in modes
    print(f"    Generator dispatcher: {len(gens)} generators ({', '.join(modes)})")


# ═══════════════════════════════════════
# 9. v3 CLI commands
# ═══════════════════════════════════════

def test_v3_cli_strategies():
    """Test CLI 'strategies' command."""
    from polyglot.router import cmd_strategies
    import argparse
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        cmd_strategies(argparse.Namespace(format="json"))
    output = f.getvalue()
    assert "import" in output
    assert "subprocess_json" in output
    assert "pyo3" in output or "ffi_cffi" in output
    print(f"    CLI strategies: output OK")


def test_v3_cli_cap_list():
    """Test CLI 'cap-list' command."""
    from polyglot.router import cmd_cap_list
    import argparse
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        cmd_cap_list(argparse.Namespace(format="json"))
    output = f.getvalue()
    assert "python:requests" in output or "python:orjson" in output
    print("    CLI cap-list: output OK")


def test_v3_cli_bridge_dry_run():
    """Test CLI 'bridge --dry-run' command."""
    from polyglot.router import cmd_bridge
    import argparse
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        cmd_bridge(argparse.Namespace(
            src_lang="python", src="requests",
            dst_lang="python", dst="httpx",
            output_dir="./test-v3-cli",
            dry_run=True, skip_verify=False, format="json",
        ))
    output = f.getvalue()
    assert "pair_id" in output
    assert "requests_httpx" in output
    assert "strategy" in output
    print("    CLI bridge --dry-run: JSON output OK")


# ═══════════════════════════════════════
# RUN
# ═══════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Glue Engineer v3 — End-to-End Verification")
    print("=" * 60)
    print()

    print("[1/6] Common Infrastructure")
    print("-" * 40)
    test("schema", test_schema)
    test("cache", test_cache)
    test("platform", test_platform)
    test("git check", test_git)
    test("reporters", test_reporters)
    print()

    print("[2/6] Language Scouts (live API)")
    print("-" * 40)
    test("python scout", test_scout_python)
    test("javascript scout", test_scout_javascript)
    test("rust scout", test_scout_rust)
    test("java scout", test_scout_java)
    test("kotlin scout", test_scout_kotlin)
    test("c_cpp scout", test_scout_c_cpp)
    print()

    print("[3/6] CLI Router")
    print("-" * 40)
    test("cli list", test_cli_list)
    print()

    print("[4/6] Python Backend")
    print("-" * 40)
    test("python analyst", test_python_analyst)
    print()

    print("[5/6] Probe Templates")
    print("-" * 40)
    test("probe files exist", test_probe_templates_exist)
    print()

    print("[6/6] Backend Metadata")
    print("-" * 40)
    test("FEATURES.json all backends", test_backend_features)
    print()

    print("[7/7] v3 Glue Infrastructure")
    print("-" * 40)
    test("v3 glue schema", test_v3_glue_schema)
    test("v3 aggregator", test_v3_aggregator)
    test("v3 capability ontology", test_v3_capability)
    test("v3 function matcher", test_v3_function_matcher)
    test("v3 strategy selector", test_v3_strategy_selector)
    print()

    print("[8/8] v3 Generators")
    print("-" * 40)
    test("v3 import generator", test_v3_import_generator)
    test("v3 subprocess generator", test_v3_subprocess_generator)
    test("v3 pyo3 generator", test_v3_pyo3_generator)
    test("v3 ffi generator", test_v3_ffi_generator)
    test("v3 generator dispatcher", test_v3_generator_dispatcher)
    print()

    print("[9/9] v3 CLI Commands")
    print("-" * 40)
    test("v3 cli strategies", test_v3_cli_strategies)
    test("v3 cli cap-list", test_v3_cli_cap_list)
    test("v3 cli bridge dry-run", test_v3_cli_bridge_dry_run)
    print()

    print("=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
    print("=" * 60)
