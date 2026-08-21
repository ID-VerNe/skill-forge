"""
polyglot/glue/glue_schema.py — Interface contract schema for v3 glue code generation.

This file is a thin re-export layer over the sectioned schema modules.
Every phase of the v3 pipeline reads/writes this same public interface.

Sections:
  - polyglot.glue.schema_types      Parameter/FunctionSignature/TransformRule/ParamMapping/FunctionMapping/StatusMachine
  - polyglot.glue.search_types      CrossLangCandidate/CrossLangSearchView/BatchSearchConfig
  - polyglot.glue.capability_types  LibraryCapability/CapabilityAlignment
  - polyglot.glue.strategy_types    GlueStrategy/LibraryEndpoint/GlueSchema/GlueOutputPackage/SCAFFOLD_DISCLAIMER
  - polyglot.glue.aliases           CROSS_LANG_ALIASES/resolve_alias
  - polyglot.glue.helpers           now_iso/build_pair_id
"""

from polyglot.glue.schema_types import (
    Parameter,
    FunctionSignature,
    TransformRule,
    ParamMapping,
    FunctionMapping,
    StatusMachine,
)
from polyglot.glue.search_types import (
    CrossLangCandidate,
    CrossLangSearchView,
    BatchSearchConfig,
)
from polyglot.glue.capability_types import (
    LibraryCapability,
    CapabilityAlignment,
)
from polyglot.glue.strategy_types import (
    SCAFFOLD_DISCLAIMER,
    GlueStrategy,
    LibraryEndpoint,
    GlueSchema,
    GlueOutputPackage,
)
from polyglot.glue.aliases import (
    CROSS_LANG_ALIASES,
    resolve_alias,
)
from polyglot.glue.helpers import (
    now_iso,
    build_pair_id,
)

__all__ = [
    "Parameter",
    "FunctionSignature",
    "TransformRule",
    "ParamMapping",
    "FunctionMapping",
    "StatusMachine",
    "CrossLangCandidate",
    "CrossLangSearchView",
    "BatchSearchConfig",
    "LibraryCapability",
    "CapabilityAlignment",
    "SCAFFOLD_DISCLAIMER",
    "GlueStrategy",
    "LibraryEndpoint",
    "GlueSchema",
    "GlueOutputPackage",
    "CROSS_LANG_ALIASES",
    "resolve_alias",
    "now_iso",
    "build_pair_id",
]