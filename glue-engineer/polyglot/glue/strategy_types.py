"""
polyglot/glue/strategy_types.py — Glue strategy, library endpoint, top-level schema, and output package.

GlueStrategy, LibraryEndpoint, GlueSchema, GlueOutputPackage.
"""

from dataclasses import dataclass, field
from typing import Optional
import json

from polyglot.glue.schema_types import FunctionSignature, FunctionMapping, ParamMapping, TransformRule
from polyglot.glue.capability_types import LibraryCapability, CapabilityAlignment


SCAFFOLD_DISCLAIMER = """GENERATED CODE — SCAFFOLD ONLY
This code is a structural starting point. It requires:
1. Manual review of all type conversions and error handling
2. Addition of edge cases (NaN, null, overflow, timeout)
3. Production hardening (logging, retry, lifecycle management)
4. Independent test suite (generated tests are also scaffold-level)
Do not deploy without review."""


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