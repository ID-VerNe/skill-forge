"""
polyglot/glue/helpers.py — Utility functions for the glue module.

now_iso() and build_pair_id().
"""

import time


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_pair_id(name_a: str, name_b: str) -> str:
    """Normalise a pair identifier like 'requests_httpx'."""
    return f"{name_a.lower().replace('-', '_')}_{name_b.lower().replace('-', '_')}"