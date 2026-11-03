# -*- coding: utf-8 -*-
"""derive_srt.py — 从 ASS 英文轨派生 SRT（无独立 SRT 源时的权威源入口）。

适用场景：英文轨本身就是 whisper 转录的权威英文，用户手上没有独立 .srt，
ASS 是唯一素材。派生只是把 ASS 里已有的英文轨转成管线认识的 SRT 容器，
不新写 ASR、不改 ASS。

派生物默认落在 `<work_dir>/derived/<stem>.srt`（不进成品目录、不改英文轨）。
同一份 ASS 反复派生逐字节相同（UTF-8 无 BOM、`\n` 换行、序号从 1 连续）。

用法:
  python derive_srt.py <ass> [--out PATH] [--work-dir .subtitle-polish]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ass_srt_pair import derive_srt_from_ass, derive_srt_path


def main():
    ap = argparse.ArgumentParser(description="从 ASS 英文轨派生 SRT")
    ap.add_argument("ass", help="含英文轨的 ASS 文件")
    ap.add_argument("--out", default="",
                    help="输出路径；省略则写到 <work-dir>/derived/<stem>.srt")
    ap.add_argument("--work-dir", default=".subtitle-polish",
                    help="工作目录（只接受 .subtitle-polish）")
    args = ap.parse_args()

    out = args.out or derive_srt_path(args.ass, args.work_dir)
    n = derive_srt_from_ass(args.ass, out)
    print(f"[*] 已从 ASS 英文轨派生 {n} 块 -> {out}")
    print("    （派生物只用于本管线，不改 ASS 英文轨、不进成品目录）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
