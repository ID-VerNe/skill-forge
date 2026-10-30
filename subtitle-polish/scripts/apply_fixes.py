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
from pysubs2 import SSAEvent

from lib.ass_srt_pair import (
    parse_ass, parse_srt, pair, TRACK_EN, TRACK_ZH, TRACK_NOTE,
    style_to_track, clean_ass_text,
)
from lib.time_fmt import seconds_to_ass
from lib.log import append_log, read_log, filter_log, make_batch_id
from lib.paths import resolve_work_dir

WORK_DIR = ".subtitle-polish"


def load_fixes(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_dialogue(subs, srt_blocks_indexed, srt_id: int, track: str,
                   fallback_text: str = "", *, used=None, prefer_text: str = ""):
    """按 srt_id + track 在 ass subs 里定位 Dialogue event。

    返回 pysubs2 Event 对象或 None。
    fallback_text: 若 srt_blocks_indexed 缺该 id，按文本在 subs 里搜当前内容（回滚用）。
    used: 本次 batch 已处理过的 event id 集合。定位时跳过它们，避免同一 srt_id
        下的多条同轨行被重复命中（如「合并碎片行」= 1 replace + N delete）。
    prefer_text: 给了就优先匹配可见文本等于它的候选（fix 里的 current 字段）。
        用于同一 srt_id 有多条同轨行时精确指定要删/要改的那一条。

    为什么需要 used/prefer_text：_find_dialogue 原本的语义是「取时间戳最近的第
    一条」，无状态。生产环节把一句中文字幕拆成多条独立 Dialogue 时，同 start/end、
    同 track 会有 2~3 条。此时 1 条 replace + N 条 delete 的 fix 若不带 current，
    每条都落在「时间戳最近的第一条」上，改哪条删哪条不可控。见 issue #2。
    """
    if used is None:
        used = set()
    if srt_id in srt_blocks_indexed:
        sb = srt_blocks_indexed[srt_id]
        target_start = sb.start  # 秒
        candidates = []
        for e in subs.events:
            if id(e) in used:
                continue
            if abs(e.start / 1000.0 - target_start) <= 0.5:
                candidates.append(e)
        # 按时间戳距离排序后取最近的，不是第一个命中的。
        # 相邻 srt 块时间差 < 0.5s 时（实测 361/362 隔 390ms），两块的容差窗
        # 互相把对方 ass 行包进来；取第一个会让两条 fix 写到同一物理行（第二条
        # 覆盖第一条），verify 报可见文本不符。取最近的能区分 361→981560 行、
        # 362→981950 行。
        candidates.sort(key=lambda e: abs(e.start / 1000.0 - target_start))
        # 按 track 筛
        candidates = [e for e in candidates if style_to_track(e.style or "") == track]
        if not candidates:
            # 退化：返回同时戳任意未用行（让调用者处理 track 不匹配）
            rest = [e for e in subs.events
                    if id(e) not in used and abs(e.start / 1000.0 - target_start) <= 0.5]
            return rest[0] if rest else None
        # prefer_text：同一 srt_id 多条同轨行时，按 current 精确挑一条。
        # 有命中就只在命中集里取最近的；都没命中则退回时间戳最近（保持旧行为，
        # 调用方需要严格性时自己校验）。current 带不带标签都要能匹配。
        if prefer_text:
            want = clean_ass_text(prefer_text)
            hits = [e for e in candidates if clean_ass_text(e.text) == want]
            if hits:
                candidates = hits
        return candidates[0]
    # 回滚场景：srt 推不到，按 fallback_text 在当前 subs 里搜
    if fallback_text:
        from lib.tags import extract_leading_tags
        # 双端归一：fallback 可能带标签也可能不带，e.text 含标签，都去前导标签后比
        _, fb_body = extract_leading_tags(fallback_text)
        for e in subs.events:
            if id(e) in used:
                continue
            if style_to_track(e.style or "") != track:
                continue
            _, e_body = extract_leading_tags(e.text)
            if e_body == fb_body:
                return e
    return None


def _remove_event(subs, e) -> bool:
    """按对象身份删除 event，返回是否删到。

    不能用 subs.events.remove(e)：pysubs2 的 SSAEvent.__eq__ 只比较 start/end
    （源码注释 "XXX document this"），不看 text/style。list.remove 走 ==，
    于是会删掉**第一条 start/end 相同的行**，而不是 e 本身。双语 ASS 里英中
    两行时间戳完全一致，删中文碎片行时会把英文行删掉。见 issue #2。
    """
    for i, x in enumerate(subs.events):
        if x is e:
            del subs.events[i]
            return True
    return False


def _build_srt_index(srt_blocks):
    return {b.index: b for b in srt_blocks}


def _resolve_style_for_track(subs, track: str) -> str:
    """从 subs.styles 找 style_to_track(name)==track 的样式名，返回首个。
    无则返回 ""（调用方报错：ASS 缺该 track 样式）。insert 用。
    """
    for name in (subs.styles or {}):
        if style_to_track(name) == track:
            return name
    return ""


from lib.tags import extract_leading_tags, merge_tags as _merge_tags


def _format_timespec(start_s: float, end_s: float) -> str:
    """时间串格式：'1422.12-1425.43'（秒，两位小数）。retime 日志用。"""
    return f"{start_s:.2f}-{end_s:.2f}"


def _parse_timespec(spec: str):
    """解析 '1422.12-1425.43' → (1422.12, 1425.43)。失败抛 ValueError。"""
    txt = (spec or "").strip()
    if not txt or "-" not in txt:
        raise ValueError(f"时间串格式应为 'start-end'，收到 {spec!r}")
    a, b = txt.split("-", 1)
    try:
        return float(a), float(b)
    except ValueError:
        raise ValueError(f"时间串格式应为 'start-end'，收到 {spec!r}")


def _retime_event(e, new_start: float, new_end: float):
    """把 event 的 start/end 改成新时段（秒）。返回 (old_start, old_end) 秒。

    new_start / new_end 为 None 时沿用原值。
    pysubs2 内部用毫秒，秒→毫秒在写盘时转换（已知坑）。
    """
    old_start, old_end = e.start / 1000.0, e.end / 1000.0
    if new_start is not None:
        e.start = int(round(new_start * 1000))
    if new_end is not None:
        e.end = int(round(new_end * 1000))
    if e.end <= e.start:
        # 回退到原值再报错，避免把非法时段留在文件里
        e.start, e.end = int(round(old_start * 1000)), int(round(old_end * 1000))
        raise ValueError(f"新时段非法：end({new_end}) 必须大于 start({new_start})")
    return old_start, old_end


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


def _manual_log_check(file: str, srt_id, track: str, old_text: str,
                      new_text: str) -> list:
    """--manual-log 的前置校验。返回警告列表；有致命问题抛 SystemExit。

    为什么需要：append_log 不做任何校验，只 append。曾经出现过调用方先跑
    --manual-log、随后删除却没匹配上，于是 log.jsonl 留下 4 条指向不存在内容
    的脏记录，只能手工清理。这里的校验全部在写盘**之前**做。

    校验项：
      1. --old 非空，且能在该 srt_id + track 的行里找到（致命）
      2. 新文本已落盘（否则日志与实际不符，警告）
      3. --old 找不到但新文本已在盘上 → 大概率是重复补记（警告）
      4. 同一 srt_id + track 存在多条同时间戳行（合并碎片行的典型场景，警告）
    """
    warns = []
    if not os.path.exists(file):
        raise SystemExit(f"[x] --manual-log 校验失败：ASS 文件不存在 {file}")
    if not (old_text or "").strip():
        raise SystemExit("[x] --manual-log 校验失败：--old 不能为空"
                         "（没有 old 的 manual_edit 无法 rollback）")

    subs = pysubs2.load(file, encoding="utf-8-sig")
    want_old = clean_ass_text(old_text)
    want_new = clean_ass_text(new_text)

    # 同 srt_id + track 的全部行（时间戳容差与 _find_dialogue 一致，0.5s）
    srt_path = _find_paired_srt(file)
    blocks = parse_srt(srt_path) if srt_path and os.path.exists(srt_path) else []
    index = _build_srt_index(blocks)
    if srt_id in index:
        start = index[srt_id].start
        same = [e for e in subs.events
                if style_to_track(e.style or "") == track
                and abs(e.start / 1000.0 - start) <= 0.5]
    else:
        # srt 推不到就不做时间戳筛选，全文找 old，避免误判成「找不到」
        same = [e for e in subs.events if style_to_track(e.style or "") == track]
        warns.append(f"找不到配对 srt 或 srt_id={srt_id} 不在 srt 里，"
                     f"--old 校验退化为在该 track 全文搜索")
    texts = [clean_ass_text(e.text) for e in same]
    old_found = want_old in texts
    new_found = bool(want_new) and want_new in texts

    if not old_found:
        # 带标签的 old 最常见的是 heredoc 把反斜杠吃掉
        hint = ""
        if "{" in old_text and "}" in old_text:
            hint = ("\n    --old 含 ASS 标签却匹配不到，检查 heredoc 是否吃了反斜杠"
                    "（用带引号的 heredoc 或 chr(92)）")
        if new_found:
            warns.append(f"--old 在盘上找不到，但新文本已在盘上——"
                         f"可能这条已经记过日志了（重复补记？）")
        else:
            shown = texts[:5]
            more = "" if len(texts) <= 5 else f" …（共 {len(texts)} 条）"
            raise SystemExit(
                f"[x] --manual-log 校验失败：--old {old_text!r} 在 "
                f"srt_id={srt_id} track={track} 的行里找不到。\n"
                f"    该位置现有文本：{shown}{more}{hint}\n"
                f"    （先确认改动真的发生了再记日志，否则会留下指向不存在内容的脏记录）")

    if old_found and not new_found:
        warns.append(f"新文本 {new_text!r} 尚未落盘——请确认已手工改好文件，"
                     f"否则日志与实际不符")

    if len(same) > 1:
        warns.append(f"srt_id={srt_id} track={track} 有 {len(same)} 条同时间戳行，"
                     f"请确认 --old 指定的是要记的那一条")
    return warns


def run_manual_log(work_dir: str, batch_id: str, file: str, srt_id: int,
                   track: str, old_text: str, new_text: str,
                   category: str = "", reason: str = "",
                   force: bool = False) -> None:
    """破例 Edit ASS 后用脚本补记 log.jsonl，避免手写 JSON 出错。

    用法：apply_fixes.py --manual-log --batch-id <id> --file <ass> \\
           --srt-id <id> --track 中文 --old "原文本" --new "新文本" \\
           --category "语境错译" --reason "用户破例 Edit"

    写盘前会校验 --old 是否真的在该位置存在（见 _manual_log_check）。
    """
    warns = _manual_log_check(file, srt_id, track, old_text, new_text)
    if warns:
        for w in warns:
            print(f"[!] {w}", file=sys.stderr)
        if not force:
            raise SystemExit("[x] 有警告未处理，已中止记录"
                             "。确认无误后加 --force 强制写入。")
    append_log(work_dir, batch_id, "manual_edit", file, srt_id, track,
               old_text, new_text, category, reason)
    print(f"[*] 补记 manual_edit: batch={batch_id} srt_id={srt_id} track={track}")
    print(f"    file={file}")
    print(f"    old={old_text!r}")
    print(f"    new={new_text!r}")
    print(f"    rollback: --rollback batch={batch_id}")


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
    # 撞车检测在每文件循环里做（subs 已加载，能拿到真实 event 身份）
    collisions = []
    cross_copies = []
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
        # 撞车检测：本文件的 fix 里，有没有两条在「没有 current」时定位到同一个
        # 物理 event。_find_dialogue 已取最近时间戳，但同一 srt_id 有多条同轨行
        # （一句被拆成多条 Dialogue）时必然撞同一行（见 issue #2）。
        # 检测**不消耗 used、不按 current 精确挑**——补了不同 current 的
        # 「1 replace + N delete」是合法的合并写法，不算撞车。
        # _find_dialogue 已取最近时间戳，但 srt_id 距离 < 0.5s 时仍可能撞同
        # 一行（实测培根链 361/362 隔 390ms）。提前报出来，accept 前拆开。
        seen_events = {}  # event_identity -> [fx_id, ...]
        for fx in fxs:
            action = fx.get("action", "replace")
            # retime 按设计就要跟 replace/delete 落同一行，不是歧义（issue #3）
            if action in ("insert", "retime"):
                continue
            track = fx.get("track", TRACK_ZH)
            sid = fx["srt_id"]
            e = _find_dialogue(subs, srt_index, sid, track)
            if e is None:
                continue
            eid = id(e)
            seen_events.setdefault(eid, []).append((fx.get("id") or fx.get("audit_id", ""), sid, track))
        # 各条 current 互不相同且都能精确匹配 → 明确指定，不算撞车
        for eid, hits in list(seen_events.items()):
            if len(hits) <= 1:
                continue
            curs = []
            for hid, sid, track in hits:
                fx = next((f for f in fxs
                           if (f.get("id") or f.get("audit_id", "")) == hid), {})
                curs.append(fx.get("current", ""))
            uniq = {clean_ass_text(c) for c in curs if c}
            if len(uniq) == len(curs) and uniq:
                del seen_events[eid]
        for eid, hits in seen_events.items():
            if len(hits) > 1:
                collisions.append({
                    "file": file,
                    "ids": [h[0] for h in hits],
                    "srt_ids": [h[1] for h in hits],
                    "track": hits[0][2],
                })
        used = set()  # 预览按实写顺序消耗候选，命中与 accept 一致
        for fx in fxs:
            action = fx.get("action", "replace")
            track = fx.get("track", TRACK_ZH)
            srt_id = fx["srt_id"]
            # 与上面撞车检测同一套消耗顺序，保证预览与实写命中同一行
            e = _find_dialogue(subs, srt_index, srt_id, track,
                               prefer_text=fx.get("current", ""), used=used)
            # insert：该 track 行尚不存在，e=None 正常；ass_time 从 srt 块取
            sb = srt_index.get(srt_id)
            is_insert = (action == "insert")
            if is_insert:
                if sb is None:
                    lines.append(f"### {fx.get('audit_id') or fx.get('id','')} — {fx.get('category','')} (insert)")
                    lines.append(f"- **（定位失败：srt_id {srt_id} 无对应时段）**")
                    lines.append("")
                    continue
                ass_time = f"{seconds_to_ass(sb.start)}-{seconds_to_ass(sb.end)}"
                new_raw = fx.get("final_new") or fx.get("suggested_new", "")
                lines.append(f"### {fx.get('audit_id') or fx.get('id','')} — {fx.get('category','')} (insert)")
                lines.append(f"- srt_id: {srt_id} / track: {track}")
                lines.append(f"- ass_time: `{ass_time}`")
                lines.append(f"- 新增 {track} 行")
                if fx.get("reason"):
                    lines.append(f"- 理由: {fx['reason']}")
                lines.append(f"- 新译: `{new_raw}`")
                lines.append("")
                continue
            # dry-run 对称显示：现译/新译都显示实际落盘的 raw text（含标签），
            # 让人看到真实写入内容，避免以为标签丢了。
            cur_raw = e.text if e else "（定位失败）"
            new_raw = fx.get("final_new") or fx.get("suggested_new", "")
            # 给新译补上原行标签做对称预览（不实际写入）
            if e and new_raw:
                orig_tags, _ = extract_leading_tags(e.text)
                new_tags, new_body = extract_leading_tags(new_raw)
                new_preview = "".join(_merge_tags(orig_tags, new_tags)) + new_body
            else:
                new_preview = new_raw
            # ass_time：从定位到的 Dialogue 取 start/end，转 ASS 串
            ass_time = ""
            if e:
                ass_time = f"{seconds_to_ass(e.start/1000.0)}-{seconds_to_ass(e.end/1000.0)}"
            lines.append(f"### {fx.get('audit_id') or fx.get('id','')} — {fx.get('category','')} ({action})")
            lines.append(f"- srt_id: {fx['srt_id']} / track: {track}")
            if ass_time:
                lines.append(f"- ass_time: `{ass_time}`")
            if fx.get("reason"):
                lines.append(f"- 理由: {fx['reason']}")
            if action == "replace":
                lines.append("- 现译 → 新译（均含实际标签）:")
                lines.append(f"  - 现: `{cur_raw}`")
                lines.append(f"  - 新: `{new_preview}`")
                # 合并碎片行时文本会显著变长，但 replace 不动时间轴 →
                # 后半截没有显示时间。提醒补一条 retime（见 issue #3）。
                old_plain = clean_ass_text(cur_raw)
                new_plain = clean_ass_text(new_preview)
                if (e and old_plain and new_plain
                        and len(new_plain) / len(old_plain) > 1.5):
                    lines.append(
                        f"- ⚠ 文本长度 {len(old_plain)} → {len(new_plain)}"
                        f"（>{1.5}×），但本条未带 retime")
                    lines.append(
                        f"  - 若是合并碎片行，需另加一条 `\"action\": \"retime\"` "
                        f"把 end 延到后一句的结束时间")
            elif action == "retime":
                ns = fx.get("new_start")
                ne = fx.get("new_end")
                old_spec = (_format_timespec(e.start / 1000.0, e.end / 1000.0)
                            if e else "")
                ns_s = old_spec.split("-")[0] if old_spec else ""
                ne_s = old_spec.split("-")[1] if old_spec else ""
                if ns is not None:
                    ns_s = f"{ns:.2f}"
                if ne is not None:
                    ne_s = f"{ne:.2f}"
                lines.append(f"- 时间轴: `{old_spec}` → `{ns_s}-{ne_s}`（秒）")
                if ns is not None and ne is not None and ne <= ns:
                    lines.append(f"- **（非法：new_end {ne} 必须大于 new_start {ns}）**")
            elif action == "delete":
                lines.append(f"- 删除整行: `{cur_raw}`")
            elif action == "swap":
                lines.append(f"- 与 srt_id={fx.get('swap_with')} 交换文本（{track} 行）")
                lines.append(f"  - 当前行: `{cur_raw}`")
            lines.append("")
        # 跨块复制预警（issue #1 修复 F）：新译文与 ±3 邻块现有译文高相似，
        # 典型是 agent 把一条译文换成了邻块的译文。只预警不拦，因为「同场景
        # 两句本来就该像」是合法情形，需要人看一眼。
        try:
            from verify_fixes import find_cross_block_copies
        except Exception:
            find_cross_block_copies = None
        if find_cross_block_copies is not None:
            # 注意：apply_fixes 在模块级 import verify_fixes 会造成循环依赖
            # （verify_fixes 反过来 import apply_fixes），故这里是函数内 import。
            for h in find_cross_block_copies(fxs, subs, srt_index):
                cross_copies.append({"file": file, **h})
        lines.append("")
    if cross_copies:
        lines.insert(3, "")
        cw = ["## ⚠ 撞车预警（新译文与邻块译文高相似，accept 前逐条确认）", ""]
        cw.append("以下 fix 的新译文与 ±3 邻块的现有译文高相似（阈值 0.55）。"
                  "多数情况是**把邻块的译文抄了过来**（实测 e04 一轮 15 条错位就是这么来的）。"
                  "少数情况是两句本来就该像，属正常。逐条读英文原文确认；"
                  "确认是抄错了就改 fixes.json，确认正常可忽略。")
        cw.append("")
        for c in cross_copies:
            cw.append(f"- `{c['id']}` srt_id={c['srt_id']} 与邻块 "
                      f"`{c['neighbor']}` 相似度 {c['score']:.2f}：`{c['new']}`")
        cw.append("")
        lines = lines[:3] + cw + lines[3:]
    if collisions:
        # 撞车预警放末尾，最显眼。报每对写到同一物理行的 fix。
        lines.insert(3, "")
        warn = ["## ⚠ 撞车预警（accept 前必须拆开）", ""]
        warn.append("以下 fix 对定位到**同一物理 ASS 行**（srt_id 时间戳过近，"
                    "_find_dialogue 取最近也分不开）。accept 会互相覆盖。"
                    "拆法：要么合一条 fix（一条整句拆多行用 a/b/c 后缀），"
                    "要么改用 insert 加注释轨，要么走 Edit 兜底（见 manual-flow.md 兜底节）。")
        warn.append("")
        for c in collisions:
            ids = "/".join(c["ids"])
            sids = "/".join(str(s) for s in c["srt_ids"])
            warn.append(f"- 文件 `{os.path.basename(c['file'])}` track={c['track']}: "
                        f"fix `{ids}` (srt_id {sids}) 写到同一行")
        warn.append("")
        lines = lines[:3] + warn + lines[3:]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[*] dry-run 写入 {out_path}")
    if collisions:
        print(f"[!] 撞车 {len(collisions)} 组：{[c['ids'] for c in collisions]}")
    if cross_copies:
        print(f"[!] 跨块复制 {len(cross_copies)} 条："
              f"{[(c['id'], c['srt_id'], c['neighbor']) for c in cross_copies]}")
    return out_path


def run_accept(fixes: list, work_dir: str, batch_id: str,
               force_collision: bool = False) -> None:
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

        # accept 前的撞车预检（issue #2）：同一物理行被两条 fix 命中说明 fix
        # 文件本身有歧义，写下去只会产生半合并残骸。默认拒写，需显式 --force-collision。
        # 预检模拟的是「没有 current 时」的退化行为：只要某条 fix 缺 current 且它
        # 会落到已被别的 fix 认领的行上，就是歧义。带了不同 current 的 fix 是明确
        # 指定的，不报（那是 merge 的正常写法：1 replace + N delete 合并碎片行）。
        # 撞车预检忽略 retime：retime 按设计就是要跟 replace / delete 落在同一行
        # （合并碎片行 = replace 合并文本 + retime 延时间轴 + delete 删后半条），
        # 它是协同操作而非歧义（见 issue #3）。
        if not force_collision:
            claimed = {}   # id(e) -> [fx_id]
            for fx in fxs:
                if fx.get("action", "replace") in ("insert", "retime"):
                    continue
                fxiv = fx.get("id") or fx.get("audit_id", "")
                track = fx.get("track", TRACK_ZH)
                cur = fx.get("current", "")
                # 该 fix 在「无 current」时（或带 current 时）会落到哪一行
                e = _find_dialogue(subs, srt_index, fx["srt_id"], track,
                                   prefer_text=cur)
                if e is None:
                    continue
                # 带了 current 但没匹配上 → 说明这条 fix 自身不准，直接拒
                if cur:
                    want = clean_ass_text(cur)
                    same = [x for x in subs.events
                            if style_to_track(x.style or "") == track
                            and abs(x.start / 1000.0
                                    - srt_index[fx["srt_id"]].start) <= 0.5]
                    if not any(clean_ass_text(x.text) == want for x in same):
                        print(f"[!] {fxiv}: current 在 srt_id={fx['srt_id']} "
                              f"track={track} 的行里找不到：{cur!r}", file=sys.stderr)
                        print("    该行可能已被改过，或 current 写错。先核对再跑。",
                              file=sys.stderr)
                        raise SystemExit(1)
                others = claimed.get(id(e), [])
                if others:
                    bad_note = others + [fxiv]
                    print(f"[!] 撞车，拒绝写入 {file}：{bad_note}", file=sys.stderr)
                    print(f"    这些 fix 会落在同一行。若确实要合并碎片行，"
                          f"请给每条 fix 补 \"current\"（该行原文）以精确定位；"
                          f"确认无误也可加 --force-collision。", file=sys.stderr)
                    raise SystemExit(1)
                claimed.setdefault(id(e), []).append(fxiv)

        used = set()  # 逐条消耗候选行，后续 fix 不会再命中已处理过的行
        for fx in fxs:
            action = fx.get("action", "replace")
            track = fx.get("track", TRACK_ZH)
            srt_id = fx["srt_id"]
            e = _find_dialogue(subs, srt_index, srt_id, track,
                               prefer_text=fx.get("current", ""), used=used)
            if action == "insert":
                sb = srt_index.get(srt_id)
                if sb is None:
                    print(f"[!] insert 定位失败: {fx.get('id')} srt_id={srt_id} 无对应时段", file=sys.stderr)
                    continue
                style = _resolve_style_for_track(subs, track)
                if not style:
                    print(f"[!] insert 失败: {fx.get('id')} ASS 缺 {track} 样式（需先在 [V4+ Styles] 定义）", file=sys.stderr)
                    continue
                new_text = fx.get("final_new") or fx.get("suggested_new", "")
                if not new_text:
                    print(f"[!] insert 无新文本: {fx.get('id')}", file=sys.stderr)
                    continue
                ne = SSAEvent()
                ne.start = int(sb.start * 1000)
                ne.end = int(sb.end * 1000)
                ne.style = style
                ne.text = new_text
                subs.events.append(ne)
                append_log(work_dir, batch_id, "insert", file, srt_id, track,
                           "", ne.text, fx.get("category", ""), fx.get("reason", ""))
                continue
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
                # 删整行（按身份，不能用 remove()，见 _remove_event）
                if not _remove_event(subs, e):
                    print(f"[!] delete 失败: {fx.get('id')} 未找到目标行", file=sys.stderr)
                    continue
                append_log(work_dir, batch_id, "delete", file, srt_id, track,
                           old_text, "", fx.get("category",""), fx.get("reason",""))
            elif action == "retime":
                new_start = fx.get("new_start")
                new_end = fx.get("new_end")
                if new_start is None and new_end is None:
                    print(f"[!] retime 无 new_start/new_end: {fx.get('id')}", file=sys.stderr)
                    continue
                try:
                    old_s, old_e = _retime_event(e, new_start, new_end)
                except ValueError as ex:
                    print(f"[!] retime 失败: {fx.get('id')} {ex}", file=sys.stderr)
                    continue
                # 时间串复用 old_text/new_text 字段（见 issue #3），
                # rollback 靠它精确恢复时间轴
                append_log(work_dir, batch_id, "retime", file, srt_id, track,
                           _format_timespec(old_s, old_e),
                           _format_timespec(e.start / 1000.0, e.end / 1000.0),
                           fx.get("category",""), fx.get("reason",""))
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
            # 回滚：按日志里的 new_text（当前内容）做 fallback 定位。
            # retime 条目的 new_text 是时间串，不能当文本用，改用 srt_id 定位。
            if ent.get("action") == "retime":
                e = _find_dialogue(subs, srt_index, ent["srt_id"], track)
            else:
                e = _find_dialogue(subs, srt_index, ent["srt_id"], track,
                                   fallback_text=ent.get("new_text",""))
            if not e:
                print(f"[!] 回滚定位失败: srt_id={ent['srt_id']} track={track} "
                      f"(srt_path={srt_path or '未找到'})", file=sys.stderr)
                continue
            if ent["action"] == "delete":
                print(f"[!] delete 回滚无法自动重建 srt_id={ent['srt_id']}", file=sys.stderr)
                continue
            if ent["action"] == "insert":
                # insert 的逆 = 删该行（按 new_text fallback 定位插入的行）
                if e is None:
                    print(f"[!] insert 回滚定位失败: srt_id={ent['srt_id']} track={track}", file=sys.stderr)
                    continue
                if not _remove_event(subs, e):
                    print(f"[!] insert 回滚失败: srt_id={ent['srt_id']} 未找到目标行", file=sys.stderr)
                    continue
                append_log(work_dir, make_batch_id(), "rollback", f,
                           ent["srt_id"], ent["track"], e.text, "",
                           ent.get("category", ""), f"rollback of {ent['batch_id']}")
                count += 1
                continue
            if ent["action"] == "retime":
                # retime 的逆 = 把时间轴写回 old_text 里的时间串
                try:
                    old_s, old_e = _parse_timespec(ent.get("old_text", ""))
                except ValueError as ex:
                    print(f"[!] retime 回滚失败: srt_id={ent['srt_id']} {ex}", file=sys.stderr)
                    continue
                cur_spec = _format_timespec(e.start / 1000.0, e.end / 1000.0)
                e.start = int(round(old_s * 1000))
                e.end = int(round(old_e * 1000))
                append_log(work_dir, make_batch_id(), "rollback", f,
                           ent["srt_id"], ent["track"], cur_spec,
                           _format_timespec(old_s, old_e),
                           ent.get("category", ""), f"rollback of {ent['batch_id']}")
                count += 1
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
    ap.add_argument("--file", default=None, help="rollback id= 时限定文件；--manual-log 时必填")
    ap.add_argument("--work-dir", default=WORK_DIR)
    ap.add_argument("--force-collision", action="store_true",
                    help="--accept 时忽略撞车预检（默认拒写，见 issue #2）")
    # 破例 Edit 兜底：手动改了 ASS 后用脚本补记 log.jsonl
    ap.add_argument("--manual-log", action="store_true",
                    help="破例 Edit 后补记一条 manual_edit 日志（避免手写 JSON）")
    ap.add_argument("--srt-id", type=int, default=None, help="--manual-log 用")
    ap.add_argument("--track", default="中文", help="--manual-log 用")
    ap.add_argument("--old", default="", help="--manual-log 用：原文本")
    ap.add_argument("--new", default="", help="--manual-log 用：新文本")
    ap.add_argument("--category", default="", help="--manual-log 用")
    ap.add_argument("--reason", default="", help="--manual-log 用")
    ap.add_argument("--force", action="store_true",
                    help="--manual-log 校验有警告时仍强制写入（--old 找不到仍直接失败）")
    args = ap.parse_args()

    if args.manual_log:
        if not args.file or args.srt_id is None:
            ap.error("--manual-log 需要 --file, --srt-id, --old, --new（--batch-id 缺省自动生成）")
        wd = resolve_work_dir(args.work_dir)
        bid = args.batch_id or make_batch_id()
        # 校验失败时 run_manual_log 抛 SystemExit(str)，Python 默认会把
        # 该字符串打到 stderr 并以 1 退出，这里不再包装，保留原始消息。
        run_manual_log(wd, bid, args.file, args.srt_id, args.track,
                       args.old, args.new, args.category, args.reason,
                       force=args.force)
        return

    if args.rollback:
        wd = resolve_work_dir(args.work_dir)
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

    wd = resolve_work_dir(args.work_dir)
    fixes = load_fixes(args.fixes)
    if args.dry_run:
        run_dry_run(fixes, wd)
    elif args.accept:
        bid = args.batch_id or make_batch_id()
        run_accept(fixes, wd, bid, force_collision=args.force_collision)
    else:
        ap.error("需要 --dry-run 或 --accept 或 --rollback")


if __name__ == "__main__":
    main()
