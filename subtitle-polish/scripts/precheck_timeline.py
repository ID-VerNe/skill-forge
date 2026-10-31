# -*- coding: utf-8 -*-
"""precheck_timeline.py — L0 结构哨兵：秒级、不加载模型的时间轴体检。

这个 skill 里任何与时间有关的检查原本都要模型（whisper 分钟级、qwen 十几分钟），
而**最致命的错往往是结构性、秒级就能看出来的**：

  - fps 错配：23.976 ↔ 25 差 1.04271，45 分钟片累积 115 秒
  - 时间基准整体错位：首条在负时间，或末条超出片长
  - 丢段：中段一大截没有字幕
  - 抽错流：条数密度与同批其他集差一个量级

L0 只做「能不能排除」，不做「确认」：

    **L0 PASS ≠ 轴对。** 结构性正常但整体平移 0.3 s，它看不出来。
    要确认轴必须上 L1（whisper 粗筛）/ L2（qwen 精测）。

用法:
  python precheck_timeline.py S06E01.ass --media S06E01.mkv
  python precheck_timeline.py S06E01.srt --duration 2712.4
  python precheck_timeline.py ./subs --baseline 16.9      # 同批条数/分钟中位数

退出码：PASS 0 / SUSPECT 2 / UNVERIFIED 3（拿不到片长，无法判断）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import align_core as ac
from lib import credential as cred
from lib import verdict as V


def tail_voice(media, start, total):
    """片尾 [start, total] 里还有没有对白。True/False/None（判断不了）。

    为什么需要：单看「末条/片长 = 0.9594」无法区分两件事——
    fps 错配（字幕整体被压短），和片尾本来就有 2 分钟纯音乐。
    前者要乘 1.0427，后者乘了就全错。这条检测把两者分开：
    片尾还有对白 → 字幕确实短了；片尾静音 → 提前结束是正常的。
    """
    ff = shutil.which("ffmpeg")
    if not ff or total <= start:
        return None
    span = total - start
    cmd = [ff, "-v", "info", "-ss", "%.2f" % start, "-t", "%.2f" % span,
           "-i", media, "-af", "silencedetect=noise=-35dB:d=1.5",
           "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception:
        return None
    err = r.stderr or ""
    silent = sum(float(x) for x in re.findall(r"silence_duration://s*([//d.]+)", err))
    if "silence_start" in err and "silence_end" not in err.rsplit("silence_start", 1)[-1]:
        # 静音一直延续到结尾，没报 duration
        m = re.search(r"silence_start://s*([//d.]+)", err.rsplit("silence_start", 1)[-1])
        if m:
            silent += max(0.0, span - float(m.group(1)))
    return (span - silent) > span * 0.25


def analyse(rows, duration=None, baseline=None, gap_warn=300.0, tail=None):
    """纯函数：给定 [(start, end, text)] 与片长，返回体检结果。"""
    items = []
    hard = 0        # SUSPECT 计数
    info = 0

    if not rows:
        return {"verdict": "UNVERIFIED", "code": V.UNVERIFIED,
                "items": [("空", "没有读到任何字幕行", "SUSPECT")],
                "first": None, "last_end": None, "density": None,
                "fps": None, "hard": 1, "info": 0}
    rows = sorted(rows, key=lambda r: r[0])
    first, last_end = rows[0][0], max(r[1] for r in rows)
    dur = duration

    # 1) 包络
    if first < -0.5:
        items.append(("包络", "首条起点 %.2fs 为负" % first, "SUSPECT"))
        hard += 1
    elif first > 60:
        items.append(("包络", "首条起点 %.1fs，片头 60s 内没有字幕" % first, "SUSPECT"))
        hard += 1
    else:
        items.append(("包络", "首条 %.2fs" % first, "OK"))

    if dur:
        if last_end > dur + 2:
            items.append(("包络", "末条 %.1fs 超出片长 %.1fs（+%.1fs）"
                          % (last_end, dur, last_end - dur), "SUSPECT"))
            hard += 1
        elif last_end < dur * 0.85:
            if tail is False:
                items.append(("包络", "末条只到片长的 %.0f%%，但片尾是静音段——"
                              "提前结束正常" % (100 * last_end / dur), "OK"))
            else:
                items.append(("包络", "末条只到片长的 %.0f%%（%.0fs / %.0fs），"
                              "疑似截断或时间基准错位"
                              % (100 * last_end / dur, last_end, dur), "SUSPECT"))
                hard += 1
        else:
            items.append(("包络", "末条 %.1fs / 片长 %.1fs（%.0f%%）"
                          % (last_end, dur, 100 * last_end / dur), "OK"))
    else:
        items.append(("包络", "无片长，跳过末条越界检查", "INFO"))
        info += 1

    # 2) 尾部缺口（截断 / 帧率错配 / 时间基准错位的共同表现）
    #
    # 曾经试过用「末条/片长」直接反解 fps（0.9590 = 23.976/25 之类）。实测
    # 行不通：正常字幕的末条本来就在片长的 0.90~0.99 之间浮动，比值同时受
    # 「末尾留白」和「帧率换算」两个未知量影响，一个端点解不出两个未知数。
    # 拿这个比值去乘系数，危险程度和收益完全不成比例。
    #
    # 改成可验证的判据：差多少秒、那段里还有没有对白。有对白才算问题。
    tail_gap = None
    fps = None
    if dur:
        tail_gap = dur - last_end
        limit = max(30.0, dur * 0.03)
        if tail_gap <= limit:
            items.append(("尾部", "末条距片尾 %.0fs（%.1f%%），正常"
                          % (tail_gap, 100 * tail_gap / dur), "OK"))
        elif tail is True:
            items.append(("尾部", "末条距片尾 %.0fs（%.1f%%），且片尾仍有对白 "
                          "→ 尾部 %.0fs 内容没字幕。常见原因：截断、"
                          "帧率错配（23.976↔25 差 4.27%%）、时间基准错位"
                          % (tail_gap, 100 * tail_gap / dur, tail_gap), "SUSPECT"))
            hard += 1
            fps = {"tail_gap": round(tail_gap, 1), "confirmed": True}
        elif tail is False:
            items.append(("尾部", "末条距片尾 %.0fs，片尾是静音段——正常留白"
                          % tail_gap, "OK"))
        else:
            items.append(("尾部", "末条距片尾 %.0fs（%.1f%%），但没验片尾是否有对白；"
                          "给 --media 可自动分辨" % (tail_gap, 100 * tail_gap / dur),
                          "INFO"))
            info += 1
            fps = {"tail_gap": round(tail_gap, 1), "confirmed": None}
    else:
        items.append(("尾部", "无片长，跳过", "INFO"))
        info += 1

    # 3) 空洞（长静默段本身常见，只报 INFO）
    gaps = []
    for i in range(1, len(rows)):
        g = rows[i][0] - rows[i - 1][1]
        if g > gap_warn:
            gaps.append((rows[i - 1][1], g))
    if gaps:
        worst = max(gaps, key=lambda x: x[1])
        items.append(("空洞", "%d 处 > %ds 无字幕，最长 %.0fs（位置 %.0fs）"
                      % (len(gaps), gap_warn, worst[1], worst[0]), "INFO"))
        info += 1
    else:
        items.append(("空洞", "无 > %ds 的空洞" % gap_warn, "OK"))

    # 4) 密度（需要同批基线）
    density = None
    if dur:
        density = len(rows) / (dur / 60.0)
        if baseline:
            ratio = density / baseline if baseline else 1.0
            if ratio < 0.5 or ratio > 2.0:
                items.append(("密度", "%.1f 条/分，是同批基线 %.1f 的 %.0f%%"
                              % (density, baseline, 100 * ratio), "SUSPECT"))
                hard += 1
            else:
                items.append(("密度", "%.1f 条/分（基线 %.1f）"
                              % (density, baseline), "OK"))
        else:
            items.append(("密度", "%.1f 条/分（未给 --baseline，不做比对）" % density, "OK"))

    if hard:
        verdict, code = "SUSPECT", V.FAIL
    elif dur is None:
        verdict, code = "UNVERIFIED", V.UNVERIFIED
    else:
        verdict, code = "PASS", V.PASS

    return {"verdict": verdict, "code": code, "items": items,
            "first": first, "last_end": last_end, "density": density,
            "tail_gap": tail_gap, "tail_voice": tail,
            "fps": fps, "hard": hard, "info": info}


def render(name, res):
    L = ["── %s" % name]
    for tag, msg, state in res["items"]:
        mark = {"OK": "   ", "INFO": " i ", "SUSPECT": " ! "}[state]
        L.append("[L0]%s%-4s %s" % (mark, tag, msg))
    L.append("[L0] 判定 %s" % res["verdict"])
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="L0 结构哨兵：秒级时间轴体检（不加载模型）",
        epilog="L0 PASS 不等于轴对——结构性正常但整体平移 0.3s 它也看不出来。"
               "确认轴必须上 L1/L2（align_audit）。")
    ap.add_argument("target", help="字幕文件或目录")
    ap.add_argument("--media", help="片源（用 ffprobe 取片长）")
    ap.add_argument("--duration", type=float, help="直接给片长（秒），免 ffprobe")
    ap.add_argument("--baseline", type=float, help="同批「条数/分钟」中位数，用于密度比对")
    ap.add_argument("--gap-warn", type=float, default=300.0, help="空洞告警阈值（秒）")
    ap.add_argument("--track", default=None, help="ASS 轨道样式名（默认全取）")
    ap.add_argument("--json", help="结果写 json")
    args = ap.parse_args()

    subs = ([args.target] if os.path.isfile(args.target)
            else sorted(p for p in glob.glob(os.path.join(args.target, "**", "*.*"),
                                             recursive=True)
                        if p.lower().endswith((".ass", ".ssa", ".srt"))))
    if not subs:
        print("[L0] 没有找到字幕：%s" % args.target, file=sys.stderr)
        sys.exit(V.UNVERIFIED)

    dur = args.duration
    if dur is None and args.media:
        dur = cred.probe_duration(args.media)
    if args.media and dur is None:
        print("[!] 取不到片长（ffprobe 不可用？），用 --duration 直接给", file=sys.stderr)

    out, codes = [], []
    for sub in subs:
        rows = ac.load_rows(sub, args.track)
        tail = None
        if args.media and dur and rows:
            tail = tail_voice(args.media, max(r[1] for r in rows), dur)
        res = analyse(rows, dur, args.baseline, args.gap_warn, tail)
        codes.append(res["code"])
        out.append({"sub": os.path.abspath(sub), **res})
        print(render(os.path.basename(sub), res))
        print()

    codes.sort()
    agg = codes[-1] if codes else V.UNVERIFIED
    if len(subs) > 1:
        print("── 汇总 %d 个文件，%d 个可疑"
              % (len(subs), sum(1 for c in codes if c != V.PASS)))

    if agg == V.PASS:
        print("[L0] PASS —— 结构正常。但这只是排除明显错，轴仍需 L1/L2 确认。")
    elif agg == V.UNVERIFIED:
        print("[L0] UNVERIFIED —— 拿不到片长，只能做部分检查。加 --media 或 --duration。")
    else:
        print("[L0] SUSPECT —— 先按上面的提示修结构问题，再花十分钟跑 L1。")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"verdict": V.label(agg), "code": agg, "duration": dur,
                       "items": out}, f, ensure_ascii=False, indent=1)
        print("[json] %s" % args.json)

    sys.exit(agg)


if __name__ == "__main__":
    main()
