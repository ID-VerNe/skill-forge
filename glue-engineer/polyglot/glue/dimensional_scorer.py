"""
polyglot/glue/dimensional_scorer.py — Analysis scoring across 6 dimensions.

Scores a glue schema or plan across dimensions (direction, architecture,
stack, feasibility, risk, focus) for analysis, not pass/fail.

This is a separate concern from the progressive verification ladder
in verifier.py.
"""

from dataclasses import dataclass, field
from typing import Optional

from polyglot.glue.glue_schema import GlueSchema, now_iso


@dataclass
class DimensionalScore:
    """A single dimensional scoring result (analysis, not pass/fail).

    Dimensions:
      direction     — Clarity of problem statement and solution direction
      architecture  — Quality of system design and component separation
      stack         — Appropriateness of tech stack choices
      feasibility   — Practical achievability within stated constraints
      risk          — Risk awareness and mitigation planning
      focus         — Whether the plan stays on-target vs scope-creep
    """
    name: str = ""
    score: float = 0.0     # 0.0-1.0
    explanation: str = ""
    warning: str = ""


@dataclass
class DimensionalReport:
    """Complete dimensional scoring results."""
    package_id: str = ""
    scored_at: str = ""
    dimensions: dict = field(default_factory=dict)  # str -> DimensionalScore
    overall: float = 0.0

    def to_dict(self) -> dict:
        return {
            "package_id": self.package_id,
            "scored_at": self.scored_at,
            "dimensions": {
                k: {"name": v.name, "score": v.score, "explanation": v.explanation, "warning": v.warning}
                for k, v in self.dimensions.items()
            },
            "overall": self.overall,
        }

    def summary(self) -> str:
        lines = [
            f"[DimensionalScore] {self.package_id}",
            f"  Overall: {self.overall:.2f}",
        ]
        for dim, ds in self.dimensions.items():
            bar = "=" * int(ds.score * 20)
            lines.append(f"  [{dim:<12}] {ds.score:.2f} |{bar:<20}|")
            if ds.explanation:
                lines.append(f"    -> {ds.explanation[:100]}")
            if ds.warning:
                lines.append(f"    !! {ds.warning[:100]}")
        return "\n".join(lines)


class DimensionalScorer:
    """Scores a glue schema or plan across 6 dimensions.

    This is analysis (not pass/fail). Scores help compare different
    approaches and identify blind spots.
    """

    DIMENSION_WEIGHTS = {
        "direction": 0.20,
        "architecture": 0.20,
        "stack": 0.15,
        "feasibility": 0.20,
        "risk": 0.15,
        "focus": 0.10,
    }

    def __init__(self, schema: Optional[GlueSchema] = None, plan_text: str = ""):
        self.schema = schema
        self.plan_text = plan_text

    def score_all(self) -> DimensionalReport:
        """Score all 6 dimensions."""
        report = DimensionalReport(
            package_id=self.schema.pair_id if self.schema else "unknown",
            scored_at=now_iso(),
        )

        report.dimensions["direction"] = self._score_direction()
        report.dimensions["architecture"] = self._score_architecture()
        report.dimensions["stack"] = self._score_stack()
        report.dimensions["feasibility"] = self._score_feasibility()
        report.dimensions["risk"] = self._score_risk()
        report.dimensions["focus"] = self._score_focus()

        # Weighted overall
        total = 0.0
        for dim, ds in report.dimensions.items():
            total += ds.score * self.DIMENSION_WEIGHTS.get(dim, 0.15)
        report.overall = round(total, 3)

        return report

    def _score_direction(self) -> DimensionalScore:
        """Score direction clarity."""
        s = self.schema
        score = 0.0
        explanation_parts = []

        if s and s.pair_id:
            score += 0.3
            explanation_parts.append(f"pair_id={s.pair_id}")
        if s and s.src:
            score += 0.2
            explanation_parts.append(f"src={s.src.name}")
        if s and s.dst:
            score += 0.2
            explanation_parts.append(f"dst={s.dst.name}")
        if s and s.strategy:
            score += 0.15
            explanation_parts.append(f"strategy={s.strategy.mode}")
        if s and s.mappings:
            score += 0.15
            explanation_parts.append(f"{len(s.mappings)} mappings")

        warning = ""
        if s and not s.pair_id:
            warning = "No pair_id — direction is unclear"
        if s and not s.mappings:
            warning = "No mappings defined — direction is vague"

        return DimensionalScore(
            name="direction",
            score=min(score, 1.0),
            explanation="; ".join(explanation_parts) if explanation_parts else "No schema data",
            warning=warning,
        )

    def _score_architecture(self) -> DimensionalScore:
        """Score architecture quality."""
        s = self.schema
        score = 0.0
        explanation_parts = []
        warning = ""

        if s and s.strategy:
            score += 0.25
            if s.strategy.rationale:
                score += 0.15
                explanation_parts.append("strategy with rationale")

        if s and s.capability_alignment:
            score += 0.2
            ca = s.capability_alignment
            if ca.overall_score > 0.5:
                score += 0.1
            explanation_parts.append(f"capability alignment={ca.overall_score:.2f}")

        # Mappings completeness
        if s and s.mappings:
            avg_conf = sum(getattr(m, "confidence", 0) for m in s.mappings) / len(s.mappings)
            if avg_conf > 0.7:
                score += 0.2
                explanation_parts.append(f"avg confidence={avg_conf:.2f}")
            else:
                score += 0.1
                explanation_parts.append(f"avg confidence={avg_conf:.2f} (low)")
        else:
            warning = "No mappings — architecture is incomplete"

        if s and s.output_dir:
            score += 0.1
            explanation_parts.append("with output dir")

        return DimensionalScore(
            name="architecture",
            score=min(score, 1.0),
            explanation="; ".join(explanation_parts) if explanation_parts else "No schema data",
            warning=warning,
        )

    def _score_stack(self) -> DimensionalScore:
        """Score tech stack appropriateness."""
        s = self.schema
        score = 0.3  # baseline
        explanation_parts = ["baseline=0.3"]
        warning = ""

        if s and s.strategy:
            mode = s.strategy.mode
            if mode == "import":
                score += 0.3
                explanation_parts.append("same-language (high confidence)")
            elif mode == "subprocess_json":
                score += 0.15
                explanation_parts.append("cross-language (universal)")
            elif mode == "pyo3":
                score += 0.1
                explanation_parts.append("native extension (scaffold)")
            elif mode == "ffi_cffi":
                score += 0.1
                explanation_parts.append("FFI (scaffold)")

        if s and s.src and s.dst:
            if s.src.language == s.dst.language:
                score += 0.2
                explanation_parts.append(f"same language: {s.src.language}")
            else:
                score += 0.1
                explanation_parts.append(f"cross-language: {s.src.language}->{s.dst.language}")

        if s and s.src and s.src.capability and s.src.capability.license:
            explanation_parts.append(f"src license: {s.src.capability.license}")
        if s and s.dst and s.dst.capability and s.dst.capability.license:
            explanation_parts.append(f"dst license: {s.dst.capability.license}")

        return DimensionalScore(
            name="stack",
            score=min(score, 1.0),
            explanation="; ".join(explanation_parts),
            warning=warning,
        )

    def _score_feasibility(self) -> DimensionalScore:
        """Score practical feasibility."""
        s = self.schema
        score = 0.5  # baseline
        explanation_parts = ["baseline=0.5"]
        warning = ""

        if s and s.mappings:
            total = len(s.mappings)
            low_conf = sum(1 for m in s.mappings if getattr(m, "confidence", 0) < 0.5)
            high_conf = total - low_conf
            ratio = high_conf / total if total > 0 else 0
            if ratio > 0.8:
                score += 0.2
                explanation_parts.append(f"{high_conf}/{total} high-confidence")
            elif ratio > 0.5:
                score += 0.1
                explanation_parts.append(f"{high_conf}/{total} high-confidence")
            else:
                score -= 0.1
                warning = f"Only {high_conf}/{total} mappings are high-confidence"

        if s and s.capability_alignment:
            ca = s.capability_alignment
            if ca.overall_score > 0.7:
                score += 0.15
                explanation_parts.append(f"strong alignment ({ca.overall_score:.2f})")
            elif ca.overall_score > 0.4:
                score += 0.05
                explanation_parts.append(f"moderate alignment ({ca.overall_score:.2f})")
            else:
                score -= 0.1
                warning = f"Weak alignment ({ca.overall_score:.2f}) — may not work well together"

        if s and s.strategy and s.strategy.rationale:
            score += 0.1
            explanation_parts.append("strategy rationale provided")

        return DimensionalScore(
            name="feasibility",
            score=max(0.0, min(score, 1.0)),
            explanation="; ".join(explanation_parts),
            warning=warning,
        )

    def _score_risk(self) -> DimensionalScore:
        """Score risk awareness. Higher = more risk-aware (lower risk)."""
        s = self.schema
        score = 0.3  # baseline — we assume risk until provenotherwise
        explanation_parts = ["baseline=0.3"]
        warning = ""

        if s and s.strategy:
            mode = s.strategy.mode
            if mode == "import":
                score += 0.25
                explanation_parts.append("same-language (low risk)")
            elif mode == "subprocess_json":
                score += 0.1
                explanation_parts.append("cross-language (medium risk)")
            else:
                score += 0.05
                explanation_parts.append("native/FFI (high risk)")

        if s and s.mappings:
            has_low_conf = any(getattr(m, "confidence", 0) < 0.5 for m in s.mappings)
            if has_low_conf:
                warning = "Has low-confidence mappings — review required"
            else:
                score += 0.15
                explanation_parts.append("all mappings high-confidence")

        if s and s.capability_alignment:
            ca = s.capability_alignment
            if ca.warnings:
                score += 0.1  # at least they're aware
                warning_count = len(ca.warnings)
                if warning_count > 3:
                    score -= 0.1
                explanation_parts.append(f"{warning_count} alignment warnings documented")

        if s and s.generated_files:
            score += 0.1
            explanation_parts.append(f"{len(s.generated_files)} files generated")

        return DimensionalScore(
            name="risk",
            score=max(0.0, min(score, 1.0)),
            explanation="; ".join(explanation_parts),
            warning=warning,
        )

    def _score_focus(self) -> DimensionalScore:
        """Score whether the plan stays on target vs scope-creep."""
        s = self.schema
        score = 0.5  # baseline
        explanation_parts = ["baseline=0.5"]
        warning = ""

        if s:
            # Fewer mappings = more focused
            mapping_count = len(s.mappings) if s.mappings else 0
            if mapping_count == 0:
                score -= 0.2
                warning = "No mappings defined — unclear focus"
            elif mapping_count <= 3:
                score += 0.2
                explanation_parts.append(f"{mapping_count} mappings (focused)")
            elif mapping_count <= 8:
                score += 0.1
                explanation_parts.append(f"{mapping_count} mappings (moderate)")
            else:
                score -= 0.1
                warning = f"{mapping_count} mappings — possible scope creep"

        if s and s.capability_alignment:
            explanation_parts.append("capability alignment present")

        return DimensionalScore(
            name="focus",
            score=max(0.0, min(score, 1.0)),
            explanation="; ".join(explanation_parts),
            warning=warning,
        )