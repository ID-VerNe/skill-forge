# -*- coding: utf-8 -*-
"""align_audit.py — 对齐审计：测字幕与**音频**的真实时间偏差。

为什么必须对音频：字幕 vs 字幕（含本片内嵌流）只能验结构，验不了同步。
实测一套 WEB-DL 音频是英国版剪辑、字幕却取自国际版，两版剪辑点相差
0.48s 整数倍，内嵌流自己也偏 2.4~2.9 秒——拿它当基准只会自证清白。

两种引擎，都归一到词级时间戳后再走同一套统计：
  whisper（默认）  faster-whisper large-v3 转录，独立于任何字幕
  qwen            Qwen3-ForcedAligner 全局强制对齐，须给模型目录

用法:
  # 最常用：视频 + 字幕，自动抽音轨
  python align_audit.py --sub S06E01.eng.ass --media S06E01.mkv

  # 复用已转好的 ASR 词级缓存（不重跑模型，秒出）
  python align_audit.py --sub S06E01.eng.ass --asr-words asr_words_E01.json

  # 轴归属：同一段音频分别比 ASS / UK 流 / US 流，MAD 最小者才是可信基线
  python align_audit.py --sub S06E01.eng.ass --asr-words w.json \
      --compare uk.ass --compare us.ass

  # 强制对齐引擎（需 Qwen3-ForcedAligner 模型目录）
  python align_audit.py --sub S06E01.eng.ass --media S06E01.mkv \
      --engine qwen --model /path/to/qwen3-aligner-0.6b --json out.json

输出：stdout 摘要 + 可选 `--report`(md) / `--json`(含曲线 spec，供 align_patch 用)。
退出码（见 lib/verdict.py）：PASS 0 / FAIL 2 / UNVERIFIED 3。`--no-strict` 回到 0。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import align_core as ac
from lib import axis as ax
from lib import credential as cred
from lib import verdict as V


# ---------------------------------------------------------------- 引擎

def tokens_whisper(wav, model_dir, cache_path, device="auto"):
    """faster-whisper 转录 -> 词级时间戳。有缓存直接读。"""
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return [tuple(x) for x in json.load(f)], "cache"
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("需要 faster-whisper：pip install faster-whisper")

    last_err = None
    for dev, ctype in (("cuda", "float16"), ("cpu", "int8")):
        if device not in ("auto", dev):
            continue
        try:
            model = WhisperModel(model_dir, device=dev, compute_type=ctype)
            segs, info = model.transcribe(
                wav, language="en", beam_size=5, word_timestamps=True,
                vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300),
                condition_on_previous_text=False,
            )
            toks = []
            for s in segs:
                for w in (s.words or []):
                    t = (w.word or "").strip()
                    if t:
                        toks.append((float(w.start), float(w.end), t))
            if toks and cache_path:
                os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(toks, f)
            return toks, "%s/%s" % (dev, ctype)
        except Exception as e:  # noqa: BLE001 — 换设备重试
            last_err = e
    raise SystemExit("faster-whisper 转录失败：%s" % last_err)


def _pick_boundaries(rows, target=240.0):
    """在目标块长 ±45s 内找**最大字幕间隙**作为切点，避免把句子切两半。

    切点落在句中会让该行锚到块首（实测 ass 602.12 -> align 600.00，差 −2.12s）。
    """
    gaps = [(a[1], b[0]) for a, b in zip(rows, rows[1:])]
    total = rows[-1][1] if rows else 0.0
    bounds, cur = [], 0.0
    while cur + target < total - 30:
        want = cur + target
        cand = [g for g in gaps
                if abs((g[0] + g[1]) / 2 - want) < 45 and g[1] > cur + 60]
        cut = (max(cand, key=lambda x: x[1] - x[0])[0]
               + max(cand, key=lambda x: x[1] - x[0])[1]) / 2 if cand else want
        bounds.append(cut)
        cur = cut
    return bounds


def tokens_qwen(wav, rows, model_dir, chunk=240.0, language="English"):
    """Qwen3-ForcedAligner 分块全局强制对齐 -> 词级时间戳。

    与 whisperX 的 align 关键差别：`align(audio, text)` **不接收时间窗**，
    是在给定音频段内对整段文本做全局对齐。原字幕偏 2~3 秒也不影响结果，
    只要块边界留足余量。
    """
    try:
        import torch
        import soundfile as sf
        from qwen_asr import Qwen3ForcedAligner
    except ImportError as e:
        raise SystemExit("需要 qwen_asr / torch / soundfile：%s" % e)

    data, sr = sf.read(wav, dtype="float32")
    total = len(data) / float(sr)
    bounds = _pick_boundaries(rows, chunk)
    edges = [0.0] + bounds + [total]

    model = Qwen3ForcedAligner.from_pretrained(
        model_dir, dtype=torch.bfloat16, device_map="cuda")

    print("  强制对齐：%d 段，共 %.0fs 音频" % (len(edges) - 1, total), flush=True)
    tokens = []
    for ci in range(len(edges) - 1):
        lo, hi = edges[ci], edges[ci + 1]
        sel = [r for r in rows if lo <= r[0] < hi]
        if not sel:
            continue
        text = " ".join(ac.clean_text(r[2]) for r in sel)
        a0 = max(0.0, lo - 2.0)
        a1 = min(total, hi + 2.0)
        seg = data[int(a0 * sr):int(a1 * sr)]
        try:
            res = model.align(audio=(seg, sr), text=text, language=language)
            items = res[0].items
        except Exception as e:  # noqa: BLE001 — 单块失败不拖垮整集
            print("  [warn] 块 %d 对齐失败：%s" % (ci, e), file=sys.stderr)
            continue
        for w in items:
            txt = (getattr(w, "text", "") or "").strip()
            if txt:
                tokens.append((float(w.start_time) + a0,
                               float(w.end_time) + a0, txt))
        print("    块 %2d  %5.0f-%5.0f s  %3d 条  token %d"
              % (ci, lo, hi, len(sel), len(items)), flush=True)
    return tokens


# ---------------------------------------------------------------- 报告

def _fmt(v, nd=3):
    return ("%+." + str(nd) + "f") % v


def print_summary(name, stats, n_rows, engine):
    print("\n%s  [%s]" % (name, engine))
    print("  锚点 %d/%d (%.1f%%)  剔除离群 %d 条 (|delta-中位| > %.2f)"
          % (stats["n_pairs"], n_rows,
             100.0 * stats["n_pairs"] / n_rows if n_rows else 0.0,
             stats["reject"]["dropped"], stats["reject"]["thr"]))
    print("  delta 中位 %s  MAD %.3f" % (_fmt(stats["median"]), stats["mad"]))
    print("  斜率 %+.6f  全长 %s s  (跨度 %.0fs)"
          % (stats["slope"], _fmt(stats["drift"], 2), stats["x_span"]))
    print("  分时段(%ds)中位极差 %.3f s  -> %s"
          % (stats["window"], stats["window_span"],
             stats["verdict"] if stats["verdict"] != "FAIL"
             else "FAIL（阈值 %.2fs）" % stats["tol"]))
    if stats.get("verdict_reason"):
        print("    %s" % stats["verdict_reason"])
    if stats["windows"]:
        print("  各时段：", " ".join(
            "%d-%ds:%s" % (w["lo"], w["hi"], _fmt(w["median"], 2))
            for w in stats["windows"]))


def build_report(args, stats, n_rows, engine, compare, axis_res=None):
    L = ["# 对齐审计 · %s" % os.path.basename(args.sub), ""]
    if args.media_path.startswith("("):
        L.append("- 音频：%s（仅用缓存的词级时间戳）" % args.media_path)
    else:
        L.append("- 音频：`%s`" % args.media_path)
        dur = ac.wav_duration(args.media_path)
        if dur:
            L.append("- 时长：%.1f s" % dur)
    L.append("- 引擎：%s" % engine)
    L.append("- 锚点：%d/%d（%.1f%%），剔除离群 %d 条（|delta−中位| > %.2f）"
             % (stats["n_pairs"], n_rows,
                100.0 * stats["n_pairs"] / n_rows if n_rows else 0.0,
                stats["reject"]["dropped"], stats["reject"]["thr"]))
    L.append("")
    # 结案口径钉在开头：这份报告的结论只有三态，不写「基本对上」这类模糊话。
    L.append("## 时间轴状态")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| 判定 | **%s** |" % stats["verdict"])
    L.append("| 分时段中位极差 | %.3f s（阈值 %.2f s） |"
             % (stats["window_span"], stats["tol"]))
    L.append("| delta 中位 / MAD | %s / %.3f |"
             % (_fmt(stats["median"]), stats["mad"]))
    L.append("| 全长漂移 | %s s（斜率 %+.6f，跨度 %.0f s） |"
             % (_fmt(stats["drift"], 2), stats["slope"], stats["x_span"]))
    L.append("| 引擎 / 锚点 | %s / %d of %d |" % (engine, stats["n_pairs"], n_rows))
    L.append("")
    if stats["verdict"] == "FAIL":
        L.append("> FAIL 意味着**不许结案**：修时间轴（`align_patch`）后必须重跑本审计，"
                 "直到 PASS 或明确按 UNVERIFIED 交付。")
        L.append("")
    elif stats["verdict"] == "UNVERIFIED":
        L.append("> UNVERIFIED 意味着**没验出来**，不是通过。按 UNVERIFIED 交付，"
                 "交付说明里不许出现「全部通过」「验证完毕」。")
        L.append("")
    L.append("## 判定")
    L.append("")
    L.append("| 指标 | 值 | 阈值 | 结论 |")
    L.append("|---|---|---|---|")
    L.append("| 分时段中位极差 | %.3f s | ≤ %.2f s | %s |"
             % (stats["window_span"], stats["tol"],
                "PASS" if stats["ok"] else ("**%s**" % stats["verdict"])))
    L.append("| 线性漂移（全长 %.0fs） | %s s | — | — |"
             % (stats["x_span"], _fmt(stats["drift"], 2)))
    L.append("| delta 中位 / MAD | %s / %.3f | — | 只看平坦度，不看绝对值 |"
             % (_fmt(stats["median"]), stats["mad"]))
    L.append("")
    if stats["windows"]:
        L.append("## 分时段（%ds 窗）" % stats["window"])
        L.append("")
        L.append("| 区间 | n | delta 中位 |")
        L.append("|---|---|---|")
        for w in stats["windows"]:
            L.append("| %d–%d s | %d | %s |" % (w["lo"], w["hi"], w["n"], _fmt(w["median"])))
        L.append("")
    if compare:
        L.append("## 轴归属对比")
        L.append("")
        L.append("同一段音频与各候选基准比对，**MAD 最小者才是可信基线**。")
        L.append("")
        L.append("| 参考 | 锚点 | 中位 | MAD | 斜率 | 全长漂移 |")
        L.append("|---|---|---|---|---|---|")
        L.append("| %s（本文件） | %d | %s | %.3f | %+.6f | %s s |"
                 % (os.path.basename(args.sub), stats["n_pairs"], _fmt(stats["median"]),
                    stats["mad"], stats["slope"], _fmt(stats["drift"], 2)))
        for label, cst in compare:
            L.append("| %s | %d | %s | %.3f | %+.6f | %s s |"
                     % (label, cst["n_pairs"], _fmt(cst["median"]), cst["mad"],
                        cst["slope"], _fmt(cst["drift"], 2)))
        L.append("")
        if axis_res:
            L.append("**判定 %s** —— %s" % (axis_res["verdict"], axis_res.get("reason", "")))
            L.append("")
            if axis_res["verdict"] == "AMBIGUOUS":
                L.append("> 候选之间差距在噪声带内，**不给出结论**。"
                         "换 `--engine qwen` 复测，或人工确认用的是哪条流。")
            elif axis_res["verdict"] == "NO_CANDIDATE":
                L.append("> 没有一条候选过绝对门。片源可能不是这批字幕对应的版本，"
                         "别在错的候选里挑「相对最好」的那条。")
        L.append("")
    L.append("## 建议")
    L.append("")
    coarse = not engine.startswith("qwen")
    if stats["verdict"] == "UNVERIFIED":
        L.append("**本次没验出来。** %s" % stats.get("verdict_reason", ""))
        L.append("")
        L.append("调小 `--window`（如 60）或调小 `--min-n` 让时段凑得够；"
                 "仍不行说明字幕密度不足以支撑分时段判据，"
                 "按 UNVERIFIED 交付，并在交付说明里写明「未验时间轴」。")
    elif stats["verdict"] == "PASS":
        L.append("对齐在阈值内，无需改时间轴。")
        if coarse:
            L.append("")
            L.append("> 提醒：whisper 的 word timestamp 带 ±0.15s 抖动，本判据只能排除"
                     "「>0.5s 的粗错」。若下游仍反馈偏轴，换 `--engine qwen` 复测，"
                     "别把这条 PASS 当成「亚 0.3s 级也对」。")
    elif coarse:

        L.append("窗间极差 %.2f s 超过 whisper 阈值，但**先别改**——whisper 引擎的"
                 "极差在 0.3~0.5s 区间几乎全是噪声（实测从未改动过的集也有 0.30s）。"
                 % stats["window_span"])
        L.append("")
        L.append("下一步：换 `--engine qwen` 复核。qwen 判出 >0.3s 才算真漂移。")
    elif abs(stats["drift"]) > 0.5 and stats["mad"] < 0.6:
        L.append("线性漂移 %s s 明显，可先线性补偿、复测：" % _fmt(stats["drift"], 2))
        L.append("")
        L.append("```bash")
        L.append("python align_patch.py --sub %s --slope %+.6f --write"
                 % (os.path.basename(args.sub), stats["slope"]))
        L.append("```")
    else:
        L.append("非线性偏移（剪辑点阶跃）。按优先级：")
        L.append("")
        L.append("1. 有可信参考流 → `align_patch.py --ref <ref.ass>` 逐条重定时；")
        L.append("2. 无参考流 → `--json` 已输出曲线 spec，用 "
                 "`align_patch.py --spec <json>` 分段补偿。")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="字幕与音频的对齐审计")
    ap.add_argument("--sub", required=True, help="待审字幕（.ass/.srt）")
    ap.add_argument("--track", default=ac.TRACK_EN, help="ASS 轨道样式名（默认 英文）")
    ap.add_argument("--media", help="视频或音频（视频会自动抽 16k 单声道）")
    ap.add_argument("--asr-words", help="复用词级时间戳 json，跳过模型")
    ap.add_argument("--engine", choices=["whisper", "qwen"], default="whisper")
    ap.add_argument("--model", help="模型目录（whisper 默认 large-v3 / qwen 必填）")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--compare", action="append", default=[],
                    help="附带比对的候选基准（可多次），用于轴归属判定")
    ap.add_argument("--window", type=float, default=180.0, help="分时段窗长（秒）")
    ap.add_argument("--tol", type=float, default=None,
                    help="分时段中位极差阈值（秒）。默认按引擎取：qwen 0.3 / whisper 0.5")
    ap.add_argument("--min-n", type=int, default=5, help="时段最少样本数")
    ap.add_argument("--cache-dir", default=".subtitle-polish/align")
    ap.add_argument("--json", help="输出逐条明细 + 曲线 spec")
    ap.add_argument("--report", help="输出 md 报告")
    ap.add_argument("--write-credential", action="store_true",
                    help="写 <episode>.ts.json 凭据（PASS 和 FAIL 都写，供 timeline_gate 读）")
    ap.add_argument("--source-index", type=int, default=None,
                    help="用的哪条内嵌流下标（记进凭据，防拿错轴）")
    ap.add_argument("--source-title", default=None, help="该流的标题")
    ap.add_argument("--source-family", default=None,
                    help="轴族短标签，如 UK / US（判轴时由 #11 自动填，也可手填）")
    ap.add_argument("--credential-target", choices=["sub", "chosen"], default="sub",
                    help="凭据写给谁：sub=--sub 这份（默认）；chosen=判定的胜者（判轴时用）")
    ap.add_argument("--strict", dest="strict", action="store_true", default=True,
                    help="按判定返回退出码（默认开）")
    ap.add_argument("--no-strict", dest="strict", action="store_false",
                    help="永远 exit 0（仅本地调试，不要写进流程）")
    args = ap.parse_args()

    # 没有音频也没有词级缓存：这不是「跑失败了」，是「没验」，必须是 UNVERIFIED。
    # 旧版走 ap.error 直接崩，退出码是 2，与 FAIL 撞车，机器分不出两者。
    if not args.asr_words and not args.media:
        print("[x] 需要 --media 或 --asr-words 之一：没有音频就无法验轴。", file=sys.stderr)
        print("    只有字幕时的结构检查用 precheck_timeline.py（L0，秒级）。",
              file=sys.stderr)
        sys.exit(V.UNVERIFIED)

    rows = ac.load_rows(args.sub, args.track or None)
    if not rows:
        raise SystemExit("没读到字幕行：检查 --track（当前 %r）与文件" % args.track)

    # 1) 词级时间戳
    if args.asr_words:
        with open(args.asr_words, encoding="utf-8") as f:
            tokens = [tuple(x) for x in json.load(f)]
        engine = "asr-words:" + os.path.basename(args.asr_words)
        args.media_path = args.media or "(未提供音频)"
    else:
        args.media_path = ac.media_to_wav(args.media, args.cache_dir)
        if args.engine == "qwen":
            if not args.model:
                ap.error("--engine qwen 必须给 --model")
            tokens = tokens_qwen(args.media_path, rows, args.model)
            engine = "qwen3-forced-aligner"
        else:
            model = args.model or "large-v3"
            cache = os.path.join(
                args.cache_dir,
                "asr_words_%s.json" % os.path.splitext(os.path.basename(args.sub))[0])
            tokens, engine = tokens_whisper(args.media_path, model, cache, args.device)

    if not tokens:
        raise SystemExit("词级时间戳为空，无法审计")

    # 阈值按引擎取：whisper 的 word timestamp 本身带 ±0.15s 抖动，
    # 实测「从未改过」的集也有 0.30s 窗间极差，硬卡 0.3 会全红。
    if args.tol is not None:
        tol = args.tol
    else:
        tol = 0.3 if engine.startswith("qwen") else 0.5

    # 2) 统计
    pairs = ac.align_anchors(rows, tokens)
    if len(pairs) < 10:
        raise SystemExit("锚点不足（%d 条）：文本与音频可能不是同一语种/版本" % len(pairs))
    stats = ac.summarize(pairs, args.window, tol, args.min_n)
    print_summary(os.path.basename(args.sub), stats, len(rows), engine)

    # 3) 轴归属 —— 判的是「哪条可信」，不是「哪条最小」
    compare = []
    compare_lookup = {}
    for ref in args.compare:
        ref_rows = ac.load_rows(ref, args.track or None)
        if not ref_rows:
            ref_rows = ac.load_rows(ref, None)
        rp = ac.align_anchors(ref_rows, tokens)
        if len(rp) < 10:
            print("  [skip] %s 锚点不足" % os.path.basename(ref))
            continue
        cst = ac.summarize(rp, args.window, tol, args.min_n)
        compare.append((os.path.basename(ref), cst))
        compare_lookup[os.path.basename(ref)] = cst
        print("  vs %-28s 中位 %s  MAD %.3f  斜率 %+.6f  全长 %s s  %s"
              % (os.path.basename(ref), _fmt(cst["median"]), cst["mad"],
                 cst["slope"], _fmt(cst["drift"], 2), cst["verdict"]))

    axis_res = None
    label_path = {os.path.basename(args.sub): args.sub}
    for _p in args.compare:
        label_path[os.path.basename(_p)] = _p
    if compare:
        cands = [{"label": os.path.basename(args.sub), "mad": stats["mad"],
                  "ok": stats["ok"], "n_pairs": stats["n_pairs"]}]
        cands += [{"label": lb, "mad": c["mad"], "ok": c["ok"],
                   "n_pairs": c["n_pairs"]} for lb, c in compare]
        axis_res = ax.adjudicate(cands)
        print("\n[axis] " + ax.render(axis_res).strip())
        if axis_res["chosen"] and axis_res["chosen"] != os.path.basename(args.sub):
            print("  → 应当使用 **%s**，当前 --sub 这条不是同轴的。" % axis_res["chosen"])

    # 4) 落盘
    if args.report:
        os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
        text = build_report(args, stats, len(rows), engine, compare, axis_res)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("\n[report] %s" % args.report)

    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        keep, _ = ac.robust_reject(pairs)
        spec, base, fdiag = ac.spec_from_pairs([(p[0], p[1]) for p in keep])
        if fdiag["verdict"] != "FIT_OK":
            print("[!] 拟合被拒：%s" % fdiag.get("reason", ""), file=sys.stderr)
        # 判 PASS 的集不给曲线：残余多是噪声，拟合出的曲线没有物理意义，
        # 反被误用会平白制造偏移。
        payload = {
            "sub": os.path.abspath(args.sub),
            "engine": engine,
            "stats": stats,
            "pairs": [[round(x, 3), round(y, 4)] for x, y, _ in pairs],
            # 只有 FAIL 才给曲线。PASS 的残余是噪声；UNVERIFIED 是没有判据，
            # 两种都不该让下游拿到一条可以施加上去的曲线。
            "curve": spec if stats["verdict"] == "FAIL" else None,
            "curve_base": round(base, 4) if stats["verdict"] == "FAIL" else 0.0,
            "curve_applicable": stats["verdict"] == "FAIL" and spec is not None,
            "fit": fdiag,
            "verdict": stats["verdict"],
            "axis": axis_res,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        tail = ("（含 curve spec，可直接喂 align_patch --spec）"
                if stats["verdict"] == "FAIL"
                else "（判 %s，不输出曲线）" % stats["verdict"])
        print("[json]   %s  %s" % (args.json, tail))

    # 5) 凭据：PASS 与 FAIL 都写。
    #    只写 PASS 的话，FAIL 在 gate 眼里会退化成「没有凭据」，分不出
    #    「验过、不对」和「没验过」——那正是 #10 要消灭的二义性。
    if args.write_credential:
        # 默认给 --sub 写（「我让你审的这份是不是对的」）；
        # --credential-target chosen 时给判定出的胜者写（「这一集的轴定在哪条流上」）。
        # 两者不能混：拿别的文件的 PASS 去给错轴的文件背书是最糟的假绿。
        cred_sub, cred_stats = args.sub, stats
        if args.credential_target == "chosen" and axis_res and axis_res.get("chosen"):
            c = axis_res["chosen"]
            if c != os.path.basename(args.sub) and c in label_path:
                cred_sub = label_path[c]
                cred_stats = dict(compare_lookup[c])
                print("[cred]   目标改为判定胜者：%s" % os.path.basename(cred_sub))
        stats = cred_stats if cred_sub != args.sub else stats
        # source 优先取判定出的胜者，其次取显式参数，最后从文件名反解。
        # 「--source-index 靠人回忆着填」等于凭据本身没被验证过。
        src_file = (axis_res or {}).get("chosen") or os.path.basename(args.sub)
        tag = ax.parse_stream_tag(src_file)
        data = cred.build(
            cred_sub, stats, engine,
            media=args.media if args.media and not args.media.startswith("(") else None,
            source={"kind": "embedded_stream" if tag["index"] is not None else "unknown",
                    "index": (args.source_index if args.source_index is not None
                              else tag["index"]),
                    "title": args.source_title or src_file,
                    "family": args.source_family or tag["family"],
                    "sdh": tag["sdh"]},
            cross_checked=bool(axis_res and axis_res.get("cross_checked")),
        )
        data["axis"]["total"] = len(rows)
        p = cred.save(cred_sub, data)
        print("[cred]   %s  verdict=%s" % (p, data["axis"]["verdict"]))

    code = V.from_verdict(stats["verdict"])
    # 轴判定比单文件判定更「上层」：主文件 FAIL 是 2，但若多条候选无法区分，
    # 说明不知道该信谁，必须报 AMBIGUOUS(4) 让人来看，不能当成「修一下就好」。
    if axis_res and axis_res["code"] == V.AMBIGUOUS and code == V.PASS:
        code = V.AMBIGUOUS
    if args.strict:
        sys.exit(code)
    print("\n[!] --no-strict：判定为 %s，但按调试模式返回 0。" % V.label(code))


if __name__ == "__main__":
    main()
