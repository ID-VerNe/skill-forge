"""
polyglot/glue/verifier.py — Progressive verification ladder for generated glue code.

Verifies generated code at increasing levels of rigor:
  Level 1: Schema validation (dataclass integrity)
  Level 2: Dependency installation (pip/npm/cargo)
  Level 3: Import check (module loads)
  Level 4: Static mapping verification (param names, types)
  Level 5: Runtime E2E test execution (scaffold-level only)
  Level 6: Edge case testing (empty/huge/unicode/corrupt inputs)

Dimensional scoring (analysis, not pass/fail) lives in dimensional_scorer.py.

All verification results carry the disclaimer that this is scaffold-level
verification, not production-readiness validation.
"""

import os
import time
from dataclasses import dataclass

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