"""Regression tests for issue #59 phase 1 CLI and dependency behavior."""

import argparse
import builtins
import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_ROOT)


class CapMatchTests(unittest.TestCase):
    # @lat: [[tests#Issue 59 Phase 1#cap-match missing registry entry is a CLI error]]
    def test_missing_capability_exits_with_readable_error(self):
        from polyglot.commands.glue import cmd_cap_match

        registry = type("Registry", (), {"get": lambda self, name, lang: None})()
        args = argparse.Namespace(
            src="unknown-source",
            src_lang="python",
            dst="known-destination",
            dst_lang="rust",
            format="markdown",
        )
        stderr = io.StringIO()

        with patch("polyglot.glue.capability_ontology.get_registry", return_value=registry):
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                cmd_cap_match(args)

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("No capability entry for python:unknown-source", stderr.getvalue())


class DeepModeCliTests(unittest.TestCase):
    # @lat: [[tests#Issue 59 Phase 1#Deep Mode directory options parse]]
    def test_deep_commands_accept_documented_dir_option(self):
        from polyglot.router import _build_parser

        parser = _build_parser()
        for command in ("deep-pack", "deep-validate", "deep-compare", "deep-summarize", "deep-clean"):
            with self.subTest(command=command):
                args = parser.parse_args([command, "--dir", ".glue/deep"])
                self.assertEqual(args.dir, ".glue/deep")

    # @lat: [[tests#Issue 59 Phase 1#Deep Mode requirements parse as separate values]]
    def test_deep_init_accepts_requirements_as_separate_arguments(self):
        from polyglot.router import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "deep-init",
            "--project", "demo",
            "--requirements", "device detection", "macro support",
            "--repos", "https://github.com/example/demo",
        ])

        self.assertEqual(args.requirements, ["device detection", "macro support"])


class DeepValidationDependencyTests(unittest.TestCase):
    # @lat: [[tests#Issue 59 Phase 1#Missing jsonschema reports installation guidance]]
    def test_missing_jsonschema_returns_install_hint(self):
        from polyglot.deep.validator import validate_architecture_schema

        real_import = builtins.__import__

        def import_without_jsonschema(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("simulated missing optional dependency")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_jsonschema):
            results = validate_architecture_schema({})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "x")
        self.assertIn("jsonschema", results[0][1])
        self.assertIn('python -m pip install "jsonschema>=4.18"', results[0][1])

    # @lat: [[tests#Issue 59 Phase 1#jsonschema is declared as a runtime dependency]]
    def test_jsonschema_is_declared_as_a_runtime_dependency(self):
        requirements_path = os.path.join(SKILL_ROOT, "polyglot", "requirements.txt")
        with open(requirements_path, encoding="utf-8") as requirements_file:
            requirements = requirements_file.read().lower()

        self.assertRegex(requirements, r"(?m)^jsonschema(?:[<>=!~].*)?$")


if __name__ == "__main__":
    unittest.main()
