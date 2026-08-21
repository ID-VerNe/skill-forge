"""
polyglot/glue/capability_types.py — Library capability description + alignment types.

LibraryCapability and CapabilityAlignment describe what a library does
semantically — data shapes, error contracts, concurrency models —
enabling real function matching across languages.
"""

from dataclasses import dataclass, field
from typing import Optional


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