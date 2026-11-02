# -*- coding: utf-8 -*-
"""show_ids.py — 批量打印 `srt_id → 英文 / 中文 / 时间`，供裁决时逐条核对。

为什么内置：这是**每一轮都用得上**的动作。以前每次要核对「agent 报的 srt_id 到底指哪句」
都是临时写一段 pysubs2 脚本，写法还各不相同——于是同一个 srt_id 在不同人的临时脚本里
能落到不同的行上（有人数 Dialogue 行、有人数 events、有人把注释轨也数进去）。
内置一份、口径唯一，比每次都写一遍可靠。

口径（与 `ass_srt_pair.pair()` 完全一致，不另立一套）：
  - `srt_id` = **SRT 块序号**（从 1 开始），与 audit/verify 报告里的 srt_id 同源。
  - 英文 / 中文 从 ASS 的对应轨道取；一轨多行时用 ` / ` 连接。
  - 时间取 SRT 的起止（`ass_time` 列给 ASS 侧，便于肉眼比对是否错位）。

用法:
  python show_ids.py <ass> --srt <srt>                  # 全量
  python show_ids.py <ass> --srt <srt> --ids 41,42,150  # 只看几条
  python show_ids.py <ass> --srt <srt> --range 100-160  # 看一段
  python show_ids.py <ass> --srt <srt> --grep 变速箱     # 按文本找（英文或中文命中）
  python show_ids.py <ass> --srt <srt> --md out.md      # 写 md 表格
  python show_ids.py <ass> --srt <srt> --empty          # 只列「某一侧为空」的块

设计取舍：
  - 默认只印**有内容**的块；`--empty` 反查空块。空块是审计结论「悬空」的常见根因
    （agent 说「这行译文丢了」，实际是那行根本没配上），所以必须能单独列。
  - 不可识别的样式名不做猜轨，直接列进 stderr 警告——猜错轨会让整列显示成别的语言的
    内容，而报告上完全看不出异常。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ass_srt_pair import (parse_ass, parse_srt, style_to_track,
                              TRACK_EN, TRACK_ZH, TRACK_NOTE)
from lib.ass_srt_pair import pair as pair_blocks


def build_rows(ass_path: str, srt_path: str) -> tuple:
    """返回 (rows, ass_only, unknown_styles)。rows 按 srt_id 升序。

    一行 = 一个 SRT 块。**以 SRT 为骨架**而不是以 ASS 为骨架：报表里的 srt_id
    是 SRT 序号，以 ASS 为骨架会让「只存在于 ASS 的额外行」把后面的号全部顶偏一位，
    那种偏移在表上完全看不出来。

    英文/中文直接取 `PairedBlock.english/.chinese`，不在这里重新拆轨——重新拆一遍
    就等于另立一套口径，和 `extract_slice`/`apply_fixes` 慢慢对不上。

    第三个返回项不是可选项：`pair()` 会把「没有任何 SRT 块匹配上的 ASS 行」单独
    吐回来（ass_only）。这些行在对照表里**根本不会出现**，于是「译文丢了」和
    「这行压根没配上」在表上长得一模一样。必须把它单独列出来，否则这张表会
    系统性地藏起一类问题。
    """
    ass = parse_ass(ass_path)
    srt = parse_srt(srt_path)

    unknown = sorted({d.style for d in ass
                      if style_to_track(d.style or "") not in
                      (TRACK_EN, TRACK_ZH, TRACK_NOTE)})

    paired, ass_only = pair_blocks(ass, srt)
    rows = []
    for pb in paired:
        rows.append({
            "srt_id": pb.srt_id,
            "srt_start": pb.srt_start,
            "srt_end": pb.srt_end,
            "ass_time": pb.ass_time,
            "en": (pb.english or "").strip(),
            "zh": (pb.chinese or "").strip(),
            "note": (pb.note or "").strip(),
            "anomalies": list(pb.anomalies or []),
        })
    rows.sort(key=lambda r: r["srt_id"])
    return rows, ass_only, unknown


def _clip(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n or n <= 0 else s[:n - 1] + "…"


def render_md(rows, ass_path, srt_path) -> str:
    L = ["# srt_id 对照表", "",
         f"- ASS：`{os.path.abspath(ass_path)}`",
         f"- SRT：`{os.path.abspath(srt_path)}`",
         f"- 块数：{len(rows)}", "",
         "| srt_id | 时间(秒) | 英文 | 中文 |",
         "|---|---|---|---|"]
    for r in rows:
        L.append("| %d | %.2f–%.2f | %s | %s |" % (
            r["srt_id"], r["srt_start"], r["srt_end"],
            _clip(r["en"], 70) or "—", _clip(r["zh"], 70) or "—"))
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="打印 srt_id → 英文/中文/时间 对照表（只读）")
    ap.add_argument("ass", help="ASS 文件")
    ap.add_argument("--srt", default="", help="配对 SRT（缺省则同目录找同名/唯一 srt）")
    ap.add_argument("--ids", default="", help="只看这些 srt_id，逗号分隔，支持 41-50 区间")
    ap.add_argument("--range", default="", dest="id_range",
                    help="等价于 --ids，写成 100-160 更好读")
    ap.add_argument("--grep", default="", help="按文本过滤（英文或中文命中即可）")
    ap.add_argument("--empty", action="store_true",
                    help="只列某一侧为空（或无对话）的块——审计悬空的常见根因")
    ap.add_argument("--md", default="", help="结果写 md（默认写 stdout）")
    ap.add_argument("--width", type=int, default=0,
                    help="文本列截断宽度，0=不截断（默认 0，裁决时要看全句）")
    ap.add_argument("--limit", type=int, default=0, help="最多打印多少行，0=不限")
    args = ap.parse_args()

    if not os.path.exists(args.ass):
        print(f"[!] 不存在：{args.ass}", file=sys.stderr)
        return 2

    srt = args.srt
    if not srt:
        # 退化：同目录同名 / 唯一 srt
        d = os.path.dirname(os.path.abspath(args.ass))
        stem = os.path.splitext(os.path.basename(args.ass))[0]
        cands = [os.path.join(d, f) for f in sorted(os.listdir(d))
                 if f.lower().endswith(".srt")]
        for c in cands:
            if os.path.splitext(os.path.basename(c))[0] == stem:
                srt = c
                break
        if not srt and len(cands) == 1:
            srt = cands[0]
    if not srt or not os.path.exists(srt):
        print(f"[!] 找不到配对 SRT，请用 --srt 指定：{args.ass}", file=sys.stderr)
        return 2

    rows, ass_only, unknown = build_rows(args.ass, srt)

    if unknown:
        print("[!] 样式名无法识别轨道，这些行不会被归入中/英任一列："
              + "、".join(repr(u) for u in unknown), file=sys.stderr)
        print("    先跑 structure_check.py --ass <ass> 查轨道污染，"
              "不要在样式名可疑的文件上直接用本表做裁决。", file=sys.stderr)

    if ass_only and not args.md:
        print(f"[!] {len(ass_only)} 行 ASS 没有被任何 SRT 块匹配上"
              f"（不会出现在下表里）：", file=sys.stderr)
        for d in ass_only[:8]:
            print("    %7.2fs [%s] %s" % (
                d.start, d.track or d.style,
                _clip(d.text, 60)), file=sys.stderr)
        if len(ass_only) > 8:
            print(f"    …另有 {len(ass_only) - 8} 行（--md 可看全量）", file=sys.stderr)

    keep = rows
    spec = (args.ids or args.id_range).strip()
    if spec:
        want = set()
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                try:
                    want.update(range(int(a), int(b) + 1))
                except ValueError:
                    print(f"[!] --ids 区间非法：{part}", file=sys.stderr)
                    return 2
            else:
                try:
                    want.add(int(part))
                except ValueError:
                    print(f"[!] --ids 非法：{part}", file=sys.stderr)
                    return 2
        keep = [r for r in keep if r["srt_id"] in want]
        missing = sorted(want - {r["srt_id"] for r in rows})
        if missing:
            print(f"[!] 这些 srt_id 不在 {os.path.basename(srt)} 里（共 {len(rows)} 块）："
                  f"{missing[:20]}{' …' if len(missing) > 20 else ''}", file=sys.stderr)

    if args.grep:
        g = args.grep.lower()
        keep = [r for r in keep if g in (r["en"] or "").lower()
                or g in (r["zh"] or "").lower()]

    if args.empty:
        keep = [r for r in keep if not (r["en"] or "").strip()
                or not (r["zh"] or "").strip()]
        if not keep:
            print("[*] 没有「某一侧为空」的块。", file=sys.stderr)

    if args.limit > 0:
        keep = keep[:args.limit]

    if args.md:
        md = render_md(keep, args.ass, srt)
        os.makedirs(os.path.dirname(os.path.abspath(args.md)) or ".", exist_ok=True)
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[md] {args.md}（{len(keep)} 行）", file=sys.stderr)
        return 0

    for r in keep:
        flag = ""
        if not (r["en"] or "").strip():
            flag += " [英文空]"
        if not (r["zh"] or "").strip():
            flag += " [中文空]"
        print("[%4d] %7.2f-%7.2f%s" % (r["srt_id"], r["srt_start"],
                                       r["srt_end"], flag))
        print("       EN: " + (_clip(r["en"], args.width) or "—"))
        print("       ZH: " + (_clip(r["zh"], args.width) or "—"))
        if r["note"]:
            print("      NOTE: " + _clip(r["note"], args.width))
        if r["anomalies"]:
            print("       ! " + "；".join(r["anomalies"]))
    print(f"[*] {len(keep)} 条（总 {len(rows)} 块）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
