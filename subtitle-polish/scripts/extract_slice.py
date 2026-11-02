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

# A1（issue v1.15）：未配上率上限。
#
# 与 MIN_NONEMPTY_RATE 不是同一个判据，别合并：
#   非空率  低于 50%  = 「这份切片基本是空的」→ 整份作废
#   未配上率 高于 10% = 「这份切片大部分是好的，但有相当一批块根本没配上」
# 后者更隐蔽：切片看起来正常，只有零星几行是空的，审计员读到会当成「这几行漏译了」
# 而去补内容。S06E02 的 38 条假漏译就是从 45 行空单元格来的（5.2%），
# 当时没有这条判据，切片照常交给了子代理。
MAX_UNPAIRED_RATE = 0.10

# 旧切片归档目录名。重建切片时，如果 --out 指向的目录里已有别的切片，
# 不做原地覆盖，整目录改名为 <out>_stale_<时间戳>。
STALE_SUFFIX = "_stale"

# 未配上的两种形态。**两者都算「未配上」，都要过门禁，但处置完全不同**，
# 所以分开统计、分开报（A1 第二版修正）：
#   PAIRING_OUT_OF_TOLERANCE → 轴错位。ASS 里有内容，只是起点差超了容差窗。
#                              该放宽容差或先做轴校准；**补译是错的**。
#   PAIRING_FAILED           → 真的没有对应行。素材不同版 / 轨缺失；该换素材。
# 只统计后者的门禁等于形同虚设——S06E02 全片 47 条未配上，**全部**是前者，
# 一条后者都没有。
PAIRING_TAGS = ("PAIRING_FAILED", "PAIRING_OUT_OF_TOLERANCE")


def _pairing_tag(pb):
    """该块命中的未配上标记前缀；都未命中返回 ""。"""
    for a in (pb.anomalies or []):
        for tag in PAIRING_TAGS:
            if a.startswith(tag):
                return tag
    return ""


def pairing_failed_ids(paired, tags=PAIRING_TAGS) -> list:
    """未配上的 srt_id 列表（默认两种形态都算）。"""
    want = (tags,) if isinstance(tags, str) else tuple(tags)
    return [pb.srt_id for pb in paired
            if _pairing_tag(pb) in want]


def pairing_offset(pb):
    """从 PAIRING_OUT_OF_TOLERANCE(off=+0.69s) 里取偏移秒数；非该形态返回 None。"""
    for a in (pb.anomalies or []):
        if a.startswith("PAIRING_OUT_OF_TOLERANCE"):
            m = re.search(r"off=([+-]?[\d.]+)s", a)
            if m:
                return float(m.group(1))
    return None


def _pairing_breakdown(paired) -> str:
    """一行统计：两种形态各多少条、超容差的偏移区间。"""
    oot = [p for p in paired if _pairing_tag(p) == "PAIRING_OUT_OF_TOLERANCE"]
    hard = [p for p in paired if _pairing_tag(p) == "PAIRING_FAILED"]
    parts = []
    if oot:
        offs = [abs(x) for x in (pairing_offset(p) for p in oot) if x is not None]
        rng = ("（偏移 %.2f~%.2f s）" % (min(offs), max(offs))) if offs else ""
        parts.append("超容差 %d 条%s" % (len(oot), rng))
    if hard:
        parts.append("无对应行 %d 条" % len(hard))
    return " + ".join(parts)


def assert_pairing_ok(paired, ass_path: str, srt_path: str,
                      label: str = "") -> None:
    """未配上率门禁（A1 / issue v1.15）。

    **必须在写任何切片之前调**，与 assert_not_empty 同一个位置、同一个理由：
    写出去再检查，坏切片已经在下一道工序手上了。
    """
    bad = pairing_failed_ids(paired)
    total = len(paired)
    if not total:
        return
    rate = len(bad) / total
    if rate <= MAX_UNPAIRED_RATE:
        return
    sample = ", ".join(str(i) for i in bad[:20])
    more = f" …（共 {len(bad)} 条）" if len(bad) > 20 else ""
    raise SystemExit(
        f"[!] {label} 未配上 {len(bad)}/{total} 块（{rate:.1%} > "
        f"{MAX_UNPAIRED_RATE:.0%}）：{_pairing_breakdown(paired)}\n"
        f"    srt_id: {sample}{more}\n"
        f"    这不是「这些行漏译了」——这些块的英文和中文列都是空的。\n"
        f"    若把切片交下去，审计员会看到空单元格并报成「译文缺失」，\n"
        f"    然后去补根本不存在的内容（S06E02 的 38 条假漏译就是这么来的）。\n"
        f"    先看是哪种形态再动手：\n"
        f"      · **超容差**（切片头注带 off=±N.NNs）：ASS 里有这句，只是起点差\n"
        f"        超出 ±0.5s。这是**轴**的问题——跑 align_audit.py 看是不是连续\n"
        f"        漂移，或先对齐时间轴再切。放宽 TIME_TOLERANCE 是最后手段，\n"
        f"        因为它会让相邻块互相抢行。\n"
        f"      · **无对应行**：ASS 里没有这段内容。查是不是不同剪辑版 / 缺轨。\n"
        f"    两类都**不要靠补译绕过**。\n"
        f"    另可跑 structure_check.py --ass {ass_path} 查中英轨是否本身错位。")


def archive_stale(out_dir: str) -> str:
    """把 out_dir 里已有的切片整体归档，返回归档后的路径（没有旧文件则返回 ""）。

    为什么归档而不是删（issue v1.15 决定）：旧切片是**上次判定的依据**。
    报告里说「R7 p2 读了 slices_v2」，事后要回答「它当时到底看到什么」，
    靠的就是那份旧文件。删掉就等于把证据也删了。
    但也不能留在原路径——同一目录两套切片并存，是 A2 描述的那个事故：
    同一次审计里两个片的事实基准不同。

    所以：改名到 <out>_stale_<YYYYmmdd_HHMMSS>/，原位留空。
    """
    if not os.path.isdir(out_dir):
        return ""
    old = [f for f in os.listdir(out_dir) if f.endswith(".txt")]
    if not old:
        return ""
    import time
    stamp = time.strftime("%Y%m%d_%H%M%S")
    # 用 normpath 抹掉尾部斜杠，拼出来的名字才不会带 `//`。
    # 相对路径（如 `.subtitle-polish/slices`）时 dirname 非空；只有 out_dir 本身
    # 就在当前目录（`slices`）时 dirname 才是 ""，那时不需要 makedirs。
    base = os.path.normpath(out_dir)
    dst = f"{base}{STALE_SUFFIX}_{stamp}"
    n = 1
    while os.path.exists(dst):
        dst = f"{base}{STALE_SUFFIX}_{stamp}_{n}"
        n += 1
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    os.rename(out_dir, dst)
    print(f"[*] 旧切片 {len(old)} 份已归档 -> {dst}")
    print(f"    （不是删除：旧切片是上次判定的依据，事后取证要用）")
    return dst


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
        # anomalies 与 notes 分两段写：前者是需要动手的问题，后者只是知情。
        # 混成一段会让审计员在同一段里读到 495 条「切点不同」，把真问题淹掉
        # （issue #24 / bug #8 的现场就是如此）。
        anomalies_in_slice = []
        notes_in_slice = []
        for pb in paired[start:end]:
            if pb.anomalies:
                anomalies_in_slice.append(
                    f"#   {pb.srt_id}: {', '.join(pb.anomalies)}"
                )
            if getattr(pb, "notes", None):
                notes_in_slice.append(
                    f"#   {pb.srt_id}: {', '.join(pb.notes)}"
                )
        if anomalies_in_slice:
            f.write("# anomalies:\n")
            f.write("\n".join(anomalies_in_slice) + "\n")
        if notes_in_slice:
            # 明写「不需处理」，否则审计员看到 off=+3.08s 仍会当成要修轴。
            f.write("# notes（已配上，仅知情，不需处理）:\n")
            f.write("\n".join(notes_in_slice) + "\n")
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

    # A1（issue v1.15）：配对失败率也是门禁，同样必须在写之前。
    # 顺序有讲究：先查「整份是不是空的」，再查「零星配不上多少条」。
    # 反过来会让一份全空的切片先报「配对失败 100%」，把人引去查错方向。
    bad_ids = pairing_failed_ids(paired)
    if bad_ids:
        print(f"    pairing_failed: {len(bad_ids)}/{total}"
              f"（{len(bad_ids)/total:.1%}）{_pairing_breakdown(paired)}，srt_id: "
              f"{', '.join(str(i) for i in bad_ids[:20])}"
              f"{' …' if len(bad_ids) > 20 else ''}")
    assert_pairing_ok(paired, ass_path, srt_path,
                      label=os.path.basename(ass_path))

    # A2（issue v1.15）：重建即归档旧切片，不留两套并存。
    # 放在建目录之前——archive_stale 是 rename 整个目录，目录里有文件才动手。
    archive_stale(out_dir)

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
