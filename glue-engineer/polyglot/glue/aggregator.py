"""
polyglot/glue/aggregator.py — Cross-language scout engine.

Wraps all 6 backend scouts in a coordinated fan-out that searches
multiple ecosystems simultaneously and deduplicates results.

DedupEngine lives in dedup.py.
"""

import sys
import os
import json
import time
import threading
from typing import Optional

_POLYGLOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _POLYGLOT_DIR not in sys.path:
    sys.path.insert(0, os.path.normpath(os.path.join(_POLYGLOT_DIR, "..")))
if _POLYGLOT_DIR not in sys.path:
    sys.path.insert(0, _POLYGLOT_DIR)

from polyglot.glue.glue_schema import (
    CrossLangCandidate,
    CrossLangSearchView,
    BatchSearchConfig,
    resolve_alias,
)
from polyglot.glue.dedup import DedupEngine


BACKENDS_DIR = os.path.join(_POLYGLOT_DIR, "backends")


class CrossLangScoutEngine:
    """Runs parallel searches across multiple language ecosystems.

    Usage:
        engine = CrossLangScoutEngine()
        view = engine.batch_search("json parser", languages=["python", "rust"])
        print(view.summary())
    """

    def __init__(self, config: Optional[BatchSearchConfig] = None):
        self.config = config or BatchSearchConfig(query="")

    def batch_search(self, query: str, languages: Optional[list] = None, limit: Optional[int] = None) -> CrossLangSearchView:
        """Search across multiple languages in parallel (threaded)."""
        self.config.query = query
        if languages:
            self.config.languages = languages
        if limit:
            self.config.limit_per_lang = limit

        start = time.time()
        results = {}       # lang -> list[dict]
        errors = {}        # lang -> error string
        threads = []
        lock = threading.Lock()

        def _search_one(lang: str):
            try:
                mod = self._import_scout(lang)
                raw = mod.search(query, limit=self.config.limit_per_lang)
                with lock:
                    results[lang] = raw.get("results", [])
                    if raw.get("errors"):
                        errors[lang] = "; ".join(raw["errors"][:2])
            except Exception as e:
                with lock:
                    errors[lang] = str(e)[:200]

        for lang in self.config.languages:
            t = threading.Thread(target=_search_one, args=(lang,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=self.config.timeout_per_lang)

        elapsed = int((time.time() - start) * 1000)

        # Build CrossLangSearchView
        view = CrossLangSearchView(
            query=query,
            targets=list(self.config.languages),
            duration_ms=elapsed,
        )

        # Flatten results into CrossLangCandidate list
        candidates = []
        for lang, items in results.items():
            for item in items:
                cand = self._item_to_candidate(item, lang)
                if self.config.include_also_available:
                    alias = resolve_alias(cand.name, lang)
                    if alias:
                        cand.also_available_in = [a for a in alias["also_in"] if a != lang]
                candidates.append(cand)

        # Dedup by canonical name if enabled
        if self.config.dedup:
            # Use the old simple dedup first (cross-language canonical name)
            candidates = self._deduplicate_simple(candidates)
            # Then run the multi-layer DedupEngine for deeper dedup
            engine = DedupEngine()
            candidates = engine.deduplicate(candidates)

        view.candidates = candidates
        view.coverage = {lang: len(items) for lang, items in results.items()}
        view.errors = errors
        return view

    def _import_scout(self, language: str):
        """Dynamically import a scout module for the given language."""
        lang_dir = os.path.join(BACKENDS_DIR, language)
        path = os.path.join(lang_dir, "scout.py")
        if not os.path.exists(path):
            raise ImportError(f"No scout backend for '{language}'")
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"{language}.scout", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _item_to_candidate(self, item: dict, language: str) -> CrossLangCandidate:
        """Convert a raw search result dict to a CrossLangCandidate."""
        return CrossLangCandidate(
            name=item.get("name", "unknown"),
            language=language,
            version=item.get("version", ""),
            description=item.get("description", "")[:200],
            registry_url=item.get("registry_url", ""),
            repo_url=item.get("repo_url", ""),
            stars=item.get("stars", 0) or 0,
            downloads=item.get("downloads", 0) or 0,
            score=item.get("score", 0.0) or 0.0,
        )

    def _deduplicate_simple(self, candidates: list) -> list:
        """Remove duplicate projects found in multiple languages (simple alias-based)."""
        seen = {}   # canonical_lower_name -> CrossLangCandidate
        deduped = []
        for c in candidates:
            alias = resolve_alias(c.name, c.language)
            key = (alias["canonical"] if alias else c.name).lower()
            if key in seen:
                existing = seen[key]
                existing.also_available_in.append(c.language)
                # Keep the one with higher score
                if c.score > existing.score:
                    existing.score = c.score
            else:
                seen[key] = c
                deduped.append(c)
        return deduped


# ───── Convenience function ─────

def cross_search(query: str, languages: Optional[list] = None, limit: int = 5) -> dict:
    """One-shot cross-language search. Returns dict for JSON serialization."""
    engine = CrossLangScoutEngine()
    view = engine.batch_search(query=query, languages=languages, limit=limit)
    return {
        "tool": "cross_lang_scout",
        "schema": "cross-lang-search-v1",
        "query": view.query,
        "languages": view.targets,
        "duration_ms": view.duration_ms,
        "coverage": view.coverage,
        "errors": view.errors,
        "candidates": [
            {
                "name": c.name,
                "language": c.language,
                "version": c.version,
                "description": c.description,
                "registry_url": c.registry_url,
                "repo_url": c.repo_url,
                "stars": c.stars,
                "downloads": c.downloads,
                "score": c.score,
                "also_available_in": c.also_available_in,
            }
            for c in view.candidates
        ],
    }