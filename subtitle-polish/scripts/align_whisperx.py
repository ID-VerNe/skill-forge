# -*- coding: utf-8 -*-
"""align_whisperx.py — 用 whisperX 的 wav2vec2 对齐器对**现成字幕文本**做强制对齐。

这是「双对齐器时间戳互证」的 whisper 一侧：输入是同一份英文轨文本 + 同一段
音频，输出词级时间戳缓存（供 `align_audit.py --asr-words-b` 读取）。它**不是
转录**：不跑 ASR、不产生第二份文本，只把已有文本钉到音频上。

## 为什么不用「按字幕行切片」

whisperX 默认按字幕每行的 start/end 切片再逐行对齐。字幕本来就可能偏，
按它切片等于用待验的时间戳去圈音频——偏得越多，越会把词对齐到错误的
位置，最后一圈回来只会「自证清白」。所以这里按**固定时间网格**切窗
（默认按显存自适应，60~300 s），窗边界与字幕行无关，时间戳仍从同一次
全局对齐得来。

整集当一个 segment 在 8 GB 卡上会 OOM（实测 `Tried to allocate 24.02 GiB`），
因此默认分窗；`--window 0` 才是旧的整段行为。某个窗仍然 OOM 时会按时间
对半切重试，而不是让整集失败。

## 运行环境

whisperX 及其 wav2vec2 模型通常装在**独立环境**里（本机已有）。用那个环境的
解释器直接跑本脚本，产物落到仓库/工作目录，再由仓库侧 `align_audit.py` 读取：

  <whisperx-python> align_whisperx.py \
      --audio clip.wav --sub clip.en.srt --out wx_words.json \
      --model-name jonatasgrosman/wav2vec2-large-xlsr-53-english \
      --model-dir <hf-hub 缓存目录>

不要求把 whisperX 装进仓库的 Python 环境；本脚本只依赖 whisperx + pysubs2。

退出码：0 成功；2 输入非法或缺依赖。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def _rows_from_srt(path: str) -> list:
    import pysubs2

    subs = pysubs2.load(path, encoding="utf-8-sig")
    return [{"start": e.start / 1000.0, "end": e.end / 1000.0,
             "text": (e.text or "").replace("\\N", " ").strip()}
            for e in subs.events if (e.text or "").strip()]


def _rows_from_ass(path: str, track: str) -> list:
    import pysubs2

    subs = pysubs2.load(path, encoding="utf-8-sig")
    events = list(subs.events)
    picked = [e for e in events if (e.style or "").strip() == track]
    if not picked:      # 样式名不叫「英文」时，退回按字符集挑非中文行
        picked = [e for e in events
                  if not any("\u4e00" <= c <= "\u9fff" for c in (e.text or ""))]
    return [{"start": e.start / 1000.0, "end": e.end / 1000.0,
             "text": (e.text or "").replace("\\N", " ").strip()}
            for e in picked if (e.text or "").strip()]


def load_rows(path: str, track: str) -> list:
    if path.lower().endswith(".srt"):
        return _rows_from_srt(path)
    return _rows_from_ass(path, track)


def _vram_info(device: str, torch) -> dict:
    """显存快照：总量 / 起点空闲 / 窗口长度的选择依据。"""
    if device != "cuda" or not torch.cuda.is_available():
        return {"device": "cpu"}
    try:
        total = int(torch.cuda.get_device_properties(0).total_memory / (1 << 20))
        free = int(torch.cuda.mem_get_info()[0] / (1 << 20))
    except Exception:  # noqa: BLE001
        return {"device": "cuda"}
    return {"device": "cuda", "total_mib": total, "free_mib": free}


#: 峰值显存估计（对齐阶段）：常驻 1.8 GB + 21 MiB / 秒窗长。
#: 实测 8 GB 卡：60 s 窗峰值 2.72 GB，120 s 窗 4.29 GB。只用来挑窗长。
_MEM_BASE_MIB = 1800
_MEM_PER_SEC_MIB = 21.0

#: 只占空闲显存的一半。桌面程序会在跑的过程中涨（实测 120 s 窗峰值 4.29 GB、
#: 起点空闲 6.5 GB，仍被挤成 WDDM 溢出：单窗 5.5 s → 38 s，且不报错）。
_MEM_FRACTION = 0.5


def _estimate_mib(window: float) -> float:
    return _MEM_BASE_MIB + _MEM_PER_SEC_MIB * window


def _auto_window(device: str, torch) -> float:
    """按**当前空闲显存**挑窗口长度（秒）。

    wav2vec2 的注意力显存随窗长增长：整集单段会要 24 GiB，8 GB 卡上要么 OOM、
    要么被 WDDM 静默搬进系统内存（不报错、单窗从 5 s 涨到几十秒）。
    这里用「常驻 + 每秒钟显存」估峰值，再要求只占空闲显存的一半；真正的兜底
    是运行期 OOM 对半切重试（见 `align_rows`）。
    """
    if device != "cuda" or not torch.cuda.is_available():
        return 60.0
    try:
        free = torch.cuda.mem_get_info()[0] / float(1 << 20)
    except Exception:  # noqa: BLE001
        return 60.0
    budget = free * _MEM_FRACTION
    for w in (300.0, 240.0, 180.0, 120.0, 90.0, 60.0, 45.0):
        if _estimate_mib(w) <= budget:
            return w
    return 30.0


def _plan_windows(rows: list, a: float, z: float, window: float) -> list:
    """按时间网格把字幕行分窗；返回 [(lo, hi, rows)]。

    行按 **start** 归窗，不重叠，所以每个词只会出现一次。窗尾取
    max(网格边界, 本窗最后一行 end)，避免行尾被截断。
    """
    out = []
    i = 0
    n = len(rows)
    k = 0
    while i < n:
        lo = a + k * window
        if lo >= z:
            break
        hi = min(z, lo + window)
        chunk = [r for r in rows[i:] if lo <= r["start"] < hi]
        if not chunk:          # 该窗没有起始行，跳过（不让空 window 占时间）
            k += 1
            continue
        i += len(chunk)
        hi = min(z, max(hi, max(r["end"] for r in chunk)))
        out.append((lo, hi, chunk))
        k += 1
    return out


def _words_of(result: dict) -> list:
    words = []
    for seg in result.get("segments") or []:
        for w in (seg.get("words") or []):
            text = (w.get("word") or "").strip()
            if not text or w.get("start") is None or w.get("end") is None:
                continue
            words.append({"start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3),
                          "text": text, "score": w.get("score")})
    return words


def main() -> int:
    ap = argparse.ArgumentParser(
        description="whisperX wav2vec2 强制对齐（输入现成字幕文本，不跑 ASR）")
    ap.add_argument("--audio", required=True, help="音频或视频（16k 单声道最佳）")
    ap.add_argument("--sub", required=True, help="同一份英文轨（.srt/.ass）")
    ap.add_argument("--track", default="英文", help="ASS 英文轨样式名（默认 英文）")
    ap.add_argument("--out", required=True, help="词级时间戳 json 输出路径")
    ap.add_argument("--model-name",
                    default="jonatasgrosman/wav2vec2-large-xlsr-53-english",
                    help="wav2vec2 对齐模型名（本机缓存里已有的那个）")
    ap.add_argument("--model-dir", default=None,
                    help="模型缓存目录（HF hub 格式）；与 --model-name 配套")
    ap.add_argument("--language", default="en")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--start", type=float, default=None, help="只对齐该秒之后的音频")
    ap.add_argument("--end", type=float, default=None, help="只对齐该秒之前的音频")
    ap.add_argument("--window", type=float, default=None,
                    help="分窗长度（秒）。缺省按显存自适应；0 = 整段单 segment"
                         "（旧行为，长片会 OOM）")
    args = ap.parse_args()

    rows_all = load_rows(args.sub, args.track)
    if not rows_all:
        print("[!] 字幕里没有可用英文行：%s" % args.sub, file=sys.stderr)
        return 2
    try:
        import torch
        import whisperx
    except ImportError as e:
        print("[!] 需要 whisperX 环境（whisperx + torch）：%s" % e, file=sys.stderr)
        return 2

    # 控制台是 GBK 时，中文提示更容易乱码；这里只影响提示，不影响产物。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    a = args.start if args.start is not None else 0.0
    z = args.end if args.end is not None else max(r["end"] for r in rows_all)
    rows = [r for r in rows_all if a <= r["start"] < z]
    if not rows:
        print("[!] 指定区间内没有字幕行", file=sys.stderr)
        return 2

    # 窗长必须在**加载模型之前**算：估算里的常驻量已经包含模型，用加载后的
    # 空闲显存会把模型算两遍，把 8 GB 卡压成 45 s 窗。
    vram = _vram_info(device, torch)
    window = args.window
    if window is None:
        window = _auto_window(device, torch)
    auto = args.window is None
    if window <= 0:
        window = max(z - a, 1.0)

    t0 = time.time()
    try:
        model, meta = whisperx.load_align_model(
            language_code=args.language, device=device,
            model_name=args.model_name, model_dir=args.model_dir,
            model_cache_only=bool(args.model_dir))
    except Exception as e:  # noqa: BLE001
        print("[!] 加载对齐模型失败：%s" % e, file=sys.stderr)
        return 2
    load_s = time.time() - t0

    # 音频只解码一次，逐窗复用：每次调用 whisperx.align 里面按 segment 的
    # [start,end) 切片，传整条数组不会把整集塞进显存。
    try:
        audio = whisperx.load_audio(args.audio)
    except Exception as e:  # noqa: BLE001
        print("[!] 读取音频失败：%s" % e, file=sys.stderr)
        return 2

    t1 = time.time()
    words = []
    win_log = []
    gpu = device == "cuda" and torch.cuda.is_available()

    def _peak_mib():
        """本窗峰值显存（分配器口径）；CPU 或不支持时返回 None。"""
        if not gpu:
            return None
        try:
            return int(round(torch.cuda.max_memory_allocated() / (1 << 20)))
        except Exception:  # noqa: BLE001
            return None

    def align_one(lo: float, hi: float, text: str):
        return whisperx.align(
            [{"start": float(lo), "end": float(hi), "text": text}],
            model, meta, audio, device=device, return_char_alignments=False)

    def align_rows(chunk: list, lo: float, hi: float, depth: int = 0) -> list:
        """对齐一个窗；显存不够就按时间对半切，而不是整段放弃。"""
        if not chunk or hi <= lo:
            return []
        text = " ".join(r["text"] for r in chunk)
        try:
            return _words_of(align_one(lo, hi, text))
        except RuntimeError as e:  # noqa: BLE001
            msg = str(e).lower()
            if "out of memory" not in msg and "alloc" not in msg:
                raise
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if depth >= 4 or len(chunk) <= 1 or (hi - lo) < 10:
                raise
            mid = (lo + hi) / 2.0
            left = [r for r in chunk if r["start"] < mid]
            right = [r for r in chunk if r["start"] >= mid]
            print("    [warn] OOM，窗 %.0f-%.0f 对半切（%d/%d 行）"
                  % (lo, hi, len(left), len(right)))
            return (align_rows(left, lo, mid, depth + 1)
                    + align_rows(right, mid, hi, depth + 1))

    wins = _plan_windows(rows, a, z, window)
    for idx, (lo, hi, chunk) in enumerate(wins, 1):
        tw = time.time()
        if gpu:
            try:
                torch.cuda.reset_peak_memory_stats()
            except Exception:  # noqa: BLE001
                pass
        ws = align_rows(chunk, lo, hi)
        sec = time.time() - tw
        words.extend(ws)
        win_log.append({"i": idx, "start": round(lo, 2), "end": round(hi, 2),
                        "rows": len(chunk), "words": len(ws),
                        "elapsed_s": round(sec, 2), "peak_mem_mib": _peak_mib()})
        print("  [%d/%d] %.0f-%.0fs  rows=%d words=%d  %.2fs  peak=%s MiB"
              % (idx, len(wins), lo, hi, len(chunk), len(ws), sec,
                 win_log[-1]["peak_mem_mib"]))

    words.sort(key=lambda w: (w["start"], w["end"]))
    align_s = time.time() - t1
    mode = "windowed" if window < (z - a) else "whole_audio_single_segment"

    payload = {
        "engine": "whisperx",
        "aligner": "wav2vec2",
        "model": args.model_name,
        "device": device,
        "language": args.language,
        "audio": os.path.basename(args.audio),
        "sub": os.path.basename(args.sub),
        "n_rows": len(rows),
        "n_words": len(words),
        "mode": mode,
        "window_s": round(window, 1),
        "window_auto": bool(auto),
        "vram": vram,
        "n_windows": len(win_log),
        "window_log": win_log,
        "elapsed_s": {"load_model": round(load_s, 2),
                      "align": round(align_s, 2),
                      "total": round(time.time() - t0, 2)},
        "words": words,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("[whisperx] %s  device=%s  mode=%s  window=%.0fs  windows=%d  "
          "words=%d  load %.1fs  align %.1fs  free=%sMiB  -> %s"
          % (args.model_name, device, mode, window, len(win_log), len(words),
             load_s, align_s, vram.get("free_mib", "-"), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
