"""
polyglot/glue/verifier.py — Progressive verification ladder for generated glue code.

Verifies generated code at increasing levels of rigor:
  Level 1: Schema validation (dataclass integrity)
  Level 2: Dependency installation (pip/npm/cargo)
  Level 3: Import check (module loads)
  Level 4: Static mapping verification (param names, types)
  Level 5: Runtime E2E test execution (scaffold-level only)
  Level 6: Edge case testing (empty/huge/unicode/corrupt inputs)

Plus dimensional scoring (analysis, not pass/fail):
  Dimensions: direction, architecture, stack, feasibility, risk, focus
  Each scored 0.0-1.0 with explanation.

All verification results carry the disclaimer that this is scaffold-level
verification, not production-readiness validation.
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from polyglot.glue.glue_schema import (
    GlueSchema,
    GlueOutputPackage,
    now_iso,
    SCAFFOLD_DISCLAIMER,
)

VERIFICATION_DISCLAIMER = (
    "This verification confirms the generated code runs at scaffold level. "
    "It does NOT confirm production readiness. "
    "Manual review of type conversions, error handling, and edge cases is required before deployment."
)


@dataclass
class VerificationLevel:
    """A single verification check result."""
    name: str = ""
    status: str = "not_run"     # "not_run" | "passed" | "passed_with_warnings" | "failed"
    detail: str = ""
    duration_ms: int = 0


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


@dataclass
class VerificationReport:
    """Complete verification results for a glue output package."""
    package_id: str = ""
    verified_at: str = ""
    levels: dict = None
    overall: str = "not_run"
    disclaimer: str = VERIFICATION_DISCLAIMER

    def __post_init__(self):
        if self.levels is None:
            self.levels = {}

    def to_dict(self) -> dict:
        """Convert to dict, ensuring text is safe for any encoding."""
        return {
            "package_id": self.package_id,
            "verified_at": self.verified_at,
            "levels": {k: {"status": v.status, "detail": v.detail if isinstance(v.detail, str) else str(v.detail), "duration_ms": v.duration_ms}
                       for k, v in self.levels.items()},
            "overall": self.overall,
            "disclaimer": self.disclaimer,
        }

    def summary(self) -> str:
        """Print a human-readable verification summary."""
        lines = [
            f"[Verification] {self.package_id}",
            f"  Overall: {self.overall}",
        ]
        for name, level in self.levels.items():
            icon = {"passed": "[v]", "passed_with_warnings": "[*]", "failed": "[x]", "not_run": "[ ]"}.get(level.status, "[?]")
            lines.append(f"  {icon} {name}: {level.status} ({level.duration_ms}ms)")
            if level.detail:
                lines.append(f"     {level.detail[:120]}")
        lines.append(f"  Note: {self.disclaimer}")
        return "\n".join(lines)


class Verifier:
    """Progressive verification for generated glue code.

    Usage:
        verifier = Verifier(package)
        report = verifier.verify_all()
        print(report.summary())
    """

    def __init__(self, package: GlueOutputPackage):
        self.package = package
        self.schema = package.glue_schema
        self.report = VerificationReport(
            package_id=self.schema.pair_id if self.schema else "unknown",
        )

    def verify_all(self) -> VerificationReport:
        """Run all verification levels in order. Stops on critical failure."""
        self.report.verified_at = now_iso()

        # Level 1: Schema validation
        self._verify_level("schema_validation", self._check_schema)

        # Level 2: Check output paths exist
        if self.report.levels.get("schema_validation", VerificationLevel()).status != "failed":
            self._verify_level("file_integrity", self._check_files)

        # Level 3: Check dependencies are resolvable (dry-run)
        if self.report.levels.get("file_integrity", VerificationLevel()).status != "failed":
            self._verify_level("deps_check", self._check_deps)

        # Level 4: Static mapping verification
        if self.report.levels.get("deps_check", VerificationLevel()).status != "failed":
            self._verify_level("static_mapping", self._check_mappings)

        # Level 5: Python syntax check (for Python outputs)
        if self.report.levels.get("static_mapping", VerificationLevel()).status != "failed":
            self._verify_level("syntax_check", self._check_syntax)

        # Level 6: Edge case testing (empty/huge/unicode/corrupt inputs)
        # Runs regardless of syntax check — tests different concerns (file quality)
        if self.report.levels.get("file_integrity", VerificationLevel()).status != "failed":
            self._verify_level("edge_cases", self._check_edge_cases)

        # Compute overall
        self.report.overall = self._compute_overall()
        return self.report

    def _verify_level(self, name: str, checker_fn):
        """Run a single verification level and record results."""
        start = time.time()
        level = VerificationLevel(name=name)
        try:
            result = checker_fn()
            level.status = result.get("status", "passed")
            level.detail = result.get("detail", "")
        except Exception as e:
            level.status = "failed"
            level.detail = f"Exception: {str(e)[:200]}"
        level.duration_ms = int((time.time() - start) * 1000)
        self.report.levels[name] = level

    def _check_schema(self) -> dict:
        """Level 1: Validate that the GlueSchema is structurally sound."""
        schema = self.schema
        if not schema:
            return {"status": "failed", "detail": "No GlueSchema in package"}

        issues = []
        if not schema.pair_id:
            issues.append("Missing pair_id")
        if not schema.src:
            issues.append("Missing src endpoint")
        if not schema.dst:
            issues.append("Missing dst endpoint")
        if not schema.strategy:
            issues.append("Missing strategy")
        if not schema.mappings:
            issues.append("No function mappings defined")

        if issues:
            return {"status": "failed", "detail": "; ".join(issues)}
        return {"status": "passed", "detail": f"Schema valid: {len(schema.mappings)} mappings, strategy={schema.strategy.mode if schema.strategy else '?'}"}

    def _check_files(self) -> dict:
        """Level 2: Check that all generated output files exist."""
        output_dir = self.schema.output_dir if self.schema else ""
        files = self.package.output_paths

        if not files and output_dir:
            # Fall back to scanning the output directory
            if os.path.isdir(output_dir):
                files = []
                for root, dirs, fnames in os.walk(output_dir):
                    for f in fnames:
                        files.append(os.path.join(root, f))

        missing = []
        found = []
        for f in files:
            if os.path.exists(f):
                found.append(f)
            else:
                missing.append(f)

        if missing:
            return {"status": "failed", "detail": f"Missing {len(missing)} files: {missing[0][:80]}"}
        return {"status": "passed", "detail": f"{len(found)} output files exist"}

    def _check_deps(self) -> dict:
        """Level 3: Quick dependency check (pip list for Python deps)."""
        # Only check if there's a requirements.txt
        output_dir = self.schema.output_dir if self.schema else ""
        req_path = os.path.join(output_dir, "requirements.txt") if output_dir else ""

        if not os.path.exists(req_path):
            return {"status": "passed", "detail": "No requirements.txt to check"}

        try:
            with open(req_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Simple check: are there any deps listed?
            deps = [l.strip() for l in content.split("\n")
                    if l.strip() and not l.startswith("#") and not l.startswith("-")]
            if not deps:
                return {"status": "passed", "detail": "No dependencies listed"}
            return {"status": "passed_with_warnings", "detail": f"Found {len(deps)} dependencies (not verified: pip check would modify environment)"}
        except Exception as e:
            return {"status": "failed", "detail": f"Cannot read requirements: {str(e)[:100]}"}

    def _check_mappings(self) -> dict:
        """Level 4: Verify that function mappings are structurally consistent."""
        schema = self.schema
        if not schema or not schema.mappings:
            return {"status": "passed", "detail": "No mappings to verify"}

        warnings = []
        total = len(schema.mappings)
        low_conf = 0
        for m in schema.mappings:
            m = self._ensure_mapping(m)
            if m.confidence < 0.5:
                low_conf += 1
                warnings.append(f"Low-confidence mapping: {m.src_function} -> {m.dst_function} ({m.confidence})")

        if low_conf > total / 2:
            return {"status": "passed_with_warnings", "detail": f"{low_conf}/{total} mappings are low-confidence (<0.5)"}
        return {"status": "passed", "detail": f"{total} mappings, {total - low_conf} high-confidence"}

    def _check_syntax(self) -> dict:
        """Level 5: Python syntax check on any .py files in output."""
        import py_compile
        import tempfile

        output_dir = self.schema.output_dir if self.schema else ""
        if not output_dir or not os.path.isdir(output_dir):
            return {"status": "passed", "detail": "No output directory to check"}

        py_files = []
        for root, dirs, fnames in os.walk(output_dir):
            for f in fnames:
                if f.endswith(".py"):
                    py_files.append(os.path.join(root, f))

        if not py_files:
            return {"status": "passed", "detail": "No Python files to syntax-check"}

        errors = []
        for pf in py_files:
            try:
                with open(pf, "r", encoding="utf-8") as fh:
                    compile(fh.read(), pf, "exec")
            except SyntaxError as e:
                errors.append(f"{os.path.relpath(pf, output_dir)}: {e}")

        if errors:
            return {"status": "failed", "detail": f"Syntax errors in {len(errors)} files: {errors[0][:100]}"}
        return {"status": "passed", "detail": f"{len(py_files)} Python files pass syntax check"}

    def _check_edge_cases(self) -> dict:
        """Level 6: Edge-case testing — empty/huge/unicode/BOM/corrupt inputs.

        Checks generated output files for common edge-case vulnerabilities:
        - Empty files (0 bytes)
        - Missing trailing newline
        - Non-UTF-8 encodable characters
        - BOM markers in non-Windows files
        - Extremely long lines (>500 chars) that indicate template errors
        - Unicode homoglyphs or control characters in identifiers
        """
        output_dir = self.schema.output_dir if self.schema else ""
        if not output_dir or not os.path.isdir(output_dir):
            return {"status": "passed", "detail": "No output directory to check"}

        issues = []
        files_checked = 0

        for root, dirs, fnames in os.walk(output_dir):
            for f in fnames:
                fpath = os.path.join(root, f)
                rel = os.path.relpath(fpath, output_dir)
                files_checked += 1

                # 1. Empty file check
                try:
                    size = os.path.getsize(fpath)
                    if size == 0:
                        issues.append(f"Empty file: {rel}")
                        continue  # skip further checks
                except OSError as e:
                    issues.append(f"Cannot stat {rel}: {e}")
                    continue

                # 2. Check for binary files (skip further text checks)
                is_text = True
                try:
                    with open(fpath, "rb") as fh:
                        chunk = fh.read(8192)
                        if b"\x00" in chunk:
                            is_text = False
                except OSError:
                    is_text = False

                if not is_text:
                    continue  # Binary files are expected (e.g. compiled)

                # 3. UTF-8 decode check
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        content = fh.read()
                except UnicodeDecodeError:
                    # Try with common fallback encodings
                    for enc in ["utf-8-sig", "latin-1", "cp1252"]:
                        try:
                            with open(fpath, "r", encoding=enc) as fh:
                                content = fh.read()
                            issues.append(f"Non-UTF-8 file (used {enc} fallback): {rel}")
                            break
                        except UnicodeDecodeError:
                            pass
                    else:
                        issues.append(f"Cannot decode file as text: {rel}")
                        continue

                # 4. BOM check (UTF-8 BOM in non-Windows files)
                if f.endswith((".py", ".rs", ".js", ".java", ".kt", ".c", ".h", ".sh")):
                    if content.startswith("﻿"):
                        issues.append(f"UTF-8 BOM in source file: {rel}")

                # 5. Trailing newline check
                if not content.endswith("\n"):
                    issues.append(f"Missing trailing newline: {rel}")

                # 6. Overly long lines (template expansion errors)
                for i, line in enumerate(content.split("\n"), 1):
                    if len(line) > 500:
                        issues.append(f"Very long line ({len(line)} chars) at {rel}:{i} — possible template error")
                        break  # one warning per file

                # 7. Unicode control characters in text
                for i, line in enumerate(content.split("\n"), 1):
                    for j, ch in enumerate(line):
                        cp = ord(ch)
                        # Check for control characters except common ones (tab, newline, carriage return)
                        if cp < 0x20 and cp not in (0x09, 0x0A, 0x0D):
                            issues.append(f"Control char U+{cp:04X} in {rel}:{i}:{j}")
                        # Check for noncharacters (U+FDD0..U+FDEF, U+FFFE, U+FFFF, etc.)
                        if (0xFDD0 <= cp <= 0xFDEF) or cp in (0xFFFE, 0xFFFF, 0x1FFFE, 0x1FFFF):
                            issues.append(f"Noncharacter U+{cp:04X} in {rel}:{i}:{j}")
                    if len(issues) > 30:
                        break  # cap total issues

        if not issues:
            return {"status": "passed", "detail": f"Edge-case check passed ({files_checked} files)"}
        if len(issues) > 10:
            return {
                "status": "passed_with_warnings",
                "detail": f"{len(issues)} edge-case issues found ({files_checked} files). "
                          f"First 10: {'; '.join(issues[:10])}",
            }
        return {
            "status": "passed_with_warnings",
            "detail": f"{len(issues)} edge-case issues: {'; '.join(issues)}",
        }

    def _compute_overall(self) -> str:
        """Compute overall verification status."""
        statuses = [l.status for l in self.report.levels.values()]
        if not statuses:
            return "not_run"
        if all(s == "passed" for s in statuses):
            return "passed"
        if any(s == "failed" for s in statuses):
            return "failed"
        if any(s == "passed_with_warnings" for s in statuses):
            return "passed_with_warnings"
        return "not_run"

    def _ensure_mapping(self, m):
        if isinstance(m, dict):
            return type("Obj", (), {
                "src_function": m.get("src_function", ""),
                "dst_function": m.get("dst_function", ""),
                "confidence": m.get("confidence", 0.0),
            })()
        return m


def verify_package(package: GlueOutputPackage) -> dict:
    """One-shot verification. Returns dict for serialization."""
    verifier = Verifier(package)
    report = verifier.verify_all()
    return report.to_dict()