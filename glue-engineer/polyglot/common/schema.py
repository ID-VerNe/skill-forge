"""
polyglot/common/schema.py — Unified output schema for all polyglot tools.

Every backend (scout, auditor, analyst, probe) returns JSON that validates
against these dataclasses. The coordinator reads JSON files, not raw output.
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import time


# ───── Search ─────

@dataclass
class SearchResult:
    name: str
    version: str
    description: str
    registry_url: str = ""
    stars: int = 0
    downloads: int = 0
    last_commit: str = ""       # ISO date
    license_name: str = ""
    dependencies: list = field(default_factory=list)
    score: float = 0.0          # 0.0-1.0 composite quality score


@dataclass
class SearchOutput:
    """Unified output schema — every scout returns this."""
    schema: str = "polyglot-output-v1"
    tool: str = "scout"
    language: str = ""
    query: str = ""
    timestamp: str = ""
    results: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    metadata: dict = field(default_factory=lambda: {
        "duration_ms": 0,
        "cache_hit": False,
        "has_more": False
    })

    def to_json(self, indent=2) -> str:
        return json.dumps(self, default=vars, indent=indent, ensure_ascii=False)

    @staticmethod
    def from_json(data: dict) -> "SearchOutput":
        return SearchOutput(**data)

    def summary(self) -> str:
        lines = [f"[{self.language}] Found {len(self.results)} results for '{self.query}':"]
        for i, r in enumerate(self.results[:5], 1):
            lines.append(f"  {i}. {r.name} ({r.version}) — {r.description[:80]}")
        return "\n".join(lines)


# ───── Audit ─────

@dataclass
class ExportSymbol:
    name: str
    kind: str = ""               # function | class | interface | type | constant
    signature: str = ""
    source: str = ""             # file:line
    doc_available: bool = False
    probed: bool = False

@dataclass
class CommunityHealth:
    stars: int = 0
    last_commit_days_ago: int = 0
    open_issues: int = 0
    has_readme: bool = False
    has_tests: bool = False
    has_docs: bool = False

@dataclass
class SecurityInfo:
    vulnerabilities: list = field(default_factory=list)
    score: float = 1.0           # 0.0 (bad) - 1.0 (clean)

@dataclass
class AuditData:
    files_scanned: int = 0
    files_skipped: int = 0
    exports: list = field(default_factory=list)
    keywords_found: list = field(default_factory=list)
    test_ratio: float = 0.0
    complexity: str = "medium"   # low | medium | high
    community_health: Optional["CommunityHealth"] = None
    security: Optional["SecurityInfo"] = None
    verdict: str = ""


@dataclass
class AuditOutput:
    schema: str = "polyglot-output-v1"
    tool: str = "auditor"
    language: str = ""
    candidate_name: str = ""
    repo_url: str = ""
    timestamp: str = ""
    data: Optional["AuditData"] = None
    errors: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_json(self, indent=2) -> str:
        return json.dumps(self, default=vars, indent=indent, ensure_ascii=False)

    @staticmethod
    def from_json(data: dict) -> "AuditOutput":
        if data.get("data"):
            data["data"] = AuditData(**data["data"])
        return AuditOutput(**data)


# ───── Probe ─────

@dataclass
class ProbeResult:
    symbol: str
    resolved: bool = False
    return_type: str = ""
    error: str = ""

@dataclass
class ProbeOutput:
    schema: str = "polyglot-output-v1"
    tool: str = "probe"
    language: str = ""
    package: str = ""
    timestamp: str = ""
    probed_symbols: list = field(default_factory=list)
    discrepancies: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_json(self, indent=2) -> str:
        return json.dumps(self, default=vars, indent=indent, ensure_ascii=False)


# ───── Helpers ─────

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# @lat: [[common#Composite Quality Score]]
def compute_score(stars: int, downloads: int, days_since_commit: int) -> float:
    """0.0 - 1.0 composite quality score."""
    s = 0.0
    if stars > 10000: s += 0.4
    elif stars > 1000: s += 0.3
    elif stars > 100: s += 0.2
    elif stars > 10: s += 0.1

    if downloads > 1_000_000: s += 0.3
    elif downloads > 100_000: s += 0.2
    elif downloads > 1_000: s += 0.1

    if days_since_commit < 30: s += 0.3
    elif days_since_commit < 365: s += 0.2
    else: s += 0.1

    return min(s, 1.0)
