#!/usr/bin/env python3
"""collect.py — handoff 事实底盘取数器。

出四块机器可复算的事实,agent 不许手改数字:
  frontmatter(schema/repo/window/baseline_commit/head_commit/supersedes)
  §1  数据口径表(每行带复算命令)
  §2  本窗口交付表(行 = merged PR,验证状态从 linked issue label 取)
  §4  遗留与阻塞骨架(open issue 按 API 状态预分三类)

用法:
  python collect.py --repo OWNER/REPO --baseline 3dfc35d --head fd0ea53
  python collect.py --repo OWNER/REPO --baseline 3dfc35d --head fd0ea53 --supersedes 298
  python collect.py --repo OWNER/REPO --baseline 3dfc35d --head fd0ea53 --out draft.md

输出到 stdout(--out 写文件)。所有数字来自 gh API / git,不来自 agent 记忆。
依赖:gh CLI 已登录(PAT 需 repo scope),git 在 PATH,目标仓可本地 clone 或已在当前目录。
失败语义:任何一步取数失败 → 非零退出 + stderr 打印缺什么,不降级、不写半份。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows 默认 GBK 代码页会解不了中文 stdout;全程强制 UTF-8
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

HANDOFF_LABEL = "handoff"

REQUIRED_FM = ["schema", "repo", "window", "baseline_commit", "head_commit", "supersedes"]


def _env() -> dict:
    e = os.environ.copy()
    e["PYTHONUTF8"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    e["LANG"] = "C.UTF-8"
    # 本机网络坑:代理失效时 gh 走直连更稳(wiredraw handoff #298 §四.7)
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        e.pop(k, None)
    return e


def run(cmd: list[str], *, cwd: Path | None = None) -> str:
    """跑命令拿 stdout;失败即 raise,不静默降级。"""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=_env())
    if p.returncode != 0:
        raise RuntimeError(
            f"命令失败({p.returncode}): {' '.join(cmd)}\nstdout: {p.stdout[:200]}\nstderr: {p.stderr.strip()[:400]}"
        )
    return p.stdout


def gh(repo: str, path: str, args: list[str] | None = None) -> dict | list:
    cmd = ["gh", "api", f"repos/{repo}/{path}"]
    if args:
        cmd += args
    out = run(cmd)
    return json.loads(out) if out.strip() else {}


def gh_list(repo: str, kind: str, **params) -> list[dict]:
    """gh issue/pr list 的分页封装。"""
    cmd = ["gh", kind, "list", "--repo", repo, "--state", "all",
           "--limit", "500", "--json", params.pop("fields")]
    for k, v in params.items():
        cmd += ["--" + k, str(v)]
    return json.loads(run(cmd))


def git(repo_dir: Path, *args: str) -> str:
    return run(["git", "-C", str(repo_dir), *args]).strip()


def parse_frontmatter(path: Path) -> dict:
    txt = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    if not m:
        return {}
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def find_prev_handoff(repo_dir: Path, repo: str) -> dict | None:
    """找当前 open handoff issue(配合 HANDOFF.md 死文字路径,不扫标题)。

    返回 {number, baseline_commit, head_commit} 或 None(首份)。
    """
    items = gh_list(repo, "issue", fields="number,title,body", label=HANDOFF_LABEL)
    # gh issue list 的 state 字段是大写 OPEN/CLOSED
    open_ones = [i for i in items if i.get("state") == "OPEN" and i.get("pull_request") is None]
    if not open_ones:
        return None
    if len(open_ones) > 1:
        sys.stderr.write(
            f"[collect] 警告:open handoff issue 有 {len(open_ones)} 份"
            f"({[i['number'] for i in open_ones]}),取最大号;请先手工关多余的\n"
        )
    cur = max(open_ones, key=lambda i: i["number"])
    body = cur.get("body") or ""
    base = re.search(r"^baseline_commit:\s*([0-9a-fA-F]+)", body, re.M)
    head = re.search(r"^head_commit:\s*([0-9a-fA-F]+)", body, re.M)
    return {"number": cur["number"],
            "baseline_commit": base.group(1) if base else None,
            "head_commit": head.group(1) if head else None}


def collect(repo: str, repo_dir: Path, baseline: str, head: str,
            supersedes: int | None, today: str, window_start: str) -> str:
    # ---- 0. 前置:gh 可用 + baseline 可达 ----
    run(["gh", "auth", "status"])  # 失败即 abort(D6 硬失败)
    git(repo_dir, "merge-base", "--is-ancestor", baseline, head)

    # ---- 1. 窗口事实(全部从 API/gits 复算)----
    compare = gh(repo, f"compare/{baseline}...{head}")
    total_commits = compare["total_commits"]

    merge_subjects = [c["commit"]["message"].split("\n")[0]
                      for c in compare["commits"]
                      if c["commit"]["message"].startswith("Merge pull request")]
    pr_merges = len(merge_subjects)
    # 全口径合并提交 = git log --merges(含本地回合 origin/main)
    all_merges = git(repo_dir, "log", f"{baseline}..{head}", "--merges", "--format=%s").splitlines()
    local_merges = len(all_merges) - pr_merges

    merged_prs = [p for p in gh_list(repo, "pr", fields="number,title,mergedAt,body")
                  if (p.get("mergedAt") or "") >= window_start]
    merged_prs.sort(key=lambda p: p["number"])

    closed_issues = [i for i in gh_list(repo, "issue", fields="number,closedAt")
                     if (i.get("closedAt") or "") >= window_start]
    # gh issue list 的 state 字段是大写 OPEN/CLOSED
    open_issues = [i for i in gh_list(repo, "issue", fields="number,title,labels,state")
                   if i["state"] == "OPEN"
                   and HANDOFF_LABEL not in [l["name"] for l in i.get("labels", [])]]
    open_issues.sort(key=lambda i: i["number"])

    tracked_files = len(git(repo_dir, "ls-files").splitlines())
    gates = run(["python", "scripts/run_gates.py", "--list"], cwd=repo_dir)
    gate_rows = re.findall(r"^\[(ci|manual|support)\]\s+(\d+) 条", gates, re.M)
    gate_str = " / ".join(f"{k} {v}" for k, v in gate_rows) or "未检出"
    common = run(["python", "scripts/_common.py"], cwd=repo_dir)
    selftest = re.search(r"自检全绿[:：]\s*(\d+)\s*项", common)
    selftest_n = selftest.group(1) if selftest else "未检出"
    vis = json.loads(run(["gh", "repo", "view", repo, "--json", "visibility"]))["visibility"]

    # ---- 2. §2 交付表(行 = merged PR,验证状态从 linked issue label 取)----
    pr_issue_map: dict[int, list[int]] = {}
    for p in merged_prs:
        body_txt = p.get("body") or ""
        # 只取 Closes/Refs/Fixes 关键词后的 #N,不扫标题、不扫正文叙述里的 #N
        nums = []
        for m in re.finditer(r"(?:Closes|Refs|Fixes)\s+#(\d+)", body_txt):
            n = int(m.group(1))
            if n not in nums:
                nums.append(n)
        pr_issue_map[p["number"]] = nums

    issue_label_cache: dict[int, list[str]] = {}
    for i in open_issues:
        issue_label_cache[i["number"]] = [l["name"] for l in i.get("labels", [])]
    for n in {num for nums in pr_issue_map.values() for num in nums}:
        if n in issue_label_cache:
            continue
        # gh api issues/N 对 PR 号会返回 PR 对象(--jq 路径不匹配 → 空 stdout,JSON 解析失败)
        # 用 issues/N + pulls/N 双查,先判类型再取 label
        p = subprocess.run(["gh", "api", f"repos/{repo}/issues/{n}",
                            "--jq", ".labels"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=_env())
        if p.returncode == 0 and p.stdout.strip().startswith("["):
            labs = json.loads(p.stdout)
        else:
            labs = []
        issue_label_cache[n] = [l["name"] for l in labs]

    def verify_state(pr: dict) -> str:
        linked = pr_issue_map.get(pr["number"], [])
        if not linked:
            return "无 linked issue"
        states = []
        for n in linked:
            labs = issue_label_cache.get(n, [])
            if "needs-live-verify" in labs:
                states.append(f"#{n} 待真机回签")
            elif n in [i["number"] for i in open_issues]:
                states.append(f"#{n} 仍 open")
            else:
                states.append(f"#{n} 已关闭")
        return "; ".join(states)

    # ---- 3. §4 遗留骨架(脚本按 label + API 状态预分四类,agent 修正)----
    # 桶语义(label 优先,窗口内 merged PR 次之):
    #   verify-pending : open + needs-live-verify label → 等真机回签(PR 在不在窗口内都进)
    #   merged-unclosed: open + 无 needs-live-verify + 窗口内有 merged PR linked → 验收口径/维护者未决
    #   needs-repro    : open + needs-repro label + 无窗口内 merged PR → 缺复现
    #   code-needed    : open + 其余 → 要代码/要硬件/要维护者/理论风险(agent 细分)
    def classify(i: dict) -> str:
        labs = [l["name"] for l in i.get("labels", [])]
        linked_prs = [p for p in merged_prs if i["number"] in pr_issue_map.get(p["number"], [])]
        if "needs-live-verify" in labs:
            return "verify-pending"
        if linked_prs:
            return "merged-unclosed"
        if "needs-repro" in labs:
            return "needs-repro"
        return "code-needed"

    buckets = {"verify-pending": [], "merged-unclosed": [], "needs-repro": [], "code-needed": []}
    for i in open_issues:
        buckets[classify(i)].append(i)

    def issue_row(i: dict) -> str:
        labs = ",".join(l["name"] for l in i.get("labels", []))
        return f"| #{i['number']} | {i['title']}" + (f" | {labs} |" if labs else " | |")

    # ---- 4. 组装输出 ----
    L: list[str] = []
    L.append("---")
    L.append("schema: handoff/v1")
    L.append(f"repo: {repo}")
    L.append(f'window: {{from: "{window_start}", to: "{today}"}}')
    L.append(f"baseline_commit: {baseline}")
    L.append(f"head_commit: {head}")
    L.append(f"supersedes: {supersedes if supersedes else 'null'}")
    L.append("---")
    L.append("")
    L.append("## 1. 数据口径")
    L.append("")
    L.append("全部数字由 collect.py 从 git/gh API 取数,复算命令见右列。open issue 口径排除 label `handoff` 自身。")
    L.append("")
    L.append("| 数字 | 值 | 取数与口径 |")
    L.append("|---|---|---|")
    L.append(f"| 提交数(含合并提交) | {total_commits} | `gh api repos/{repo}/compare/{baseline}...{head} --jq .total_commits` |")
    L.append(f"| 合并提交 | {len(all_merges)} | `git log {baseline}..{head} --merges` 全口径;其中 {pr_merges} 条 `Merge pull request`,{local_merges} 条本地回合 origin/main |")
    L.append(f"| 合并 PR(窗口内) | {len(merged_prs)} | `gh pr list --state all --json mergedAt` 过滤 `mergedAt >= {window_start}` |")
    L.append(f"| 关闭 issue(窗口内) | {len(closed_issues)} | `gh issue list --state closed --json closedAt` 过滤 `closedAt >= {window_start}` |")
    L.append(f"| 当前 open issue | {len(open_issues)} | `gh issue list --state open` 排除 label `handoff` |")
    L.append(f"| 被跟踪文件 | {tracked_files} | `git ls-files \\| wc -l` |")
    L.append(f"| 门禁条数 | {gate_str} | `python scripts/run_gates.py --list` |")
    L.append(f"| 共享层自检 | {selftest_n} 项 | `python scripts/_common.py` 末行 `== 自检全绿:N 项 ==` |")
    L.append(f"| 仓库可见性 | {vis} | `gh repo view --json visibility --jq .visibility` |")
    L.append("")
    L.append("## 2. 本窗口交付")
    L.append("")
    L.append(f"行 = merged PR({len(merged_prs)} 个)。验证状态 = linked issue 的 label(由 collect.py 从 PR body 的 Closes/Refs 解析)。")
    L.append("")
    L.append("| PR | 标题 | linked issue | 验证状态 |")
    L.append("|---|---|---|---|")
    for p in merged_prs:
        linked = pr_issue_map.get(p["number"], [])
        link_str = " ".join(f"#{n}" for n in linked) or "-"
        L.append(f"| #{p['number']} | {p['title']} | {link_str} | {verify_state(p)} |")
    L.append("")
    L.append("## 3. 决策与理由")
    L.append("")
    L.append("(agent 填写:本轮关键决策、取舍理由、被否掉的方案)")
    L.append("")
    L.append("## 4. 遗留与阻塞")
    L.append("")
    L.append("行 = 当前 open issue(排除 handoff 自身),按脚本预分四类;agent 修正分类后定稿。")
    L.append("")
    L.append("### 4.1 待真机回签(verify-pending)")
    L.append("")
    L.append("| issue | 标题 | label |")
    L.append("|---|---|---|")
    for i in buckets["verify-pending"]:
        L.append(issue_row(i))
    L.append("")
    L.append("### 4.2 已合并但 issue 未关(merged-unclosed)")
    L.append("")
    L.append("| issue | 标题 | label |")
    L.append("|---|---|---|")
    for i in buckets["merged-unclosed"]:
        L.append(issue_row(i))
    L.append("")
    L.append("### 4.3 缺复现(needs-repro)")
    L.append("")
    L.append("| issue | 标题 | label |")
    L.append("|---|---|---|")
    for i in buckets["needs-repro"]:
        L.append(issue_row(i))
    L.append("")
    L.append("### 4.4 要代码 / 要硬件 / 要维护者(code-needed)")
    L.append("")
    L.append("| issue | 标题 | label |")
    L.append("|---|---|---|")
    for i in buckets["code-needed"]:
        L.append(issue_row(i))
    L.append("")
    L.append("## 5. 下一步")
    L.append("")
    L.append("(agent 填写:可执行顺序,每条带前置 + 验收命令)")
    L.append("")
    L.append("## 6. 环境与坑")
    L.append("")
    L.append("(agent 填写:环境事实 + 复现命令;口述无记录的一律进 §7)")
    L.append("")
    L.append("## 7. 无法追溯与不确定项")
    L.append("")
    L.append("(agent 填写:无复算命令的数字、无文字记录的结论、来源不明的口径;允许为空,不允许省略本节)")
    L.append("")
    return "\n".join(L)


def read_handoff(path: Path) -> int:
    """--read:给 agent 用的结构化读取器。只解析,不取数、不联网。"""
    txt = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(path)
    for f in REQUIRED_FM:
        if not fm.get(f):
            print(f"[read] 错误:frontmatter 缺 {f}", file=sys.stderr)
            return 2

    def sec(title: str) -> str:
        m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", txt, re.M | re.S)
        return m.group(1).strip("\n") if m else ""

    rows = re.findall(r"^\| (.+?) \| (.+?) \| `.+?` \|$", sec("1. 数据口径"), re.M)
    facts = {name.strip(): val.strip() for name, val in rows}
    pr_rows = re.findall(r"^\| #(\d+) \| (.+?) \| (.+?) \| (.+?) \|$", sec("2. 本窗口交付"), re.M)
    buckets = {}
    for b in ("verify-pending", "merged-unclosed", "needs-repro", "code-needed"):
        # 桶标题后可能跟 agent 拆的子节(####),子节标题也带桶名,只数桶自己的表行
        m = re.search(rf"^### 4\.\d .*{re.escape(b)}\)\n(.*?)(?=^### |\Z)",
                      sec("4. 遗留与阻塞"), re.M | re.S)
        buckets[b] = len(re.findall(r"^\| #\d+ ", m.group(1), re.M)) if m else 0
    out = {
        "schema": fm["schema"], "repo": fm["repo"], "window": fm["window"],
        "baseline_commit": fm["baseline_commit"], "head_commit": fm["head_commit"],
        "supersedes": fm["supersedes"],
        "facts": facts,
        "deliveries": [{"pr": int(n), "title": t, "linked": l, "verify_state": v}
                       for n, t, l, v in pr_rows],
        "leftovers": buckets,
        "sections_filled": {s: bool(sec(s).strip()) for s in
                            ("3. 决策与理由", "5. 下一步", "6. 环境与坑", "7. 无法追溯与不确定项")},
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="handoff 事实底盘取数器")
    ap.add_argument("--read", metavar="FILE",
                    help="读取器模式:解析已生成的 handoff 草案/正文,输出结构化 JSON(不联网)")
    args, rest = ap.parse_known_args()
    if args.read:
        return read_handoff(Path(args.read))

    ap2 = argparse.ArgumentParser(description="handoff 事实底盘取数器")
    ap2.add_argument("--repo", required=True, help="OWNER/REPO")
    ap2.add_argument("--baseline", required=True, help="基线 commit(上一份 frontmatter.baseline_commit)")
    ap2.add_argument("--head", help="head commit,默认 HEAD")
    ap2.add_argument("--supersedes", type=int, default=None, help="上一份 handoff issue 号,首份省略")
    ap2.add_argument("--today", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                     help="窗口右界(默认今天 UTC)")
    ap2.add_argument("--window-start",
                     help="窗口起点(YYYY-MM-DD),默认取上一份 handoff 的 head_commit 日期;首份必传")
    ap2.add_argument("--repo-dir", default=".", help="本地 git 仓路径,默认当前目录")
    ap2.add_argument("--out", help="输出文件,默认 stdout")
    a = ap2.parse_args(rest)

    repo_dir = Path(a.repo_dir)
    head = a.head or git(repo_dir, "rev-parse", "--short", "HEAD")

    # supersedes 未传 → 自动找当前 open handoff(D1 链)
    prev = find_prev_handoff(repo_dir, a.repo)
    sup = a.supersedes if a.supersedes is not None else (prev["number"] if prev else None)
    base = a.baseline or (prev["baseline_commit"] if prev else None)
    if not base:
        sys.stderr.write("[collect] 错误:无上一份 handoff 且未传 --baseline;首份请手工指定基线\n")
        return 2

    # window_start:显式传入 > 上一份 head 日期 > 报错(首份必须给)
    ws = a.window_start
    if not ws:
        if prev and prev.get("head_commit"):
            ws = gh(a.repo, f"commits/{prev['head_commit']}")["commit"]["committer"]["date"][:10]
        else:
            sys.stderr.write("[collect] 错误:无上一份 handoff 且未传 --window-start;首份请手工指定窗口起点\n")
            return 2

    body = collect(a.repo, repo_dir, base, head, sup, a.today, ws)
    if a.out:
        out_path = Path(a.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
        print(f"[collect] 已写 {a.out}({len(body)} 字符)")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"[collect] 硬失败:{e}", file=sys.stderr)
        sys.exit(1)
