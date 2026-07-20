"""polyglot/common/cache.py — Disk cache with 24h TTL."""

import json
import os
import time
import hashlib

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache")


def _cache_path(key: str) -> str:
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")


def cache_get(key: str) -> dict | None:
    """Returns cached value or None if missing/expired."""
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if entry.get("expires", 0) > time.time():
            return entry.get("data")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def cache_set(key: str, data: dict, ttl_seconds: int = 86400) -> None:
    """Cache data with TTL (default 24h)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    entry = {"data": data, "expires": time.time() + ttl_seconds}
    path = _cache_path(key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
    except OSError:
        pass
