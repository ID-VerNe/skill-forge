# -*- coding: utf-8 -*-
"""regression_check.py — 跨轮次回归检测（只用 log.jsonl，不需要模型）。

为什么需要：审计 agent 每轮看到的只有**当前盘面 + 英文源**。它不知道哪些行
上周刚改过、为什么改，于是可能出现

  R6 强项 → 地盘      （改错）
  R7 地盘 → 强项      （改回来）
  R8 维持强项          （agent 又把 R7 报了一遍「强项偏成归属」，已驳回）

三轮 `verify_fixes` 都是 0 失败、`cross_check` 都是 0 预警——**没有信号能发现
这个来回**。三条里两条要翻回来（skill-forge issue #6）。

三个子功能都只输出线索，不阻断：

  --ledger     台账：近 N 轮改过哪些行、改成什么、当时理由。直接贴进审计 prompt
  --conflicts  同一行被 ≥2 轮改过；标出「疑似反向」
  --converged  连续两轮相同结论 → 已收敛，后续可降权抽查

用法:
  python regression_check.py                     # 台账 + 连续改动（默认）
  python regression_check.py --ledger --window 3  # 只要台账，整段贴进审计 prompt
  python regression_check.py --conflicts         # 只看「同一行被多轮改过」
  python regression_check.py --converged         # 只看已收敛的
  python regression_check.py --all --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import log as plog
from lib import regress as rg
from lib.paths import resolve_work_dir, report_path


def build(entries, window=3):
    hist = rg.history(entries)
    return {
        "history": hist,
        "conflicts": rg.conflicts(hist, window),
        "ledger": rg.ledger(hist, window),
    }


def render_md(data, window, out_path, sections=("ledger", "conflicts")):
    show_ledger = "ledger" in sections
    show_conf = "conflicts" in sections
    L = ["# 轮次回归检测", "",
         f"- 窗口: 近 {window} 轮" if window else "- 窗口: 全部",
         f"- 有过文本改动的行: {len(data['history'])}",
         f"- 连续改动: {len(data['conflicts'])}", ""]

    if show_ledger and data["ledger"]:
        L += ["## 台账（贴进审计 prompt）", "",
              "> 这些行近期被改过，请**特别核验现在的译文是否正确**。",
              "> 若判为错误，必须说明「当时那条理由错在哪」，不是只说「现在这个不对」。", "",
              "| srt_id | 轮次 | 改动前 | 改动后 | 当时理由 |",
              "|---|---|---|---|---|"]
        for r in data["ledger"]:
            L.append("| %s | %s | %s | %s | %s |" % (
                r["srt_id"], r["batch"],
                rg.clean(r["old"])[:28] or "—",
                rg.clean(r["new"])[:28] or "—",
                (r["reason"] or r["category"] or "—")[:30]))
        L.append("")
    elif show_ledger:
        L += ["## 台账（贴进审计 prompt）", "", "近期没有文本改动。", ""]

    if not show_conf:
        pass
    elif data["conflicts"]:
        L += ["## 连续改动", ""]
        for c in data["conflicts"]:
            _f, sid, track = c["key"]
            conv = rg.converged(c["trail"])
            L.append(f"### #{sid}（{track}）· 被 {c['n_rounds']} 轮改过"
                     + ("　✅ 已收敛" if conv else "　⚠ 还没收敛"))
            L.append("")
            for h in c["trail"]:
                L.append(f"- `{h['batch']}`: {rg.clean(h['old'])[:40] or '—'} → "
                         f"**{rg.clean(h['new'])[:40]}**"
                         + (f"（{h['reason']}）" if h["reason"] else ""))
            rev = rg.reversals(c["trail"])
            for r in rev:
                L.append(f"- ⚠ **疑似反向**：与 `{r['earlier_round']}` 的相似度 "
                         f"{r['sim_earlier']:.2f} > 与 `{r['prev_round']}` 的 "
                         f"{r['sim_prev']:.2f}")
            L.append("")
        L.append("> 「疑似反向」是确定性判据（字符串相似度），不是语义判断。"
                 "翻回去有时是对的——上一轮确实可能改错了。")
        L.append("")
    else:
        L += ["## 连续改动", "", "没有同一行被多轮改动的情况。", ""]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="跨轮次回归检测（只读 log.jsonl）")
    ap.add_argument("--window", type=int, default=3,
                    help="看最近几个 batch（0 = 全部，默认 3）")
    ap.add_argument("--ledger", action="store_true", help="只输出台账表")
    ap.add_argument("--conflicts", action="store_true", help="只输出连续改动")
    ap.add_argument("--converged", action="store_true", help="只列已收敛的连续改动")
    ap.add_argument("--all", action="store_true", help="全部输出（默认行为）")
    ap.add_argument("--work-dir", default=".subtitle-polish")
    ap.add_argument("--json", help="结果写 json")
    ap.add_argument("--out", help="md 输出路径（默认 reports/regression.md）")
    args = ap.parse_args()

    wd = resolve_work_dir(args.work_dir)
    entries = plog.read_log(wd)
    if not entries:
        print(f"[!] {wd}/log.jsonl 不存在或为空")
        return 1

    data = build(entries, args.window)
    if args.converged:
        data["conflicts"] = [c for c in data["conflicts"]
                             if rg.converged(c["trail"])]

    # 选段：给了 --ledger/--conflicts/--converged 就只输出点名的那些段，
    # 都没给（或 --all）就全出。--conflicts 以前是装饰性开关——默认本来就
    # 输出全部，所以它实际上什么也不做。现在它真的管用。
    picked = set()
    if args.ledger:
        picked.add("ledger")
    if args.conflicts or args.converged:
        picked.add("conflicts")
    sections = picked or {"ledger", "conflicts"}

    out = args.out or report_path(wd, "regression.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    render_md(data, args.window, out, sections)

    n_rev = sum(len(rg.reversals(c["trail"])) for c in data["conflicts"])
    n_conv = sum(1 for c in data["conflicts"] if rg.converged(c["trail"]))
    print(f"[*] 连续改动 {len(data['conflicts'])} 行（已收敛 {n_conv}，"
          f"疑似反向 {n_rev}），台账 {len(data['ledger'])} 条")
    print(f"[*] 报告 {out}")

    if args.ledger:
        for r in data["ledger"]:
            print("  #%-5s %-16s %s → %s" % (
                r["srt_id"], r["batch"],
                rg.clean(r["old"])[:20] or "—", rg.clean(r["new"])[:20]))

    if args.json:
        payload = {
            "window": args.window,
            "conflicts": [{"srt_id": c["key"][1], "track": c["key"][2],
                           "rounds": c["rounds"],
                           "converged": rg.converged(c["trail"]),
                           "reversals": rg.reversals(c["trail"]),
                           "trail": c["trail"]} for c in data["conflicts"]],
            "ledger": data["ledger"],
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"[json] {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
