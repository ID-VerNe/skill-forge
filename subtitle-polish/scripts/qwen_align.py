# -*- coding: utf-8 -*-
"""qwen_align.py — 在**独立的 qwen 环境**里跑 Qwen3-ForcedAligner，产出词级 JSON。

为什么要单独一个脚本：qwen_asr 依赖的 torch / transformers 版本与主环境、
与 whisperX 环境都可能冲突。把它关在自己的 venv 里、用子进程调用，主环境
就只读这份 JSON，不需要安装 qwen_asr（与 whisperX 对齐器的接法一致）。

本脚本自己不做统计、不改字幕：只负责「文本 + 音频 -> 词级时间戳」。
分块规划与跨档复核沿用 `align_audit` 的同一套逻辑，避免两份实现漂移。

用法（用 qwen 环境的解释器跑）:
  python qwen_align.py --sub ep.srt --wav ep.wav --model <模型目录> \
      --out qwen_words.json [--single-chunk] [--chunk 120] [--track 英文]

输出 JSON:
  {"engine": "...", "model": "...", "chunks": [c1, c2?],
   "runs": [[chunk, [[start, end, text], ...]], ...], "elapsed_s": 12.3}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import align_audit as aa                    # noqa: E402  同一套分块/对齐实现
from lib import align_core as ac            # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="独立环境里的 qwen 强制对齐（只产 JSON）")
    ap.add_argument("--sub", required=True, help="英文轨字幕（srt/ass）")
    ap.add_argument("--wav", required=True, help="已解码好的 wav")
    ap.add_argument("--model", required=True, help="Qwen3-ForcedAligner 模型目录")
    ap.add_argument("--out", required=True, help="输出词级 JSON")
    ap.add_argument("--track", default=None, help="ASS 轨道（如 英文）")
    ap.add_argument("--chunk", type=int, default=None, help="固定分块秒数")
    ap.add_argument("--single-chunk", action="store_true",
                    help="只跑主分块，不做跨分块复核（省一半时间）")
    ap.add_argument("--language", default="English")
    args = ap.parse_args(argv)

    rows = ac.load_rows(args.sub, args.track or None)
    if not rows:
        raise SystemExit("没读到字幕行：检查 --track 与文件")

    if args.single_chunk:
        c1 = args.chunk or aa.plan_chunk()[0]
        chunks = [c1]
        why = "--single-chunk，不做跨分块复核"
    else:
        c1, c2, why = aa.plan_chunks(args.chunk)
        chunks = [c1] + ([c2] if c2 else [])
    print("  分块规划：%s（%s）"
          % (" + ".join("%ds" % c for c in chunks), why), flush=True)

    t0 = time.time()
    runs = aa.tokens_qwen_dual(args.wav, rows, args.model, chunks,
                               language=args.language)
    elapsed = time.time() - t0

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    payload = {
        "engine": "qwen3-forced-aligner",
        "model": os.path.basename(os.path.normpath(args.model)),
        "chunks": [c for c, _ in runs],
        "runs": [[c, [[float(s), float(e), str(t)] for s, e, t in tk]]
                 for c, tk in runs],
        "elapsed_s": round(elapsed, 2),
        "plan": why,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.write("\n")
    print("  [out] %s（%d 档，%.2f s）"
          % (args.out, len(runs), elapsed), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
