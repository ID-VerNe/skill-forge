"""
polyglot/glue/aliases.py — Cross-language alias table and resolver.

Maps library names across ecosystems (e.g. orjson exists in both
python and rust) so search results can be deduplicated.
"""

from typing import Optional


# ───── Known cross-language alias table ─────

CROSS_LANG_ALIASES = {
    # (name_in_lang_a, lang_a) -> (canonical, also_in)
    "polars": {"canonical": "polars", "also_in": ["python", "rust"]},
    "tiktoken": {"canonical": "tiktoken", "also_in": ["python", "rust"]},
    "pyo3": {"canonical": "pyo3", "also_in": ["python", "rust"]},
    "tokenizers": {"canonical": "tokenizers", "also_in": ["python", "rust"]},
    "safetensors": {"canonical": "safetensors", "also_in": ["python", "rust"]},
    "nodejs-polars": {"canonical": "polars", "also_in": ["python", "rust", "javascript"]},
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
    return None