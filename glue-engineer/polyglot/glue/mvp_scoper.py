"""
polyglot/glue/mvp_scoper.py — MVP scoping engine.

Classifies features and mappings into P0/P1/P2 tiers based on
project context, helping prioritize what to build first.

Tiers:
  P0 (Required)   — Must have for MVP. Core functionality.
  P1 (Nice)       — Important but can come after MVP.
  P2 (Future)     — Desirable but deferrable. Icebox.

Usage:
    from polyglot.glue.mvp_scoper import MvpScoper
    scoper = MvpScoper()
    scope = scoper.classify_item("PDF import", "import_pipeline")
    print(scope.tier, scope.rationale)
"""

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class ScopeDecision:
    """Single scope decision for a feature or mapping."""
    name: str = ""
    category: str = ""        # e.g. "import", "export", "ui", "llm", "core"
    tier: str = "P2"          # "P0" | "P1" | "P2"
    rationale: str = ""
    depends_on: list = field(default_factory=list)   # list[str] — names of features this depends on
    effort_estimate: str = ""  # "small" | "medium" | "large" | "unknown"
    risk: str = ""             # "low" | "medium" | "high" | "unknown"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "tier": self.tier,
            "rationale": self.rationale,
            "depends_on": self.depends_on,
            "effort_estimate": self.effort_estimate,
            "risk": self.risk,
        }


@dataclass
class ScopeReport:
    """Complete MVP scope report."""
    project: str = ""
    scoped_at: str = ""
    decisions: dict = field(default_factory=dict)  # name -> ScopeDecision
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "scoped_at": self.scoped_at,
            "decisions": {k: v.to_dict() for k, v in self.decisions.items()},
            "notes": self.notes,
        }

    def summary(self) -> str:
        p0 = [d for d in self.decisions.values() if d.tier == "P0"]
        p1 = [d for d in self.decisions.values() if d.tier == "P1"]
        p2 = [d for d in self.decisions.values() if d.tier == "P2"]

        lines = [
            f"[Scope] {self.project}",
            f"  P0 (Required): {len(p0)} items",
        ]
        for d in p0:
            lines.append(f"    [{d.category}] {d.name} — {d.rationale[:80]}")

        if p1:
            lines.append(f"  P1 (Nice): {len(p1)} items")
            for d in p1:
                lines.append(f"    [{d.category}] {d.name} — {d.rationale[:80]}")

        if p2:
            lines.append(f"  P2 (Future): {len(p2)} items")
            for d in p2:
                lines.append(f"    [{d.category}] {d.name} — {d.rationale[:80]}")

        if self.notes:
            lines.append(f"  Notes: {self.notes[:120]}")

        return "\n".join(lines)


class MvpScoper:
    """Classifies features/items into P0/P1/P2 tiers.

    Uses keyword-based heuristics to auto-classify, with
    manual override support.
    """

    # Keywords that signal P0 (required)
    P0_KEYWORDS = [
        "import", "parse", "convert", "load", "read", "open", "view",
        "export", "save", "write", "search", "query", "browse",
        "core", "pipeline", "flow", "auth", "login", "input",
    ]

    # Keywords that signal P1 (nice to have)
    P1_KEYWORDS = [
        "filter", "sort", "tag", "label", "categorize",
        "preview", "highlight", "annotate", "note",
        "batch", "bulk", "sync", "schedule",
        "share", "embed", "link", "reference",
        "template", "macro", "plugin", "extension",
    ]

    # Categories that are usually P0
    P0_CATEGORIES = {"import", "export", "core", "pipeline", "search", "view"}

    # Categories that are usually P1
    P1_CATEGORIES = {"annotation", "filter", "batch", "analysis", "custom"}

    def __init__(self, project: str = ""):
        self.project = project

    def classify_item(
        self,
        name: str,
        category: str = "",
        depends_on: Optional[list] = None,
        manual_tier: str = "",
    ) -> ScopeDecision:
        """Classify a single feature/mapping.

        Args:
            name: Feature name (e.g., "PDF import").
            category: Category (e.g., "import", "export", "ui").
            depends_on: List of feature names this depends on.
            manual_tier: Manual override ("P0", "P1", "P2", or "" for auto).

        Returns:
            ScopeDecision with auto-classified tier.
        """
        if manual_tier:
            tier = manual_tier
            rationale = "Manual override"
        else:
            tier, rationale = self._auto_classify(name, category)

        return ScopeDecision(
            name=name,
            category=category,
            tier=tier,
            rationale=rationale,
            depends_on=depends_on or [],
            effort_estimate=self._estimate_effort(category),
            risk=self._estimate_risk(category, tier),
        )

    def _auto_classify(self, name: str, category: str) -> tuple[str, str]:
        """Auto-classify a feature into P0/P1/P2 by keywords + category."""
        name_lower = name.lower()

        # Check category first
        if category.lower() in self.P0_CATEGORIES:
            return ("P0", f"Category '{category}' is P0 by default")

        if category.lower() in self.P1_CATEGORIES:
            return ("P1", f"Category '{category}' is P1 by default")

        # Check keywords
        for kw in self.P0_KEYWORDS:
            if kw in name_lower:
                return ("P0", f"Contains P0 keyword '{kw}'")

        for kw in self.P1_KEYWORDS:
            if kw in name_lower:
                return ("P1", f"Contains P1 keyword '{kw}'")

        # Default: P2
        return ("P2", "No P0/P1 keywords or category detected")

    def _estimate_effort(self, category: str) -> str:
        """Rough effort estimate by category."""
        high_effort = {"core", "export", "import", "pipeline", "search"}
        medium_effort = {"annotation", "filter", "batch", "analysis", "custom", "ui"}
        if category.lower() in high_effort:
            return "large"
        if category.lower() in medium_effort:
            return "medium"
        return "small"

    def _estimate_risk(self, category: str, tier: str) -> str:
        """Rough risk estimate."""
        high_risk = {"core", "pipeline", "import", "export"}
        if category.lower() in high_risk and tier in ("P0",):
            return "high"  # Core features that must work = higher impact risk
        if tier == "P2":
            return "low"  # Future features = low urgency risk
        return "medium"

    def classify_mappings(
        self,
        mappings: list,
        known_p0_functions: Optional[list] = None,
    ) -> list[ScopeDecision]:
        """Classify a list of function mappings by function name.

        Args:
            mappings: List of objects with src_function attributes (or dicts).
            known_p0_functions: Function names that are always P0.

        Returns:
            List of ScopeDecision objects.
        """
        p0_funcs = set(known_p0_functions or [])
        decisions = []
        for m in mappings:
            if hasattr(m, "src_function"):
                func_name = m.src_function
            elif isinstance(m, dict):
                func_name = m.get("src_function", "")
            else:
                func_name = str(m)

            if func_name in p0_funcs:
                tier = "P0"
                rationale = "In known P0 functions list"
            else:
                tier, rationale = self._auto_classify(func_name, "pipeline")

            decisions.append(ScopeDecision(
                name=func_name,
                category="pipeline",
                tier=tier,
                rationale=rationale,
            ))
        return decisions

    def bucket_decisions(self, decisions: list[ScopeDecision]) -> tuple:
        """Group decisions by tier."""
        p0 = [d for d in decisions if d.tier == "P0"]
        p1 = [d for d in decisions if d.tier == "P1"]
        p2 = [d for d in decisions if d.tier == "P2"]
        return p0, p1, p2

    def generate_report(self, decisions: list[ScopeDecision]) -> ScopeReport:
        """Generate a scope report from decisions."""
        from polyglot.glue.glue_schema import now_iso
        report = ScopeReport(
            project=self.project,
            scoped_at=now_iso(),
        )
        for d in decisions:
            report.decisions[d.name] = d
        # Add summary note
        p0, p1, p2 = self.bucket_decisions(decisions)
        report.notes = f"{len(p0)} P0, {len(p1)} P1, {len(p2)} P2 — {len(decisions)} total items scoped"
        return report
