# -*- coding: utf-8 -*-
"""build_verify_ctx.py — 构造 verify agent 的上下文。

为一批 findings 构造：每条 finding 的前后各 N 块上下文（从切片文件按 srt_id 直读，
支持多切片跨边界自动取）+ srt 原文。主 agent 把输出 inline 进 verify.tmpl 的 {findings}。

用法:
  python build_verify_ctx.py <findings.json> <slice_paths...> <srt_path> [--before 5] [--after 5]

findings.json schema（每条）:
  {"srt_id": "17", "category": "...", "severity": "...", "en": "...", "zh": "...",
   "problem": "...", "suggest": "..."}

输出（stdout）: 每条 finding 一个 ### 块，含上下文 + srt 原文，供 inline 进 verify prompt。

设计：
- 禁止手工编号上下文块（数行易偏移，test2 实测偏移 -2 导致 verify agent 被误导）。
- 多切片支持：finding 的 srt_id 可能落在任一切片，从含该 id 的切片取上下文；
  若该 id 在切片边界（前后不足 N 块），就用切片内能取到的全部。
- 不靠 SendMessage 二次喂、不让 verify agent 自己 Read ctx 文件。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def load_slices(slice_files):
    """合并多切片，返回 {srt_id: {en, zh, time, line}} + order 列表。

    order 是按 srt_id 升序的全局顺序（跨切片），用于取前后 N 块上下文。
    重叠区（同一 srt_id 出现在多切片）只记第一份。
    """
    rows = {}
    order = []
    for sf in slice_files:
        with open(sf, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split(" | ")
                if len(parts) < 5:
                    continue
                head = parts[0]
                # 切片行首可能带 "行号:srt_id" 前缀（兼容旧格式），取 ":" 后的
                sid = head.split(":", 1)[1].strip() if ":" in head else head.strip()
                if sid in rows:
                    continue  # 重叠区，已记
                rows[sid] = {
                    "en": parts[2].strip(),
                    "zh": parts[3].strip(),
                    "time": parts[1].strip(),
                    "line": ln,
                }
                order.append(sid)
    # order 按数值排序
    def _key(s):
        try:
            return (0, int(s))
        except ValueError:
            return (1, s)
    order.sort(key=_key)
    return rows, order


def load_srt(srt_file):
    """返回 {block_num: english_text}，block_num 从 1 开始。"""
    text = Path(srt_file).read_text(encoding="utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    out = {}
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 2:
            continue
        # 第一行是序号（或跳过找时间戳行）
        idx = None
        ts_idx = None
        for i, ln in enumerate(lines):
            if "-->" in ln:
                ts_idx = i
                break
        if ts_idx is None:
            continue
        if ts_idx > 0 and lines[0].strip().isdigit():
            idx = lines[0].strip()
        else:
            # 没有序号行，按出现顺序
            pass
        body = "\n".join(lines[ts_idx + 1:]).strip()
        if idx:
            out[idx] = body
        else:
            out[str(len(out) + 1)] = body
    return out


def context_around(rows, order, sid, before=5, after=5):
    """返回前后各 N 块的文本（含本块），按 srt_id 升序。

    sid 在 order 中的位置取上下文；边界时用切片内能取到的全部。
    """
    if sid not in rows:
        return None, None
    idx = order.index(sid)
    lo = max(0, idx - before)
    hi = min(len(order), idx + after + 1)
    ctx = []
    for s in order[lo:hi]:
        r = rows[s]
        marker = " <== 本块" if s == sid else ""
        ctx.append(f"[{s}] {r['time']} | EN: {r['en']} | ZH: {r['zh']}{marker}")
    return "\n".join(ctx), rows[sid]


def main():
    ap = argparse.ArgumentParser(description="构造 verify 上下文")
    ap.add_argument("findings", help="findings.json 路径")
    ap.add_argument("slices", nargs="+", help="切片文件路径（可多份）")
    ap.add_argument("--srt", required=True, help="srt 路径（取原文）")
    ap.add_argument("--before", type=int, default=5, help="前 N 块（默认 5）")
    ap.add_argument("--after", type=int, default=5, help="后 N 块（默认 5）")
    args = ap.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    rows, order = load_slices(args.slices)
    srt = load_srt(args.srt)

    for i, f in enumerate(findings, 1):
        sid = str(f.get("srt_id", ""))
        ctx, row = context_around(rows, order, sid, args.before, args.after)
        srt_orig = srt.get(sid, "(srt 中未找到该序号)")
        print(f"\n### 发现 {i}")
        print(f"- srt_id: {sid}")
        print(f"- 类别: {f.get('category', '')}（{f.get('severity', '')}）")
        print(f"- 英文: {f.get('en', '')}")
        print(f"- 现译: {f.get('zh', '')}")
        print(f"- 问题: {f.get('problem', '')}")
        print(f"- 建议: {f.get('suggest', '')}")
        print(f"- 上下文（前后各 {args.before}/{args.after} 块）:")
        if ctx:
            print(ctx)
        else:
            print(f"(切片中未找到 srt_id {sid})")
            # 主 agent 见到此行必须查为何该 id 不在切片（可能 audit agent 报错 id）
        print(f"- ass_time: {row['time'] if row else '(未找到)'}")
        print(f"- srt 原文（权威英文源）:")
        print(srt_orig)


if __name__ == "__main__":
    main()
