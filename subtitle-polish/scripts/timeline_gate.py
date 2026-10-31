# -*- coding: utf-8 -*-
"""timeline_gate.py — 阶段 0 闸门：这条字幕的时间轴能不能用于开工。

只读 `<episode>.ts.json`（由 `align_audit --write-credential` 产出），不跑模型、
不碰音频，毫秒级返回。存在的意义是**不给「静默跳过」留路**：文档里写一句
「必须写明未验」是软约束，赶工时一定被跳过；只有退出码非零，才会真的停下来。

用法:
  python timeline_gate.py S06E01.ass
  python timeline_gate.py S06E01.ass --media S06E01.mkv
  python timeline_gate.py <目录>                # 逐集检查，任一不过则整体不过
  python timeline_gate.py S06E01.ass --json out.json

退出码（见 lib/verdict.py）:
  0 PASS        可以开工
  2 FAIL        凭据判定轴有问题，必须先修
  3 UNVERIFIED  没验 / 凭据失效，先跑 align_audit --write-credential
  4 AMBIGUOUS   验了但判不出来（多条候选轴无法区分）

批量时取最坏：任一 FAIL -> 2，否则任一 AMBIGUOUS -> 4，否则任一 UNVERIFIED -> 3。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import credential as cred
from lib import verdict as V

SUB_EXT = (".ass", ".ssa", ".srt")
SEVERITY = {V.PASS: 0, V.UNVERIFIED: 1, V.AMBIGUOUS: 2, V.FAIL: 3}


def collect(target: str) -> list:
    if os.path.isdir(target):
        out = []
        for ext in SUB_EXT:
            out += glob.glob(os.path.join(target, "**", "*" + ext), recursive=True)
        return sorted(p for p in out if not p.endswith(".bak"))
    if os.path.isdir(os.path.dirname(os.path.abspath(target))) and any(
            c in target for c in "*?["):
        return sorted(glob.glob(target))
    return [target]


def aggregate(codes: list) -> int:
    if not codes:
        return V.UNVERIFIED
    worst = max(codes, key=lambda c: SEVERITY.get(c, 1))
    return worst


def main():
    ap = argparse.ArgumentParser(
        description="时间轴闸门：读 sidecar 凭据判定能否开工（不跑模型）",
        epilog="PASS 只代表凭据有效且当时验过；它不重新验轴，也不代表现在一定没跑偏。")
    ap.add_argument("target", help="字幕文件，或包含字幕的目录")
    ap.add_argument("--media", help="片源。凭据绑定过片源时必须提供，否则判 UNVERIFIED")
    ap.add_argument("--json", help="把逐集结果写成 json")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args()

    subs = collect(args.target)
    if not subs:
        print("[gate] 没有找到字幕文件：%s" % args.target, file=sys.stderr)
        sys.exit(V.UNVERIFIED)

    # 目录模式下，同一个片源对应多集是不成立的；只有单文件才允许 --media
    media = args.media if len(subs) == 1 else None
    if args.media and len(subs) > 1:
        print("[!] 多文件模式下忽略 --media（应为每集各自的片源）", file=sys.stderr)

    results = []
    for sub in subs:
        res = cred.check(sub, media=media)
        results.append({"sub": os.path.abspath(sub), "code": res["verdict"],
                        "state": V.label(res["verdict"]),
                        "reasons": res["reasons"],
                        "detail": res["detail"]})
        if not args.quiet:
            print("── %s" % os.path.basename(sub))
            print(cred.render(res))
            print()

    codes = [r["code"] for r in results]
    agg = aggregate(codes)
    n_bad = sum(1 for c in codes if c != V.PASS)
    if len(results) > 1:
        print("── 汇总  %d 集，%d 集不可用" % (len(results), n_bad))
        for r in results:
            if r["code"] != V.PASS:
                print("   %-12s %-11s %s"
                      % (r["state"], os.path.basename(r["sub"]),
                         (r["reasons"] or [""])[0][:70]))

    if agg == V.PASS:
        print("[gate] PASS —— 凭据有效，可开工")
    elif agg == V.FAIL:
        print("[gate] FAIL —— 轴有问题，先修再开工（见 references/align-audit.md）")
    elif agg == V.AMBIGUOUS:
        print("[gate] AMBIGUOUS —— 验了但判不出来。两种常见成因：")
        print("       ① 多条候选轴无法区分，需人工确认用的是哪条流；")
        print("       ② 换一种 qwen 分块，窗间极差就跨到阈值另一边——")
        print("          说明这个极差没稳定到可判定的程度，别当成 PASS 用。")
    else:
        print("[gate] UNVERIFIED —— 没验或凭据失效。先跑：")
        print("       python align_audit.py --sub <ass> --media <片源> --write-credential")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"verdict": V.label(agg), "code": agg,
                       "items": results}, f, ensure_ascii=False, indent=1)
        print("[json] %s" % args.json)

    sys.exit(agg)


if __name__ == "__main__":
    main()
