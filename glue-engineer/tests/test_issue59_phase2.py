"""Regression tests for issue #59 phase 2 bridge mapping behavior."""

import argparse
import contextlib
import hashlib
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

    def pair_output_dir(self, output_dir, src="source_fixture", dst="dest_fixture"):
        from polyglot.glue.glue_schema import build_pair_id

        return output_dir / build_pair_id(src, dst)

    def test_pair_ids_do_not_collide_when_component_boundaries_overlap(self):
        from polyglot.glue.glue_schema import build_pair_id

        first_pair = build_pair_id("foo_bar", "baz")
        second_pair = build_pair_id("foo", "bar_baz")

        self.assertNotEqual(first_pair, second_pair)
        self.assertNotIn("/", first_pair)
        self.assertNotIn("\\", first_pair)

    def test_pair_id_uses_full_digest_and_bounds_long_components(self):
        from polyglot.glue.glue_schema import build_pair_id

        source_name = "a" * 120
        destination_name = "b" * 120
        pair_id = build_pair_id(source_name, destination_name)
        expected_digest = hashlib.sha256(
            f"{len(source_name)}:{source_name}{len(destination_name)}:{destination_name}".encode("utf-8")
        ).hexdigest()

        self.assertTrue(pair_id.endswith(expected_digest))
        self.assertLessEqual(len(pair_id.encode("ascii")), 255)
        self.assertEqual(len(pair_id.split("_")[-1]), 64)

    def test_long_valid_python_names_generate_with_bounded_pair_directory(self):
        long_src = "s" * 120
        long_dst = "d" * 120
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "long-name-mapping",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
            }
        ])
        output_dir = self.root / "long-output"

        code, stdout = self.call_bridge(
            self.bridge_args(
                output_dir,
                src=long_src,
                dst=long_dst,
                mappings=mappings_path,
                skip_verify=True,
            )
        )

        self.assertEqual(code, 0)
        result = json.loads(stdout)
        pair_id = result["pair_id"]
        self.assertLessEqual(len(pair_id.encode("ascii")), 255)
        self.assertTrue((output_dir / pair_id / "generated" / "glue.py").is_file())

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
        pair_dir = self.pair_output_dir(output_dir)
        schema_path = pair_dir / "schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual([m["mapping_id"] for m in schema["mappings"]], ["reviewed-fetch"])
        generated = (pair_dir / "generated" / "glue.py").read_text(encoding="utf-8")
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
        generated_path = self.pair_output_dir(output_dir) / "generated" / "glue.py"
        generated = generated_path.read_text(encoding="utf-8")
        self.assertIn("def fetch_via_dest_fixture(url='https://example.test'):", generated)
        compile(generated, str(generated_path), "exec")

    def test_required_parameter_cannot_follow_defaulted_parameter(self):
        mappings_path = self.write_mapping_file([
            {
                "mapping_id": "invalid-default-order",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
                "param_mappings": [
                    {"src_name": "optional", "dst_name": "optional", "src_default": "1"},
                    {"src_name": "required", "dst_name": "required"},
                ],
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
        generated_path = self.pair_output_dir(output_dir) / "generated" / "glue.py"
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
        generated_path = self.pair_output_dir(output_dir) / "generated" / "glue.py"
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

    def test_unsafe_library_names_fail_before_writing(self):
        cases = (("../outside", "python"), ("source\nimport os", "rust"))
        for source_name, destination_language in cases:
            with self.subTest(source_name=source_name, destination_language=destination_language):
                output_dir = self.root / f"out-{destination_language}"

                code, stdout = self.call_bridge(
                    self.bridge_args(
                        output_dir,
                        src=source_name,
                        dst_lang=destination_language,
                    )
                )

                self.assertNotEqual(code, 0)
                self.assertEqual(json.loads(stdout)["status"], "input_invalid")
                self.assertFalse(output_dir.exists())

    def test_python_import_names_must_be_identifiers(self):
        output_dir = self.root / "out"
        mapping_path = self.write_mapping_file([
            {
                "mapping_id": "reviewed-fetch",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
            }
        ])

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, dst="dest-fixture", mappings=mapping_path)
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "input_invalid")
        self.assertFalse(output_dir.exists())

    def test_other_supported_generator_is_reported_as_scaffold(self):
        output_dir = self.root / "out"
        mapping_path = self.write_mapping_file([
            {
                "mapping_id": "reviewed-fetch-rust",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
            }
        ])

        code, stdout = self.call_bridge(
            self.bridge_args(output_dir, dst_lang="rust", dst="dest_rust", mappings=mapping_path)
        )

        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "scaffold_only")
        self.assertTrue(result["scaffold_only"])
        self.assertEqual(result["generator_status"], "scaffold")

    def test_scoped_npm_package_generates_with_safe_pair_path_and_module_reference(self):
        output_dir = self.root / "out"
        mapping_path = self.write_mapping_file([
            {
                "mapping_id": "reviewed-fetch-scoped-npm",
                "src_function": "fetch",
                "dst_function": "lookup",
                "confidence": 0.95,
                "confidence_label": "identical",
                "review_status": "reviewed",
            }
        ])

        code, stdout = self.call_bridge(
            self.bridge_args(
                output_dir,
                dst_lang="javascript",
                dst="@example/http-client",
                mappings=mapping_path,
                skip_verify=True,
            )
        )

        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["generator_status"], "scaffold")
        pair_id = result["pair_id"]
        self.assertNotIn("/", pair_id)
        self.assertNotIn("\\", pair_id)
        pair_dir = output_dir / pair_id
        self.assertTrue(pair_dir.is_relative_to(output_dir))
        bridge_code = (pair_dir / "generated" / "bridge.js").read_text(encoding="utf-8")
        self.assertIn('require("@example/http-client")', bridge_code)
        self.assertIn('destinationModule["lookup"](...params)', bridge_code)

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

    def test_strategy_list_marks_generator_unsupported_routes(self):
        from polyglot.glue.strategy_selector import list_available_strategies
        from polyglot.commands.glue import cmd_strategies
        from argparse import Namespace

        routes = {
            (item["from"], item["to"]): item
            for item in list_available_strategies()
        }

        self.assertFalse(routes[("java", "kotlin")]["generator_supported"])
        self.assertEqual(routes[("java", "kotlin")]["generator_status"], "unsupported")
        self.assertFalse(routes[("javascript", "javascript")]["generator_supported"])
        self.assertEqual(routes[("python", "rust")]["generator_status"], "scaffold")
        self.assertTrue(routes[("python", "python")]["generator_supported"])
        self.assertEqual(routes[("python", "python")]["generator_status"], "functional")

        text_output = io.StringIO()
        with contextlib.redirect_stdout(text_output):
            cmd_strategies(Namespace(format="text"))
        self.assertIn("generator availability shown", text_output.getvalue())
        self.assertIn("generator=unsupported", text_output.getvalue())

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

        generated_path = self.pair_output_dir(output_dir) / "generated" / "glue.py"
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
