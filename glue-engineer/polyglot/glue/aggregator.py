"""
polyglot/glue/aggregator.py — Cross-language scout engine.

Wraps all 6 backend scouts in a coordinated fan-out that searches
multiple ecosystems simultaneously and deduplicates results.
"""

import hashlib
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


BACKENDS_DIR = os.path.join(_POLYGLOT_DIR, "backends")


# ═══════════════════════════════════════════════════════════════════
# Multi-layer deduplication engine
# ═══════════════════════════════════════════════════════════════════

def _levenshtein_ratio(a: str, b: str) -> float:
    """Compute similarity ratio (0.0-1.0) between two strings via Levenshtein."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Make a the shorter
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a):
        curr[0] = i + 1
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr[j + 1] = min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost)
        prev, curr = curr, prev
    distance = prev[len(b)]
    max_len = max(len(a), len(b))
    return 1.0 - (distance / max_len) if max_len > 0 else 1.0


# @lat: [[glue#Dedup Engine]]
class DedupEngine:
    """Multi-layer dedup engine.

    Layers (applied in order):
        1. SHA256 hash dedup     — exact file content match
        2. DOI dedup             — academic paper identifier match
        3. Levenshtein title     — fuzzy title matching (threshold 0.85)
        4. Title+author fuzzy    — combined fuzzy match (threshold 0.75)

    Each layer has a configurable threshold. Higher layers only
    process candidates that survive lower layers.
    """

    def __init__(self, title_threshold: float = 0.85, combined_threshold: float = 0.75):
        self.title_threshold = title_threshold
        self.combined_threshold = combined_threshold

        # Internal tracking sets per layer
        self._seen_sha256: set[str] = set()
        self._seen_doi: set[str] = set()
        self._seen_titles: list[str] = []
        self._seen_author_title: list[tuple[str, str]] = []

    # ── Layer 1: SHA256 hash ──

    def dedup_sha256(self, candidates: list) -> list:
        """Remove candidates with duplicate content_hash (sha256)."""
        result = []
        for c in candidates:
            h = getattr(c, "content_hash", "") or ""
            if not h:
                result.append(c)
            elif h not in self._seen_sha256:
                self._seen_sha256.add(h)
                result.append(c)
        return result

    # ── Layer 2: DOI ──

    def dedup_doi(self, candidates: list) -> list:
        """Remove candidates with duplicate DOI."""
        result = []
        for c in candidates:
            doi = getattr(c, "doi", "") or ""
            if not doi:
                result.append(c)
            elif doi not in self._seen_doi:
                self._seen_doi.add(doi)
                result.append(c)
        return result

    # ── Layer 3: Levenshtein title ──

    def dedup_title(self, candidates: list) -> list:
        """Remove candidates whose title is very similar to a previously-seen one."""
        result = []
        for c in candidates:
            title = (getattr(c, "title", "") or c.name or "").lower().strip()
            if not title:
                result.append(c)
                continue
            is_dup = False
            for seen in self._seen_titles:
                if _levenshtein_ratio(title, seen) >= self.title_threshold:
                    is_dup = True
                    break
            if not is_dup:
                self._seen_titles.append(title)
                result.append(c)
        return result

    # ── Layer 4: Title + Author fuzzy ──

    def dedup_title_author(self, candidates: list) -> list:
        """Remove candidates with similar title AND same author/list of authors."""
        result = []
        for c in candidates:
            title = (getattr(c, "title", "") or c.name or "").lower().strip()
            author = (getattr(c, "author", "") or "").lower().strip()
            if not title or not author:
                result.append(c)
                continue
            is_dup = False
            for seen_title, seen_author in self._seen_author_title:
                if seen_author == author:
                    if _levenshtein_ratio(title, seen_title) >= self.combined_threshold:
                        is_dup = True
                        break
            if not is_dup:
                self._seen_author_title.append((title, author))
                result.append(c)
        return result

    # ── Full pipeline ──

    def deduplicate(self, candidates: list) -> list:
        """Run all dedup layers in order. Returns deduplicated list."""
        for layer_name, layer_fn in [
            ("sha256", self.dedup_sha256),
            ("doi", self.dedup_doi),
            ("title", self.dedup_title),
            ("title+author", self.dedup_title_author),
        ]:
            before = len(candidates)
            candidates = layer_fn(candidates)
            after = len(candidates)
            if after < before:
                pass  # logging possible here in future
        return candidates

    def reset(self) -> None:
        """Clear all seen sets (for a new batch)."""
        self._seen_sha256.clear()
        self._seen_doi.clear()
        self._seen_titles.clear()
        self._seen_author_title.clear()


# @lat: [[glue#Cross-Language Search]]
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