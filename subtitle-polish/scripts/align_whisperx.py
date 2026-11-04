# -*- coding: utf-8 -*-
"""align_whisperx.py — 用 whisperX 的 wav2vec2 对齐器对**现成字幕文本**做强制对齐。

这是「双对齐器时间戳互证」的 whisper 一侧：输入是同一份英文轨文本 + 同一段
音频，输出词级时间戳缓存（供 `align_audit.py --asr-words-b` 读取）。它**不是
转录**：不跑 ASR、不产生第二份文本，只把已有文本钉到音频上。

## 为什么用「整段一个 segment」

whisperX 默认按字幕每行的 start/end 切片再逐行对齐。字幕本来就可能偏，
按它切片等于用待验的时间戳去圈音频——偏得越多，越会把词对齐到错误的
位置，最后一圈回来只会「自证清白」。所以这里把整段音频作为一个 segment，
文本按行拼接后整体对齐；`whisperx.align` 会按句切分输出，但时间戳来自同一次
全局对齐，不再受字幕行时间约束。

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
    args = ap.parse_args()

    rows = load_rows(args.sub, args.track)
    if not rows:
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

    if args.start is not None or args.end is not None:
        a = args.start or 0.0
        z = args.end if args.end is not None else max(r["end"] for r in rows)
        rows = [r for r in rows if a <= r["start"] < z]
    if not rows:
        print("[!] 指定区间内没有字幕行", file=sys.stderr)
        return 2

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

    # 整段一个 segment：文本按行拼接，时间覆盖整段音频。
    a = args.start if args.start is not None else 0.0
    if args.end is not None:
        z = args.end
    else:
        z = max(r["end"] for r in rows)
    full = " ".join(r["text"] for r in rows)

    t1 = time.time()
    result = whisperx.align(
        [{"start": float(a), "end": float(z), "text": full}],
        model, meta, args.audio, device=device, return_char_alignments=False)
    align_s = time.time() - t1

    words = []
    for seg in result.get("segments") or []:
        for w in (seg.get("words") or []):
            text = (w.get("word") or "").strip()
            if not text or w.get("start") is None or w.get("end") is None:
                continue
            words.append({"start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3),
                          "text": text,
                          "score": w.get("score")})

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
        "mode": "whole_audio_single_segment",
        "elapsed_s": {"load_model": round(load_s, 2),
                      "align": round(align_s, 2),
                      "total": round(time.time() - t0, 2)},
        "words": words,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("[whisperx] %s  device=%s  words=%d  load %.1fs  align %.1fs  -> %s"
          % (args.model_name, device, len(words), load_s, align_s, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
