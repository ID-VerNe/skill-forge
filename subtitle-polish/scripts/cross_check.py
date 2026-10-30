# -*- coding: utf-8 -*-
"""cross_check.py — 中英对照复核（独立于 log.jsonl）。

verify_fixes.py 只证明「字写进去了」，不证明「写进去的是对的」。
本脚本以 SRT 英文为锚，把成品 ASS 的中文轨逐块与英文对照摊开，
供 agent 或人做语义判断。它**不做**语义结论，只做三件事：

  1. 列出指定 srt_id（或区间）的「英文 / 中文」对照
  2. 标出「本批 fix 改过的行」与「其±N邻块原文」的相似度（撞车预警）
  3. 统计本批改动行的类别分布，供抽检

用法:
  # 看本批所有改动的对照
  python cross_check.py --batch-id <ts>
  # 只看指定块
  python cross_check.py --srt 343,344,679
  # 指定区间
  python cross_check.py --range 600-700
  # 只看撞车预警
  python cross_check.py --batch-id <ts> --collision-only

输出 .subtitle-polish/reports/cross-check.md（或 stdout）。
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pysubs2

from lib.ass_srt_pair import parse_srt, TRACK_ZH, TRACK_EN
from lib.log import read_log, filter_log
from lib.paths import resolve_work_dir, report_path
from lib.tags import extract_leading_tags

TAG = re.compile(r"\{[^}]*\}")
CJK = re.compile(r"[\u4e00-\u9fff]")


def _cjk(s):
    return "".join(CJK.findall(s or ""))


def _ms_to_key(ms):
    """pysubs2 start(ms) → 与 srt timestamp 对齐的 2 位小数秒。"""
    return round(ms / 1000.0, 2)


def load_pairs(ass_path, srt_path):
    """返回 [{srt_id, start, end, en, zh}]，按时间戳配对同一行。"""
    blocks = parse_srt(srt_path)
    subs = pysubs2.load(ass_path, encoding="utf-8-sig")

    en_map, zh_map = {}, {}
    for line in subs:
        style = line.style.strip()
        body = TAG.sub("", line.text).strip()
        key = _ms_to_key(line.start)
        if style == TRACK_EN:
            en_map[key] = body
        elif style == TRACK_ZH:
            zh_map[key] = body

    out = []
    for b in blocks:
        key = round(b.start, 2)
        out.append({
            "srt_id": b.index,
            "start": key,
            "end": round(b.end, 2),
            "en": en_map.get(key, ""),
            "zh": zh_map.get(key, ""),
        })
    return out


def collision_score(rows, idx, window=3, floor=0.55):
    """新译文与 ±window 邻块现有中文的最高相似度。"""
    me = rows[idx]
    n = _cjk(me["zh"])
    if not n:
        return 0.0, None
    best = (0.0, None)
    for d in range(-window, window + 1):
        if d == 0:
            continue
        j = idx + d
        if not (0 <= j < len(rows)):
            continue
        o = _cjk(rows[j]["zh"])
        if not o:
            continue
        r = difflib.SequenceMatcher(None, n, o).ratio()
        if r > best[0]:
            best = (r, rows[j]["srt_id"])
    return best if best[0] >= floor else (best[0], None)


def fmt_tc(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def main():
    ap = argparse.ArgumentParser(description="中英对照复核（独立于 log）")
    ap.add_argument("--batch-id", help="只复核某 batch 改过的行")
    ap.add_argument("--srt", help="指定 srt_id，逗号分隔")
    ap.add_argument("--range", help="区间，如 600-700")
    ap.add_argument("--collision-only", action="store_true", help="只输出撞车预警")
    ap.add_argument("--window", type=int, default=3, help="邻块窗口，默认 3")
    ap.add_argument("--floor", type=float, default=0.55, help="撞车阈值，默认 0.55")
    ap.add_argument("--work-dir", default=".subtitle-polish")
    ap.add_argument("--ass", help="成品 ASS（默认从 log 推断）")
    ap.add_argument("--srt-path", help="配对 SRT")
    args = ap.parse_args()

    wd = resolve_work_dir(args.work_dir)
    entries = read_log(wd)
    if args.batch_id:
        entries = filter_log(entries, batch_id=args.batch_id)
    if not entries:
        print(f"[!] {wd}/log.jsonl 里没有匹配 batch={args.batch_id} 的条目")
        sub = [d for d in os.listdir(wd)
               if os.path.isdir(os.path.join(wd, d, "").rstrip(os.sep))
               and os.path.exists(os.path.join(wd, d, "log.jsonl"))]
        if sub:
            print(f"    归档目录里有 log：{', '.join(sub)}")
            print(f"    试：--work-dir {wd}/{sub[0]}")
        print("    或直接用 --ass/--srt-path + --srt/--range 指定范围")
        return 1

    targets = {}
    for e in entries:
        sid = e.get("srt_id")
        if not sid:
            continue
        targets.setdefault((e["file"], sid), []).append(e)

    ass_path = args.ass or next(iter(targets))[0]
    srt_path = args.srt_path or entries[0].get("srt_path")
    if not srt_path or not os.path.exists(srt_path):
        # 同目录下找唯一的 .srt
        cands = [f for f in os.listdir(os.path.dirname(ass_path) or ".")
                 if f.lower().endswith(".srt")]
        if len(cands) == 1:
            srt_path = os.path.join(os.path.dirname(ass_path) or ".", cands[0])
    if not srt_path:
        print("[!] 找不到配对 SRT，请用 --srt-path 指定")
        return 1

    rows = load_pairs(ass_path, srt_path)
    by_sid = {r["srt_id"]: i for i, r in enumerate(rows)}

    want = set()
    if args.srt:
        want |= {int(x) for x in args.srt.split(",") if x.strip()}
    if args.range:
        a, b = args.range.split("-")
        want |= set(range(int(a), int(b) + 1))
    if not want:
        want = {sid for (_f, sid) in targets}

    lines = ["# 中英对照复核（独立于 log.jsonl）", "",
             f"- 成品: `{ass_path}`",
             f"- 源: `{srt_path}`",
             f"- 复核块数: {len(want)}",
             ""]

    collisions = []
    for sid in sorted(want):
        if sid not in by_sid:
            lines.append(f"## e04#{sid} — ⚠ 该 srt_id 在源里不存在")
            lines.append("")
            continue
        r = rows[by_sid[sid]]
        score, nbr = collision_score(rows, by_sid[sid], args.window, args.floor)
        if nbr:
            collisions.append((sid, nbr, score))
        if args.collision_only and not nbr:
            continue
        lines.append(f"## e04#{sid}  `{fmt_tc(r['start'])}`")
        lines.append(f"- 英文: {r['en']}")
        lines.append(f"- 中文: {r['zh']}")
        if nbr:
            lines.append(f"- ⚠ 撞车预警: 与 e04#{nbr} 相似度 {score:.2f}")
        ops = targets.get((ass_path, sid), [])
        for o in ops:
            lines.append(f"- 本批改动: {o.get('old_text', '')!r} → {o.get('new_text', '')!r}"
                         f"（{o.get('category', '')}）")
        lines.append("")

    lines.insert(5, f"- 撞车预警: {len(collisions)} 条")
    if collisions:
        lines.insert(6, "")
        lines.insert(7, "| srt | 撞车对象 | 相似度 |")
        lines.insert(8, "|---|---|---|")
        for i, (sid, nbr, sc) in enumerate(collisions):
            lines.insert(9 + i, f"| {sid} | {nbr} | {sc:.2f} |")
        lines.insert(9 + len(collisions), "")

    text = "\n".join(lines)
    out = report_path(wd, "cross-check.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[*] 复核 {len(want)} 块，撞车预警 {len(collisions)} 条")
    print(f"[*] 报告写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
