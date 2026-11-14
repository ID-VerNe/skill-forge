"""Offline regression tests for issue #59 phase 3 data completeness gates."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_ROOT)


# @lat: [[tests#Issue 59 Phase 3]]
class DeepCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "repos" / "owner-demo").mkdir(parents=True)

    def write_session(self, *, clone_results=None, requirements=None):
        session = {
            "project": "test-project",
            "requirements": requirements if requirements is not None else ["device detection"],
            "candidate_repos": [{
                "name": "demo",
                "url": "https://github.com/owner/demo",
                "slug": "owner-demo",
                "local_path": str(self.root / "repos" / "owner-demo" / "source"),
                "commit": "abc123",
            }],
            "candidate_count": 1 if clone_results is None else len(clone_results),
            "clone_results": clone_results if clone_results is not None else [{
                "name": "demo", "url": "https://github.com/owner/demo", "slug": "owner-demo",
                "status": "cloned", "commit": "abc123", "error": "",
            }],
            "created_at": "2026-01-01T00:00:00Z",
            "workflow": "test",
        }
        (self.root / "session.json").write_text(json.dumps(session), encoding="utf-8")
        return session

    def write_valid_artifacts(self, *, gaps=None):
        repo_dir = self.root / "repos" / "owner-demo"
        architecture = {
            "repo": "demo", "slug": "owner-demo", "source_path": "source", "commit": "abc123",
            "one_line_summary": "A test repository", "language": "Python",
            "core_modules": [{"name": "main", "path": "main.py", "purpose": "entry"}],
            "key_types": [{"name": "Client", "kind": "class", "file": "main.py", "line": 1}],
            "platform_apis": [],
            "known_gaps": gaps if gaps is not None else [{
                "requirement": "device detection", "status": "supported", "details": "implemented",
            }],
            "confidence": 0.9,
            "evidence": [{"claim": "has detection", "file": "main.py", "line_start": 1, "line_end": 2}],
        }
        (repo_dir / "architecture.md").write_text("# architecture\n", encoding="utf-8")
        (repo_dir / "architecture.json").write_text(json.dumps(architecture), encoding="utf-8")
        (repo_dir / "source_manifest.json").write_text(json.dumps({"files_read": [{"path": "main.py"}]}), encoding="utf-8")
        (repo_dir / "unresolved.md").write_text("None\n", encoding="utf-8")

    def test_requirement_coverage_must_match_exactly_once(self):
        from polyglot.deep.validator import validate_requirement_coverage

        missing = validate_requirement_coverage({"known_gaps": []}, ["device detection"])
        duplicate = validate_requirement_coverage({"known_gaps": [
            {"requirement": "device detection"}, {"requirement": "Device Detection"},
        ]}, ["device detection"])
        complete = validate_requirement_coverage({"known_gaps": [
            {"requirement": " Device   Detection "},
        ]}, ["device detection"])

        self.assertTrue(any("no entry" in msg for status, msg in missing if status == "x"))
        self.assertTrue(any("duplicate" in msg for status, msg in duplicate if status == "x"))
        self.assertEqual(complete[0][0], "v")

    def test_corrupt_architecture_is_validation_error(self):
        self.write_session()
        self.write_valid_artifacts()
        (self.root / "repos" / "owner-demo" / "architecture.json").write_text("{bad", encoding="utf-8")

        from polyglot.deep.validator import validate_all
        result = validate_all(str(self.root))

        self.assertFalse(result["all_pass"])
        self.assertTrue(any("invalid JSON" in error for error in result["errors"]))

    def test_missing_requirement_coverage_blocks_compare_with_nonzero_exit(self):
        self.write_session()
        self.write_valid_artifacts(gaps=[])

        from polyglot.deep.comparer import compare_all, main
        result = compare_all(str(self.root))
        self.assertEqual(result["status"], "data_incomplete")
        self.assertEqual(result["ranking"], [])
        self.assertTrue(any("no entry" in error for error in result["validation_errors"]))

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(str(self.root)), 2)
        comparison = json.loads((self.root / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(comparison["status"], "data_incomplete")
        self.assertEqual(comparison["ranking"], [])

    def test_complete_data_writes_complete_status_and_ranking(self):
        self.write_session()
        self.write_valid_artifacts()

        from polyglot.deep.comparer import compare_all
        result = compare_all(str(self.root))

        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["ranking"]), 1)

    def test_partial_clone_failure_is_persisted_and_blocks_ranking(self):
        clone_results = [
            {"name": "demo", "url": "https://github.com/owner/demo", "slug": "owner-demo",
             "status": "cloned", "commit": "abc123", "error": ""},
            {"name": "other", "url": "https://github.com/other/demo", "slug": "other-demo",
             "status": "failed", "commit": "", "error": "repository not found"},
        ]
        session = self.write_session(clone_results=clone_results)
        session["candidate_count"] = 2
        (self.root / "session.json").write_text(json.dumps(session), encoding="utf-8")
        self.write_valid_artifacts()

        from polyglot.deep.comparer import compare_all
        result = compare_all(str(self.root))

        self.assertEqual(result["status"], "data_incomplete")
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["cloned_count"], 1)
        self.assertEqual(result["clone_failures"][0]["error"], "repository not found")
        self.assertEqual(result["ranking"], [])

    def test_summary_always_preserves_incomplete_banner_and_suppresses_ranking(self):
        session = self.write_session()
        session["clone_results"].append({
            "name": "other", "url": "https://github.com/other/demo", "slug": "other-demo",
            "status": "failed", "commit": "", "error": "not found",
        })
        session["candidate_count"] = 2
        (self.root / "session.json").write_text(json.dumps(session), encoding="utf-8")
        self.write_valid_artifacts()
        (self.root / "comparison.json").write_text(json.dumps({
            "status": "data_incomplete", "validation_failed": True,
            "validation_errors": ["clone failed: not found"], "comparisons": [], "ranking": [],
            "clone_failures": session["clone_results"][1:],
        }), encoding="utf-8")

        from polyglot.deep.summarizer import generate_draft
        draft = generate_draft(str(self.root))

        self.assertIn("DATA INCOMPLETE", draft)
        self.assertIn("Clone failed", draft)
        self.assertIn("not found", draft)
        self.assertIn("Ranking suppressed", draft)
        self.assertNotIn("Top candidate", draft)

    def test_missing_or_corrupt_comparison_is_incomplete_not_success(self):
        self.write_session()
        self.write_valid_artifacts()

        from polyglot.deep.summarizer import generate_draft
        missing_draft = generate_draft(str(self.root))
        self.assertIn("DATA INCOMPLETE", missing_draft)
        self.assertIn("comparison.json is missing", missing_draft)

        (self.root / "comparison.json").write_text("not-json", encoding="utf-8")
        corrupt_draft = generate_draft(str(self.root))
        self.assertIn("comparison.json is invalid", corrupt_draft)
        self.assertNotIn("Top candidate", corrupt_draft)

    def test_stale_or_forged_complete_comparison_cannot_rank(self):
        self.write_session()
        self.write_valid_artifacts()

        from polyglot.deep.comparer import compare_all
        from polyglot.deep.summarizer import generate_draft

        valid = compare_all(str(self.root))
        (self.root / "comparison.json").write_text(json.dumps(valid), encoding="utf-8")
        valid_draft = generate_draft(str(self.root))
        self.assertIn("Top candidate", valid_draft)

        forged = dict(valid)
        forged["ranking"] = [{
            "rank": 1, "slug": "unrelated-repo", "score": 1.0,
            "coverage_ratio": 1.0, "supported": 1, "partial": 0,
            "missing": 0, "confidence": 1.0, "evidence_count": 100,
        }]
        (self.root / "comparison.json").write_text(json.dumps(forged), encoding="utf-8")
        forged_draft = generate_draft(str(self.root))
        self.assertIn("DATA INCOMPLETE", forged_draft)
        self.assertIn("does not match current architecture data", forged_draft)
        self.assertNotIn("Top candidate", forged_draft)

        forged = dict(valid)
        forged["matrix"] = dict(valid["matrix"], repos=["owner-demo", "extra-repo"])
        (self.root / "comparison.json").write_text(json.dumps(forged), encoding="utf-8")
        matrix_draft = generate_draft(str(self.root))
        self.assertIn("DATA INCOMPLETE", matrix_draft)
        self.assertNotIn("Top candidate", matrix_draft)

    def test_incomplete_comparison_without_errors_still_suppresses_ranking(self):
        self.write_session()
        self.write_valid_artifacts()
        (self.root / "comparison.json").write_text(json.dumps({
            "status": "data_incomplete",
            "validation_failed": True,
            "validation_errors": [],
            "clone_failures": [],
            "candidate_count": 1,
            "cloned_count": 1,
            "matrix": {"requirements": [], "repos": [], "matrix": []},
            "comparisons": [],
            "ranking": [],
        }), encoding="utf-8")

        from polyglot.deep.summarizer import generate_draft
        draft = generate_draft(str(self.root))

        self.assertIn("DATA INCOMPLETE", draft)
        self.assertIn("comparison is marked validation_failed", draft)
        self.assertNotIn("Top candidate", draft)

    def test_missing_or_corrupt_session_fails_closed_in_compare_and_summary(self):
        from polyglot.deep.comparer import compare_all, main
        from polyglot.deep.summarizer import generate_draft

        missing_result = compare_all(str(self.root))
        self.assertEqual(missing_result["status"], "data_incomplete")
        self.assertEqual(missing_result["ranking"], [])
        self.assertIn("missing", missing_result["error"])
        self.assertEqual(main(str(self.root)), 1)
        self.assertIn("DATA INCOMPLETE", generate_draft(str(self.root)))

        (self.root / "session.json").write_text("not-json", encoding="utf-8")
        corrupt_result = compare_all(str(self.root))
        self.assertEqual(corrupt_result["status"], "data_incomplete")
        self.assertEqual(corrupt_result["ranking"], [])
        self.assertIn("invalid", corrupt_result["error"])
        self.assertIn("invalid or unreadable", generate_draft(str(self.root)))

    # @lat: [[tests#Issue 59 Phase 3#deep-summarize returns nonzero for incomplete data]]
    def test_summarize_returns_nonzero_for_incomplete_data_and_zero_when_complete(self):
        import argparse

        from polyglot.commands.deep import cmd_deep_summarize
        from polyglot.deep.comparer import compare_all
        from polyglot.deep.summarizer import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(str(self.root)), 1)
        self.assertIn("DATA INCOMPLETE", (self.root / "final-report-draft.md").read_text(encoding="utf-8"))
        self.assertIn("incomplete data", output.getvalue())

        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cmd_deep_summarize(argparse.Namespace(dir=str(self.root)))
        self.assertEqual(raised.exception.code, 1)

        self.write_session()
        self.write_valid_artifacts()
        (self.root / "comparison.json").write_text(
            json.dumps(compare_all(str(self.root))), encoding="utf-8"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(str(self.root)), 0)

        comparison = json.loads((self.root / "comparison.json").read_text(encoding="utf-8"))
        comparison["status"] = "data_incomplete"
        comparison["validation_failed"] = True
        comparison["validation_errors"] = ["candidate data is incomplete"]
        (self.root / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(str(self.root)), 2)

    # @lat: [[tests#Issue 59 Phase 3#deep-summarize handles malformed comparison shapes]]
    def test_summarize_fails_closed_when_matrix_repos_is_not_an_array(self):
        from polyglot.deep.comparer import compare_all
        from polyglot.deep.summarizer import main

        self.write_session()
        self.write_valid_artifacts()
        comparison = compare_all(str(self.root))
        self.assertEqual(comparison["status"], "complete")
        comparison["matrix"]["repos"] = 7
        (self.root / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(str(self.root)), 2)

        draft = (self.root / "final-report-draft.md").read_text(encoding="utf-8")
        self.assertIn("DATA INCOMPLETE", draft)
        self.assertIn("comparison candidate details do not match the current session", draft)
        self.assertNotIn("Top candidate", draft)

    # @lat: [[tests#Issue 59 Phase 3#deep-init avoids case-insensitive slug collisions]]
    def test_deep_init_avoids_case_insensitive_slug_collisions(self):
        import argparse

        from polyglot.commands.deep import cmd_deep_init

        args = argparse.Namespace(
            dir=str(self.root / "initialized"),
            project="test-project",
            requirements=["device detection"],
            target_license="",
            repos=[
                "https://github.com/Owner/Repo",
                "https://github.com/owner/repo",
            ],
        )
        with patch(
            "polyglot.deep.repo_resolver.clone_repo",
            return_value={"success": True, "commit": "abc123", "error": ""},
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_deep_init(args)

        session = json.loads((Path(args.dir) / "session.json").read_text(encoding="utf-8"))
        slugs = [repo["slug"] for repo in session["candidate_repos"]]
        self.assertEqual(len(slugs), 2)
        self.assertEqual(len({slug.casefold() for slug in slugs}), 2)
        self.assertEqual(session["candidate_count"], 2)

    def test_malformed_session_shapes_fail_closed_without_crashing(self):
        (self.root / "session.json").write_text(json.dumps({
            "project": "test-project",
            "requirements": "not-an-array",
            "candidate_repos": [None],
            "candidate_count": 1,
            "clone_results": "not-an-array",
        }), encoding="utf-8")

        from polyglot.deep.comparer import compare_all
        from polyglot.deep.summarizer import generate_draft
        from polyglot.deep.validator import validate_all

        result = compare_all(str(self.root))
        self.assertEqual(result["status"], "data_incomplete")
        self.assertEqual(result["ranking"], [])
        self.assertFalse(validate_all(str(self.root))["all_pass"])
        draft = generate_draft(str(self.root))
        self.assertIn("DATA INCOMPLETE", draft)
        self.assertNotIn("Top candidate", draft)

    def test_architecture_evidence_shape_errors_block_ranking(self):
        self.write_session()
        self.write_valid_artifacts()
        arch_path = self.root / "repos" / "owner-demo" / "architecture.json"
        architecture = json.loads(arch_path.read_text(encoding="utf-8"))
        architecture["evidence"] = [{"claim": "claim without line references"}]
        arch_path.write_text(json.dumps(architecture), encoding="utf-8")

        from polyglot.deep.comparer import compare_all
        result = compare_all(str(self.root))
        self.assertEqual(result["status"], "data_incomplete")
        self.assertEqual(result["ranking"], [])
        self.assertTrue(any("evidence" in error for error in result["validation_errors"]))

    def test_owner_is_part_of_repository_slug(self):
        from polyglot.deep.repo_resolver import url_to_slug

        first = url_to_slug("https://github.com/alpha/tool.git")
        second = url_to_slug("git@github.com:beta/tool.git")

        self.assertNotEqual(first, second)
        self.assertIn("alpha", first)
        self.assertIn("beta", second)

    def test_clone_results_are_recorded_for_success_and_failure(self):
        from polyglot.deep.outputs import create_session, record_clone_result

        create_session(str(self.root), "project", ["requirement"])
        session = json.loads((self.root / "session.json").read_text(encoding="utf-8"))
        record_clone_result(str(self.root), session, name="ok", url="ok/repo", slug="ok-repo", success=True, commit="abc")
        record_clone_result(str(self.root), session, name="bad", url="bad/repo", slug="bad-repo", success=False, error="offline")
        saved = json.loads((self.root / "session.json").read_text(encoding="utf-8"))

        self.assertEqual(saved["candidate_count"], 2)
        self.assertEqual([item["status"] for item in saved["clone_results"]], ["cloned", "failed"])
        self.assertEqual(saved["clone_results"][1]["error"], "offline")


if __name__ == "__main__":
    unittest.main()
