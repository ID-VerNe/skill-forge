"""
polyglot/glue/glue_schema.py — Interface contract schema for v3 glue code generation.

Every phase of the v3 pipeline reads/writes this schema. Every piece of data
in it has a known confidence level — nothing is silently assumed.
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import time


# ═══════════════════════════════════════════════════════════════════
# 1. Foundational types
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Parameter:
    """A single function parameter."""
    name: str
    type_hint: str = ""
    default_value: str = ""
    required: bool = True


@dataclass
class FunctionSignature:
    """A single function or method signature from any language.

    Populated by Phase 2 (auditor/analyst). The `probed` flag means
    this was verified at runtime, not just extracted from source.
    """
    name: str
    kind: str = "function"          # "function" | "method" | "class" | "async_function"
    params: list = field(default_factory=list)   # list[dict] or list[Parameter]
    return_type: str = ""
    doc: str = ""
    probed: bool = False
    source_location: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "params": [p if isinstance(p, dict) else {"name": p.name, "type_hint": p.type_hint, "default_value": p.default_value, "required": p.required} for p in self.params],
            "return_type": self.return_type,
            "doc": self.doc,
            "probed": self.probed,
            "source_location": self.source_location,
        }

    @staticmethod
    def from_dict(d: dict) -> "FunctionSignature":
        return FunctionSignature(**d)


@dataclass
class TransformRule:
    """Describes how to transform a value from source to destination format."""
    kind: str = "identity"          # "identity" | "rename" | "type_cast" | "unwrap" | "composite"
    expr: str = ""                   # code expression for the transform
    params: dict = field(default_factory=dict)


@dataclass
class ParamMapping:
    """Maps one source parameter to one destination parameter."""
    src_name: str
    dst_name: str
    transform: Optional[TransformRule] = None
    src_default: str = ""
    dst_default: str = ""


@dataclass
class FunctionMapping:
    """One logical mapping: how to convert src.func -> dst.func call.

    CRITICAL: confidence is per-mapping, not per-package.
    High-confidence get() and low-confidence save() coexist in the
    same GlueSchema — the user only reviews low-confidence ones.
    """
    mapping_id: str
    src_function: str
    dst_function: str
    confidence: float = 0.0          # 0.0-1.0 — honest score
    confidence_label: str = ""       # "identical" | "similar" | "cross_lang_guess"

    param_mappings: list = field(default_factory=list)  # list[ParamMapping] or list[dict]
    return_transform: Optional[TransformRule] = None

    error_map: dict = field(default_factory=dict)        # {"src.exception": "dst.exception"}
    code_snippet: str = ""                               # generated glue function body

    review_status: str = "unreviewed"                    # "unreviewed" | "reviewed" | "rejected"
    review_note: str = ""

    def to_dict(self) -> dict:
        return {
            "mapping_id": self.mapping_id,
            "src_function": self.src_function,
            "dst_function": self.dst_function,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "param_mappings": [p if isinstance(p, dict) else {
                "src_name": p.src_name, "dst_name": p.dst_name,
                "transform": {"kind": p.transform.kind, "expr": p.transform.expr} if p.transform else None,
                "src_default": p.src_default, "dst_default": p.dst_default,
            } for p in self.param_mappings],
            "return_transform": {"kind": self.return_transform.kind, "expr": self.return_transform.expr} if self.return_transform else None,
            "error_map": self.error_map,
            "code_snippet": self.code_snippet,
            "review_status": self.review_status,
            "review_note": self.review_note,
        }


# ═══════════════════════════════════════════════════════════════════
# 1b. Failure state machine
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StatusMachine:
    """Failure-aware state machine for multi-step pipelines.

    Tracks the status of each step in a multi-phase pipeline (e.g. PDF import,
    LLM extraction, code generation). Supports 8+ states for granular error
    tracking.

    States:
      pending              → initial, not started
      queued               → waiting in queue
      in_progress          → actively processing
      retrying             → automatic retry after transient failure
      succeeded            → completed successfully
      failed               → permanent failure
      failed_partial       → partial success with some errors
      cancelled            → user-/system-cancelled
      needs_review         → completed but requires human review
      skipped              → dependency failed, step skipped

    Transitions (directed graph):
      pending → queued → in_progress → succeeded (normal happy path)
      in_progress → failed (permanent error)
      in_progress → retrying → in_progress (transient error, retry)
      in_progress → failed_partial (partial success)
      in_progress → cancelled (user interrupt)
      pending → skipped (upstream failure)
      succeeded → needs_review (low confidence threshold)
      any → cancelled (user/system override)
    """
    step_name: str = ""
    status: str = "pending"
    attempts: int = 0
    max_retries: int = 3
    error_message: str = ""
    error_code: str = ""          # e.g. "CONVERSION_FAILED", "LLM_TIMEOUT"
    error_detail: str = ""        # JSON string for structured error data
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0

    VALID_TRANSITIONS = {
        "pending":     ["queued", "skipped", "cancelled"],
        "queued":      ["in_progress", "cancelled"],
        "in_progress": ["succeeded", "failed", "failed_partial", "retrying", "cancelled"],
        "retrying":    ["in_progress", "failed", "cancelled"],
        "succeeded":   ["needs_review"],
        "failed":      ["retrying"],    # manual retry
        "failed_partial": ["retrying", "needs_review"],
        "cancelled":   [],
        "needs_review":["succeeded", "failed"],
        "skipped":     [],
    }

    def can_transition_to(self, new_status: str) -> bool:
        """Check if a transition to new_status is valid."""
        if self.status == new_status:
            return True  # idempotent
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        return new_status in allowed

    def transition(self, new_status: str, error: str = "", error_code: str = "") -> bool:
        """Attempt a state transition. Returns True if successful."""
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Invalid transition: {self.status} -> {new_status} "
                f"(step: {self.step_name})"
            )
        self.status = new_status
        if error:
            self.error_message = error
        if error_code:
            self.error_code = error_code
        if new_status == "retrying":
            self.attempts += 1
        return True

    @property
    def is_terminal(self) -> bool:
        """Check if the step has reached a terminal state."""
        return self.status in ("succeeded", "failed", "cancelled", "skipped")

    @property
    def is_error(self) -> bool:
        """Check if the step is in an error state."""
        return self.status in ("failed", "failed_partial")

    @property
    def can_retry(self) -> bool:
        """Check if retry is possible (attempts < max_retries)."""
        return self.attempts < self.max_retries and self.is_error

    def to_dict(self) -> dict:
        return {
            "step_name": self.step_name,
            "status": self.status,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
        }


# ═══════════════════════════════════════════════════════════════════
# 2. Cross-language search types
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CrossLangCandidate:
    """A search result from one backend, tagged with language and metadata."""
    name: str
    language: str
    version: str = ""
    description: str = ""
    registry_url: str = ""
    repo_url: str = ""
    stars: int = 0
    downloads: int = 0
    score: float = 0.0              # 0.0-1.0 per-ecosystem quality score
    also_available_in: list = field(default_factory=list)  # ["python", "rust"] if cross-lang project


@dataclass
class CrossLangSearchView:
    """Unified cross-ecosystem search result.

    This is what the user sees after a batch search completes.
    All results from all queried backends, deduplicated and ranked.
    """
    query: str = ""
    targets: list = field(default_factory=list)      # languages searched
    candidates: list = field(default_factory=list)    # list[CrossLangCandidate]
    coverage: dict = field(default_factory=dict)      # {"python": 5, "rust": 3} — count per lang
    errors: dict = field(default_factory=dict)        # {"rust": "timeout"} — per-lang errors
    duration_ms: int = 0

    def summary(self) -> str:
        lines = [f"Cross-language search for '{self.query}':"]
        for lang, count in self.coverage.items():
            lines.append(f"  [{lang}] {count} candidates")
        if self.errors:
            for lang, err in self.errors.items():
                lines.append(f"  [!] {lang}: {err}")
        return "\n".join(lines)


@dataclass
class BatchSearchConfig:
    """Configuration for a batch cross-language search."""
    query: str
    languages: list = field(default_factory=lambda: ["python", "javascript", "rust", "java", "kotlin", "c_cpp"])
    limit_per_lang: int = 5
    timeout_per_lang: int = 60       # seconds
    dedup: bool = True
    include_also_available: bool = True


# ═══════════════════════════════════════════════════════════════════
# 3. Capability ontology types
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LibraryCapability:
    """Structured semantic description of what a library does.

    Unlike FEATURES.json (which describes tooling operations),
    this describes library semantics — data shapes, error contracts,
    concurrency models. Enables real function matching.
    """
    library: str = ""
    language: str = ""
    version: str = ""

    io_patterns: list = field(default_factory=list)     # ["serialize", "deserialize", "fetch", "write"]
    data_formats_in: list = field(default_factory=list)  # ["python_object", "json_bytes", "csv"]
    data_formats_out: list = field(default_factory=list) # ["json_bytes", "json_str", "csv_file"]

    data_shape_constraints: dict = field(default_factory=dict)
    protocol: list = field(default_factory=list)
    runtime_reqs: dict = field(default_factory=dict)
    error_categories: list = field(default_factory=list)
    concurrency_model: dict = field(default_factory=dict)
    lifecycle: dict = field(default_factory=dict)
    license: str = ""                                    # SPDX: "MIT", "Apache-2.0", "GPL-3.0", "BSD-3-Clause", "LGPL-3.0"

    def to_dict(self) -> dict:
        return {
            "library": self.library,
            "language": self.language,
            "version": self.version,
            "io_patterns": self.io_patterns,
            "data_formats_in": self.data_formats_in,
            "data_formats_out": self.data_formats_out,
            "data_shape_constraints": self.data_shape_constraints,
            "protocol": self.protocol,
            "runtime_reqs": self.runtime_reqs,
            "error_categories": self.error_categories,
            "concurrency_model": self.concurrency_model,
            "lifecycle": self.lifecycle,
            "license": self.license,
        }


@dataclass
class CapabilityAlignment:
    """Pre-computed compatibility between two libraries' capabilities.

    Score is weighted intersection of compatible fields:
    - io_patterns: 0.3
    - data_formats (out->in): 0.3
    - error_model: 0.15
    - data_shape: 0.15
    - runtime_reqs: 0.1
    """
    overall_score: float = 0.0      # 0.0-1.0
    io_compatible: bool = False
    format_compatible: bool = False
    error_model_compatible: bool = False
    runtime_compatible: bool = False
    shape_compatible: bool = False
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "io_compatible": self.io_compatible,
            "format_compatible": self.format_compatible,
            "error_model_compatible": self.error_model_compatible,
            "runtime_compatible": self.runtime_compatible,
            "shape_compatible": self.shape_compatible,
            "warnings": self.warnings,
        }


# ═══════════════════════════════════════════════════════════════════
# 4. Glue strategy types
# ═══════════════════════════════════════════════════════════════════

@dataclass
class GlueStrategy:
    """The mechanical bridge strategy for connecting two libraries.

    Mode matrix:
    - "import":            same-language, same-runtime. Highest confidence.
    - "subprocess_json":   cross-language, universal fallback.
    - "pyo3":              Python->Rust native extension. Scaffold only.
    - "ffi_cffi":          Python<->C/C++. Scaffold only.
    """
    mode: str = "import"           # "import" | "subprocess_json" | "pyo3" | "ffi_cffi"
    bridge_lang: str = "python"    # language of the host-side bridge
    host_framework: str = ""       # e.g. "pyo3", "cffi"
    required_system_tools: list = field(default_factory=list)
    docker_supported: bool = False
    rationale: str = ""            # why this strategy was chosen


# ═══════════════════════════════════════════════════════════════════
# 5. Library endpoint
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LibraryEndpoint:
    """One side of a glue connection.

    api_surface is populated by Phase 2 (auditor/analyst).
    capability is populated from the Capability Ontology.
    """
    name: str
    language: str
    version: str = ""
    registry_url: str = ""
    repo_url: str = ""
    api_surface: list = field(default_factory=list)     # list[FunctionSignature] or list[dict]
    capability: Optional[LibraryCapability] = None
    role: str = "source"                                # "source" | "sink"

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "language": self.language,
            "version": self.version,
            "registry_url": self.registry_url,
            "repo_url": self.repo_url,
            "api_surface": [f if isinstance(f, dict) else f.to_dict() for f in self.api_surface],
            "role": self.role,
        }
        if self.capability:
            d["capability"] = self.capability.to_dict()
        return d


# ═══════════════════════════════════════════════════════════════════
# 6. Top-level GlueSchema
# ═══════════════════════════════════════════════════════════════════

SCAFFOLD_DISCLAIMER = """GENERATED CODE — SCAFFOLD ONLY
This code is a structural starting point. It requires:
1. Manual review of all type conversions and error handling
2. Addition of edge cases (NaN, null, overflow, timeout)
3. Production hardening (logging, retry, lifecycle management)
4. Independent test suite (generated tests are also scaffold-level)
Do not deploy without review."""


@dataclass
class GlueSchema:
    """The complete interface contract between two libraries.

    This is the universal data contract for v3 — all phases read/write
    this schema. Every field has a known confidence level.
    """
    schema: str = "glue-schema-v1"

    # Identity
    src: Optional[LibraryEndpoint] = None
    dst: Optional[LibraryEndpoint] = None
    pair_id: str = ""                # e.g. "requests_httpx"

    # Strategy
    strategy: Optional[GlueStrategy] = None

    # Interface mapping
    mappings: list = field(default_factory=list)  # list[FunctionMapping]

    # Capability alignment (pre-computed compatibility)
    capability_alignment: Optional[CapabilityAlignment] = None

    # Meta
    generated_at: str = ""
    version: str = "1.0.0"

    # Generated code output paths (populated after generation)
    output_dir: str = ""
    generated_files: list = field(default_factory=list)

    def to_json(self, indent=2) -> str:
        return json.dumps(self, default=self._to_serializable, indent=indent, ensure_ascii=False)

    def _to_serializable(self, obj):
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    @staticmethod
    def from_json(data: dict) -> "GlueSchema":
        """Deserialize from a dict (JSON parse result)."""
        schema = GlueSchema()
        if "src" in data and data["src"]:
            schema.src = GlueSchema._endpoint_from_dict(data["src"])
        if "dst" in data and data["dst"]:
            schema.dst = GlueSchema._endpoint_from_dict(data["dst"])
        if "strategy" in data and data["strategy"]:
            schema.strategy = GlueStrategy(**data["strategy"])
        if "capability_alignment" in data and data["capability_alignment"]:
            schema.capability_alignment = CapabilityAlignment(**data["capability_alignment"])
        if "mappings" in data:
            schema.mappings = [GlueSchema._mapping_from_dict(m) for m in data["mappings"]]
        schema.pair_id = data.get("pair_id", "")
        schema.generated_at = data.get("generated_at", "")
        schema.version = data.get("version", "1.0.0")
        schema.output_dir = data.get("output_dir", "")
        schema.generated_files = data.get("generated_files", [])
        return schema

    @staticmethod
    def _endpoint_from_dict(d: dict) -> LibraryEndpoint:
        ep = LibraryEndpoint(
            name=d.get("name", ""),
            language=d.get("language", ""),
            version=d.get("version", ""),
            registry_url=d.get("registry_url", ""),
            repo_url=d.get("repo_url", ""),
            role=d.get("role", "source"),
        )
        if "api_surface" in d:
            ep.api_surface = [
                FunctionSignature(**f) if isinstance(f, dict) else f
                for f in d["api_surface"]
            ]
        if "capability" in d and d["capability"]:
            ep.capability = LibraryCapability(**d["capability"])
        return ep

    @staticmethod
    def _mapping_from_dict(d: dict) -> FunctionMapping:
        mapping = FunctionMapping(
            mapping_id=d.get("mapping_id", ""),
            src_function=d.get("src_function", ""),
            dst_function=d.get("dst_function", ""),
            confidence=d.get("confidence", 0.0),
            confidence_label=d.get("confidence_label", ""),
            review_status=d.get("review_status", "unreviewed"),
            review_note=d.get("review_note", ""),
            code_snippet=d.get("code_snippet", ""),
            error_map=d.get("error_map", {}),
        )
        if "param_mappings" in d:
            mapping.param_mappings = [
                ParamMapping(**p) if isinstance(p, dict) else p
                for p in d["param_mappings"]
            ]
        if "return_transform" in d and d["return_transform"]:
            rt = d["return_transform"]
            mapping.return_transform = TransformRule(**rt) if isinstance(rt, dict) else rt
        return mapping

    def summary(self) -> str:
        """Human-readable summary for terminal display."""
        src_name = self.src.name if self.src else "?"
        dst_name = self.dst.name if self.dst else "?"
        strategy_mode = self.strategy.mode if self.strategy else "?"
        mapping_count = len(self.mappings)
        confidences = [f"{m.confidence:.2f}" for m in self.mappings[:5]]
        ca_score = self.capability_alignment.overall_score if self.capability_alignment else 0.0
        lines = [
            f"[GlueSchema] {src_name} -> {dst_name}",
            f"  Strategy: {strategy_mode}  |  Mappings: {mapping_count}",
            f"  Top confidences: {', '.join(confidences)}" if confidences else "",
            f"  Capability alignment: {ca_score:.2f}",
            f"  Generated files: {len(self.generated_files)}" if self.generated_files else "",
        ]
        return "\n".join(l for l in lines if l)


# ═══════════════════════════════════════════════════════════════════
# 7. Output packaging
# ═══════════════════════════════════════════════════════════════════

@dataclass
class GlueOutputPackage:
    """Complete output of a glue generation session.

    Encompasses the schema, verification results, and output paths.
    This is what Phase 4 receives and what the user sees.
    """
    schema: str = "glue-output-v1"

    glue_schema: Optional[GlueSchema] = None
    verification: dict = field(default_factory=dict)
    disclaimer: str = SCAFFOLD_DISCLAIMER

    output_paths: list = field(default_factory=list)
    generated_at: str = ""

    def to_json(self, indent=2) -> str:
        return json.dumps(self, default=self._to_serializable, indent=indent, ensure_ascii=False)

    def _to_serializable(self, obj):
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if isinstance(obj, GlueSchema):
            return json.loads(obj.to_json())
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    def summary(self) -> str:
        """Human-readable summary."""
        pair = self.glue_schema.pair_id if self.glue_schema else "?"
        files = len(self.output_paths)
        ver = self.verification.get("overall", "unknown") if self.verification else "not run"
        return f"[GlueOutput] {pair}: {files} files generated | Verification: {ver}"


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_pair_id(name_a: str, name_b: str) -> str:
    """Normalise a pair identifier like 'requests_httpx'."""
    return f"{name_a.lower().replace('-', '_')}_{name_b.lower().replace('-', '_')}"


# ───── Known cross-language alias table ─────

CROSS_LANG_ALIASES = {
    # (name_in_lang_a, lang_a) -> (canonical, also_in)
    "polars": {"canonical": "polars", "also_in": ["python", "rust"]},
    "tiktoken": {"canonical": "tiktoken", "also_in": ["python", "rust"]},
    "pyo3": {"canonical": "pyo3", "also_in": ["python", "rust"]},
    "tokenizers": {"canonical": "tokenizers", "also_in": ["python", "rust"]},
    "safetensors": {"canonical": "safetensors", "also_in": ["python", "rust"]},
    "nodejs-polars": {"canonical": "polars", "also_in": ["python", "rust", "javascript"]},
    "pyo3": {"canonical": "pyo3", "also_in": ["python", "rust"]},
    "serde": {"canonical": "serde", "also_in": ["rust"]},
    "serde_json": {"canonical": "serde_json", "also_in": ["rust"]},
    "requests": {"canonical": "requests", "also_in": ["python"]},
    "httpx": {"canonical": "httpx", "also_in": ["python"]},
    "orjson": {"canonical": "orjson", "also_in": ["python", "rust"]},
    # JavaScript <-> TypeScript overlap
    "typescript": {"canonical": "typescript", "also_in": ["javascript"]},
    "ts-node": {"canonical": "ts-node", "also_in": ["javascript"]},
    "ts_node": {"canonical": "ts-node", "also_in": ["javascript"]},
    # Java <-> Kotlin interop
    "kotlin-stdlib": {"canonical": "kotlin-stdlib", "also_in": ["java"]},
    "kotlin_stdlib": {"canonical": "kotlin-stdlib", "also_in": ["java"]},
    "kotlinx-serialization": {"canonical": "kotlinx-serialization", "also_in": ["java", "kotlin"]},
    "kotlinx_serialization": {"canonical": "kotlinx-serialization", "also_in": ["java", "kotlin"]},
    "jackson": {"canonical": "jackson", "also_in": ["java", "kotlin"]},
    "gson": {"canonical": "gson", "also_in": ["java", "kotlin"]},
}


def resolve_alias(name: str, language: str) -> Optional[dict]:
    """Check if a library name is a known cross-language alias.

    Returns None if no alias found, or a dict with "canonical" and "also_in" keys.
    """
    key = name.lower().replace("-", "_")
    if key in CROSS_LANG_ALIASES:
        return CROSS_LANG_ALIASES[key]
    # Try without language suffix
    return None
