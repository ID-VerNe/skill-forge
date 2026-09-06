# -*- coding: utf-8 -*-
"""apply_fixes.py — 精确替换脚本。

按 srt_id + track 定位 ASS Dialogue 行，执行 replace / delete / swap。
支持 dry-run（输出可读 md）和 accept（写入 ASS + 记 log.jsonl）。
rollback 按 batch_id / srt_id / before-timestamp 反向应用。

用法:
  python apply_fixes.py <fixes.json> --dry-run
  python apply_fixes.py <fixes.json> --accept --batch-id <id>
  python apply_fixes.py --rollback batch=<id>
  python apply_fixes.py --rollback id=<srt_id> [--file <path>]
  python apply_fixes.py --rollback before=<ts>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pysubs2

from lib.ass_srt_pair import (
    parse_ass, parse_srt, pair, TRACK_EN, TRACK_ZH, TRACK_NOTE,
    style_to_track, clean_ass_text,
)
from lib.time_fmt import seconds_to_ass
from lib.log import append_log, read_log, filter_log, make_batch_id
from lib.paths import resolve_work_dir

WORK_DIR = ".subtitle-polish"


def _resolve_work_dir(work_dir: str) -> str:
    """兼容旧调用名，转发到 lib.paths.resolve_work_dir。"""
    return resolve_work_dir(work_dir)
    return os.path.join(os.getcwd(), ".subtitle-polish")


def load_fixes(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_dialogue(subs, srt_blocks_indexed, srt_id: int, track: str, fallback_text: str = ""):
    """按 srt_id + track 在 ass subs 里定位 Dialogue event。

    返回 pysubs2 Event 对象或 None。
    fallback_text: 若 srt_blocks_indexed 缺该 id，按文本在 subs 里搜当前内容（回滚用）。
    """
    if srt_id in srt_blocks_indexed:
        sb = srt_blocks_indexed[srt_id]
        target_start = sb.start  # 秒
        candidates = []
        for e in subs.events:
            if abs(e.start / 1000.0 - target_start) <= 0.5:
                candidates.append(e)
        # 按 track 筛
        for e in candidates:
            if style_to_track(e.style or "") == track:
                return e
        # 退化：返回同时戳任意行（让调用者处理 track 不匹配）
        return candidates[0] if candidates else None
    # 回滚场景：srt 推不到，按 fallback_text 在当前 subs 里搜
    if fallback_text:
        from lib.tags import extract_leading_tags
        # 双端归一：fallback 可能带标签也可能不带，e.text 含标签，都去前导标签后比
        _, fb_body = extract_leading_tags(fallback_text)
        for e in subs.events:
            if style_to_track(e.style or "") != track:
                continue
            _, e_body = extract_leading_tags(e.text)
            if e_body == fb_body:
                return e
    return None


def _build_srt_index(srt_blocks):
    return {b.index: b for b in srt_blocks}


from lib.tags import extract_leading_tags, merge_tags as _merge_tags


def _replace_text(e, new_text: str):
    """替换 Event 的文本字段，自动检测并还原原行的特效标签。

    策略：提取原行所有前导 ASS 标签（{\\be3}、{\\an8} 等），
    与 new_text 自带的标签合并去重，拼在纯文本前。
    - new_text 不带标签：补原行标签（如 {\\be3}新译文）
    - new_text 带 {\\an8}：保留原 {\\be3} + 追加 {\\an8}（{\\be3}{\\an8}新译文）
    - new_text 带与原行相同标签：去重，不重复
    """
    orig_tags, _ = extract_leading_tags(e.text)
    new_tags, new_body = extract_leading_tags(new_text)
    merged = _merge_tags(orig_tags, new_tags)
    e.text = "".join(merged) + new_body


def _swap_text(subs, srt_blocks_indexed, id_a: int, id_b: int, track: str):
    """交换两个 srt_id 对应行的文本部分，各自保留原特效标签（不动时间戳/样式/标签）。"""
    ea = _find_dialogue(subs, srt_blocks_indexed, id_a, track)
    eb = _find_dialogue(subs, srt_blocks_indexed, id_b, track)
    if not ea or not eb:
        return None, None, None, None
    tags_a, body_a = extract_leading_tags(ea.text)
    tags_b, body_b = extract_leading_tags(eb.text)
    old_a, old_b = ea.text, eb.text
    # 各自保留自己的标签，只换可见文本
    ea.text = "".join(tags_a) + body_b
    eb.text = "".join(tags_b) + body_a
    return ea, eb, old_a, old_b


def run_dry_run(fixes: list, work_dir: str) -> str:
    """生成 dry-run.md，返回路径。每条从真实 ASS 读现译。"""
    out_path = os.path.join(work_dir, "reports", "dry-run.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    by_file = {}
    for fx in fixes:
        if not fx.get("enabled", True):
            continue
        by_file.setdefault(fx["file"], []).append(fx)

    total = sum(len(v) for v in by_file.values())
    lines = ["# Dry-run 预览", "", f"共 {total} 条待执行（enabled=true）", ""]
    for file, fxs in by_file.items():
        lines.append(f"## {os.path.basename(file)}")
        lines.append("")
        subs = pysubs2.load(file, encoding="utf-8-sig")
        # dry-run 也要优先用 fixes 里的 srt_path，推不到才 fallback
        srt_path = ""
        for fx in fxs:
            if fx.get("srt_path"):
                srt_path = fx["srt_path"]
                break
        if not srt_path:
            srt_path = _find_paired_srt(file)
        srt_blocks = parse_srt(srt_path) if srt_path and os.path.exists(srt_path) else []
        srt_index = _build_srt_index(srt_blocks)
        for fx in fxs:
            action = fx.get("action", "replace")
            track = fx.get("track", TRACK_ZH)
            e = _find_dialogue(subs, srt_index, fx["srt_id"], track)
            # dry-run 对称显示：现译/新译都显示实际落盘的 raw text（含标签），
            # 让人看到真实写入内容，避免以为标签丢了。
            cur_raw = e.text if e else "（定位失败）"
            new_raw = fx.get("final_new") or fx.get("suggested_new", "")
            # 给新译补上原行标签做对称预览（不实际写入）
            if e and new_raw:
                from lib.tags import extract_leading_tags, merge_tags
                orig_tags, _ = extract_leading_tags(e.text)
                new_tags, new_body = extract_leading_tags(new_raw)
                new_preview = "".join(merge_tags(orig_tags, new_tags)) + new_body
            else:
                new_preview = new_raw
            lines.append(f"### {fx.get('id','')} — {fx.get('category','')} ({action})")
            lines.append(f"- srt_id: {fx['srt_id']} / track: {track}")
            if fx.get("reason"):
                lines.append(f"- 理由: {fx['reason']}")
            if action == "replace":
                lines.append("- 现译 → 新译（均含实际标签）:")
                lines.append(f"  - 现: `{cur_raw}`")
                lines.append(f"  - 新: `{new_preview}`")
            elif action == "delete":
                lines.append(f"- 删除整行: `{cur_raw}`")
            elif action == "swap":
                lines.append(f"- 与 srt_id={fx.get('swap_with')} 交换文本（{track} 行）")
                lines.append(f"  - 当前行: `{cur_raw}`")
            lines.append("")
        lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[*] dry-run 写入 {out_path}")
    return out_path


def run_accept(fixes: list, work_dir: str, batch_id: str) -> None:
    """执行替换，写 ASS + log.jsonl。"""
    by_file = {}
    for fx in fixes:
        if not fx.get("enabled", True):
            continue
        by_file.setdefault(fx["file"], []).append(fx)

    for file, fxs in by_file.items():
        subs = pysubs2.load(file, encoding="utf-8-sig")
        srt_path = fx_srt_path = None
        # 找该文件配对的 srt：先尝试自动推，推不到则从同 batch 的 fixes 找带 srt_path 字段的
        for fx in fxs:
            if fx.get("srt_path"):
                srt_path = fx["srt_path"]
                break
        if not srt_path:
            srt_path = _find_paired_srt(file)
        srt_blocks = parse_srt(srt_path) if srt_path and os.path.exists(srt_path) else []
        if not srt_blocks:
            print(f"[!] 找不到配对 srt: {file}（推路径 {_find_paired_srt(file)}）", file=sys.stderr)
            print(f"    在 fixes.json 里给每条加 \"srt_path\" 字段可显式指定", file=sys.stderr)
        srt_index = _build_srt_index(srt_blocks)

        for fx in fxs:
            action = fx.get("action", "replace")
            track = fx.get("track", TRACK_ZH)
            srt_id = fx["srt_id"]
            e = _find_dialogue(subs, srt_index, srt_id, track)
            if not e:
                print(f"[!] 定位失败: {fx.get('id')} srt_id={srt_id} track={track}", file=sys.stderr)
                continue
            old_text = e.text
            if action == "replace":
                new_text = fx.get("final_new") or fx.get("suggested_new", "")
                if not new_text:
                    print(f"[!] 无新文本: {fx.get('id')}", file=sys.stderr)
                    continue
                _replace_text(e, new_text)
                # log 记实际落盘的 e.text（含合并标签），与 rollback 对称、可重放
                append_log(work_dir, batch_id, "replace", file, srt_id, track,
                           old_text, e.text, fx.get("category",""), fx.get("reason",""))
            elif action == "delete":
                # 删整行
                subs.events.remove(e)
                append_log(work_dir, batch_id, "delete", file, srt_id, track,
                           old_text, "", fx.get("category",""), fx.get("reason",""))
            elif action == "swap":
                ea, eb, old_a, old_b = _swap_text(subs, srt_index, srt_id,
                                                    fx["swap_with"], track)
                if ea:
                    append_log(work_dir, batch_id, "swap", file, srt_id, track,
                               old_a, ea.text, fx.get("category",""), fx.get("reason",""))
                    append_log(work_dir, batch_id, "swap", file, fx["swap_with"], track,
                               old_b, eb.text, fx.get("category",""), fx.get("reason",""))
        # 备份原文件
        bak = file + ".bak"
        if not os.path.exists(bak):
            import shutil
            shutil.copy2(file, bak)
        subs.save(file, encoding="utf-8")
        print(f"[*] 写入 {file} (batch {batch_id}, {len(fxs)} 条)")


def _find_paired_srt(ass_path: str) -> str:
    """从 ass 路径推 srt 路径。

    查找顺序：
    1. ass 同目录同名 .srt
    2. ass 同目录的 原始srt/ 下同名 .srt
    3. ass 所在目录的父目录的 原始srt/ 下同名 .srt（项目根常见布局）
    4. ass 所在目录的父目录同名 .srt
    """
    base = os.path.splitext(ass_path)[0]
    name = os.path.basename(base)
    ass_dir = os.path.dirname(ass_path)
    parent = os.path.dirname(ass_dir)
    candidates = [
        base + ".srt",
        os.path.join(ass_dir, "原始srt", name + ".srt"),
        os.path.join(parent, "原始srt", name + ".srt"),
        os.path.join(parent, name + ".srt"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def run_rollback(work_dir: str, *, batch_id=None, srt_id=None, file=None, before_ts=None) -> int:
    """按条件回滚，反向应用 old_text。"""
    entries = read_log(work_dir)
    targets = filter_log(entries, batch_id=batch_id, srt_id=srt_id,
                         file=file, before_ts=before_ts)
    if not targets:
        print("[!] 无匹配的回滚条目")
        return 0
    # 按文件分组，反向应用（后做的先回滚）
    targets.reverse()
    by_file = {}
    for e in targets:
        by_file.setdefault(e["file"], []).append(e)
    count = 0
    for f, ents in by_file.items():
        subs = pysubs2.load(f, encoding="utf-8-sig")
        # 回滚也需要 srt_id -> timestamp 映射。优先用日志里的 old_text 直接按时间戳定位
        # （日志有 old_text，按 track + 时间戳找当前行）
        srt_path = _find_paired_srt(f)
        srt_blocks = parse_srt(srt_path) if srt_path and os.path.exists(srt_path) else []
        srt_index = _build_srt_index(srt_blocks)
        for ent in ents:
            track = ent.get("track", TRACK_ZH)
            # 回滚：按日志里的 new_text（当前内容）做 fallback 定位
            e = _find_dialogue(subs, srt_index, ent["srt_id"], track,
                               fallback_text=ent.get("new_text",""))
            if not e:
                print(f"[!] 回滚定位失败: srt_id={ent['srt_id']} track={track} "
                      f"(srt_path={srt_path or '未找到'})", file=sys.stderr)
                continue
            if ent["action"] == "delete":
                print(f"[!] delete 回滚无法自动重建 srt_id={ent['srt_id']}", file=sys.stderr)
                continue
            cur = e.text
            e.text = ent["old_text"]
            append_log(work_dir, make_batch_id(), "rollback", f,
                       ent["srt_id"], ent["track"], cur, ent["old_text"],
                       ent.get("category",""), f"rollback of {ent['batch_id']}")
            count += 1
        subs.save(f, encoding="utf-8")
    print(f"[*] 回滚 {count} 条")
    return count


def main():
    ap = argparse.ArgumentParser(description="精确替换 ASS 字幕")
    ap.add_argument("fixes", nargs="?", help="fixes.json 路径")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--accept", action="store_true")
    ap.add_argument("--batch-id", default=None)
    ap.add_argument("--rollback", default=None,
                    help="batch=<id> | id=<srt_id> | before=<ts>")
    ap.add_argument("--file", default=None, help="rollback id= 时限定文件")
    ap.add_argument("--work-dir", default=WORK_DIR)
    args = ap.parse_args()

    if args.rollback:
        wd = _resolve_work_dir(args.work_dir)
        kwargs = {}
        spec = args.rollback
        if spec.startswith("batch="):
            kwargs["batch_id"] = spec.split("=",1)[1]
        elif spec.startswith("id="):
            kwargs["srt_id"] = int(spec.split("=",1)[1])
            if args.file:
                kwargs["file"] = args.file
        elif spec.startswith("before="):
            kwargs["before_ts"] = spec.split("=",1)[1]
        run_rollback(wd, **kwargs)
        return

    if not args.fixes:
        ap.error("需要 fixes.json 或 --rollback")

    wd = _resolve_work_dir(args.work_dir)
    fixes = load_fixes(args.fixes)
    if args.dry_run:
        run_dry_run(fixes, wd)
    elif args.accept:
        bid = args.batch_id or make_batch_id()
        run_accept(fixes, wd, bid)
    else:
        ap.error("需要 --dry-run 或 --accept 或 --rollback")


if __name__ == "__main__":
    main()
