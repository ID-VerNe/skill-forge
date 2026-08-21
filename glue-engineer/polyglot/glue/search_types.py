"""
polyglot/glue/search_types.py — Cross-language search view types.

CrossLangCandidate, CrossLangSearchView, BatchSearchConfig.
"""

from dataclasses import dataclass, field


@dataclass
class CrossLangCandidate:
    """A search result from one backend, tagged with language and metadata."""
    name: str
    language: str
    version: str = ""
    description: str = ""
    registry_url: str = ""
    repo_url: str = ""
    stars: int = 0
    downloads: int = 0
    score: float = 0.0              # 0.0-1.0 per-ecosystem quality score
    also_available_in: list = field(default_factory=list)  # ["python", "rust"] if cross-lang project


@dataclass
class CrossLangSearchView:
    """Unified cross-ecosystem search result.

    This is what the user sees after a batch search completes.
    All results from all queried backends, deduplicated and ranked.
    """
    query: str = ""
    targets: list = field(default_factory=list)      # languages searched
    candidates: list = field(default_factory=list)    # list[CrossLangCandidate]
    coverage: dict = field(default_factory=dict)      # {"python": 5, "rust": 3} — count per lang
    errors: dict = field(default_factory=dict)        # {"rust": "timeout"} — per-lang errors
    duration_ms: int = 0

    def summary(self) -> str:
        lines = [f"Cross-language search for '{self.query}':"]
        for lang, count in self.coverage.items():
            lines.append(f"  [{lang}] {count} candidates")
        if self.errors:
            for lang, err in self.errors.items():
                lines.append(f"  [!] {lang}: {err}")
        return "\n".join(lines)


@dataclass
class BatchSearchConfig:
    """Configuration for a batch cross-language search."""
    query: str
    languages: list = field(default_factory=lambda: ["python", "javascript", "rust", "java", "kotlin", "c_cpp"])
    limit_per_lang: int = 5
    timeout_per_lang: int = 60       # seconds
    dedup: bool = True
    include_also_available: bool = True