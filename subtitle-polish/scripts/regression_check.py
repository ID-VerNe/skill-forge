# -*- coding: utf-8 -*-
"""regression_check.py — 跨轮次回归检测（只用 log.jsonl，不需要模型）。

为什么需要：审计 agent 每轮看到的只有**当前盘面 + 英文源**。它不知道哪些行
上周刚改过、为什么改，于是可能出现

  R6 强项 → 地盘      （改错）
  R7 地盘 → 强项      （改回来）
  R8 维持强项          （agent 又把 R7 报了一遍「强项偏成归属」，已驳回）

三轮 `verify_fixes` 都是 0 失败、`cross_check` 都是 0 预警——**没有信号能发现
这个来回**。三条里两条要翻回来（skill-forge issue #6）。

四个子功能都只输出线索，不阻断：

  --ledger   台账：近 N 轮改过哪些行、改成什么、（可选）当时理由。
             `--no-reason` 去掉理由列 = 可贴进审计 prompt 的那一份
  --conflicts 同一行被 ≥2 轮改过；标出「疑似反向」
  --settled  改过、但最近 N 轮没再被动的行（「沉住」的唯一可观测形式）

**没有「已收敛」这一项。** log 只记改动，不记「看过了、同意」——一致是不留痕的，
所以「已收敛」不可观测。「连续两轮给出相同 new_text」在一致的日志里永远为假：
相邻两条满足 old[i] == new[i-1]，若再有 new[i] == new[i-1]，则 old[i] == new[i]，
那是一条空改动记录。详见 lib/regress.py 的 _is_text_change / settled。

用法:
  python regression_check.py                     # 台账 + 连续改动（默认）
  python regression_check.py --ledger --no-reason # 只要台账，贴进审计 prompt（不含理由）
  python regression_check.py --ledger --window 3  # 只要台账，含当时理由（人工复看用）
  python regression_check.py --conflicts         # 只看「同一行被多轮改过」
  python regression_check.py --settled           # 只看「最近没再被推翻」的
  python regression_check.py --all --json out.json

`--no-reason` 的意义：台账里的 reason 是上一轮的**判断结论**。贴进审计 prompt 后，
agent 会顺着上轮逻辑往下推（`bag` 连推三轮即此成因）。所以给 prompt 的那一份必须
剥掉理由列，只留「哪一行被改成什么」。详见 references/prompt-injection.md 规则 4。
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


def recent_batches(entries, n):
    """最近 n 个 batch_id（按 ts）。n=0 表示空集（不筛）。"""
    if not n:
        return set()
    order = []
    for e in sorted(entries, key=lambda x: x.get("ts", "")):
        b = e.get("batch_id")
        if b not in order:
            order.append(b)
    return set(order[-n:])


def build(entries, window=3):
    hist = rg.history(entries)
    return {
        "history": hist,
        "conflicts": rg.conflicts(hist, window),
        "ledger": rg.ledger(hist, window),
        "settled": rg.settled(hist, recent_batches(entries, window)),
        "churn": rg.churn(hist),
    }


def render_md(data, window, out_path, sections=("ledger", "conflicts"),
              with_reason=True):
    show_ledger = "ledger" in sections
    show_conf = "conflicts" in sections
    show_settled = "settled" in sections
    L = ["# 轮次回归检测", "",
         f"- 窗口: 近 {window} 轮" if window else "- 窗口: 全部",
         f"- 有过文本改动的行: {len(data['history'])}",
         f"- 连续改动: {len(data['conflicts'])}",
         f"- 最近 {window} 轮没再被动: {len(data['settled'])}", ""]

    if show_ledger and data["ledger"]:
        L += ["## 台账（贴进审计 prompt）", "",
              "> 这些行近期被改过，请**特别核验现在的译文是否正确**。", ""]
        if with_reason:
            L += ["> 若判为错误，必须说明「当时那条理由错在哪」，不是只说「现在这个不对」。", "",
                  "| srt_id | 轮次 | 改动前 | 改动后 | 当时理由 |",
                  "|---|---|---|---|---|"]
            for r in data["ledger"]:
                L.append("| %s | %s | %s | %s | %s |" % (
                    r["srt_id"], r["batch"],
                    rg.clean(r["old"])[:28] or "—",
                    rg.clean(r["new"])[:28] or "—",
                    (r["reason"] or r["category"] or "—")[:30]))
        else:
            # --no-reason：只给「改了什么」，不给「为什么改」。理由属判断结论，
            # 贴进审计 prompt 会让 agent 顺着上轮逻辑往下推（prompt-injection.md 规则 4）。
            L += ["> 若判为错误，必须说明「这条改动错在哪」——不是「改得不好」，"
                  "而是「它把 X 当成 Y，而 X 实际是 Z」。", "",
                  "| srt_id | 轮次 | 改动前 | 改动后 |", "|---|---|---|---|"]
            for r in data["ledger"]:
                L.append("| %s | %s | %s | %s |" % (
                    r["srt_id"], r["batch"],
                    rg.clean(r["old"])[:28] or "—",
                    rg.clean(r["new"])[:28] or "—"))
            L += ["", "> 本表**不含当时理由**（判断结论不外喂）。"
                  "要复看理由用不带 `--no-reason` 的输出。"]
        L.append("")
    elif show_ledger:
        L += ["## 台账（贴进审计 prompt）", "", "近期没有文本改动。", ""]

    if not show_conf:
        pass
    elif data["conflicts"]:
        L += ["## 连续改动", ""]
        for c in data["conflicts"]:
            _f, sid, track = c["key"]
            L.append(f"### #{sid}（{track}）· 被 {c['n_rounds']} 轮改过")
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
        L += ["> 「疑似反向」是确定性判据（字符串相似度），不是语义判断。"
              "翻回去有时是对的——上一轮确实可能改错了。",
              "",
              "> **没有「已收敛」标记。** log 只记改动、不记「看过了、同意」，"
              "一致是不留痕的，所以「已经收敛」不可观测；"
              "可观测的是反面——改完之后又被人动了。",
              ""]
    else:
        L += ["## 连续改动", "", "没有同一行被多轮改动的情况。", ""]

    if show_settled:
        L += ["## 沉住的（最近 %s 轮没再被动）" % (window or "全部"), ""]
        if data["settled"]:
            L += ["| srt_id | 轨道 | 改过几轮 | 最后改于 |", "|---|---|---|---|"]
            for s in data["settled"]:
                L.append("| %s | %s | %s | %s |" % (
                    s["key"][1], s["key"][2], s["n_rounds"], s["last"]["batch"]))
            L.append("")
        else:
            L += ["没有。", ""]

    if data["churn"]:
        L += ["## 批次沉住度", "",
              "> 这一批改的行里，后来又被改过的比例。比例高的批次，"
              "说明那批的判断后来被推翻了。", "",
              "| 轮次 | 改了 | 后来又被改 | 比例 |", "|---|---|---|---|"]
        for r in data["churn"]:
            L.append("| %s | %s | %s | %d%% |" % (
                r["batch"], r["n"], r["again"], round(r["rate"] * 100)))
        L.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="跨轮次回归检测（只读 log.jsonl）")
    ap.add_argument("--window", type=int, default=3,
                    help="看最近几个 batch（0 = 全部，默认 3）")
    ap.add_argument("--ledger", action="store_true", help="只输出台账表")
    ap.add_argument("--conflicts", action="store_true", help="只输出连续改动")
    ap.add_argument("--settled", action="store_true",
                    help="只列「改过，但最近 N 轮没再被动」的行")
    ap.add_argument("--all", action="store_true", help="全部输出（默认行为）")
    ap.add_argument("--no-reason", action="store_true",
                    help="台账不输出「当时理由」列（贴进审计 prompt 时用，防判断结论注入）")
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

    # 选段：给了 --ledger/--conflicts/--settled 就只输出点名的那些段，
    # 都没给（或 --all）就全出。--conflicts 以前是装饰性开关——默认本来就
    # 输出全部，所以它实际上什么也不做。现在它真的管用。
    picked = set()
    if args.ledger:
        picked.add("ledger")
    if args.conflicts:
        picked.add("conflicts")
    if args.settled:
        picked.add("settled")
    sections = picked or {"ledger", "conflicts", "settled"}

    out = args.out or report_path(wd, "regression.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    render_md(data, args.window, out, sections, with_reason=not args.no_reason)

    n_rev = sum(len(rg.reversals(c["trail"])) for c in data["conflicts"])
    print(f"[*] 连续改动 {len(data['conflicts'])} 行（疑似反向 {n_rev}），"
          f"台账 {len(data['ledger'])} 条，"
          f"最近 {args.window or '全部'} 轮没再被动 {len(data['settled'])} 行")
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
                           "reversals": rg.reversals(c["trail"]),
                           "trail": c["trail"]} for c in data["conflicts"]],
            "settled": [{"srt_id": s["key"][1], "track": s["key"][2],
                         "n_rounds": s["n_rounds"],
                         "last_batch": s["last"]["batch"]} for s in data["settled"]],
            "churn": data["churn"],
            "ledger": data["ledger"],
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"[json] {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
