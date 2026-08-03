"""polyglot/common/cache.py — SQLite-backed disk cache with TTL and stale fallback.

Cache database lives at a fixed system-level location (not project-relative),
so it persists across projects and CWDs.

  Windows:  %LOCALAPPDATA%/polyglot/cache.db
  macOS:    ~/.cache/polyglot/cache.db
  Linux:    $XDG_CACHE_HOME/polyglot/cache.db  (default ~/.cache/polyglot/cache.db)

Thread-safe via thread-local connections + WAL mode.
"""

import json
import os
import random
import sys
import time
import sqlite3
import threading

from polyglot.common.platform import detect_os


# ───── Database location (fixed, not project-relative) ─────


def _cache_dir() -> str:
    """Return the platform-appropriate cache directory (created if needed)."""
    os_name = detect_os()
    if os_name == "windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        xdg = os.environ.get("XDG_CACHE_HOME", "")
        base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".cache")
    cache_dir = os.path.join(base, "polyglot")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


DB_PATH = os.path.join(_cache_dir(), "cache.db")

# Thread-local connection so each thread gets its own SQLite connection
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection (WAL mode)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
        _init_schema(conn)
        _local.conn = conn
    return _local.conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key    TEXT PRIMARY KEY,
            data   TEXT NOT NULL,
            expires REAL NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires)")
    conn.commit()


# ───── Public API ─────


def cache_get(key: str) -> dict | None:
    """Return cached value or None if missing/expired."""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT data FROM cache WHERE key = ? AND expires > ?",
            (key, time.time()),
        ).fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def cache_get_stale(key: str) -> dict | None:
    """Return cached value even if expired, or None if never cached.

    This is the degradation path: when the network is unreachable,
    stale data is better than nothing.
    """
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT data FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def cache_set(key: str, data: dict, ttl_seconds: int = 86400) -> None:
    """Cache data with TTL (default 24h)."""
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, data, expires, created_at) VALUES (?, ?, ?, ?)",
            (key, json.dumps(data, ensure_ascii=False), time.time() + ttl_seconds, time.time()),
        )
        conn.commit()

        # Probabilistic cleanup: ~1% chance to clear expired entries on each set
        if random.random() < 0.01:
            try:
                now = time.time()
                conn.execute(
                    "DELETE FROM cache WHERE expires < ? OR created_at < ?",
                    (now, now - 86400 * 7),
                )
                conn.commit()
            except Exception:
                pass
    except Exception:
        pass


def cache_clean(older_than_seconds: int = 86400 * 7) -> int:
    """Remove expired entries and entries older than ``older_than_seconds``.

    Returns the number of rows deleted.
    """
    try:
        conn = _get_conn()
        now = time.time()
        cursor = conn.execute(
            "DELETE FROM cache WHERE expires < ? OR created_at < ?",
            (now, now - older_than_seconds),
        )
        conn.commit()
        return cursor.rowcount
    except Exception:
        return 0


def cache_stats() -> dict:
    """Return cache statistics: total entries, expired entries, db size."""
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        expired = conn.execute(
            "SELECT COUNT(*) FROM cache WHERE expires < ?",
            (time.time(),),
        ).fetchone()[0]
        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        return {"total": total, "expired": expired, "db_size_bytes": db_size}
    except Exception:
        return {"total": 0, "expired": 0, "db_size_bytes": 0}