#!/usr/bin/env python3
"""check.py — handoff 草案发布前硬门禁(D12:全过才创建,失败即 abort)。

校验项(共九项,对应规范 §check):
  0  正文无 H1 行(标题信息由 frontmatter 承载,H1 属禁止项)
  1  frontmatter 必填字段齐且格式对(schema/repo/window/baseline_commit/head_commit/supersedes)
  2  baseline_commit 是 head_commit 的祖先(git merge-base --is-ancestor)
  3  §1 口径表每行的复算命令在本机重跑结果与表中数字一致
  4  正文 #N 引用全部存在于该仓(issue 或 PR 均可,但 §4 表行首必须 issue)
  5  8 节骨架标题文字齐全(§1 数据口径 ... §7 无法追溯与不确定项,§7 允许空但不许省)
  6  issue 模式下已有 HANDOFF.md 无未提交改动(文件不存在时通过)
  7  issue 模式发布前 open handoff 与 supersedes 一致
  8  §4 表行首 #N 必须是 issue 号(不是 PR 号)

用法:
  python check.py <draft.md> --repo OWNER/REPO --baseline 3dfc35d --head fd0ea53
                 [--repo-dir /path/to/clone] [--mode issue|local]

退出码:0 = 全过;1 = 有 FAIL;2 = 参数/环境错。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

REQUIRED_FM = ["schema", "repo", "window", "baseline_commit", "head_commit", "supersedes"]
SECTION_TITLES = [
    "## 1. 数据口径",
    "## 2. 本窗口交付",
    "## 3. 决策与理由",
    "## 4. 遗留与阻塞",
    "## 5. 下一步",
    "## 6. 环境与坑",
    "## 7. 无法追溯与不确定项",
]


def _env() -> dict:
    e = os.environ.copy()
    e["PYTHONUTF8"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    e["LANG"] = "C.UTF-8"
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        e.pop(k, None)
    return e


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_env())


def gh(repo: str, path: str, args: list[str] | None = None) -> dict | list:
    cmd = ["gh", "api", f"repos/{repo}/{path}"]
    if args:
        cmd += args
    p = run(cmd)
    if p.returncode != 0:
        raise RuntimeError(f"gh api 失败({p.returncode}): {' '.join(cmd)}\n{p.stderr.strip()[:300]}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


def open_handoffs(repo: str) -> list[int]:
    p = run(["gh", "issue", "list", "--repo", repo, "--label", "handoff",
             "--state", "open", "--limit", "2", "--json", "number"])
    if p.returncode != 0:
        raise RuntimeError(f"查询失败: {p.stderr.strip()[:120]}")
    items = json.loads(p.stdout)
    if not isinstance(items, list) or any(
        not isinstance(i, dict) or type(i.get("number")) is not int or i["number"] <= 0
        for i in items
    ):
        raise ValueError("open handoff 查询结果无效")
    return [i["number"] for i in items]


def main() -> int:
    ap = argparse.ArgumentParser(description="handoff 草案发布前硬门禁")
    ap.add_argument("draft", nargs="?", help="草案 md 路径")
    ap.add_argument("--repo", required=True, help="OWNER/REPO")
    ap.add_argument("--baseline", help="基线 commit")
    ap.add_argument("--head", help="head commit")
    ap.add_argument("--published", type=int, help="发布后检查唯一 open handoff 是否为此编号")
    ap.add_argument("--repo-dir", default=".", help="本地 git 仓路径")
    ap.add_argument("--mode", choices=["issue", "local"], default="issue",
                    help="issue 模式校验 HANDOFF.md 和发布前状态;local 模式跳过 6/7")
    args = ap.parse_args()

    if args.published is not None:
        if args.published <= 0 or args.draft or args.baseline or args.head or args.mode != "issue":
            ap.error("--published 需要正整数,不能与草案参数或 local 模式组合")
        try:
            actual = open_handoffs(args.repo)
            ok = actual == [args.published]
            print(f"[{'PASS' if ok else 'FAIL'}] 发布后 open handoff: {actual}, 期望 [{args.published}]")
            return 0 if ok else 1
        except (RuntimeError, ValueError) as e:
            print(f"[FAIL] 发布后查询失败: {e}", file=sys.stderr)
            return 1
    if not args.draft or not args.baseline or not args.head:
        ap.error("发布前检查需要 draft、--baseline 和 --head")

    draft = Path(args.draft)
    if not draft.exists():
        print(f"[check] 错误:草案不存在 {draft}", file=sys.stderr)
        return 2
    txt = draft.read_text(encoding="utf-8")
    repo_dir = Path(args.repo_dir)

    results: list[tuple[str, bool, str]] = []

    def ck(no: str, desc: str, ok: bool, detail: str = "") -> None:
        results.append((no, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {no} {desc}" + (f": {detail}" if detail else ""))

    # ---- 0. 正文无 H1 ----
    print("=== check 0: 正文无 H1(标题信息由 frontmatter 承载) ===")
    ck("0", "正文无 H1 行", not re.search(r"^# ", txt, re.M),
       "" if not re.search(r"^# ", txt, re.M) else "含 H1 行,frontmatter 已承载标题信息")

    # ---- 1. frontmatter ----
    print("=== check 1: frontmatter 必填字段 ===")
    fm: dict = {}
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    duplicates = []
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                if k in fm:
                    duplicates.append(k)
                fm[k] = v.strip()
    ck("1.duplicate", "frontmatter 字段无重复", not duplicates, ", ".join(duplicates))
    for f in REQUIRED_FM:
        ck(f"1.{f}", f"字段 {f}", f in fm and fm[f] != "", fm.get(f, "(缺失)"))
    ck("1.schema", "schema 值 = handoff/v1", fm.get("schema") == "handoff/v1", fm.get("schema", ""))
    ck("1.repo", "repo 值 = --repo", fm.get("repo") == args.repo, fm.get("repo", ""))
    ck("1.base", "baseline_commit = --baseline",
       fm.get("baseline_commit", "").lower() == args.baseline.lower(), fm.get("baseline_commit", ""))
    ck("1.head", "head_commit = --head",
       fm.get("head_commit", "").lower() == args.head.lower(), fm.get("head_commit", ""))

    # ---- 2. baseline 可达 ----
    print("=== check 2: baseline 是 head 的祖先 ===")
    p = run(["git", "-C", str(repo_dir), "merge-base", "--is-ancestor", args.baseline, args.head])
    ck("2", f"{args.baseline} 是 {args.head} 的祖先", p.returncode == 0,
       "" if p.returncode == 0 else p.stderr.strip()[:120])

    # ---- 3. §1 口径表数字复算 ----
    print("=== check 3: §1 口径表数字复算 ===")
    sec1 = re.search(r"## 1\. 数据口径\n(.*?)\n## 2\.", txt, re.S)
    if not sec1:
        ck("3", "§1 存在", False, "未找到 '## 1. 数据口径'")
    else:
        rows = re.findall(r"^\| (.+?) \| (.+?) \| `(.+?)` \|$", sec1.group(1), re.M)
        if not rows:
            ck("3.rows", "§1 表格行可解析", False, "无匹配行")
        else:
            for name, val, cmd in rows:
                # 只复算能本地跑的:gh api / gh pr list / gh issue list / git ls-files / python scripts/
                if cmd.startswith("gh api repos/") and "compare/" in cmd:
                    try:
        # compare URL 形如 repos/O/R/compare/A...B,gh api 只要 compare/A...B 段
                        cmp_arg = cmd.split("compare/")[1].split(" ")[0]
                        got = gh(args.repo, f"compare/{cmp_arg}")["total_commits"]
                        ck(f"3.{name}", name, str(got) == val.strip(), f"表={val.strip()} 算={got}")
                    except Exception as e:
                        ck(f"3.{name}", name, False, f"复算失败: {str(e)[:80]}")
                elif cmd.startswith("git log") and "--merges" in cmd:
                    got = run(["git", "-C", str(repo_dir), "log",
                               f"{args.baseline}..{args.head}", "--merges", "--format=%s"]).stdout.strip().splitlines()
                    ck(f"3.{name}", name, str(len(got)) == val.strip(), f"表={val.strip()} 算={len(got)}")
                elif cmd.startswith("gh pr list"):
                    try:
                        p2 = run(["gh", "pr", "list", "--repo", args.repo, "--state", "all",
                                  "--limit", "500", "--json", "mergedAt"])
                        merged = [x for x in json.loads(p2.stdout)
                                  if (x.get("mergedAt") or "") >= fm.get("window", "").split('"')[1]]
                        ck(f"3.{name}", name, str(len(merged)) == val.strip(), f"表={val.strip()} 算={len(merged)}")
                    except Exception as e:
                        ck(f"3.{name}", name, False, f"复算失败: {str(e)[:80]}")
                elif cmd.startswith("gh issue list") and "closed" in cmd:
                    try:
                        p2 = run(["gh", "issue", "list", "--repo", args.repo, "--state", "closed",
                                  "--limit", "500", "--json", "closedAt"])
                        closed = [x for x in json.loads(p2.stdout)
                                  if (x.get("closedAt") or "") >= fm.get("window", "").split('"')[1]]
                        ck(f"3.{name}", name, str(len(closed)) == val.strip(), f"表={val.strip()} 算={len(closed)}")
                    except Exception as e:
                        ck(f"3.{name}", name, False, f"复算失败: {str(e)[:80]}")
                elif cmd.startswith("gh issue list") and "open" in cmd:
                    try:
                        p2 = run(["gh", "issue", "list", "--repo", args.repo, "--state", "open",
                                  "--limit", "500", "--json", "labels,state"])
                        opens = [x for x in json.loads(p2.stdout)
                                 if "handoff" not in [l["name"] for l in x.get("labels", [])]]
                        ck(f"3.{name}", name, str(len(opens)) == val.strip(), f"表={val.strip()} 算={len(opens)}")
                    except Exception as e:
                        ck(f"3.{name}", name, False, f"复算失败: {str(e)[:80]}")
                elif cmd.startswith("git ls-files"):
                    got = len(run(["git", "-C", str(repo_dir), "ls-files"]).stdout.strip().splitlines())
                    ck(f"3.{name}", name, str(got) == val.strip(), f"表={val.strip()} 算={got}")
                else:
                    print(f"  [SKIP] 3.{name} {name}: 复算命令需本机特殊环境,跳过({cmd[:50]}...)")

    # ---- 4. 正文 #N 引用存在 ----
    print("=== check 4: 正文 #N 引用全部存在 ===")
    missing = []
    for n in sorted(set(int(x) for x in re.findall(r"#(\d+)", txt))):
        p = run(["gh", "api", f"repos/{args.repo}/issues/{n}", "--jq", ".state"])
        if p.returncode != 0:
            p2 = run(["gh", "api", f"repos/{args.repo}/pulls/{n}", "--jq", ".state"])
            if p2.returncode != 0:
                missing.append(n)
    ck("4", "缺失引用数", not missing, f"缺失: {missing}" if missing else "全部存在")

    # ---- 5. 8 节骨架 ----
    print("=== check 5: 8 节骨架(含 §7) ===")
    for s in SECTION_TITLES:
        ck(f"5.{s.split('.')[0]}", s, s in txt, "" if s in txt else "缺失")

    # ---- 6. HANDOFF.md 未改 ----
    print("=== check 6: HANDOFF.md 无未提交改动 ===")
    if args.mode == "local":
        print("  [SKIP] local 模式不校验 HANDOFF.md")
    else:
        p = run(["git", "-C", str(repo_dir), "status", "--short", "HANDOFF.md"])
        ck("6", "HANDOFF.md 无未提交改动", p.returncode == 0 and not p.stdout.strip(),
           (p.stderr.strip() if p.returncode else p.stdout.strip())[:80])

    # ---- 7. 发布前 open handoff 与 supersedes 一致 ----
    print("=== check 7: 发布前 open handoff ===")
    if args.mode == "local":
        print("  [SKIP] local 模式不校验")
    else:
        try:
            sup = fm.get("supersedes", "")
            if sup == "null":
                expected = []
            elif re.fullmatch(r"[1-9][0-9]*", sup):
                expected = [int(sup)]
            else:
                raise ValueError("supersedes 必须是 null 或正整数")
            actual = open_handoffs(args.repo)
            ck("7", "open handoff 与 supersedes 一致", actual == expected,
               f"当前 {actual}, 期望 {expected}")
        except (RuntimeError, ValueError) as e:
            ck("7", "open handoff 与 supersedes 一致", False, f"检查失败: {str(e)[:80]}")

    # ---- 8. §4 表行首必须 issue 号 ----
    print("=== check 8: §4 表行首 #N 必须是 issue 号 ===")
    sec4 = re.search(r"## 4\. 遗留与阻塞\n(.*?)\n## 5\.", txt, re.S)
    if not sec4:
        ck("8", "§4 存在", False, "未找到 §4")
    else:
        bad = []
        for line in sec4.group(1).splitlines():
            m2 = re.match(r"^\| #(\d+) \|", line)
            if not m2:
                continue
            n = int(m2.group(1))
            p = run(["gh", "api", f"repos/{args.repo}/issues/{n}", "--jq", ".state"])
            if p.returncode != 0:
                bad.append(n)
                continue
            # PR 也是 issue 子类,issues/N 对 PR 返回 200;要再查 pulls/N 才分得清
            p2 = run(["gh", "api", f"repos/{args.repo}/pulls/{n}", "--jq", ".state"])
            if p2.returncode == 0:
                bad.append(n)
        ck("8", "§4 行首全为 issue 号", not bad, f"PR 号误入: {bad}" if bad else "全部是 issue")

    # ---- 汇总 ----
    fails = [r for r in results if not r[1]]
    print("")
    print(f"=== 结果: PASS={len(results) - len(fails)} FAIL={len(fails)} ===")
    if fails:
        print("失败项:")
        for no, _, detail in fails:
            print(f"  {no}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
