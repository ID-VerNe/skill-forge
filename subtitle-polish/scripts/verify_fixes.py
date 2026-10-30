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
from lib.ass_srt_pair import clean_ass_text
from apply_fixes import _find_dialogue, _build_srt_index, _find_paired_srt

# 邻块撞车默认参数（实测校准：坏条 4/15 命中，好条 0/84 误报）
NEIGHBOR_WINDOW = 3
NEIGHBOR_FLOOR = 0.55
_CJK_LO, _CJK_HI = chr(0x4E00), chr(0x9FFF)  # CJK 统一汉字区间


def _latest_per_target(entries):
    """每个 (file, srt_id, track) 取最后一条记录（后续操作覆盖前述）。

    delete 也按此聚合：若某行先 replace 再 delete，最终态是"已删"。
    """
    latest = {}
    for e in entries:
        key = (e["file"], e["srt_id"], e.get("track", TRACK_ZH))
        latest[key] = e
    return list(latest.values())


def _cjk(s):
    """取中文字符序列，用于中中相似度比较。"""
    return "".join(ch for ch in (s or "") if _CJK_LO <= ch <= _CJK_HI)


def detect_neighbor_duplicate(zh_text, srt_id, zh_by_sid, window=NEIGHBOR_WINDOW,
                              floor=NEIGHBOR_FLOOR, exclude=()):
    """新译文与 ±window 邻块现有译文的最大相似度。

    zh_by_sid: {srt_id: 中文可见文本}
    exclude: 同 srt_id 被拆成多条 Dialogue 时要排除的其它行文本（自己不算"邻块"）。
    返回 (score, neighbor_srt_id or None)。

    为什么需要：verify 只证明「字写进去了」，不证明「写进去的是对的」。实测
    S06E04 一轮 99 条 fix 里 15 条把正确译文换成邻块译文，verify 报 0 失败。
    这条判据对该错位形态误报 0、召回 4/15，是纯字符串能抓到的部分；其余 11 条
    是「换成同场景另一句」，任何字符串判据都抓不到，只能靠 cross_check 人工
    复核语义。不要把它当成完整的错位检测器。
    """
    import difflib

    n = _cjk(zh_text)
    if not n:
        return 0.0, None
    best = (0.0, None)
    for sid, other in zh_by_sid.items():
        try:
            d = abs(int(sid) - int(srt_id))
        except (TypeError, ValueError):
            continue
        if d == 0 or d > window:
            continue
        if other in exclude:
            continue
        o = _cjk(other)
        if not o:
            continue
        r = difflib.SequenceMatcher(None, n, o).ratio()
        if r > best[0]:
            best = (r, sid)
    return best if best[0] >= floor else (best[0], None)


def build_zh_index(subs, srt_index):
    """{srt_id: 中文可见文本}（同 srt_id 多条时取第一条非空）。"""
    out = {}
    for sid in (srt_index or {}):
        e = _find_dialogue(subs, srt_index, sid, TRACK_ZH)
        if e is None:
            continue
        txt = clean_ass_text(e.text)
        if txt:
            out[sid] = txt
    return out


def find_cross_block_copies(fixes, subs, srt_index):
    """dry-run 用：本批 fix 的新译文与邻块现有译文撞车的条目。

    返回 [{"id", "srt_id", "score", "neighbor", "new"}]。
    只做预警，不改任何文本。
    """
    zh_by_sid = build_zh_index(subs, srt_index)
    hits = []
    for fx in fixes:
        if not fx.get("enabled", True):
            continue
        if fx.get("action", "replace") in ("delete", "insert"):
            continue
        new = fx.get("final_new") or fx.get("suggested_new", "")
        if not new:
            continue
        _, body = extract_leading_tags(new)
        sid = fx["srt_id"]
        own = zh_by_sid.get(sid, "")
        score, nbr = detect_neighbor_duplicate(body, sid, zh_by_sid,
                                               exclude=(own,) if own else ())
        if nbr:
            hits.append({
                "id": fx.get("id") or fx.get("audit_id", ""),
                "srt_id": sid,
                "score": score,
                "neighbor": nbr,
                "new": body,
            })
    return hits


def _english_leak(zh_body):
    """中文轨里混入整句英文原文（可判定的不对应）。返回混入的英文片段或 ""。"""
    import re as _re
    # 去掉 <i> 之类标记后找连续 >=4 个英文单词的片段
    frag = _re.sub(r"<[^>]+>", " ", zh_body or "")
    m = _re.search(r"([A-Za-z][A-Za-z'’,.?!]*(?:\s+[A-Za-z][A-Za-z'’,.?!]*){3,})", frag)
    return m.group(1).strip() if m else ""


def check_english_alignment(entry, subs, srt_index):
    """D1 硬约束：只判**可证明**的「译文与英文对不上」。

    能判的只有两类，其余（语义错译）交给 cross_check 人工复核——
    纯字符串无法判断「这句中文是不是这句英文的翻译」，不要假装能判。

      1. 中文轨译文为空/只剩标点
      2. 中文轨里塞进了整句英文原文（>=4 个连续英文词）

    返回 (ok, detail)。ok=True 表示没发现问题，不代表译文正确。
    """
    if entry.get("track", TRACK_ZH) != TRACK_ZH:
        return True, ""
    _, body = extract_leading_tags(entry.get("new_text", ""))
    if not body.strip():
        return False, "译文为空"
    if not any(u"一" <= ch <= u"鿿" for ch in body):
        return False, f"译文无中文（疑似直接抄了英文）：'{body}'"
    leak = _english_leak(body)
    if leak:
        return False, f"中文轨里混入英文原文：'{leak}'"
    return True, ""


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

    if action == "manual_edit":
        # 破例 Edit：按 log 的 new_text fallback 定位，核对可见文本一致即可。
        # 不要求 srt_id 精确时间戳匹配（manual_edit 可能改了时间戳）。
        e = _find_dialogue(subs, srt_index, entry["srt_id"], track,
                           fallback_text=expected_new)
        if e is None:
            return False, "", "定位失败（manual_edit 后该行找不到，可能时间戳变了）"
        _, exp_body = extract_leading_tags(expected_new)
        _, act_body = extract_leading_tags(e.text)
        if act_body == exp_body:
            return True, e.text, "可见文本一致（manual_edit）"
        return False, e.text, f"可见文本不符：期望 '{exp_body}' 实际 '{act_body}'"

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
        # D1 硬约束：可证明的「译文与英文对不上」直接判失败
        ok_align, why = check_english_alignment(entry, subs, srt_index)
        if not ok_align:
            return False, e.text, f"落盘一致但译文与英文对不上：{why}"
        # E：与 ±3 邻块译文撞车，典型是抄错行。注意这不是完整的错位
        # 检测器——「换成同场景另一句」判不出来，仍须 cross_check 人工复核。
        if track == TRACK_ZH:
            zh_by_sid = build_zh_index(subs, srt_index)
            # 先和**本轮之前**的邻块译文比（排除本次写入的那条），
            # 免得「我把两条都改对了、只是恰好写得像」被判撞车。
            prior = dict(zh_by_sid)
            prior.pop(entry["srt_id"], None)
            if entry.get("old_text"):
                _, old_body = extract_leading_tags(entry["old_text"])
                for k, v in list(prior.items()):
                    if clean_ass_text(old_body) == v:
                        prior.pop(k)
                        break
            score, nbr = detect_neighbor_duplicate(
                act_body, entry["srt_id"], prior)
            if nbr:
                return False, e.text, (f"新译文与邻块 srt_id={nbr} 撞车"
                                       f"（相似度 {score:.2f}），疑似抄错行")
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
        # 失败条目按 file 分组重新加载一次取 ass_time（不依赖上面的循环局部变量）
        from lib.time_fmt import seconds_to_ass
        fail_by_file = {}
        for e, actual, detail in fail_sections:
            fail_by_file.setdefault(e["file"], []).append((e, actual, detail))
        for f, items in fail_by_file.items():
            try:
                fsubs = pysubs2.load(f, encoding="utf-8-sig")
            except Exception:
                fsubs = None
            fsrt_path = _find_paired_srt(f)
            fsrt_blocks = parse_srt(fsrt_path) if fsrt_path and os.path.exists(fsrt_path) else []
            fsrt_index = _build_srt_index(fsrt_blocks)
            for e, actual, detail in items:
                ass_time = ""
                if fsubs is not None:
                    ev = _find_dialogue(fsubs, fsrt_index, e["srt_id"],
                                        e.get("track", TRACK_ZH),
                                        fallback_text=e.get("new_text", ""))
                    if ev:
                        ass_time = f"{seconds_to_ass(ev.start/1000.0)}-{seconds_to_ass(ev.end/1000.0)}"
                lines.append(f"### srt_id={e['srt_id']} track={e.get('track','')} "
                             f"action={e.get('action','')} batch={e.get('batch_id','')}")
                if ass_time:
                    lines.append(f"- ass_time: `{ass_time}`")
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
