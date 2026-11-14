"""Regression tests for issue #59 phase 2 bridge mapping behavior."""

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_ROOT)


class BridgeMappingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def write_mapping_file(self, mappings):
        path = self.root / "mappings.json"
        path.write_text(json.dumps({"mappings": mappings}), encoding="utf-8")
        return str(path)

    def bridge_args(self, output_dir, **overrides):
        values = {
            "src_lang": "python",
            "src": "source_fixture",
            "dst_lang": "python",
            "dst": "dest_fixture",
            "output_dir": str(output_dir),
            "dry_run": False,
            "skip_verify": False,
            "format": "json",
            "mappings": None,
            "scaffold_only": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def call_bridge(self, args):
        from polyglot.commands.glue import cmd_bridge

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            try:
                cmd_bridge(args)
            except SystemExit as exc:
                return exc.code, stdout.getvalue()
        return 0, stdout.getvalue()

    def test_missing_mappings_fail_without_writing_files(self):
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(self.bridge_args(output_dir))

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "mappings_required")
        self.assertFalse(output_dir.exists())

    def test_scaffold_only_is_explicit_and_reported(self):
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, scaffold_only=True)
        )

        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "scaffold_only")
        self.assertTrue(result["scaffold_only"])
        self.assertEqual(result["mappings_count"], 0)
        self.assertTrue(output_dir.exists())

    def test_only_reviewed_mappings_reach_schema_and_generator(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "reviewed-fetch",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "review_note": "Manually checked against both APIs.",
                "param_mappings": [
                    {"src_name": "url", "dst_name": "address"}
                ],
            },
            {
                "review_status": "unreviewed",
                "src_function": "not-valid-python-name!",
                "param_mappings": "candidate metadata is ignored until reviewed",
            },
        ])
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path)
        )

        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["mappings_count"], 1)
        self.assertEqual(result["reviewed_mappings_count"], 1)
        schema_path = output_dir / "source_fixture_dest_fixture" / "schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual([m["mapping_id"] for m in schema["mappings"]], ["reviewed-fetch"])
        generated = (output_dir / "source_fixture_dest_fixture" / "generated" / "glue.py").read_text(encoding="utf-8")
        self.assertIn("lookup(address=url)", generated)
        self.assertNotIn("not-valid-python-name!", generated)

    def test_invalid_reviewed_mapping_shape_fails_before_writing(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "invalid-reviewed",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "param_mappings": [{
                    "src_name": "url",
                    "dst_name": "address",
                    "transform": "identity",
                }],
            }
        ])
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path)
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "input_invalid")
        self.assertFalse(output_dir.exists())

    def test_reviewed_mapping_requires_confidence_label(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "missing-confidence-label",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "review_status": "reviewed",
            }
        ])
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path)
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "input_invalid")
        self.assertFalse(output_dir.exists())

    def test_reviewed_mapping_rejects_unknown_fields(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "unknown-field",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "guessed_transform_code": "dangerous()",
            }
        ])
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path)
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "input_invalid")
        self.assertFalse(output_dir.exists())

    def test_source_parameter_defaults_are_preserved(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "reviewed-fetch-default",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "param_mappings": [{
                    "src_name": "url",
                    "dst_name": "address",
                    "src_default": "'https://example.test'",
                }],
            }
        ])
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path, skip_verify=True)
        )

        self.assertEqual(code, 0)
        generated_path = output_dir / "source_fixture_dest_fixture" / "generated" / "glue.py"
        generated = generated_path.read_text(encoding="utf-8")
        self.assertIn("def fetch_via_dest_fixture(url='https://example.test'):", generated)
        compile(generated, str(generated_path), "exec")

    def test_source_parameter_defaults_are_preserved(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "reviewed-fetch-default",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "param_mappings": [{
                    "src_name": "url",
                    "dst_name": "address",
                    "src_default": "'https://example.test'",
                }],
            }
        ])
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path, skip_verify=True)
        )

        self.assertEqual(code, 0)
        generated_path = output_dir / "source_fixture_dest_fixture" / "generated" / "glue.py"
        generated = generated_path.read_text(encoding="utf-8")
        self.assertIn("def fetch_via_dest_fixture(url='https://example.test'):", generated)
        compile(generated, str(generated_path), "exec")

    def test_identity_transform_objects_are_normalized_in_generated_code(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "reviewed-fetch-transform",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "param_mappings": [
                    {
                        "src_name": "url",
                        "dst_name": "address",
                        "transform": {"kind": "identity", "expr": ""},
                    }
                ],
                "return_transform": {"kind": "identity", "expr": ""},
            }
        ])
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path, skip_verify=True)
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["mappings_count"], 1)
        generated_path = output_dir / "source_fixture_dest_fixture" / "generated" / "glue.py"
        compile(generated_path.read_text(encoding="utf-8"), str(generated_path), "exec")

    def test_invalid_mapping_input_is_machine_readable_and_does_not_write(self):
        path = self.root / "invalid.json"
        path.write_text("{not json", encoding="utf-8")
        output_dir = self.root / "out"

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=str(path))
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "input_invalid")
        self.assertFalse(output_dir.exists())

    def test_unsupported_generator_language_pair_fails_before_writing(self):
        output_dir = self.root / "out"
        mapping_path = self.write_mapping_file([
            {
                "mapping_id": "unsupported-fetch",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
            }
        ])
        args = self.bridge_args(
            output_dir,
            src_lang="javascript",
            dst_lang="rust",
            mappings=mapping_path,
        )

        code, stdout = self.call_bridge(args)

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "unsupported_strategy")
        self.assertFalse(output_dir.exists())

    def test_python_mapping_runs_against_fixture_module(self):
        from polyglot.commands.glue import cmd_bridge

        (self.root / "source_fixture.py").write_text("def fetch(url):\n    return url\n", encoding="utf-8")
        (self.root / "dest_fixture.py").write_text(
            "def lookup(address):\n    return {'address': address, 'ok': True}\n",
            encoding="utf-8",
        )
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "fetch-lookup",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 1.0,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "param_mappings": [
                    {"src_name": "url", "dst_name": "address"}
                ],
            }
        ])
        output_dir = self.root / "out"
        args = self.bridge_args(output_dir, mappings=mappings_path, skip_verify=True)
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_bridge(args)

        generated_path = output_dir / "source_fixture_dest_fixture" / "generated" / "glue.py"
        source = generated_path.read_text(encoding="utf-8")
        compile(source, str(generated_path), "exec")

        sys.path.insert(0, str(self.root))
        sys.path.insert(0, str(generated_path.parent))
        try:
            import importlib

            importlib.invalidate_caches()
            glue = importlib.import_module("glue")
            self.assertEqual(
                glue.fetch_via_dest_fixture("https://example.test"),
                {"address": "https://example.test", "ok": True},
            )
        finally:
            sys.path.remove(str(generated_path.parent))
            sys.path.remove(str(self.root))
            sys.modules.pop("glue", None)
            sys.modules.pop("source_fixture", None)
            sys.modules.pop("dest_fixture", None)

    def test_verifier_reports_compile_but_not_runtime_execution(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "verify-fetch",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 1.0,
                "confidence_label": "identical",
                "review_status": "reviewed",
            }
        ])
        output_dir = self.root / "out"
        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, mappings=mappings_path)
        )

        self.assertEqual(code, 0)
        report = json.loads(stdout)["verification"]
        self.assertEqual(report["levels"]["syntax_check"]["status"], "passed")
        self.assertEqual(report["levels"]["runtime_check"]["status"], "not_run")
        self.assertIn("not executed", report["levels"]["runtime_check"]["detail"].lower())


if __name__ == "__main__":
    unittest.main()
