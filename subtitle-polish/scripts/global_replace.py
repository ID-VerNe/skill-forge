# -*- coding: utf-8 -*-
"""global_replace.py — 跨文件全局替换。

跨文件统一专名 / 术语（如 维多利亚皇冠→皇冠维多利亚）。
默认只改中文行；--track 指定改英文/注释行。

用法:
  python global_replace.py <pattern> <replacement> [--track <中文|英文|注释>] [--files <glob1> ...] [--dry-run|--accept]
"""
from __future__ import annotations

import argparse
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pysubs2

from lib.ass_srt_pair import style_to_track
from lib.log import append_log, make_batch_id
from lib.paths import resolve_work_dir
from apply_fixes import _find_paired_srt, parse_srt, _build_srt_index


def collect_files(files_glob: list) -> list:
    """展开文件/目录/glob 为 ass 文件列表。"""
    result = []
    for pat in files_glob:
        if os.path.isdir(pat):
            for f in os.listdir(pat):
                if f.lower().endswith(".ass"):
                    result.append(os.path.join(pat, f))
        elif os.path.isfile(pat):
            result.append(pat)
        else:
            # glob
            import glob
            result.extend(glob.glob(pat))
    return sorted(set(result))


def run(pattern: str, replacement: str, track: str, files: list,
        work_dir: str, dry_run: bool, batch_id: str) -> None:
    matches = []  # (file, event, old_text, new_text, srt_id)
    for f in files:
        subs = pysubs2.load(f, encoding="utf-8-sig")
        srt_path = _find_paired_srt(f)
        srt_blocks = parse_srt(srt_path) if srt_path and os.path.exists(srt_path) else []
        srt_index = _build_srt_index(srt_blocks)
        # 反向索引：start秒 -> srt_id
        start_to_id = {round(b.start, 2): b.index for b in srt_blocks}
        for e in subs.events:
            if style_to_track(e.style or "") != track:
                continue
            # 只替换可见文本部分，保留前导标签
            m = re.match(r"^(\{[^}]*\}+)(.*)$", e.text, re.DOTALL)
            tags, visible = (m.group(1), m.group(2)) if m else ("", e.text)
            if pattern in visible:
                new_visible = visible.replace(pattern, replacement)
                new_text = tags + new_visible
                srt_id = start_to_id.get(round(e.start / 1000.0, 2), 0)
                matches.append((f, e, e.text, new_text, srt_id))

    if dry_run:
        out_path = os.path.join(work_dir, "reports", "global-replace-dry-run.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        lines = [f"# 全局替换 dry-run", "",
                 f"- pattern: `{pattern}`", f"- replacement: `{replacement}`",
                 f"- track: {track}", f"- 命中 {len(matches)} 处", ""]
        for f, e, old, new, srt_id in matches:
            lines.append(f"## {os.path.basename(f)} — srt_id {srt_id}")
            lines.append(f"- 现: {old}")
            lines.append(f"- 新: {new}")
            lines.append("")
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(lines))
        print(f"[*] 命中 {len(matches)} 处，dry-run 写入 {out_path}")
        return

    if not matches:
        print("[*] 无命中")
        return

    # accept：按文件分组写
    by_file = {}
    for f, e, old, new, srt_id in matches:
        by_file.setdefault(f, []).append((e, old, new, srt_id))
    for f, ents in by_file.items():
        subs = pysubs2.load(f, encoding="utf-8-sig")
        # 重新匹配（因为 subs 是新加载的，e 引用要换）
        for e in subs.events:
            if style_to_track(e.style or "") != track:
                continue
            m = re.match(r"^(\{[^}]*\}+)(.*)$", e.text, re.DOTALL)
            tags, visible = (m.group(1), m.group(2)) if m else ("", e.text)
            if pattern in visible:
                old = e.text
                e.text = tags + visible.replace(pattern, replacement)
                srt_path = _find_paired_srt(f)
                srt_blocks = parse_srt(srt_path) if srt_path and os.path.exists(srt_path) else []
                start_to_id = {round(b.start,2): b.index for b in srt_blocks}
                sid = start_to_id.get(round(e.start/1000.0, 2), 0)
                append_log(work_dir, batch_id, "global_replace", f, sid, track,
                           old, e.text, "全局替换", f"{pattern} -> {replacement}")
        subs.save(f, encoding="utf-8")
        print(f"[*] {os.path.basename(f)}: 写入 (batch {batch_id})")


def main():
    ap = argparse.ArgumentParser(description="跨文件全局替换")
    ap.add_argument("pattern", help="要替换的文本")
    ap.add_argument("replacement", help="替换为")
    ap.add_argument("--track", default="中文", choices=["中文","英文","注释"],
                    help="改哪个 track 的行（默认中文）")
    ap.add_argument("--files", nargs="+", required=True,
                    help="ass 文件/目录/glob（可多个）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--accept", action="store_true")
    ap.add_argument("--work-dir", default=".subtitle-polish")
    args = ap.parse_args()

    wd = resolve_work_dir(args.work_dir)
    files = collect_files(args.files)
    if not files:
        print("[!] 无匹配文件", file=sys.stderr)
        return
    batch_id = make_batch_id()
    if args.accept:
        run(args.pattern, args.replacement, args.track, files, wd, False, batch_id)
    else:
        run(args.pattern, args.replacement, args.track, files, wd, True, batch_id)


if __name__ == "__main__":
    main()
