"""
polyglot/glue/dedup.py — Multi-layer deduplication engine.

Provides DedupEngine with 4 layers of dedup (SHA256, DOI, Levenshtein
title, title+author fuzzy) and a Levenshtein ratio helper.

Used by CrossLangScoutEngine in aggregator.py.
"""


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