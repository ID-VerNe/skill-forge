"""
polyglot/glue/capability_ontology.py — Library capability registry + matching.

Provides a structured, machine-readable description per library that enables
real functional matching (unlike FEATURES.json which only describes tooling ops).


Bootstrapping strategy (per synthesis plan):
1. Manual tags for top ~20 most-requested libraries per ecosystem
2. LLM-assisted extraction (preview only — not for automated matching)
3. Community contributions via PR-reviewed capability descriptions
4. Usage-based refinement when users verify generated glue
"""

import json
import os
from typing import Optional

from polyglot.glue.glue_schema import (
    LibraryCapability,
    CapabilityAlignment,
)


# ═══════════════════════════════════════════════════════════════════
# Starter capability registry (manually curated top libraries)
# ═══════════════════════════════════════════════════════════════════

STARTER_REGISTRY = {
    # ── Python: HTTP ──
    "python:requests": LibraryCapability(
        library="requests", language="python", version="2.32.0",
        io_patterns=["fetch", "send"],
        data_formats_in=["url", "params", "headers"],
        data_formats_out=["http_response", "bytes", "text"],
        data_shape_constraints={"timeout_support": True, "streaming": True},
        protocol=["http", "https"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "ConnectionError", "kind": "recoverable"},
                          {"name": "Timeout", "kind": "recoverable"},
                          {"name": "HTTPError", "kind": "recoverable"}],
        concurrency_model={"thread_safe": True, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
        license="Apache-2.0",
    ),
    "python:httpx": LibraryCapability(
        library="httpx", language="python", version="0.27.0",
        io_patterns=["fetch", "send"],
        data_formats_in=["url", "params", "headers"],
        data_formats_out=["http_response", "bytes", "text", "json"],
        data_shape_constraints={"timeout_support": True, "streaming": True},
        protocol=["http", "https", "http2"],
        runtime_reqs={"async": True, "sync": True, "threadsafe": True},
        error_categories=[{"name": "RequestError", "kind": "recoverable"},
                          {"name": "TimeoutException", "kind": "recoverable"},
                          {"name": "HTTPStatusError", "kind": "recoverable"}],
        concurrency_model={"thread_safe": True, "async_compatible": True},
        lifecycle={"init_required": False, "close_required": False},
        license="BSD-3-Clause",
    ),

    # ── Python: Serialization ──
    "python:orjson": LibraryCapability(
        library="orjson", language="python", version="3.10.15",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["python_object"],
        data_formats_out=["json_bytes"],
        data_shape_constraints={"nan_support": "none", "infinity_support": "none",
                                "none_handling": "null", "max_depth": 512},
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "JSONEncodeError", "kind": "fatal", "recovery": "catch_exception"},
                          {"name": "JSONDecodeError", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": True, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
        license="Apache-2.0",
    ),
    "python:json": LibraryCapability(
        library="json", language="python", version="stdlib",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["python_object"],
        data_formats_out=["json_str"],
        data_shape_constraints={"nan_support": "converts_to_null", "infinity_support": "converts_to_null",
                                "none_handling": "null", "max_depth": "default_recursive"},
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "ValueError", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": True, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
        license="PSF",
    ),

    # ── Rust: Serialization ──
    "rust:serde": LibraryCapability(
        library="serde", language="rust", version="1.0.0",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["rust_struct"],
        data_formats_out=["serialized_bytes"],
        data_shape_constraints={"derive_macro": True, "custom_deserialize": True},
        protocol=["derive_macro", "custom_impl"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "Error", "kind": "fatal", "recovery": "propagate"}],
        concurrency_model={"thread_safe": True, "async_compatible": True},
        lifecycle={"init_required": False, "close_required": False},
        license="Apache-2.0",
    ),
    "rust:serde_json": LibraryCapability(
        library="serde_json", language="rust", version="1.0.0",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["rust_struct", "json_bytes"],
        data_formats_out=["json_bytes", "json_str"],
        data_shape_constraints={"nan_support": "none", "infinity_support": "none"},
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "Error", "kind": "fatal", "recovery": "propagate"}],
        concurrency_model={"thread_safe": True, "async_compatible": True},
        lifecycle={"init_required": False, "close_required": False},
        license="Apache-2.0",
    ),

    # ── Rust: HTTP ──
    "rust:reqwest": LibraryCapability(
        library="reqwest", language="rust", version="0.12.0",
        io_patterns=["fetch", "send"],
        data_formats_in=["url", "headers"],
        data_formats_out=["http_response", "bytes", "text"],
        protocol=["http", "https"],
        runtime_reqs={"async": True, "sync": True, "threadsafe": True},
        error_categories=[{"name": "Error", "kind": "recoverable"}],
        concurrency_model={"thread_safe": True, "async_compatible": True},
        lifecycle={"init_required": False, "close_required": False},
        license="Apache-2.0",
    ),

    # ── JavaScript: HTTP ──
    "javascript:axios": LibraryCapability(
        library="axios", language="javascript", version="1.7.0",
        io_patterns=["fetch", "send"],
        data_formats_in=["url", "params", "headers"],
        data_formats_out=["http_response", "json", "text"],
        protocol=["http", "https"],
        runtime_reqs={"async": True, "sync": False, "threadsafe": True},
        error_categories=[{"name": "AxiosError", "kind": "recoverable"}],
        concurrency_model={"thread_safe": True, "async_compatible": True},
        lifecycle={"init_required": False, "close_required": False},
        license="MIT",
    ),
    "javascript:lodash": LibraryCapability(
        library="lodash", language="javascript", version="4.17.21",
        io_patterns=["transform", "query"],
        data_formats_in=["array", "object", "collection"],
        data_formats_out=["array", "object", "value"],
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[],
        concurrency_model={"thread_safe": True, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
        license="MIT",
    ),

    # ── Java: Serialization ──
    "java:jackson": LibraryCapability(
        library="jackson", language="java", version="2.17.0",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["java_object", "json_bytes", "json_str"],
        data_formats_out=["json_bytes", "json_str", "java_object"],
        data_shape_constraints={"annotations": True, "custom_serializer": True},
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "JsonProcessingException", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": True, "async_compatible": False},
        lifecycle={"init_required": True, "close_required": False, "global_init": False},
        license="Apache-2.0",
    ),
    "java:gson": LibraryCapability(
        library="gson", language="java", version="2.11.0",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["java_object", "json_str"],
        data_formats_out=["json_str", "java_object"],
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "JsonSyntaxException", "kind": "fatal", "recovery": "catch_exception"},
                          {"name": "JsonIOException", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": False, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
        license="Apache-2.0",
    ),

    # ── Kotlin: Serialization ──
    "kotlin:kotlinx-serialization": LibraryCapability(
        library="kotlinx-serialization", language="kotlin", version="1.7.0",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["kotlin_object", "json_str"],
        data_formats_out=["json_str", "kotlin_object"],
        data_shape_constraints={"compile_time_plugin": True, "annotation_driven": True},
        protocol=["compiler_plugin", "native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "SerializationException", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": True, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
        license="Apache-2.0",
    ),

    # ── C/C++: Serialization ──
    "c_cpp:nlohmann-json": LibraryCapability(
        library="nlohmann-json", language="c_cpp", version="3.11.0",
        io_patterns=["serialize", "deserialize"],
        data_formats_in=["cpp_object", "json_str"],
        data_formats_out=["json_str", "cpp_object"],
        data_shape_constraints={"header_only": True, "cxx11_required": True},
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": False},
        error_categories=[{"name": "parse_error", "kind": "fatal", "recovery": "catch_exception"},
                          {"name": "type_error", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": False, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
    ),

    # ── Python: Data processing ──
    "python:pandas": LibraryCapability(
        library="pandas", language="python", version="2.2.0",
        io_patterns=["read", "write", "transform", "aggregate"],
        data_formats_in=["csv", "json", "parquet", "excel", "sql", "dataframe"],
        data_formats_out=["csv", "json", "parquet", "excel", "sql", "dataframe"],
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": False},
        error_categories=[{"name": "ValueError", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": False, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
    ),
    "python:polars": LibraryCapability(
        library="polars", language="python", version="1.0.0",
        io_patterns=["read", "write", "transform", "aggregate"],
        data_formats_in=["csv", "json", "parquet", "dataframe"],
        data_formats_out=["csv", "json", "parquet", "dataframe"],
        protocol=["native_api"],
        runtime_reqs={"async": False, "sync": True, "threadsafe": True},
        error_categories=[{"name": "ComputeError", "kind": "fatal", "recovery": "catch_exception"},
                          {"name": "SchemaError", "kind": "fatal", "recovery": "catch_exception"}],
        concurrency_model={"thread_safe": True, "async_compatible": False},
        lifecycle={"init_required": False, "close_required": False},
    ),
}


class CapabilityRegistry:
    """Registry of library capabilities.

    Provides lookup and matching. Loads from built-in STARTER_REGISTRY
    and can merge additional entries from disk.
    """

    def __init__(self):
        self._entries: dict[str, LibraryCapability] = {}
        self._load_starter()

    def _load_starter(self):
        for key, cap in STARTER_REGISTRY.items():
            self._entries[key] = cap

    def get(self, library: str, language: str) -> Optional[LibraryCapability]:
        """Look up a library's capability by name and language."""
        key = f"{language}:{library}"
        return self._entries.get(key)

    def register(self, cap: LibraryCapability):
        """Register or update a capability entry."""
        key = f"{cap.language}:{cap.library}"
        self._entries[key] = cap

    def save_to_file(self, path: str):
        """Persist registry to JSON file."""
        data = {}
        for key, cap in self._entries.items():
            data[key] = cap.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_from_file(self, path: str):
        """Load additional entries from a JSON file."""
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, d in data.items():
            self._entries[key] = LibraryCapability(**d)

    def list_available(self) -> list[dict]:
        """List all registered libraries (for CLI display)."""
        result = []
        for key, cap in sorted(self._entries.items()):
            result.append({
                "key": key,
                "library": cap.library,
                "language": cap.language,
                "io_patterns": cap.io_patterns,
                "license": cap.license,
            })
        return result

    def match(self, src_cap: LibraryCapability, dst_cap: LibraryCapability) -> CapabilityAlignment:
        """Compute compatibility alignment between two library capabilities."""
        return match_capabilities(src_cap, dst_cap)


# ═══════════════════════════════════════════════════════════════════
# Capability matching logic
# ═══════════════════════════════════════════════════════════════════

WEIGHTS = {
    "io_patterns": 0.25,
    "data_formats": 0.25,
    "error_model": 0.15,
    "data_shape": 0.15,
    "runtime_reqs": 0.10,
    "license": 0.10,
}

# SPDX license compatibility matrix
# 0.0 = incompatible, 0.5 = conditional, 1.0 = fully compatible
LICENSE_COMPAT = {
    "MIT": {"MIT": 1.0, "Apache-2.0": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
            "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "Apache-2.0": {"Apache-2.0": 1.0, "MIT": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
                   "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "GPL-3.0": {"GPL-3.0": 1.0, "GPL-2.0": 1.0, "MIT": 0.5, "Apache-2.0": 0.5, "BSD-2-Clause": 0.5, "BSD-3-Clause": 0.5,
                "LGPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 0.5},
    "GPL-2.0": {"GPL-2.0": 1.0, "GPL-3.0": 1.0, "MIT": 0.5, "Apache-2.0": 0.5, "BSD-2-Clause": 0.5, "BSD-3-Clause": 0.5,
                "LGPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 0.5},
    "LGPL-3.0": {"LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "MIT": 1.0, "Apache-2.0": 1.0,
                 "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "BSD-3-Clause": {"BSD-3-Clause": 1.0, "BSD-2-Clause": 1.0, "MIT": 1.0, "Apache-2.0": 1.0,
                     "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "BSD-2-Clause": {"BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0, "MIT": 1.0, "Apache-2.0": 1.0,
                     "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "CC0-1.0": {"CC0-1.0": 1.0, "MIT": 1.0, "Apache-2.0": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
               "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "Unlicense": {"Unlicense": 1.0, "MIT": 1.0, "Apache-2.0": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
                  "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "": 1.0},
    "": {"": 1.0, "MIT": 0.5, "Apache-2.0": 0.5, "BSD-2-Clause": 0.5, "BSD-3-Clause": 0.5,
         "LGPL-3.0": 0.5, "GPL-2.0": 0.5, "GPL-3.0": 0.5, "CC0-1.0": 0.5, "Unlicense": 0.5},
}


def match_capabilities(src: LibraryCapability, dst: LibraryCapability) -> CapabilityAlignment:
    """Compute compatibility alignment between two library capabilities.

    Score = weighted intersection of compatible fields:
    - io_patterns: 0.25 weight
    - data_formats_out -> data_formats_in match: 0.25 weight
    - error_model compatibility: 0.15 weight
    - data_shape_constraints compatibility: 0.15 weight
    - runtime_reqs compatibility: 0.10 weight
    - license_compatibility: 0.10 weight
    """
    alignment = CapabilityAlignment()
    warnings = []

    # ── IO patterns ──
    src_io = set(src.io_patterns)
    dst_io = set(dst.io_patterns)
    io_intersection = src_io & dst_io
    io_union = src_io | dst_io
    io_score = len(io_intersection) / max(len(io_union), 1)
    alignment.io_compatible = io_score >= 0.5
    if not alignment.io_compatible and io_union:
        warnings.append(f"No matching I/O pattern: src={src.io_patterns}, dst={dst.io_patterns}")

    # ── Data formats (out -> in) ──
    src_out = set(src.data_formats_out)
    dst_in = set(dst.data_formats_in)
    format_matches = src_out & dst_in
    format_score = len(format_matches) / max(len(src_out), 1) if src_out else 0.5
    alignment.format_compatible = format_score >= 0.3
    if not alignment.format_compatible and src_out:
        warnings.append(f"Data format mismatch: src outputs {src_out}, dst accepts {dst_in}")

    # ── Error model compatibility ──
    src_errs = {e.get("name", "") if isinstance(e, dict) else str(e) for e in src.error_categories}
    dst_errs = {e.get("name", "") if isinstance(e, dict) else str(e) for e in dst.error_categories}
    err_shared = src_errs & dst_errs
    err_score = len(err_shared) / max(max(len(src_errs), len(dst_errs)), 1)
    alignment.error_model_compatible = err_score >= 0.3 or (not src_errs and not dst_errs)
    if not alignment.error_model_compatible:
        warnings.append("Error model mismatch: incompatible error handling patterns")

    # ── Data shape constraints ──
    shape_score = _compare_shape_constraints(
        src.data_shape_constraints,
        dst.data_shape_constraints,
    )
    alignment.shape_compatible = shape_score >= 0.5
    if not alignment.shape_compatible:
        warnings.append("Data shape constraints differ (nan/infinity handling, etc.)")

    # ── Runtime requirements ──
    runtime_score = _compare_runtime(src.runtime_reqs, dst.runtime_reqs)
    alignment.runtime_compatible = runtime_score >= 0.5
    if not alignment.runtime_compatible:
        warnings.append("Runtime requirements differ (async/sync/threadsafe mismatch)")

    # ── License compatibility ──
    license_compat = LICENSE_COMPAT.get(src.license, {}).get(dst.license, 0.3)
    license_score = license_compat
    if license_score < 0.5:
        warnings.append(f"License mismatch: src={src.license}, dst={dst.license} (score={license_score})")

    # ── Overall score ──
    alignment.overall_score = (
        WEIGHTS["io_patterns"] * io_score +
        WEIGHTS["data_formats"] * format_score +
        WEIGHTS["error_model"] * err_score +
        WEIGHTS["data_shape"] * shape_score +
        WEIGHTS["runtime_reqs"] * runtime_score +
        WEIGHTS["license"] * license_score
    )
    alignment.warnings = warnings
    return alignment


def _compare_shape_constraints(src: dict, dst: dict) -> float:
    """Compare data shape constraints between two capabilities. Returns 0.0-1.0."""
    if not src and not dst:
        return 1.0
    if not src or not dst:
        return 0.3

    total_keys = set(src.keys()) | set(dst.keys())
    if not total_keys:
        return 1.0

    matches = 0
    for key in total_keys:
        s_val = src.get(key)
        d_val = dst.get(key)
        if s_val == d_val:
            matches += 1
        elif s_val is None or d_val is None:
            matches += 0.3  # partial credit

    return matches / len(total_keys)


def _compare_runtime(src: dict, dst: dict) -> float:
    """Compare runtime requirements. Returns 0.0-1.0."""
    if not src and not dst:
        return 1.0
    if not src or not dst:
        return 0.5

    # Check key compatibility fields
    score = 1.0
    penalties = 0

    src_async = src.get("async", False)
    dst_async = dst.get("async", False)
    if src_async and not dst_async:
        penalties += 0.5

    src_st = src.get("threadsafe", True)
    dst_st = dst.get("threadsafe", True)
    if not src_st and dst_st:
        penalties += 0.2
    if src_st and not dst_st:
        penalties += 0.2

    return max(0.0, score - penalties)


# ───── Convenience ─────

def get_registry() -> CapabilityRegistry:
    """Get the global capability registry (singleton)."""
    return CapabilityRegistry()
