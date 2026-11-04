# -*- coding: utf-8 -*-
"""tests/run_all.py — 跑 tests/ 下全部脚本，解析断言汇总，失败时非零退出。

为什么需要它：多数脚本断言失败时会 `sys.exit(1)`，但 `test_green_bugs.py`
与 `test_red_bugs.py` **从不设置退出码**。只看 `returncode` 会把这两个脚本的
失败当成通过——这正是 CI 假绿的来源（issue #39 附带项）。

约定与判定：

- 每个脚本在结尾打印一行能被 `PATTERNS` 解析的断言汇总
  （`通过 X / 失败 Y`、`GREEN RESULTS: X passed, Y failed`、
  `ALL OK  (X passed, Y failed)`）；
- **预期失败清单** `EXPECTED_FAILURES` 是唯一特例来源：脚本名 -> (期望失败条数, 理由)。
  命中且条数一致 → 不算非预期失败；条数变少 → 清单过期（报警，提示更新清单）；
  条数变多或退出码非零 → 按非预期失败处理（回归）；
- 不在清单里的脚本：退出码 0 且 0 失败才算通过；
- 解析不到汇总的脚本退化为只看退出码，并在结果里标 `no-summary`；
- 退出码：有非预期失败或清单过期 → 1，否则 0。

跑法（仓库根目录）:
  python tests/run_all.py
  python tests/run_all.py --filter align_cross
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))

#: 预期失败清单：脚本名 -> (期望失败条数, 理由)。
#:
#: 这里是**唯一**允许「失败不算失败」的地方。加项必须带理由，且条数要与
#: 实测一致；债修好后应把条数改成 0 / 移出清单，否则 run_all 会报「清单过期」。
EXPECTED_FAILURES = {
    "test_red_bugs.py": (
        6,
        "按设计应失败（RED）：验证 bug 仍然存在；全绿说明测试前提已变，需重写测试",
    ),
    "test_green_bugs.py": (
        2,
        "已知债（issue #41）：Bug 3/5 的 _ALT_HEADERS 未接进 CF 重试；"
        "修复后应改为 0 或移出清单",
    ),
}

#: 汇总行解析。顺序有意义：先匹配带标签的，再匹配裸 `X passed, Y failed`。
PATTERNS = (
    re.compile(r"通过\s*(\d+)\s*/\s*失败\s*(\d+)"),
    re.compile(r"结果:\s*(\d+)\s*通过\s*/\s*(\d+)\s*失败"),
    re.compile(r"GREEN RESULTS:\s*(\d+)\s*passed,\s*(\d+)\s*failed"),
    re.compile(r"RED RESULTS:\s*(\d+)\s*passed,\s*(\d+)\s*failed"),
    re.compile(r"(\d+)\s*passed,\s*(\d+)\s*failed"),
)

#: 结果标签：ok 通过；unexpected 非预期失败；stale 清单过期。
_LABEL = {"ok": "OK", "unexpected": "FAIL", "stale": "ALARM"}


def discover(flt: str = "", tests_dir: str = HERE) -> list:
    names = sorted(n for n in os.listdir(tests_dir)
                   if n.endswith(".py") and n != "run_all.py")
    if flt:
        names = [n for n in names if flt in n]
    return names


def parse_summary(out: str):
    """返回 `(passed, failed)`；解析不到返回 None。"""
    for pat in PATTERNS:
        m = pat.search(out)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def classify(name: str, rc: int, summary, manifest=None) -> tuple:
    """判定单个脚本。返回 `(kind, expected, note)`。

    `kind`：`ok` / `unexpected`（非预期失败）/ `stale`（清单过期，债可能已修）。
    `manifest` 缺省用模块级 `EXPECTED_FAILURES`，测试可注入临时清单。
    """
    entry = (EXPECTED_FAILURES if manifest is None else manifest).get(name)
    exp = entry[0] if entry else None
    if summary is None:
        if exp is not None:
            return "unexpected", exp, "清单项解析不到汇总，无法核对条数"
        if rc == 0:
            return "ok", 0, "no-summary（只按退出码判定）"
        return "unexpected", 0, "no-summary + 非零退出"

    passed, failed = summary
    if exp is None:
        if rc == 0 and failed == 0:
            return "ok", 0, ""
        if rc != 0 and failed == 0:
            return "unexpected", 0, "汇总说 0 失败，但退出码非零"
        if rc == 0 and failed > 0:
            return "unexpected", 0, "汇总有失败，但退出码为 0（假绿）"
        return "unexpected", 0, ""

    # --- 清单内的项：条数必须与实测一致，且退出码必须为 0（脚本自己没崩）
    if rc != 0:
        return "unexpected", exp, "清单项退出码非零（脚本可能在汇总前就崩了）"
    if failed == exp:
        return "ok", exp, "预期失败 %d 条（清单）" % exp
    if failed < exp:
        return "stale", exp, ("清单期望 %d 条失败，实测 %d——债可能已被修，"
                              "请更新清单" % (exp, failed))
    return "unexpected", exp, ("清单期望 %d 条失败，实测 %d——出现新增失败，"
                               "按回归处理" % (exp, failed))


def run_one(name: str, tests_dir: str = HERE, manifest=None) -> dict:
    path = os.path.join(tests_dir, name)
    try:
        proc = subprocess.run(
            [sys.executable, path], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return {"name": name, "rc": -1, "passed": 0, "failed": 0,
                "expected": 0, "kind": "unexpected", "note": "超时 900s"}

    summary = parse_summary(out)
    kind, expected, note = classify(name, rc, summary, manifest)
    passed, failed = summary if summary else (0, 0)
    return {"name": name, "rc": rc, "passed": passed, "failed": failed,
            "expected": expected, "kind": kind, "note": note}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="跑 tests/ 全部脚本并按断言汇总判定")
    ap.add_argument("--filter", default="", help="只跑文件名包含该子串的脚本")
    ap.add_argument("--tests-dir", default=HERE, help="测试脚本目录（测试用）")
    args = ap.parse_args(argv)

    names = discover(args.filter, args.tests_dir)
    if not names:
        print("没有匹配的测试脚本")
        return 1

    rows = []
    print("测试脚本：%d 个\n" % len(names))
    print("%-46s %4s %5s %5s %5s  %s"
          % ("脚本", "rc", "通过", "失败", "预期失败", "结果"))
    print("-" * 100)
    for name in names:
        r = run_one(name, args.tests_dir)
        rows.append(r)
        print("%-46s %4d %5d %5d %5d  %s%s"
              % (name, r["rc"], r["passed"], r["failed"], r["expected"],
                 _LABEL.get(r["kind"], "FAIL"),
                 ("  " + r["note"]) if r["note"] else ""))

    bad = [r for r in rows if r["kind"] != "ok"]
    unexpected = [r for r in rows if r["kind"] == "unexpected"]
    stale = [r for r in rows if r["kind"] == "stale"]
    total_pass = sum(r["passed"] for r in rows)
    total_fail = sum(r["failed"] for r in rows)
    expected = sum(r["expected"] for r in rows)
    print("-" * 100)
    print("汇总：%d 脚本；断言通过 %d / 失败 %d（其中预期失败 %d）；"
          "非预期失败 %d；清单过期 %d"
          % (len(rows), total_pass, total_fail, expected,
             len(unexpected), len(stale)))
    if bad:
        print("\n未通过的脚本 %d 个：" % len(bad))
        for r in bad:
            print("  - %s [%s]（rc=%d，失败 %d%s）"
                  % (r["name"], _LABEL.get(r["kind"], "FAIL"), r["rc"],
                     r["failed"], "，" + r["note"] if r["note"] else ""))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
