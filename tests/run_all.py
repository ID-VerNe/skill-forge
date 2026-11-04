# -*- coding: utf-8 -*-
"""tests/run_all.py — 跑 tests/ 下全部脚本，解析断言汇总，失败时非零退出。

为什么需要它：多数脚本断言失败时会 `sys.exit(1)`，但 `test_green_bugs.py`
与 `test_red_bugs.py` **从不设置退出码**。只看 `returncode` 会把这两个脚本的
失败当成通过——这正是 CI 假绿的来源（issue #39 附带项）。

约定与判定：

- 每个脚本在结尾打印一行能被 `PATTERNS` 解析的断言汇总
  （`通过 X / 失败 Y`、`GREEN RESULTS: X passed, Y failed`、
  `ALL OK  (X passed, Y failed)`）；
- `test_red_bugs.py` 是「按设计应失败」：它的失败计为 expected，不算回归；
  但如果它一条都不失败，说明 RED 测试的前提变了，按失败处理（需要更新测试）；
- 解析不到汇总的脚本退化为只看退出码，并在结果里标 `no-summary`；
- 任一脚本非零退出或出现非预期失败 → 本脚本退出码 1。

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

#: 按设计应失败（RED）的脚本：失败本身是预期，不是回归。
RED_SCRIPTS = {"test_red_bugs.py"}

#: 汇总行解析。顺序有意义：先匹配带标签的，再匹配裸 `X passed, Y failed`。
PATTERNS = (
    re.compile(r"通过\s*(\d+)\s*/\s*失败\s*(\d+)"),
    re.compile(r"结果:\s*(\d+)\s*通过\s*/\s*(\d+)\s*失败"),
    re.compile(r"GREEN RESULTS:\s*(\d+)\s*passed,\s*(\d+)\s*failed"),
    re.compile(r"RED RESULTS:\s*(\d+)\s*passed,\s*(\d+)\s*failed"),
    re.compile(r"(\d+)\s*passed,\s*(\d+)\s*failed"),
)


def discover(flt: str = "") -> list:
    names = sorted(n for n in os.listdir(HERE)
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


def run_one(name: str) -> dict:
    path = os.path.join(HERE, name)
    try:
        proc = subprocess.run(
            [sys.executable, path], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return {"name": name, "rc": -1, "passed": 0, "failed": 0,
                "expected": 0, "ok": False, "note": "超时 900s"}

    summary = parse_summary(out)
    red = name in RED_SCRIPTS
    note = ""
    if summary is None:
        # 没有汇总行：只能信退出码，明确标注这是弱证据。
        passed, failed = 0, 0
        ok = rc == 0
        note = "no-summary（只按退出码判定）" if ok else "no-summary + 非零退出"
    else:
        passed, failed = summary
        if red:
            # RED 的失败是预期；全部「通过」反而说明测试前提失效。
            ok = rc == 0 and failed > 0
            note = ("按设计应失败：%d failed（预期）" % failed if ok
                    else "RED 测试不再失败，前提已变，需更新测试")
            return {"name": name, "rc": rc, "passed": passed, "failed": failed,
                    "expected": failed if ok else 0, "ok": ok, "note": note}
        ok = rc == 0 and failed == 0
        if rc != 0 and failed == 0:
            note = "汇总说 0 失败，但退出码非零"
        elif rc == 0 and failed > 0:
            note = "汇总有失败，但退出码为 0（假绿）"

    return {"name": name, "rc": rc, "passed": passed, "failed": failed,
            "expected": 0, "ok": ok, "note": note}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="跑 tests/ 全部脚本并按断言汇总判定")
    ap.add_argument("--filter", default="", help="只跑文件名包含该子串的脚本")
    args = ap.parse_args(argv)

    names = discover(args.filter)
    if not names:
        print("没有匹配的测试脚本")
        return 1

    rows = []
    print("测试脚本：%d 个\n" % len(names))
    print("%-46s %4s %5s %5s %5s  %s"
          % ("脚本", "rc", "通过", "失败", "预期失败", "结果"))
    print("-" * 100)
    for name in names:
        r = run_one(name)
        rows.append(r)
        print("%-46s %4d %5d %5d %5d  %s%s"
              % (name, r["rc"], r["passed"], r["failed"], r["expected"],
                 "OK" if r["ok"] else "FAIL",
                 ("  " + r["note"]) if r["note"] else ""))

    bad = [r for r in rows if not r["ok"]]
    total_pass = sum(r["passed"] for r in rows)
    total_fail = sum(r["failed"] for r in rows)
    expected = sum(r["expected"] for r in rows)
    print("-" * 100)
    print("汇总：%d 脚本；断言通过 %d / 失败 %d（其中预期失败 %d）"
          % (len(rows), total_pass, total_fail, expected))
    if bad:
        print("\n失败脚本 %d 个：" % len(bad))
        for r in bad:
            print("  - %s（rc=%d，失败 %d%s）"
                  % (r["name"], r["rc"], r["failed"],
                     "，" + r["note"] if r["note"] else ""))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
