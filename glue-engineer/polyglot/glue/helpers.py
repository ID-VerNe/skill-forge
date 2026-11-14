"""
polyglot/glue/helpers.py — Utility functions for the glue module.

now_iso() and build_pair_id().
"""

import hashlib
import re
import time

_PAIR_COMPONENT_MAX_LENGTH = 90


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_pair_id(name_a: str, name_b: str) -> str:
    """Build a filesystem-safe pair identifier like 'requests_httpx'.

    Keep the normalized names readable while adding a digest of the complete
    ordered pair. The digest preserves component boundaries and distinguishes
    names that normalize to the same filesystem-safe slug.
    """
    def component(name: str) -> str:
        normalized = name.lower().replace("-", "_")
        safe = re.sub(r"[^a-z0-9_]", "_", normalized) or "library"
        return safe[:_PAIR_COMPONENT_MAX_LENGTH]

    pair = f"{len(name_a)}:{name_a}{len(name_b)}:{name_b}"
    digest = hashlib.sha256(pair.encode("utf-8")).hexdigest()
    return f"{component(name_a)}_{component(name_b)}_{digest}"
