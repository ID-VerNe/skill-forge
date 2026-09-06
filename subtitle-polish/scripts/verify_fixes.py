# -*- coding: utf-8 -*-
"""verify_fixes.py — 执行后验证。

读 log.jsonl，按 srt_id + track 重读 ASS，逐条核对每条操作记录的 new_text
是否真的落在盘上。不依赖 agent 手写 pysubs2 脚本或硬编码时间戳。

定位逻辑与 apply_fixes 一致：srt_id → srt timestamp → ass Dialogue（timestamp
模糊匹配 + 样式名=track）。delete 操作验该行已不存在。

用法:
  python verify_fixes.py --batch-id <id> [--work-dir .subtitle-polish]
  python verify_fixes.py --all [--work-dir .subtitle-polish]   # 验全部日志
  python verify_fixes.py --since <ts> [--work-dir .subtitle-polish]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pysubs2

from lib.ass_srt_pair import parse_srt, style_to_track, TRACK_ZH
from lib.log import read_log, filter_log
from lib.paths import resolve_work_dir, report_path
from lib.tags import extract_leading_tags
from apply_fixes import _find_dialogue, _build_srt_index, _find_paired_srt


def _latest_per_target(entries):
    """每个 (file, srt_id, track) 取最后一条记录（后续操作覆盖前述）。

    delete 也按此聚合：若某行先 replace 再 delete，最终态是"已删"。
    """
    latest = {}
    for e in entries:
        key = (e["file"], e["srt_id"], e.get("track", TRACK_ZH))
        latest[key] = e
    return list(latest.values())


def verify_entry(entry, subs, srt_index):
    """核对单条记录。返回 (ok: bool, actual: str, detail: str)。"""
    track = entry.get("track", TRACK_ZH)
    action = entry.get("action", "replace")
    expected_new = entry.get("new_text", "")

    if action == "delete":
        # 验该行已不存在：按 srt_id+track 找，应返回 None
        e = _find_dialogue(subs, srt_index, entry["srt_id"], track)
        if e is None:
            return True, "", "行已删除"
        return False, e.text, "delete 后该行仍存在"

    if action == "rollback" and expected_new == "":
        # rollback 到 delete 前态：行应已删除（log 的 new_text 空）
        e = _find_dialogue(subs, srt_index, entry["srt_id"], track)
        if e is None:
            return True, "", "行已删除（rollback of delete）"
        return False, e.text, "rollback-to-delete 后该行仍存在"

    # replace / swap / rollback-to-replace：按 srt_id+track 定位，核对 new_text
    e = _find_dialogue(subs, srt_index, entry["srt_id"], track,
                       fallback_text=expected_new)
    if e is None:
        return False, "", "定位失败（srt_id+track 找不到对应行）"
    # 双端去前导标签后比可见文本（标签合并策略可能让标签顺序略不同，
    # 但可见文本必须一致）
    _, exp_body = extract_leading_tags(expected_new)
    _, act_body = extract_leading_tags(e.text)
    if act_body == exp_body:
        return True, e.text, "可见文本一致"
    return False, e.text, f"可见文本不符：期望 '{exp_body}' 实际 '{act_body}'"


def run(entries, work_dir, label):
    """验一批 entries，写报告，返回 (ok_count, fail_count)。"""
    # 按 file 分组加载 ASS（每文件只加载一次）
    by_file = {}
    for e in entries:
        by_file.setdefault(e["file"], []).append(e)

    out_path = report_path(work_dir, "verify-fixes.md")
    lines = [f"# 执行后验证 — {label}", "",
             f"- 日志条目: {len(entries)}",
             f"- 验证目标: {len(_latest_per_target(entries))} 条（去重后）", ""]

    ok_count = 0
    fail_count = 0
    fail_sections = []

    for f, ents in by_file.items():
        if not os.path.exists(f):
            for e in ents:
                fail_count += 1
                fail_sections.append((e, "", f"ASS 文件不存在: {f}"))
            continue
        subs = pysubs2.load(f, encoding="utf-8-sig")
        srt_path = _find_paired_srt(f)
        srt_blocks = parse_srt(srt_path) if srt_path and os.path.exists(srt_path) else []
        srt_index = _build_srt_index(srt_blocks)
        # 该文件内每 (srt_id, track) 取最后一条
        latest = _latest_per_target(ents)
        for e in latest:
            ok, actual, detail = verify_entry(e, subs, srt_index)
            if ok:
                ok_count += 1
            else:
                fail_count += 1
                fail_sections.append((e, actual, detail))

    if fail_sections:
        lines.append(f"## 验证结果: 通过 {ok_count} / 失败 {fail_count}")
        lines.append("")
        lines.append("## 失败明细")
        lines.append("")
        for e, actual, detail in fail_sections:
            lines.append(f"### srt_id={e['srt_id']} track={e.get('track','')} "
                         f"action={e.get('action','')} batch={e.get('batch_id','')}")
            lines.append(f"- 文件: `{e['file']}`")
            lines.append(f"- 期望 new_text: `{e.get('new_text','')}`")
            lines.append(f"- 实际落盘: `{actual}`")
            lines.append(f"- 原因: {detail}")
            lines.append("")
    else:
        lines.append(f"## 验证结果: 全部通过 ({ok_count} 条)")

    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    print(f"[*] 验证 {ok_count} 通过 / {fail_count} 失败，报告 {out_path}")
    return ok_count, fail_count


def main():
    ap = argparse.ArgumentParser(description="执行后验证：核对 log.jsonl 的 new_text 是否落盘")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--batch-id", help="只验某 batch")
    g.add_argument("--all", action="store_true", help="验全部日志")
    g.add_argument("--since", help="验某时间点之后的操作")
    ap.add_argument("--work-dir", default=".subtitle-polish")
    args = ap.parse_args()

    wd = resolve_work_dir(args.work_dir)
    entries = read_log(wd)
    if args.batch_id:
        entries = filter_log(entries, batch_id=args.batch_id)
        label = f"batch {args.batch_id}"
    elif args.since:
        entries = [e for e in entries if e.get("ts", "") >= args.since]
        label = f"since {args.since}"
    else:
        label = "全部日志"

    if not entries:
        print(f"[!] 无匹配日志条目 ({label})")
        return 1

    ok, fail = run(entries, wd, label)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
