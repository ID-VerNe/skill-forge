"""
polyglot/backends/javascript/scout.py — npm registry scout backend.

Searches the npm registry via its public /-/v1/search endpoint and returns
results shaped to match the SearchOutput schema (plain dict, not dataclass).
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests


NPM_SEARCH_URL = "https://registry.npmjs.org/-/v1/search"


def search(query: str, limit: int = 5) -> dict:
    """Search npm registry. Returns dict matching SearchOutput schema."""
    start = time.monotonic()
    errors = []
    results = []

    try:
        resp = requests.get(
            NPM_SEARCH_URL,
            params={"text": query, "size": limit},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        now_float = time.time()
        for obj in data.get("objects", []):
            pkg = obj.get("package", {})
            score_detail = obj.get("score", {}).get("detail", {})
            flags = obj.get("flags", {})

            name = pkg.get("name", "")
            version = pkg.get("version", "")
            description = pkg.get("description", "")
            registry_url = (pkg.get("links") or {}).get("npm", "")
            repo_url = (pkg.get("links") or {}).get("repository", "")
            date_str = pkg.get("date", "")

            # ── stars ──
            stars = flags.get("unstable", False) if isinstance(flags, dict) else False
            # npm search flags don't directly give star count;
            # fall back to score detail field for a rough proxy
            stars = int(
                score_detail.get("popularity", 0) * 10000
                if score_detail
                else 0
            )

            if score_detail:
                downloads = int(score_detail.get("downloads", 0))
            else:
                downloads = 0

            # ── downloads_ratio ──
            downloads_ratio = min(downloads / 1_000_000, 1.0)

            # ── recency ──
            days_since = _days_since(date_str) if date_str else 999
            if days_since <= 30:
                recency = 0.3
            elif days_since <= 365:
                recency = 0.2
            else:
                recency = 0.1

            # ── composite score ──
            score = min(stars / 10000 * 0.4 + downloads_ratio * 0.3 + recency * 0.3, 1.0)

            results.append({
                "name": name,
                "version": version,
                "description": description,
                "registry_url": registry_url,
                "stars": stars,
                "downloads": downloads,
                "last_commit": date_str,
                "license_name": pkg.get("license", ""),
                "dependencies": [],
                "score": round(score, 4),
            })

        has_more = len(results) >= limit

    except requests.RequestException as e:
        errors.append(str(e))
        has_more = False
    except (KeyError, ValueError, TypeError) as e:
        errors.append(f"Parse error: {e}")
        has_more = False

    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "schema": "polyglot-output-v1",
        "tool": "scout",
        "language": "javascript",
        "query": query,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
        "errors": errors,
        "metadata": {
            "duration_ms": duration_ms,
            "cache_hit": False,
            "has_more": has_more,
        },
    }


def _days_since(iso_date: str) -> int:
    """Return whole days elapsed between iso_date (UTC) and now."""
    try:
        from datetime import datetime, timezone
        if "." in iso_date:
            iso_date = iso_date.split(".")[0] + "Z"
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - dt).days
    except Exception:
        return 999


# ── Minimal smoke test ──
if __name__ == "__main__":
    out = search("express", limit=3)
    print(f"Found {len(out['results'])} results, errors={len(out['errors'])}")
    for r in out["results"]:
        print(f"  {r['name']} ({r['version']}) — score={r['score']:.3f}")
