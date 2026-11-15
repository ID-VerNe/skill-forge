"""Offline regression tests for issue #59 phase 4 CLI consistency."""

import contextlib
import io
import json
import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch


SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_ROOT)


class CrossSearchPhase4Tests(unittest.TestCase):
    # @lat: [[tests#Issue 59 Phase 4#Default cross-search ecosystem inventory]]
    def test_default_search_targets_all_scout_backends(self):
        from polyglot.glue.search_types import BatchSearchConfig, SUPPORTED_SCOUT_LANGUAGES

        defaults = BatchSearchConfig(query="test").languages
        self.assertEqual(defaults, list(SUPPORTED_SCOUT_LANGUAGES))
        self.assertEqual(set(defaults), {"python", "javascript", "rust", "java", "kotlin", "c_cpp", "php", "go"})

    # @lat: [[tests#Issue 59 Phase 4#Cross-search backend exceptions are visible]]
    def test_backend_exception_is_returned_in_structured_errors(self):
        from polyglot.glue.aggregator import CrossLangScoutEngine

        engine = CrossLangScoutEngine()
        engine._import_scout = lambda _lang: (_ for _ in ()).throw(ImportError("offline test failure"))
        view = engine.batch_search("query", languages=["python"])

        self.assertEqual(view.errors, {"python": "offline test failure"})
        self.assertEqual(view.targets, ["python"])
        self.assertIn("(partial)", view.summary())
        self.assertIn("offline test failure", view.summary())

    # @lat: [[tests#Issue 59 Phase 4#Backend errors retain partial results]]
    def test_backend_reported_error_is_preserved_with_partial_results(self):
        from polyglot.glue.aggregator import CrossLangScoutEngine

        engine = CrossLangScoutEngine()
        engine._import_scout = lambda _lang: SimpleNamespace(
            search=lambda *_args, **_kwargs: {
                "results": [{"name": "demo", "version": "1.0"}],
                "errors": ["registry unavailable"],
            }
        )
        view = engine.batch_search("query", languages=["python"])

        self.assertEqual(view.coverage, {"python": 1})
        self.assertEqual(view.errors, {"python": "registry unavailable"})
        self.assertEqual([candidate.name for candidate in view.candidates], ["demo"])

    # @lat: [[tests#Issue 59 Phase 4#Deadline rejects late worker outcomes]]
    def test_result_completed_after_deadline_is_rejected_even_if_collected_later(self):
        from polyglot.glue.aggregator import CrossLangScoutEngine
        from polyglot.glue.search_types import BatchSearchConfig

        release_worker = threading.Event()

        def late_search(*_args, **_kwargs):
            release_worker.wait(timeout=1)
            return {"results": [{"name": "late-result"}], "errors": []}

        engine = CrossLangScoutEngine(BatchSearchConfig(query="", timeout_per_lang=0.04))
        engine._import_scout = lambda lang: SimpleNamespace(
            search=(lambda *_args, **_kwargs: {"results": [], "errors": []})
            if lang == "fast" else late_search
        )
        try:
            view = engine.batch_search("query", languages=["slow", "fast"])
        finally:
            release_worker.set()

        self.assertEqual(view.errors, {"slow": "Timed out after 0.04 seconds"})
        self.assertEqual(view.coverage, {"fast": 0})
        self.assertEqual(view.candidates, [])

    # @lat: [[tests#Issue 59 Phase 4#Cross-search timeouts are explicit]]
    def test_slow_backend_is_reported_as_timeout_and_late_result_is_ignored(self):
        from polyglot.glue.aggregator import CrossLangScoutEngine
        from polyglot.glue.search_types import BatchSearchConfig

        release_worker = threading.Event()

        def slow_search(*_args, **_kwargs):
            release_worker.wait(timeout=1)
            return {"results": [{"name": "late-result"}], "errors": []}

        engine = CrossLangScoutEngine(BatchSearchConfig(query="", timeout_per_lang=0.02))
        engine._import_scout = lambda _lang: SimpleNamespace(search=slow_search)
        try:
            view = engine.batch_search("query", languages=["python"])
        finally:
            release_worker.set()

        self.assertEqual(view.errors, {"python": "Timed out after 0.02 seconds"})
        self.assertEqual(view.coverage, {})
        self.assertEqual(view.candidates, [])

    # @lat: [[tests#Issue 59 Phase 4#Cross-search CLI exposes status and backend inventory]]
    def test_cross_search_json_cli_exposes_status_errors_and_supported_languages(self):
        from polyglot.commands.glue import cmd_cross_search
        from polyglot.glue.search_types import CrossLangSearchView, SUPPORTED_SCOUT_LANGUAGES

        view = CrossLangSearchView(
            query="query",
            targets=["python", "go"],
            errors={"go": "Timed out after 1 seconds"},
        )
        with patch("polyglot.glue.aggregator.CrossLangScoutEngine") as engine_class:
            engine_class.return_value.batch_search.return_value = view
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cmd_cross_search(SimpleNamespace(keyword="query", languages="python,go", limit=5, format="json"))

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"]["go"], "Timed out after 1 seconds")
        self.assertEqual(result["languages"], ["python", "go"])
        self.assertEqual(result["supported_languages"], list(SUPPORTED_SCOUT_LANGUAGES))

        view.errors = {"go": "registry unavailable"}
        markdown_output = io.StringIO()
        with patch("polyglot.glue.aggregator.CrossLangScoutEngine") as engine_class:
            engine_class.return_value.batch_search.return_value = view
            with contextlib.redirect_stdout(markdown_output):
                cmd_cross_search(SimpleNamespace(keyword="query", languages="python,go", limit=5, format="markdown"))
        self.assertIn("(partial)", markdown_output.getvalue())
        self.assertIn("go error: registry unavailable", markdown_output.getvalue())

    # @lat: [[tests#Issue 59 Phase 4#Cross-search convenience API exposes status]]
    def test_convenience_api_exposes_status_and_supported_languages(self):
        from polyglot.glue.aggregator import cross_search
        from polyglot.glue.search_types import CrossLangSearchView

        with patch("polyglot.glue.aggregator.CrossLangScoutEngine") as engine_class:
            engine_class.return_value.batch_search.return_value = CrossLangSearchView(
                query="query", targets=["python"], errors={"python": "timeout"}
            )
            result = cross_search("query", languages=["python"])

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"], {"python": "timeout"})
        self.assertIn("go", result["supported_languages"])

    # @lat: [[tests#Issue 59 Phase 4#Cross-search help lists supported ecosystems]]
    def test_cli_help_documents_supported_search_ecosystems(self):
        from polyglot.router import _build_parser

        help_text = _build_parser().format_help()
        self.assertIn("php", help_text)
        self.assertIn("go", help_text)


class CapabilityRegistryPhase4Tests(unittest.TestCase):
    # @lat: [[tests#Issue 59 Phase 4#Fresh capability registries isolate mutable entries]]
    def test_get_registry_returns_independent_starter_registries(self):
        from polyglot.glue.capability_ontology import get_registry
        from polyglot.glue.capability_types import LibraryCapability

        first = get_registry()
        second = get_registry()
        self.assertIsNot(first, second)
        first.register(LibraryCapability(library="local-only", language="python"))
        self.assertIsNone(second.get("local-only", "python"))
        first.get("requests", "python").io_patterns.append("mutated-locally")
        self.assertNotIn("mutated-locally", second.get("requests", "python").io_patterns)

    # @lat: [[tests#Issue 59 Phase 4#Capability CLI labels heuristic limits]]
    def test_cap_list_and_cap_match_identify_heuristic_scope(self):
        from polyglot.commands.glue import cmd_cap_list, cmd_cap_match

        list_output = io.StringIO()
        with contextlib.redirect_stdout(list_output):
            cmd_cap_list(SimpleNamespace(format="markdown"))
        self.assertIn("limited and manually curated", list_output.getvalue())
        self.assertIn("not a complete/live package index", list_output.getvalue())

        match_output = io.StringIO()
        with contextlib.redirect_stdout(match_output):
            cmd_cap_match(SimpleNamespace(
                src_lang="python", src="orjson", dst_lang="rust", dst="serde_json", format="json"
            ))
        result = json.loads(match_output.getvalue())
        self.assertEqual(result["status"], "heuristic_only")
        self.assertIn("not legal advice", result["notice"])

    # @lat: [[tests#Issue 59 Phase 4#Capability JSON declares curated starter scope]]
    def test_cap_list_json_declares_curated_starter_scope(self):
        from polyglot.commands.glue import cmd_cap_list

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cmd_cap_list(SimpleNamespace(format="json"))

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "curated_starter")
        self.assertEqual(result["scope"], "limited_manual_dataset")
        self.assertIn("not a complete or live package index", result["notice"])
        self.assertTrue(any(entry["key"] == "python:requests" for entry in result["entries"]))


if __name__ == "__main__":
    unittest.main()
