# -*- coding: utf-8 -*-
"""extract_slice.py — 切割 + 文本提取。

ass + srt -> 按 srt 块序号切，~700 块/份 + 100 块 overlap。
每份格式（一 block 一行）:
  <srt_id> | <ass_time> | <英文> | <中文> | <注释>
头注列异常标记。

用法:
  python extract_slice.py <ass> <srt> [--out DIR] [--blocks N] [--overlap N]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# 让脚本能 import 同级 lib（直接运行时）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ass_srt_pair import (
    pair_files, pair, TRACK_EN, TRACK_ZH, TRACK_NOTE,
)
from lib.time_fmt import seconds_to_ass


DEFAULT_BLOCKS = 700
DEFAULT_OVERLAP = 100

# C2（M4）：非空率下限。低于它直接 abort，不写切片。
#
# 起因：R1 曾因切片全空作废重跑 11 次审计。全空的切片**不会报错**——它只是
# 一堆 `<id> | <time> |  |  | ` 的空行，subagent 读到的是「这段没有对白」，
# 于是整轮审计基于空气做出结论，报告上还写着「本轮已审」。
MIN_NONEMPTY_RATE = 0.5


def nonempty_rate(paired) -> tuple:
    """(非空块数, 总块数, 比率)。「非空」= 英文或中文至少一侧有内容。"""
    total = len(paired)
    if total == 0:
        return 0, 0, 0.0
    n = sum(1 for pb in paired
            if (pb.english or "").strip() or (pb.chinese or "").strip())
    return n, total, n / total


def assert_not_empty(paired, ass_path: str, srt_path: str,
                     label: str = "") -> None:
    """空切片门禁：全空或非空率过低时 abort（C2 / M4）。

    **必须在写任何切片之前调**。写出来再检查，等于已经把空切片留给下一道工序了。
    """
    n, total, rate = nonempty_rate(paired)
    if total == 0:
        raise SystemExit(
            f"[!] {label} 配对结果为 0 块（srt={srt_path}）\n"
            f"    这不是「提词器段落」，是根本没配上。")
    if n == 0 or rate < MIN_NONEMPTY_RATE:
        raise SystemExit(
            f"[!] {label} nonempty={n}（{total} 块里 {n} 块匹配到英文，"
            f"非空率 {rate:.0%} < {MIN_NONEMPTY_RATE:.0%}）\n"
            f"    这通常不是「提词器段落」，先查三件事：\n"
            f"      1. 时间轴容差（默认 TIME_TOLERANCE=0.5s）是否小于实际漂移\n"
            f"      2. 中英轨是否错位（跑 structure_check.py --ass {ass_path}）\n"
            f"      3. 该段是否真的无对白（抽 3 个块人工对照视频）\n"
            f"    **不要在此基础上继续审计**：空切片会让整轮结论基于空气，"
            f"而报告上看不出异常。")


def slice_blocks(paired, total_blocks: int, blocks_per: int, overlap: int):
    """按 srt_id 切片，返回 [(start, end, [blocks]), ...]。"""
    if total_blocks == 0:
        return []
    step = max(1, blocks_per - overlap)
    slices = []
    start = 0
    while start < total_blocks:
        end = min(start + blocks_per, total_blocks)
        slices.append((start, end))
        if end >= total_blocks:
            break
        start += step
    return slices


def format_block_line(pb) -> str:
    """一 block 一行。"""
    english = pb.english or ""
    chinese = pb.chinese or ""
    note = pb.note or ""
    return f"{pb.srt_id} | {pb.ass_time} | {english} | {chinese} | {note}"


def write_slice(out_dir: str, stem: str, idx: int, start: int, end: int,
                paired, ass_only_in_range) -> str:
    """写一份切片文件。返回路径。"""
    path = os.path.join(out_dir, f"{stem}_p{idx}.txt")
    with open(path, "w", encoding="utf-8") as f:
        # 头注
        f.write(f"# slice {idx}: srt_id {start+1}-{end} (ass Dialogue index 0-based)\n")
        anomalies_in_slice = []
        for pb in paired[start:end]:
            if pb.anomalies:
                anomalies_in_slice.append(
                    f"#   {pb.srt_id}: {', '.join(pb.anomalies)}"
                )
        if anomalies_in_slice:
            f.write("# anomalies:\n")
            f.write("\n".join(anomalies_in_slice) + "\n")
        # 异常：该范围内 ass 有 srt 无
        if ass_only_in_range:
            f.write(f"# ASS_HAS_SRT_NONE ({len(ass_only_in_range)} 行未配对):\n")
            for ab in ass_only_in_range[:50]:
                f.write(f"#   {ab.start_raw} [{ab.track}] {ab.text[:60]}\n")
            if len(ass_only_in_range) > 50:
                f.write(f"#   ... and {len(ass_only_in_range)-50} more\n")
        f.write("\n")
        # blocks
        for pb in paired[start:end]:
            f.write(format_block_line(pb) + "\n")
    return path


def run(ass_path: str, srt_path: str, out_dir: str,
        blocks_per: int = DEFAULT_BLOCKS, overlap: int = DEFAULT_OVERLAP) -> list:
    """主流程。返回切片文件路径列表。"""
    ass_blocks, srt_blocks = pair_files(ass_path, srt_path)
    if not srt_blocks:
        print(f"[!] SRT 解析为空: {srt_path}", file=sys.stderr)
        return []
    paired, ass_only = pair(ass_blocks, srt_blocks)
    total = len(paired)
    print(f"[*] {ass_path}")
    print(f"    srt blocks: {total}, ass dialogues: {len(ass_blocks)}, ass_only: {len(ass_only)}")

    # C2：门禁在建目录、写文件之前。先写再查，空切片就已经交到下一道工序手上了。
    ne, _, rate = nonempty_rate(paired)
    print(f"    nonempty: {ne}/{total}（{rate:.0%}）")
    assert_not_empty(paired, ass_path, srt_path,
                     label=os.path.basename(ass_path))

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(ass_path))[0]
    # 简化 stem：剧集命名 s01e0X 取 e0X（与 id 空间 shortname 一致）；否则用完整 stem
    short = stem
    m = re.search(r"s0?(\d+)\s*e0?(\d+)", stem, re.I)
    if m:
        short = f"e{m.group(2).zfill(2)}"
    # 单文件/非剧集场景直接用完整 stem

    slices = slice_blocks(paired, total, blocks_per, overlap)
    out_paths = []
    for i, (start, end) in enumerate(slices, 1):
        # 该范围内 ass_only（ass 行未配对）：近似按时间在 [start,end] 的 srt 范围
        # 简化：ass_only 全局输出到每个切片头注不合适，只放第一个切片
        ass_only_range = ass_only if i == 1 else []
        p = write_slice(out_dir, short, i, start, end, paired, ass_only_range)
        out_paths.append(p)
        print(f"    slice {i}: srt_id {start+1}-{end} -> {os.path.basename(p)}")
    return out_paths


def main():
    ap = argparse.ArgumentParser(description="ass+srt -> 按 srt 块切片")
    ap.add_argument("ass", help="ass 文件路径")
    ap.add_argument("srt", help="srt 文件路径")
    ap.add_argument("--out", default=".subtitle-polish/slices", help="输出目录")
    ap.add_argument("--blocks", type=int, default=DEFAULT_BLOCKS, help="每份块数")
    ap.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP, help="overlap 块数")
    args = ap.parse_args()
    run(args.ass, args.srt, args.out, args.blocks, args.overlap)


if __name__ == "__main__":
    main()
