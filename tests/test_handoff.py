"""Regression tests for first and subsequent handoffs with a real git repository.

GitHub is simulated at the subprocess boundary; no network or issue writes occur.
Run directly with ``python tests/test_handoff.py``.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "handoff" / "scripts"
sys.path.insert(0, str(SCRIPTS))
REAL_RUN = subprocess.run


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "handoff" / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = load_script("collect")
check = load_script("check")


def issue(number, body, state="OPEN"):
    return {"number": number, "title": "handoff", "body": body, "state": state,
            "labels": [{"name": "handoff"}], "closedAt": None}


def frontmatter(base, head, supersedes="null"):
    return ("---\n"
            "schema: handoff/v1\n"
            "repo: example/repo\n"
            'window: {from: "2024-01-01", to: "2024-01-03"}\n'
            f"baseline_commit: {base}\nhead_commit: {head}\n"
            f"supersedes: {supersedes}\n---\n")


class FakeGitHub:
    def __init__(self, repo):
        self.repo = repo
        self.issues = []
        self.prs = []
        self.issue_objects = {}
        self.calls = []
        self.fail = None
        self.response_override = None

    def run(self, cmd, **kwargs):
        if cmd[0] != "gh":
            # A repository-local script is never part of the handoff contract.
            if cmd[0] in ("python", "python3"):
                raise AssertionError(f"unexpected project script: {cmd}")
            return REAL_RUN(cmd, **kwargs)
        self.calls.append(cmd)
        if self.fail and self.fail(cmd):
            # A failure can have apparently valid stdout and must still fail closed.
            return subprocess.CompletedProcess(cmd, 1, "[]", "simulated gh failure")
        if cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "ok", "")
        if cmd[1:3] == ["repo", "view"]:
            if "--jq" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "PUBLIC", "")
            data = {"visibility": "PUBLIC"}
        elif cmd[1:3] == ["pr", "list"]:
            data = self.prs
        elif cmd[1:3] == ["issue", "list"]:
            label = "--label" in cmd and cmd[cmd.index("--label") + 1] == "handoff"
            if label and self.response_override is not None:
                return subprocess.CompletedProcess(cmd, 0, self.response_override, "")
            state = cmd[cmd.index("--state") + 1] if "--state" in cmd else "open"
            data = [i for i in self.issues
                    if (not label or any(l["name"] == "handoff" for l in i["labels"]))
                    and (state == "all" or i["state"].lower() == state)]
            # gh outputs only requested fields. In particular, state is not implicit.
            if "--json" in cmd:
                fields = cmd[cmd.index("--json") + 1].split(",")
                data = [{k: v for k, v in i.items() if k in fields} for i in data]
        elif cmd[1] == "api":
            path = cmd[2]
            if "/compare/" in path:
                revision_range = path.split("/compare/", 1)[1]
                p = REAL_RUN(["git", "-C", str(self.repo), "rev-list", "--count",
                              revision_range], capture_output=True, text=True, check=True)
                data = {"total_commits": int(p.stdout.strip()), "commits": []}
            elif "/commits/" in path:
                data = {"commit": {"committer": {"date": "2024-01-02T12:00:00Z"}}}
            elif "/issues/" in path:
                number = int(path.rsplit("/", 1)[1])
                data = "open" if "--jq" in cmd else self.issue_objects.get(
                    number, {"state": "open", "labels": []})
            else:
                return subprocess.CompletedProcess(cmd, 1, "", "unknown API")
        else:
            raise AssertionError(f"unexpected gh command: {cmd}")
        out = data if isinstance(data, str) else json.dumps(data)
        if isinstance(data, list) and "--limit" in cmd:
            out = json.dumps(data[: int(cmd[cmd.index("--limit") + 1])])
        return subprocess.CompletedProcess(cmd, 0, out, "")


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.repo / "file.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "file.txt")
        self.git("commit", "-qm", "base", date="2024-01-01T12:00:00+00:00")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "file.txt").write_text("head\n", encoding="utf-8")
        self.git("commit", "-qam", "head", date="2024-01-02T12:00:00+00:00")
        self.head = self.git("rev-parse", "HEAD")
        self.github = FakeGitHub(self.repo)
        self.output = self.repo / "draft.md"

    def git(self, *args, date=None):
        env = os.environ.copy()
        if date:
            env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        p = REAL_RUN(["git", "-C", str(self.repo), *args], capture_output=True,
                     text=True, encoding="utf-8", check=True, env=env)
        return p.stdout.strip()

    def invoke(self, module, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", [module.__file__, *map(str, args)]), \
             mock.patch.object(subprocess, "run", side_effect=self.github.run), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = module.main()
            except SystemExit as exc:
                code = exc.code
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                code = 1
                print(str(exc), file=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def collect(self, *args):
        return self.invoke(collect, "--repo", "example/repo", "--repo-dir", self.repo,
                           "--head", self.head, "--today", "2024-01-03",
                           "--out", self.output, *args)

    def check(self, *args, base=None, head=None):
        return self.invoke(check, self.output, "--repo", "example/repo",
                           "--repo-dir", self.repo, "--baseline", base or self.base,
                           "--head", head or self.head, *args)

    def check_published(self, number):
        return self.invoke(check, "--repo", "example/repo", "--published", str(number))

    def first_draft(self):
        result = self.collect("--baseline", self.base, "--window-start", "2024-01-01")
        self.assertEqual(result[0], 0, result)
        return self.output.read_text(encoding="utf-8")

    def test_first_handoff_collect_to_check_without_entry_or_project_scripts(self):
        self.assertFalse((self.repo / "HANDOFF.md").exists())
        body = self.first_draft()
        self.assertIn("supersedes: null", body)
        self.assertNotIn("scripts/run_gates.py", body)
        self.assertNotIn("scripts/_common.py", body)
        result = self.check()
        self.assertEqual(result[0], 0, result)
        self.assertIn("[PASS] 7", result[1])

    def test_subsequent_handoff_uses_previous_head_and_date(self):
        prev = issue(42, frontmatter(self.base, self.head))
        self.github.issues = [prev, issue(8, "old", "CLOSED")]
        result = self.collect()
        self.assertEqual(result[0], 0, result)
        body = self.output.read_text(encoding="utf-8")
        self.assertIn(f"baseline_commit: {self.head}", body)
        self.assertIn("supersedes: 42", body)
        self.assertIn('from: "2024-01-02"', body)
        result = self.check(base=self.head)
        self.assertEqual(result[0], 0, result)
        label_queries = [c for c in self.github.calls if c[1:3] == ["issue", "list"]
                         and "--label" in c]
        self.assertTrue(label_queries)
        self.assertTrue(any("state" in c[c.index("--json") + 1].split(",")
                            for c in label_queries))

    def test_subsequent_handoff_allows_explicit_baseline_and_window_override(self):
        self.github.issues = [issue(42, frontmatter(self.base, self.head))]
        result = self.collect("--baseline", self.base, "--window-start", "2023-12-25")
        self.assertEqual(result[0], 0, result)
        body = self.output.read_text(encoding="utf-8")
        self.assertIn(f"baseline_commit: {self.base}", body)
        self.assertIn('from: "2023-12-25"', body)
        self.assertIn("supersedes: 42", body)

    def test_first_requires_baseline_and_window_start(self):
        for args in ((), ("--baseline", self.base), ("--window-start", "2024-01-01")):
            with self.subTest(args=args):
                self.assertNotEqual(self.collect(*args)[0], 0)
                self.assertFalse(self.output.exists())

    def test_supersedes_must_match_actual_previous_issue(self):
        args = ("--baseline", self.base, "--window-start", "2024-01-01")
        self.assertNotEqual(self.collect(*args, "--supersedes", "42")[0], 0)
        self.github.issues = [issue(42, frontmatter(self.base, self.head))]
        self.assertNotEqual(self.collect(*args, "--supersedes", "43")[0], 0)
        self.assertEqual(self.collect(*args, "--supersedes", "42")[0], 0)

    def test_multiple_open_handoffs_fail(self):
        self.github.issues = [issue(41, frontmatter(self.base, self.head)),
                              issue(42, frontmatter(self.base, self.head))]
        self.assertNotEqual(self.collect("--baseline", self.base,
                                         "--window-start", "2024-01-01")[0], 0)
        self.assertFalse(self.output.exists())

    def test_previous_frontmatter_supports_crlf(self):
        self.github.issues = [issue(42, frontmatter(self.base, self.head).replace("\n", "\r\n"))]
        result = self.collect()
        self.assertEqual(result[0], 0, result)
        body = self.output.read_text(encoding="utf-8")
        self.assertIn(f"baseline_commit: {self.head}", body)
        self.assertIn("supersedes: 42", body)

    def test_entry_file_must_be_committed_or_absent(self):
        (self.repo / "HANDOFF.md").write_text("# HANDOFF\n", encoding="utf-8")
        self.git("add", "HANDOFF.md")
        self.git("commit", "-qm", "add handoff entry")
        self.first_draft()
        self.assertEqual(self.check()[0], 0)
        (self.repo / "HANDOFF.md").write_text("# HANDOFF changed\n", encoding="utf-8")
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("[FAIL] 6", result[1])

    def test_previous_frontmatter_must_be_valid_and_not_body_text(self):
        bad_bodies = [
            f"baseline_commit: {self.base}\nhead_commit: {self.head}\n",
            frontmatter(self.base, self.head).replace(f"head_commit: {self.head}\n", "")
            + f"\nhead_commit: {self.head}\n",
            frontmatter(self.base, self.head).replace(self.head, "not-a-commit"),
            frontmatter(self.base, self.head).replace("schema: handoff/v1", "schema: invalid"),
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                self.github.issues = [issue(42, body)]
                self.assertNotEqual(self.collect("--baseline", self.base,
                                                 "--window-start", "2024-01-01")[0], 0)
                self.assertFalse(self.output.exists())

    def test_collect_gh_failure_and_unrelated_git_baseline_fail(self):
        self.github.fail = lambda cmd: cmd[1:3] == ["issue", "list"]
        self.assertNotEqual(self.collect("--baseline", self.base,
                                         "--window-start", "2024-01-01")[0], 0)
        self.assertFalse(self.output.exists())
        self.github.fail = None
        self.assertNotEqual(self.collect("--baseline", self.head, "--head", self.base,
                                         "--window-start", "2024-01-01")[0], 0)
        self.assertFalse(self.output.exists())

    def test_explicit_head_ref_is_resolved_to_full_sha(self):
        result = self.collect("--head", "HEAD", "--baseline", self.base,
                              "--window-start", "2024-01-01")
        self.assertEqual(result[0], 0, result)
        body = self.output.read_text(encoding="utf-8")
        self.assertIn(f"head_commit: {self.head}\n", body)
        self.assertEqual(self.check()[0], 0)

    def test_linked_issue_api_failure_does_not_become_closed(self):
        self.github.prs = [{"number": 51, "title": "delivery", "mergedAt": "2024-01-02T00:00:00Z",
                            "body": "Closes #52"}]
        self.github.issue_objects[52] = {"state": "closed", "labels": []}
        args = ("--baseline", self.base, "--window-start", "2024-01-01")
        result = self.collect(*args)
        self.assertEqual(result[0], 0, result)
        self.assertIn("#52 已关闭", self.output.read_text(encoding="utf-8"))
        self.output.unlink()
        self.github.fail = lambda c: c[1:3] == ["api", "repos/example/repo/issues/52"]
        result = self.collect(*args)
        self.assertNotEqual(result[0], 0, result)
        self.assertFalse(self.output.exists())

    def test_check_recomputes_row_with_trailing_note(self):
        body = self.first_draft()
        value = body.split("| 合并提交 | ")[1].split(" |")[0]
        self.output.write_text(body.replace(f"| 合并提交 | {value} |",
                                            f"| 合并提交 | {int(value) + 1} |"), encoding="utf-8")
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("[FAIL] 3.合并提交", result[1])

    def test_rows_without_padding_are_still_recomputed(self):
        body = self.first_draft().replace("| 仓库可见性 | PUBLIC |", "|仓库可见性|PRIVATE|")
        self.output.write_text(body, encoding="utf-8")
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("[FAIL] 3.仓库可见性", result[1])

    def test_empty_values_and_option_like_rev_are_rejected(self):
        self.assertFalse(check.same_value("", ""))
        ok, why = check.recompute("git log --output=/tmp/x --merges", "example/repo",
                                  self.repo, ("2024-01-01", "2024-01-03"))
        self.assertFalse(ok, why)

    def test_check_rejects_malformed_fact_row(self):
        body = self.first_draft().replace("| 被跟踪文件 |", "| 被跟踪文件 | extra |", 1)
        self.output.write_text(body, encoding="utf-8")
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("[FAIL] 3.parse", result[1])

    def test_check_rejects_unknown_recompute_command(self):
        body = self.first_draft().replace("`git ls-files` 行数",
                                          "`python scripts/run_gates.py --list` 行数")
        self.output.write_text(body, encoding="utf-8")
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("未识别", result[1])
        self.assertIn("[FAIL] 3.coverage", result[1])

    def test_check_rejects_repo_name_literal_in_command(self):
        body = self.first_draft().replace("`gh repo view $REPO",
                                          "`gh repo view example/repo")
        self.output.write_text(body, encoding="utf-8")
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("仓名字面量", result[1])

    def test_window_right_bound_excludes_later_merges(self):
        self.github.prs = [
            {"number": 51, "title": "in window", "mergedAt": "2024-01-02T00:00:00Z", "body": ""},
            {"number": 52, "title": "after window", "mergedAt": "2024-01-04T00:00:00Z", "body": ""},
        ]
        body = self.first_draft()
        self.assertIn("| 合并 PR(窗口内) | 1 |", body)
        self.assertNotIn("#52", body)

    def test_recompute_excludes_merges_after_window_end(self):
        self.first_draft()
        self.github.prs = [
            {"number": 52, "title": "after window", "mergedAt": "2024-01-04T00:00:00Z", "body": ""},
        ]
        result = self.check()
        self.assertEqual(result[0], 0, result)

    def test_check_rejects_non_unified_list_limit(self):
        body = self.first_draft().replace("--limit 1000", "--limit 1", 1)
        self.output.write_text(body, encoding="utf-8")
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("统一上限", result[1])

    def test_list_exactly_at_limit_is_not_truncation(self):
        self.addCleanup(setattr, collect, "LIST_LIMIT", collect.LIST_LIMIT)
        collect.LIST_LIMIT = 2
        self.github.prs = [
            {"number": 51, "title": "one", "mergedAt": "2024-01-02T00:00:00Z", "body": ""},
            {"number": 52, "title": "two", "mergedAt": "2024-01-02T00:00:00Z", "body": ""},
        ]
        result = self.collect("--baseline", self.base, "--window-start", "2024-01-01")
        self.assertEqual(result[0], 0, result)
        self.assertTrue(self.output.exists())

    def test_check_probe_matches_collect_limit(self):
        self.addCleanup(setattr, check, "LIST_LIMIT", check.LIST_LIMIT)
        self.addCleanup(setattr, collect, "LIST_LIMIT", collect.LIST_LIMIT)
        check.LIST_LIMIT = collect.LIST_LIMIT = 2
        self.github.prs = [
            {"number": 51, "title": "one", "mergedAt": "2024-01-02T00:00:00Z", "body": ""},
            {"number": 52, "title": "two", "mergedAt": "2024-01-02T00:00:00Z", "body": ""},
        ]
        self.first_draft()
        self.assertEqual(self.check()[0], 0)
        self.github.prs.append(
            {"number": 53, "title": "three", "mergedAt": "2024-01-02T00:00:00Z", "body": ""})
        result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("截断", result[1])

    def test_read_reports_rows_with_trailing_note(self):
        self.first_draft()
        code, out, _ = self.invoke(collect, "--read", self.output)
        self.assertEqual(code, 0)
        facts = json.loads(out)["facts"]
        self.assertIn("合并提交", facts)
        self.assertEqual(facts["合并提交"], "0")

    def test_truncated_list_fails_closed_without_output(self):
        self.addCleanup(setattr, collect, "LIST_LIMIT", collect.LIST_LIMIT)
        collect.LIST_LIMIT = 1
        self.github.prs = [
            {"number": 51, "title": "one", "mergedAt": "2024-01-02T00:00:00Z", "body": ""},
            {"number": 52, "title": "two", "mergedAt": "2024-01-02T00:00:00Z", "body": ""},
        ]
        result = self.collect("--baseline", self.base, "--window-start", "2024-01-01")
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("截断", result[2])
        self.assertFalse(self.output.exists())

    def test_merge_count_uses_local_git_not_compare_list(self):
        branch = self.git("rev-parse", "--abbrev-ref", "HEAD")
        self.git("checkout", "-q", "-b", "side")
        (self.repo / "side.txt").write_text("side\n", encoding="utf-8")
        self.git("add", "side.txt")
        self.git("commit", "-qm", "side")
        self.git("checkout", "-q", branch)
        self.git("merge", "-q", "--no-ff", "side", "-m", "Merge pull request #1 from x/y")
        result = self.collect("--head", "HEAD", "--baseline", self.base,
                              "--window-start", "2024-01-01")
        self.assertEqual(result[0], 0, result)
        body = self.output.read_text(encoding="utf-8")
        self.assertIn("| 合并提交 | 1 |", body)
        self.assertIn("其中 1 条 `Merge pull request`", body)

    def test_check_accepts_short_sha_for_snapshot_fields(self):
        self.first_draft()
        result = self.check(base=self.base[:7], head=self.head[:8])
        self.assertEqual(result[0], 0, result)

    def test_check_rejects_other_commit_as_baseline(self):
        self.first_draft()
        result = self.check(base=self.head[:7], head=self.head[:8])
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("[FAIL] 1.base", result[1])

    def test_check_prepublication_identity_and_count(self):
        self.first_draft()
        for issues, expected in [([], True), ([42], False), ([42, 43], False)]:
            with self.subTest(supersedes=None, issues=issues):
                self.github.issues = [issue(n, frontmatter(self.base, self.head)) for n in issues]
                self.assertEqual(self.check()[0] == 0, expected)
        self.output.write_text(self.output.read_text(encoding="utf-8").replace(
            "supersedes: null", "supersedes: 42"), encoding="utf-8")
        for issues, expected in [([], False), ([42], True), ([43], False), ([42, 43], False)]:
            with self.subTest(supersedes=42, issues=issues):
                self.github.issues = [issue(n, frontmatter(self.base, self.head)) for n in issues]
                self.assertEqual(self.check()[0] == 0, expected)

    def test_check_published_identity_and_count(self):
        self.first_draft()
        for issues, expected in [([], False), ([42], True), ([43], False), ([42, 43], False)]:
            with self.subTest(issues=issues):
                self.github.issues = [issue(n, frontmatter(self.base, self.head)) for n in issues]
                self.assertEqual(self.check_published(42)[0] == 0, expected)

    def test_published_after_replacement_requires_only_the_new_issue(self):
        self.github.issues = [issue(42, frontmatter(self.base, self.head))]
        result = self.collect("--baseline", self.base, "--window-start", "2024-01-01")
        self.assertEqual(result[0], 0, result)
        self.assertEqual(self.check()[0], 0)
        self.github.issues.append(issue(43, self.output.read_text(encoding="utf-8")))
        self.assertNotEqual(self.check_published(43)[0], 0)
        self.github.issues[0]["state"] = "CLOSED"
        self.assertEqual(self.check_published(43)[0], 0)
        self.assertNotEqual(self.check_published(42)[0], 0)

    def test_check_gh_failure_and_malformed_response_fail_closed(self):
        self.first_draft()
        self.github.fail = lambda c: c[1:3] == ["issue", "list"] and "--label" in c
        self.assertNotEqual(self.check()[0], 0)
        self.github.fail = None
        for response in ("not json", "{}", "null"):
            with self.subTest(response=response):
                self.github.response_override = response
                self.assertNotEqual(self.check()[0], 0)

    def test_published_check_fails_closed_on_failed_or_malformed_query(self):
        self.github.issues = [issue(42, frontmatter(self.base, self.head))]
        self.github.fail = lambda c: c[1:3] == ["issue", "list"] and "--label" in c
        self.assertNotEqual(self.check_published(42)[0], 0)
        self.github.fail = None
        for response in ("not json", "{}", "null"):
            with self.subTest(response=response):
                self.github.response_override = response
                self.assertNotEqual(self.check_published(42)[0], 0)

    def test_check_git_failure_is_not_clean_entry_file(self):
        self.first_draft()
        # The invalid repository also causes check 2 to fail. Inspect check 6 itself.
        original_run = self.github.run
        with mock.patch.object(self.github, "run") as run:
            def fail_status(cmd, **kwargs):
                if cmd[0] == "git" and "status" in cmd:
                    return subprocess.CompletedProcess(cmd, 128, "", "git failure")
                return original_run(cmd, **kwargs)
            run.side_effect = fail_status
            result = self.check()
        self.assertNotEqual(result[0], 0, result)
        self.assertIn("[FAIL] 6", result[1])

    def test_local_skips_only_checks_6_and_7(self):
        self.first_draft()
        self.github.issues = [issue(42, frontmatter(self.base, self.head)),
                              issue(43, frontmatter(self.base, self.head))]
        result = self.check("--mode", "local")
        self.assertEqual(result[0], 0, result)
        self.assertNotIn("[FAIL] 6", result[1])
        self.assertNotIn("[FAIL] 7", result[1])
        self.assertGreaterEqual(result[1].count("[SKIP]"), 2)
        self.output.write_text(self.output.read_text(encoding="utf-8").replace(
            "schema: handoff/v1", "schema: invalid"), encoding="utf-8")
        self.assertNotEqual(self.check("--mode", "local")[0], 0)


if __name__ == "__main__":
    unittest.main()
