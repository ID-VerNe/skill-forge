# -*- coding: utf-8 -*-
"""align_patch.py — 按偏移量改时间轴（只动时间字段，其余字节原样）。

与 apply_fixes 的分工：apply_fixes 改**文本**并按 srt_id 定位；本脚本改
**时间**，且刻意不依赖 srt_id 配对——`off(t)` 是纯时间函数，对 ASS 的
英文轨、中文轨、配套 SRT 各自独立施加即可，天然不会出现「ASS 改了 SRT 没改」
或「条数不等脚本跳过」的问题（实测 E04 的 SRT 750 块 vs 英文轨 749 条）。

三种偏移来源：
  --slope K [--origin T]  线性补偿 off(t) = K × (t − T)。origin 默认首条字幕起点，
                         保证开头不动、只补末端漂移。
  --spec spec.json        align_audit --json 产出的 curve（分段常数），或手写
                          {"kind":"curve","segments":[[t0,off],...]}
  --ref ref.ass           把英文轨逐条重定时到参考流的时间轴（阶跃偏移唯一正解）。

用法:
  python align_patch.py --sub S06E01.eng.ass --sub S06E01.eng.srt --slope 0.000096
  python align_patch.py --sub a.ass --spec audit.json --write
  python align_patch.py --sub a.ass --ref uk.ass --write --emit-spec step.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import align_core as ac
from lib import credential as cred
from lib import log as plog
from lib.ass_srt_pair import style_to_track


# ---------------------------------------------------------------- 写盘

def _detect_newline(path, default="\r\n"):
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
        return "\r\n" if b"\r\n" in head else ("\n" if b"\n" in head else default)
    except OSError:
        return default


def _backup(path, tag):
    bak = "%s.%s.bak" % (path, tag)
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    return bak


def patch_sub(path, offset_fn, write=False, tag="align", track=ac.TRACK_EN):
    """对单个字幕文件施加 off(t)。返回统计 dict。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".ass", ".ssa"):
        lines, events = ac.read_ass_raw(path)
        units = events
    elif ext == ".srt":
        lines, units = ac.read_srt_raw(path)
    else:
        raise SystemExit("不支持的字幕扩展名：%s" % path)

    if not units:
        raise SystemExit("没读到时间行：%s" % path)

    new_times, clamped = [], 0
    for u in units:
        st = u["start"] + offset_fn(u["start"])
        en = u["end"] + offset_fn(u["end"])
        if st < 0:
            en -= st
            st = 0.0
            clamped += 1
        if en <= st:
            en = st + 0.4
        new_times.append((st, en))

    shifts = [nt[0] - u["start"] for nt, u in zip(new_times, units)]
    steps = [(units[i]["start"], shifts[i - 1], shifts[i])
             for i in range(1, len(shifts))
             if abs(shifts[i] - shifts[i - 1]) > 0.2]

    print("\n%s  条目 %d" % (os.path.basename(path), len(units)))
    print("  偏移 首 %+.3f  末 %+.3f  min %+.3f  max %+.3f%s"
          % (shifts[0], shifts[-1], min(shifts), max(shifts),
             "  钳位 %d 条" % clamped if clamped else ""))
    if steps:
        print("  阶跃 %d 处，前 8：" % len(steps))
        for t, a, b in steps[:8]:
            print("    t=%8.1fs  %+.2f -> %+.2f" % (t, a, b))
    print("  抽样：", " ".join("%.0fs:%+.2f" % (t, offset_fn(t))
                               for t in (0, 600, 1200, 1800, 2400)))

    if not write:
        # 改动最大的 20 条先摊开看。曲线整体看着对、却把某一段推过头，
        # 是这类「整片乘一个函数」的操作最容易犯的错。
        order = sorted(range(len(units)), key=lambda i: -abs(shifts[i]))[:20]
        print("  改动最大的 20 条：")
        for i in order:
            if abs(shifts[i]) < 1e-6:
                break
            print("    #%-5d %8.2f -> %8.2f  (%+.2f)"
                  % (i + 1, units[i]["start"], new_times[i][0], shifts[i]))
        print("  [dry-run] 加 --write 生效")
        return {"file": path, "n": len(units), "shifts": shifts, "steps": steps,
                "clamped": clamped, "written": False,
                "max_shift": max(shifts, key=abs) if shifts else 0.0}

    bak = _backup(path, tag)
    for u, (st, en) in zip(units, new_times):
        if ext == ".srt":
            lines[u["line_no"]] = "%s --> %s" % (ac.sec_to_srt(st), ac.sec_to_srt(en))
        else:
            parts = u["parts"][:]
            parts[1] = ac.sec_to_ass(st)
            parts[2] = ac.sec_to_ass(en)
            lines[u["line_no"]] = "Dialogue:" + ",".join(parts)
    ac.write_lines(path, lines, _detect_newline(path, "\r\n" if ext != ".srt" else "\n"))
    print("  [write] %s  (备份 %s)" % (path, os.path.basename(bak)))
    return {"file": path, "n": len(units), "shifts": shifts, "steps": steps,
            "clamped": clamped, "written": True, "backup": bak,
            "max_shift": max(shifts, key=abs) if shifts else 0.0}


# ---------------------------------------------------------------- 重定时

def build_retime(sub_path, ref_path, track=ac.TRACK_EN):
    """把英文轨逐条重定时到参考流。返回 (row_new_times, info)。

    row_new_times: {row_idx: (new_start, new_end)}
    未匹配行按前后锚点的偏移线性插值（不是按索引平均，避免剪辑点处跳空）。
    """
    _lines, events = ac.read_ass_raw(sub_path)
    rows = [e for e in events if style_to_track(e["style"]) == track]
    if not rows:
        raise SystemExit("参考重定时需要 ASS 且含 %s 轨：%s" % (track, sub_path))

    ref_ext = os.path.splitext(ref_path)[1].lower()
    if ref_ext in (".ass", ".ssa"):
        ref = [e for e in ac.read_ass_raw(ref_path)[1]]
    else:
        ref = ac.read_srt_raw(ref_path)[1]
        ref = [{"start": b["start"], "end": b["end"], "text": ""} for b in ref]
        # SRT 无文本无法 LCS，只能按时间比例——拒绝，避免静默降质
        raise SystemExit("参考流需为 ASS（需文本做对齐），SRT 仅能按时间比例缩放，不可靠")

    sub_words, owner = [], []
    for i, e in enumerate(rows):
        for w in ac.words_of(_part_text(e["parts"])):
            sub_words.append(w)
            owner.append(i)
    ref_words, ref_owner = [], []
    for j, e in enumerate(ref):
        for w in ac.words_of(_part_text(e["parts"])):
            ref_words.append(w)
            ref_owner.append(j)

    if not sub_words or not ref_words:
        raise SystemExit("参考流无可用文本")

    import difflib

    sm = difflib.SequenceMatcher(None, sub_words, ref_words, autojunk=False)
    pair = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            si, ri = blk.a + k, blk.b + k
            i, j = owner[si], ref_owner[ri]
            if i not in pair or si < pair[i][1]:
                pair[i] = (j, si)

    ordered = sorted((i, pair[i][0]) for i in pair)
    mono = sum(1 for a, b in zip(ordered, ordered[1:]) if b[1] <= a[1])
    anchors = [(i, ref[j]["start"] - rows[i]["start"], ref[j]["end"] - rows[i]["end"])
               for i, j in ordered]

    def interp(idx):
        if not anchors:
            return 0.0, 0.0
        if idx <= anchors[0][0]:
            return anchors[0][1], anchors[0][2]
        if idx >= anchors[-1][0]:
            return anchors[-1][1], anchors[-1][2]
        for k in range(len(anchors) - 1):
            x0, s0, e0 = anchors[k]
            x1, s1, e1 = anchors[k + 1]
            if x0 <= idx <= x1:
                if x1 == x0:
                    return s0, e0
                r = (idx - x0) / float(x1 - x0)
                return s0 + (s1 - s0) * r, e0 + (e1 - e0) * r
        return anchors[-1][1], anchors[-1][2]

    new_times = {}
    for i in range(len(rows)):
        if i in pair:
            j = pair[i][0]
            new_times[i] = (ref[j]["start"], ref[j]["end"])
        else:
            ds, de = interp(i)
            new_times[i] = (max(0.0, rows[i]["start"] + ds),
                            max(0.0, rows[i]["end"] + de))

    info = {"matched": len(pair), "total": len(rows),
            "non_monotonic": mono, "anchors": anchors}
    return rows, events, new_times, info


def _part_text(parts):
    return parts[9] if len(parts) > 9 else ""


def apply_retime(path, rows, events, new_times, write=False, tag="retime",
                 track=ac.TRACK_EN):
    """写回：英文轨用新时间；中文/注释轨跟随其**前一条**英文轨。"""
    lines, _ = ac.read_ass_raw(path)
    order = []  # 英文轨在 rows 中的序号，按事件顺序
    for e in events:
        if style_to_track(e["style"]) == track:
            order.append(e)

    if len(order) != len(rows):
        raise SystemExit("英文轨条数不一致（%d vs %d），中止" % (len(order), len(rows)))

    by_line, last = {}, None
    for idx, e in enumerate(order):
        nt = new_times[idx]
        by_line[e["line_no"]] = nt
        last = nt
    # 中文轨跟随前一条英文
    prev = None
    for e in events:
        if style_to_track(e["style"]) == track:
            prev = by_line[e["line_no"]]
            continue
        if prev is not None:
            by_line[e["line_no"]] = prev

    shifts = [new_times[i][0] - rows[i]["start"] for i in range(len(rows))]
    steps = [(rows[i]["start"], shifts[i - 1], shifts[i])
             for i in range(1, len(shifts))
             if abs(shifts[i] - shifts[i - 1]) > 0.2]
    print("\n%s  英文轨 %d 条" % (os.path.basename(path), len(rows)))
    print("  偏移 首 %+.3f  末 %+.3f  min %+.3f  max %+.3f"
          % (shifts[0], shifts[-1], min(shifts), max(shifts)))
    print("  阶跃 %d 处，前 8：" % len(steps))
    for t, a, b in steps[:8]:
        print("    t=%8.1fs  %+.2f -> %+.2f" % (t, a, b))

    if not write:
        print("  [dry-run] 加 --write 生效")
        return {"file": path, "n": len(rows), "written": False,
                "max_shift": max(shifts, key=abs) if shifts else 0.0}

    bak = _backup(path, tag)
    for line_no, (st, en) in by_line.items():
        e = next(x for x in events if x["line_no"] == line_no)
        parts = e["parts"][:]
        parts[1] = ac.sec_to_ass(st)
        parts[2] = ac.sec_to_ass(en)
        lines[line_no] = "Dialogue:" + ",".join(parts)
    ac.write_lines(path, lines, _detect_newline(path, "\r\n"))
    print("  [write] %s  (备份 %s)" % (path, os.path.basename(bak)))
    return {"file": path, "n": len(rows), "written": True, "backup": bak,
            "max_shift": max(shifts, key=abs) if shifts else 0.0}


# ---------------------------------------------------------------- 主流程

def _after_write(path, st, spec, work_dir, batch_id, fit=None, action="retime_curve"):
    """写盘后的三件事，缺一不可。

    1. 记 log.jsonl —— 否则 `--rollback batch=` 回滚完文本、时间还错着，
       回滚本身变成一次新的错误
    2. 让时间轴凭据失效 —— patched_at > computed_at，闸门立刻转 UNVERIFIED
    3. 记备份索引 —— .bak 不进 git，误删就没了，至少要能枚举出来
    """
    bak = st.get("backup")
    try:
        plog.append_curve_log(work_dir, batch_id, path, spec or {},
                              st.get("max_shift", 0.0), st.get("n", 0),
                              bak or "", fit)
        cred.touch_patch(path, st.get("max_shift", 0.0), st.get("n", 0))
        plog.record_backup(work_dir, path, bak or "", batch_id, action)
    except OSError as e:
        # 记不上账就不能留着改动——「改了但没记账」比不改更麻烦
        if bak and os.path.exists(bak):
            shutil.copy2(bak, path)
            print("[x] 记账失败（%s），已从备份还原 %s" % (e, path), file=sys.stderr)
        raise SystemExit("记账失败，改动已回滚")
    print("  [log]    %s  batch=%s  max %+.2f"
          % (os.path.basename(path), batch_id, st.get("max_shift", 0.0)))


def run_revert(args):
    """撤销最近一次 retime_curve：从备份还原，并记一条 revert_curve。"""
    work_dir = os.path.abspath(args.work_dir)
    batch_id = plog.make_batch_id()
    targets = args.sub or []
    done = 0
    for path in targets:
        e = plog.last_curve_entry(work_dir, path)
        if not e:
            print("[skip] %s：log 里没有 retime_curve 记录" % os.path.basename(path))
            continue
        bak = e.get("backup") or ""
        if not os.path.exists(bak):
            print("[x] 备份不存在：%s" % bak, file=sys.stderr)
            continue
        shutil.copy2(bak, path)
        plog.append_raw(work_dir, {
            "batch_id": batch_id, "action": "revert_curve", "file": path,
            "srt_id": 0, "track": "*", "old_text": "", "new_text": "",
            "reverted_batch": e.get("batch_id"), "backup": bak,
            "category": "时间轴", "reason": "align_patch --revert",
        })
        cred.touch_patch(path, 0.0, 0)
        print("[revert] %s  <- %s（撤销 batch %s）"
              % (os.path.basename(path), os.path.basename(bak), e.get("batch_id")))
        done += 1
    if not done:
        print("没有可撤销的记录。")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="按偏移量改字幕时间轴")
    ap.add_argument("--sub", action="append", required=True,
                    help="待改字幕（可多次；ASS 与配套 SRT 各自独立施加同一 off(t)）")
    ap.add_argument("--slope", type=float, help="线性斜率 K")
    ap.add_argument("--origin", type=float, help="线性原点 T（默认首条字幕起点）")
    ap.add_argument("--spec", help="偏移 spec json（align_audit --json 产出或手写）")
    ap.add_argument("--ref", help="参考流 ASS：逐条重定时（仅对 ASS 生效）")
    ap.add_argument("--track", default=ac.TRACK_EN, help="英文轨样式名")
    ap.add_argument("--emit-spec", help="把本次使用的偏移函数存成 spec json")
    ap.add_argument("--tag", default=None,
                    help="备份后缀：<file>.<tag>.bak（默认 retime / align）")
    ap.add_argument("--write", action="store_true", help="真正写盘（默认 dry-run）")
    ap.add_argument("--revert", action="store_true",
                    help="撤销最近一次时间轴改动（从 log 里找 retime_curve 的备份）")
    ap.add_argument("--work-dir", default=".subtitle-polish",
                    help="log.jsonl / backups.jsonl 所在目录")
    ap.add_argument("--batch-id", default=None, help="指定 batch_id（默认按时间生成）")
    args = ap.parse_args()

    if args.revert:
        run_revert(args)
        return

    given = sum(x is not None for x in (args.slope, args.spec, args.ref))
    if given != 1:
        ap.error("--slope / --spec / --ref 三者选一")
    if args.tag is None:
        args.tag = "retime" if args.ref else "align"

    work_dir = os.path.abspath(args.work_dir)
    batch_id = args.batch_id or plog.make_batch_id()

    if args.ref:
        sub_ass = next((p for p in args.sub
                        if p.lower().endswith((".ass", ".ssa"))), None)
        if not sub_ass:
            ap.error("--ref 需要至少一个 ASS 作为 --sub")
        rows, events, new_times, info = build_retime(sub_ass, args.ref, args.track)
        print("参考 %s：匹配 %d/%d (%.1f%%)，非单调 %d"
              % (os.path.basename(args.ref), info["matched"], info["total"],
                 100.0 * info["matched"] / info["total"], info["non_monotonic"]))
        st = apply_retime(sub_ass, rows, events, new_times, args.write, args.tag, args.track)

        # 同一 off(t) 供配套 SRT/其他文件复用（按行偏移拟合成阶梯曲线）
        pairs = [(rows[i]["start"], new_times[i][0] - rows[i]["start"])
                 for i in range(len(rows))]
        spec, base, fdiag = ac.spec_from_pairs(pairs)
        print("  派生曲线：%d 段（base %+.3f，残差 P90 %s）"
              % (fdiag.get("segs", 0), base,
                 ("%.3f" % fdiag["p90"]) if fdiag.get("p90") is not None else "—"))
        if fdiag["verdict"] != "FIT_OK":
            print("  [!] 拟合被拒：%s" % fdiag.get("reason", ""), file=sys.stderr)
            print("      逐条重定时已经写入了，但**不要**拿这条曲线去施加别的文件。")
        if args.emit_spec and spec is not None:
            with open(args.emit_spec, "w", encoding="utf-8") as f:
                json.dump(spec, f, ensure_ascii=False, indent=1)
            print("  [spec] %s" % args.emit_spec)
        if st and st.get("written"):
            _after_write(sub_ass, st, spec, work_dir, batch_id, fdiag, "retime_ref")
        others = [p for p in args.sub if p != sub_ass]
        if others:
            if spec is None:
                print("\n其余文件：拟合被拒，不能自动派生曲线，需单独处理。")
            else:
                print("\n提示：其余文件请用同一条曲线各自施加，避免条数不等时被跳过：")
                print("  python align_patch.py --spec %s %s --write"
                      % (args.emit_spec or "<spec.json>",
                         " ".join("--sub %s" % p for p in others)))
        return

    fit = None
    if args.spec:
        with open(args.spec, encoding="utf-8") as f:
            data = json.load(f)
        spec = data.get("curve")
        fit = data.get("fit")
        if spec is None:
            fv = (fit or {}).get("verdict")
            if fv == "FIT_REJECTED":
                raise SystemExit(
                    "拟合被拒：%s\n改用 --slope 做线性补偿，或分区段手工处理。"
                    % (fit or {}).get("reason", ""))
            if "curve_applicable" in data:
                v = data.get("verdict") or "PASS"
                if v == "UNVERIFIED":
                    raise SystemExit(
                        "这份审计判 UNVERIFIED（没验出来，不是通过），没有曲线可施加。\n"
                        "先调小 --window/--min-n 让分时段凑够样本，再复测。")
                raise SystemExit(
                    "这份审计判 %s，没输出曲线——不需要改时间轴。" % v)
            spec = data  # 手写 spec
        if "kind" not in spec:
            raise SystemExit("spec 里没有 kind 字段，无法解释偏移函数：%s" % args.spec)
    else:
        origin = args.origin
        if origin is None:
            first = min((u["start"] for u in
                         (ac.read_ass_raw(args.sub[0])[1]
                          if args.sub[0].lower().endswith((".ass", ".ssa"))
                          else ac.read_srt_raw(args.sub[0])[1])), default=0.0)
            origin = first
        spec = ac.spec_from_linear(args.slope, origin)
        print("线性补偿 off(t) = %+.6f × (t − %.2f)" % (args.slope, origin))

    if args.emit_spec:
        with open(args.emit_spec, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=1)
        print("[spec] %s" % args.emit_spec)

    offset_fn = lambda t: ac.offset_at(spec, t)  # noqa: E731
    for path in args.sub:
        st = patch_sub(path, offset_fn, args.write, args.tag, args.track)
        if st.get("written"):
            _after_write(path, st, spec, work_dir, batch_id, fit)


if __name__ == "__main__":
    main()
