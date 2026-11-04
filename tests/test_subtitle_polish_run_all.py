# -*- coding: utf-8 -*-
"""tests/run_all.py 的预期失败清单机制（issue #41 配套）。

锁四件事：
  1. 清单命中（条数一致）→ 退出码 0；
  2. 非预期失败（不在清单 / 条数变多）→ 退出码非 0；
  3. 清单项意外通过或条数变少 → 报警「清单过期」，退出码非 0；
  4. 清单项拿不到汇总 → 按非预期失败处理，不静默放过。

用临时目录里的假脚本做 fixture，**不跑也不改真实测试脚本**。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_run_all.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_run_all():
    """按文件路径加载 tests/run_all.py，避免依赖包结构。"""
    path = os.path.join(TESTS_DIR, "run_all.py")
    spec = importlib.util.spec_from_file_location("run_all_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PASS = FAIL = 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        FAIL += 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        FAIL += 1
    else:
        print(f"  [PASS] {name}")
        PASS += 1


def _fake(dirpath, name, summary_txt, rc=0):
    """写一个只打印汇总、不干别的假测试脚本。"""
    body = ("# -*- coding: utf-8 -*-\n"
            "import sys\n"
            "print(%r)\n"
            "sys.exit(%d)\n" % (summary_txt, rc))
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as f:
        f.write(body)


def _run(mod, tests_dir, manifest):
    """跑 run_all.main，返回 `(rc, stdout)`；临时替换清单后复原。"""
    saved = mod.EXPECTED_FAILURES
    mod.EXPECTED_FAILURES = manifest
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main(["--tests-dir", tests_dir])
    finally:
        mod.EXPECTED_FAILURES = saved
    return rc, buf.getvalue()


def t_expectation_hit_exits_zero():
    mod = _load_run_all()
    root = tempfile.mkdtemp(prefix="runall-hit-")
    try:
        _fake(root, "fake_pass.py", "FAKE RESULTS: 5 passed, 0 failed", rc=0)
        _fake(root, "fake_known.py", "FAKE RESULTS: 4 passed, 2 failed", rc=0)
        rc, out = _run(mod, root, {"fake_known.py": (2, "测试用债")})
        assert rc == 0, (rc, out)
        assert "预期失败 2 条（清单）" in out, out
        assert "非预期失败 0" in out and "清单过期 0" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_unexpected_failure_exits_nonzero():
    mod = _load_run_all()
    root = tempfile.mkdtemp(prefix="runall-bad-")
    try:
        _fake(root, "fake_pass.py", "FAKE RESULTS: 5 passed, 0 failed", rc=0)
        # 不在清单里，且「有失败但退出码 0」——旧口径会判绿
        _fake(root, "fake_bad.py", "结果: 3 通过 / 1 失败", rc=0)
        rc, out = _run(mod, root, {"fake_pass.py": (0, "占位")})
        assert rc != 0, (rc, out)
        assert "非预期失败 1" in out, out
        assert "假绿" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_manifest_item_passing_alarms():
    mod = _load_run_all()
    root = tempfile.mkdtemp(prefix="runall-stale-")
    try:
        # 清单说该脚本应有 2 条失败，实际全绿 → 债被修了，清单过期
        _fake(root, "fake_debt.py", "FAKE RESULTS: 6 passed, 0 failed", rc=0)
        rc, out = _run(mod, root, {"fake_debt.py": (2, "应失败的债" )})
        assert rc != 0, (rc, out)
        assert "ALARM" in out, out
        assert "清单过期 1" in out, out
        assert "债可能已被修" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_manifest_count_increase_is_regression():
    mod = _load_run_all()
    root = tempfile.mkdtemp(prefix="runall-worse-")
    try:
        # 清单期望 2 条，实测 3 条 → 新增失败，按回归处理
        _fake(root, "fake_worse.py", "FAKE RESULTS: 4 passed, 3 failed", rc=0)
        rc, out = _run(mod, root, {"fake_worse.py": (2, "原有债")})
        assert rc != 0, (rc, out)
        assert "新增失败" in out, out
        assert "非预期失败 1" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_manifest_entry_without_summary_is_unexpected():
    mod = _load_run_all()
    root = tempfile.mkdtemp(prefix="runall-nosum-")
    try:
        _fake(root, "fake_nosum.py", "没有汇总行", rc=0)
        rc, out = _run(mod, root, {"fake_nosum.py": (2, "清单项" )})
        assert rc != 0, (rc, out)
        assert "解析不到汇总" in out, out
        assert "非预期失败 1" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_manifest_covers_red_and_debt():
    """真实清单必须显式覆盖 RED 与已知债，不再靠代码里的脚本特例。"""
    mod = _load_run_all()
    m = mod.EXPECTED_FAILURES
    assert "test_red_bugs.py" in m, m
    assert "test_green_bugs.py" in m, m
    assert m["test_red_bugs.py"][0] == 6, m
    assert m["test_green_bugs.py"][0] == 2, m
    # 每项都要有理由，不能只写数字
    for name, (n, why) in m.items():
        assert isinstance(n, int) and n > 0, (name, n)
        assert why and len(why) >= 8, (name, why)


if __name__ == "__main__":
    print("run_all 预期失败清单（issue #41）")
    test("清单命中 → 退出 0", t_expectation_hit_exits_zero)
    test("非预期失败 → 退出非 0", t_unexpected_failure_exits_nonzero)
    test("清单项意外通过 → 报警清单过期", t_manifest_item_passing_alarms)
    test("清单条数变多 → 按回归处理", t_manifest_count_increase_is_regression)
    test("清单项无汇总 → 按非预期失败处理",
         t_manifest_entry_without_summary_is_unexpected)
    test("真实清单覆盖 RED 与已知债且都带理由", t_manifest_covers_red_and_debt)
    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
