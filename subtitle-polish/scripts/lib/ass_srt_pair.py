# -*- coding: utf-8 -*-
"""ASS / SRT 解析与配对。

按 srt 块组织，配对 ass 的 Dialogue 行。时间戳模糊匹配 + 原文文本双校验。

暴露：
  parse_srt(path) -> List[SrtBlock]
  parse_ass(path) -> List[AssDialogue]   (用 pysubs2)
  pair(ass_blocks, srt_blocks) -> List[PairedBlock]
  pair_dirs(ass_dir, srt_dir, strip_suffix=...) -> List[(ass_path, srt_path)]
"""
from __future__ import annotations

import bisect
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

try:
    import pysubs2
except ImportError:
    raise SystemExit(
        "pysubs2 未安装。skill 应已自动安装；手动: pip install pysubs2"
    )

from .time_fmt import ass_to_seconds, srt_to_seconds

TIME_TOLERANCE = 0.5  # 秒，时间戳模糊匹配容差
TEXT_RATIO_THRESHOLD = 0.85  # 文本相似度阈值

# 容差窗外最近邻差值的上报上限（秒）。超过它就认为该块在 ASS 里
# 根本没对应内容（素材不同版 / 轨缺失），报「配对失败」而不是「错位 N 秒」。
# 30 s 足够覆盖连续漂移曲线的量级（S06E02 全长 869 块、最大差 1.92 s）。
MAX_REPORTABLE_OFFSET = 30.0

TRACK_EN = "英文"
TRACK_ZH = "中文"
TRACK_NOTE = "注释"

# 样式名 -> track 映射（容错各种写法）
STYLE_TRACK_MAP = {
    "英文": TRACK_EN, "eng": TRACK_EN, "english": TRACK_EN, "en": TRACK_EN,
    "中文": TRACK_ZH, "zh": TRACK_ZH, "chinese": TRACK_ZH, "cn": TRACK_ZH,
    "注释": TRACK_NOTE, "note": TRACK_NOTE, "notes": TRACK_NOTE,
    "comment": TRACK_NOTE, "comments": TRACK_NOTE,
}


def style_to_track(style: str) -> str:
    if not style:
        return ""
    key = style.strip().lower()
    if key in STYLE_TRACK_MAP:
        return STYLE_TRACK_MAP[key]
    # 中文样式名里带"英"判英文，带"中"判中文，带"注"判注释
    if "英" in style or "eng" in key:
        return TRACK_EN
    if "中" in style or "zh" in key or "chn" in key:
        return TRACK_ZH
    if "注" in style or "note" in key or "comment" in key:
        return TRACK_NOTE
    return style.strip()


def clean_ass_text(text: str) -> str:
    """去 ASS 标签 {\\be3} 等，去 \\N，合并空白。"""
    text = re.sub(r"\{.*?\}", "", text)
    text = text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_for_compare(text: str) -> str:
    """为文本相似度比较做归一化：去说话人/音效标记、去标点、小写、合并空白。"""
    text = re.sub(r"\{.*?\}", "", text)  # ASS 标签
    text = text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    # 去说话人标记 [Tom]、(Tom)、[tense sting] 等方括号/圆括号内容
    text = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", text)
    # 去前导连字符（对白标记）
    text = re.sub(r"^\s*[-—]+\s*", "", text)
    # 去标点
    text = re.sub(r"[，。！？；：、,.!?;:\"'…·\-—]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


@dataclass
class SrtBlock:
    index: int           # 1-based srt 序号
    start: float        # 秒
    end: float
    start_raw: str      # 原始 srt 时间串
    end_raw: str
    text: str           # 原文（保留多行，用 \n）

    def english_text(self) -> str:
        """取英文部分（srt 若双语，取非中文行；纯英则全部，但排除纯音效/说话人标记行）。"""
        lines = [ln.strip() for ln in self.text.split("\n") if ln.strip()]
        en_lines = []
        for ln in lines:
            if any("一" <= c <= "鿿" for c in ln):
                continue  # 中文行跳过
            # 去说话人标记 [Tom] / (Tom)
            cleaned = re.sub(r"^\s*[\[\(][^\]\)]*[\]\]]\s*", "", ln)
            cleaned = cleaned.strip()
            if cleaned:
                en_lines.append(cleaned)
        return " ".join(en_lines)

    def is_sound_effect_only(self) -> bool:
        """整块是否纯音效/动作提示（无对白）。如 [upbeat rock music]、[clicks]。"""
        en = self.english_text()
        # english_text 已去说话人标记，剩下的若为空，说明整块只有音效
        return not en


@dataclass
class AssDialogue:
    """一条 ASS Dialogue 行。"""
    start: float        # 秒
    end: float
    start_raw: str      # ASS 原始时间串
    end_raw: str
    style: str          # 样式名
    track: str          # 英文/中文/注释（映射后）
    text: str           # 清洗后的文本（去标签）
    raw_line: str       # 原始整行（用于重写）
    text_field: str     # 原始 text 字段（含标签，用于精确替换）
    # Dialogue 字段索引：Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text


@dataclass
class PairedBlock:
    srt_id: int
    srt_start: float
    srt_end: float
    ass_time: str       # 展示用 "start-end" ASS 串
    english: str = ""
    chinese: str = ""
    note: str = ""
    anomalies: List[str] = field(default_factory=list)
    # 用于修复脚本定位：track -> AssDialogue
    lines: dict = field(default_factory=dict)  # track -> List[AssDialogue]


def parse_srt(path: str) -> List[SrtBlock]:
    """解析 SRT，返回块列表。兼容 BOM。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    except FileNotFoundError:
        raise SystemExit(f"找不到 SRT 文件: {path}")

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", content)
    result = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        # 找时间戳行
        ts_idx = None
        for i, ln in enumerate(lines):
            if "-->" in ln:
                ts_idx = i
                break
        if ts_idx is None:
            continue
        ts = lines[ts_idx].strip()
        m = re.match(r"(\S+)\s*-->\s*(\S+)", ts)
        if not m:
            continue
        start_raw, end_raw = m.group(1), m.group(2)
        try:
            start = srt_to_seconds(start_raw)
            end = srt_to_seconds(end_raw)
        except Exception:
            continue
        text = "\n".join(lines[ts_idx + 1:]).strip()
        # index 行（ts_idx 之前第一行若是数字）
        idx = len(result) + 1
        if ts_idx > 0 and lines[0].strip().isdigit():
            idx = int(lines[0].strip())
        result.append(SrtBlock(
            index=idx, start=start, end=end,
            start_raw=start_raw, end_raw=end_raw, text=text,
        ))
    return result


def _ass_time_str(seconds: float) -> str:
    from .time_fmt import seconds_to_ass
    return seconds_to_ass(seconds)


def parse_ass(path: str) -> List[AssDialogue]:
    """解析 ASS，返回 Dialogue 列表。用 pysubs2 兼容 BOM/缺 [Events] 头。"""
    try:
        subs = pysubs2.load(path, encoding="utf-8")
    except Exception:
        try:
            subs = pysubs2.load(path, encoding="utf-8-sig")
        except Exception as e:
            raise SystemExit(f"解析 ASS 失败: {path} ({e})")

    result = []
    for e in subs.events:
        if not e.text or not e.text.strip():
            continue
        # 重新构造原始行（用于重写）
        # 注意 pysubs2 的 plaintext 已去标签；text 是带标签原始
        text_field = e.text
        cleaned = clean_ass_text(text_field)
        if not cleaned:
            continue
        style = e.style or ""
        track = style_to_track(style)
        # 重建 raw_line（pysubs2 不直接暴露，自己拼）
        # pysubs2 的 start/end 是毫秒，转秒
        start_sec = e.start / 1000.0
        end_sec = e.end / 1000.0
        start_raw = _ass_time_str(start_sec)
        end_raw = _ass_time_str(end_sec)
        raw_line = (
            f"Dialogue: 0,{start_raw},{end_raw},{style},,0,0,0,,{text_field}"
        )
        result.append(AssDialogue(
            start=start_sec,
            end=end_sec,
            start_raw=start_raw,
            end_raw=end_raw,
            style=style,
            track=track,
            text=cleaned,
            raw_line=raw_line,
            text_field=text_field,
        ))
    return result


def _text_ratio(a: str, b: str) -> float:
    """文本相似度（0-1）。归一化后比较。"""
    a = normalize_for_compare(a)
    b = normalize_for_compare(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _match_by_time_and_text(srt_block: SrtBlock, ass_blocks: List[AssDialogue]) -> List[AssDialogue]:
    """时间戳模糊匹配 + 文本双校验，返回匹配的 ass 行。

    同 track 多候选时只留时间戳最近的（实测相邻 srt 块间隔 < 0.5s 容差时，
    ±0.5s 窗会把相邻 ass 行都包进来，导致 MULTI_SAME_LANG 误配 + 切片
    `⏎` 重复行误导 agent 误判物理重复）。多个候选时间戳距离相同时（真正的
    同时间戳重复行）全部保留，让 pair() 标 MULTI_SAME_LANG —— 那才是真
    生产缺陷，不该被容差窗误配产生，也不该被这里误删。
    """
    candidates = []
    for ab in ass_blocks:
        if abs(ab.start - srt_block.start) <= TIME_TOLERANCE:
            candidates.append(ab)
    if not candidates:
        return []
    srt_en = srt_block.english_text()
    is_sfx = srt_block.is_sound_effect_only()
    matched = []
    for ab in candidates:
        if ab.track == TRACK_EN:
            if is_sfx:
                # srt 这块是纯音效，ass 英文行若也是音效/空对白，按时间配即可
                matched.append(ab)
                continue
            ratio = _text_ratio(srt_en, ab.text)
            if ratio >= TEXT_RATIO_THRESHOLD:
                matched.append(ab)
            elif any("一" <= c <= "鿿" for c in ab.text):
                # 英文行写着中文（轨覆盖），配对但 anomaly 在 pair() 标
                matched.append(ab)
            elif ratio >= 0.6:
                # 时间戳对上但文本仅部分相似（ass 可能人工调轴 / 轻微差异），
                # 仍配对但 pair() 会标 anomaly 提示时间/文本偏移
                matched.append(ab)
            # 文本对不上且非覆盖且相似度过低 -> 不配对，可能是错位
        else:
            # 中文/注释行，时间戳对上就算配对
            matched.append(ab)
    # 同 track 多候选 → 只留时间戳距离最近的；距离相同的全留（真重复行）。
    # 避免 ±0.5s 容差在相邻 srt 块（实测 361/362 隔 390ms）上把两条中文行
    # 都配到两个 srt 块、切片出现"是的 ⏎ 它变硬了"假重复。
    by_track = {}
    for ab in matched:
        by_track.setdefault(ab.track, []).append(ab)
    deduped = []
    for trk, abs_ in by_track.items():
        abs_.sort(key=lambda x: abs(x.start - srt_block.start))
        if not abs_:
            continue
        best_d = abs(abs_[0].start - srt_block.start)
        deduped.extend(ab for ab in abs_ if abs(ab.start - srt_block.start) == best_d)
    return deduped


def _nearest_ass_offset(srt_block: SrtBlock, ass_blocks: List[AssDialogue]):
    """容差窗外最近的 ass 起点与 srt 起点之差（秒）。没有任何 ass 行时返回 None。

    只用来**判断「到底是错位还是缺失」**，不参与配对决策——配对仍是
    `_match_by_time_and_text` 的事，这里多出来的信息只写进异常标记，
    不改任何一行是否被配上（改配对行为要连带改 A5 定位器，是批次 F 的事）。

    为什么按时间轴取最近邻而不是按索引：两轨条数不同（S06E02 是
    ass 1738 / srt 869，ass 有中英两条各 869 条但有 95 条 ass_only），
    同索引根本不指向同一句台词。

    阈值 MAX_REPORTABLE_OFFSET 的用处：差 30 秒的「最近邻」说明这一块
    在 ASS 里压根没有对应内容，那是缺失不是错位。超过就不报偏移量，
    让调用方走 PAIRING_FAILED 分支。
    """
    if not ass_blocks:
        return None
    starts = sorted({b.start for b in ass_blocks})
    i = bisect.bisect_left(starts, srt_block.start)
    cands = [starts[j] for j in (i - 1, i) if 0 <= j < len(starts)]
    if not cands:
        return None
    near = min(cands, key=lambda x: abs(x - srt_block.start))
    off = near - srt_block.start
    if abs(off) > MAX_REPORTABLE_OFFSET:
        return None
    return off


def _monotonic_fallback(srt_blocks: List[SrtBlock],
                        ass_blocks: List[AssDialogue],
                        already: set) -> dict:
    """容差窗外的「顺序 + 文本」兜底配对：srt 块 -> 英文 ass 行。

    为什么需要：`_match_by_time_and_text` 只认 ±TIME_TOLERANCE 窗。当 ASS 与
    SRT 对**同一句**台词的起点相差 1~6 s（S06E02 实测集中在 4 处剪辑点，
    T 侧在剪接后把整段向后推），窗内没有候选，整块被判空 → 非空率跌到 43%、
    切片全废。这不是「漏译」，是**行边界 / 剪辑点分歧**，处置方式完全不同
    （不改文本、不改时间轴）。

    为什么不能简单放宽 TIME_TOLERANCE：相邻块间隔常在 0.3~0.5 s，放宽后
    相邻块会互相抢行，制造假重复。

    这里的做法：
      ① LCS 找文本一致的锚点，按出现次序对应（重复台词也按序对各的）；
      ② 锚点之间（含首尾）两段**条数相等**时才按序一一对应——这时顺序
         本身就是充分证据（S06E02 实测 869 vs 869，869 块文本全一致）；
      ③ 条数不等（真并块/拆块）才按位置比例对应，且要求文本比例达标，
         宁可留空也不硬配一句不相干的台词；
      ④ **同起点的多行不参与**（见下方 `_start_count` 段）：顺序映射的产物是
         「一块 -> 一行」，面对同起点 N 行只能挑一行、静默丢掉其余，
         会把 MULTI_SAME_LANG 这个真缺陷信号吃掉。

    返回 {srt_id: (en_row, zh_row)}；已由时间窗配上的块不参与。
    """
    srt_sorted = sorted(srt_blocks, key=lambda b: b.start)
    en_rows = sorted([r for r in ass_blocks if r.track == TRACK_EN],
                     key=lambda r: r.start)
    zh_rows = sorted([r for r in ass_blocks if r.track == TRACK_ZH],
                     key=lambda r: r.start)
    if not srt_sorted or not en_rows:
        return {}

    # 同起点的多行**不参与顺序映射**。理由：顺序映射的产物是「一个 srt 块 -> 一行」，
    # 面对同起点的 N 行它只能挑一行，剩下 N-1 行被静默丢掉；而 `pair()` 的
    # MULTI_SAME_LANG 判定恰恰依赖「同一个 matched 里同 track 有多行」——
    # 映射把多行压成一行，那条真重复就再也报不出来了
    # （tests/test_subtitle_polish_bugs.py 的 C2 实测：真同时间戳重复行
    # anomalies=[]，信号彻底消失）。
    #
    # 同起点多行是**生产缺陷**（该删的碎片行），删它全靠 MULTI_SAME_LANG，
    # 不能让一个只为「吸收行边界分歧」而生的兜底机制把它吃掉。这类块的起点差
    # 本来就为 0（同时间戳），时间窗必然命中，不需要兜底——留给
    # `_match_by_time_and_text`（它遇距离相同会**全部保留**）。
    _start_count = {}
    for r in en_rows:
        _k = round(r.start, 3)
        _start_count[_k] = _start_count.get(_k, 0) + 1
    en_rows_unique = [r for r in en_rows if _start_count[round(r.start, 3)] == 1]

    srt_keys = [normalize_for_compare(b.english_text()) for b in srt_sorted]
    en_keys = [normalize_for_compare(r.text) for r in en_rows_unique]

    # ① LCS 锚点：文本完全一致的块按出现次序对应（重复台词也按序对各的）。
    sm = SequenceMatcher(None, srt_keys, en_keys, autojunk=False)
    anchors = [(blk.a, blk.b, blk.size) for blk in sm.get_matching_blocks()
               if blk.size]
    anchor_pairs = []
    for a0, b0, size in anchors:
        for k in range(size):
            anchor_pairs.append((a0 + k, b0 + k))

    # ② 锚点之间（以及首尾）配对：条数相等按序对，不等按比例 + 文本校验。
    out = {}

    def link(si, ri, strict):
        if not (0 <= si < len(srt_sorted) and 0 <= ri < len(en_rows_unique)):
            return
        # 第二道闸：同起点多行的那一行绝不能进兜底表。en_rows_unique 已经剔掉了，
        # 这里再挡一次，防止将来有人误把 en_rows 传回来时 MULTI_SAME_LANG
        # 悄无声息地消失（C2 就是这么红过）。
        if _start_count.get(round(en_rows_unique[ri].start, 3), 0) > 1:
            return
        if strict:
            ratio = _text_ratio(srt_sorted[si].english_text(),
                                en_rows_unique[ri].text)
            if ratio < TEXT_RATIO_THRESHOLD:
                return      # 比例兜底配上不相干的台词，宁可留空报未配上
        out[srt_sorted[si].index] = (si, ri)

    def fill_gap(s_lo, s_hi, r_lo, r_hi):
        """把 srt[s_lo:s_hi] 与 ass[r_lo:r_hi] 对应起来。"""
        n_s, n_r = s_hi - s_lo, r_hi - r_lo
        if n_s <= 0 or n_r <= 0:
            return
        if n_s == n_r:
            for j in range(n_s):
                link(s_lo + j, r_lo + j, strict=False)
        else:
            for j in range(n_s):
                link(s_lo + j, r_lo + min(n_r - 1, j * n_r // n_s), strict=True)

    prev_s = prev_r = -1
    for si, ri in anchor_pairs:
        fill_gap(prev_s + 1, si, prev_r + 1, ri)
        link(si, ri, strict=False)
        prev_s, prev_r = si, ri
    fill_gap(prev_s + 1, len(srt_sorted), prev_r + 1, len(en_rows_unique))

    # ③ 中文轨：该英文行在中文轨里的同起点行（ASS 双语轨同时间戳对齐）。
    zh_by_start = {}
    for r in zh_rows:
        zh_by_start.setdefault(round(r.start, 3), r)

    result = {}
    for srt_id, (si, ri) in out.items():
        en_row = en_rows_unique[ri]
        result[srt_id] = (en_row, zh_by_start.get(round(en_row.start, 3)))
    return result


def pair(ass_blocks: List[AssDialogue], srt_blocks: List[SrtBlock]) -> List[PairedBlock]:
    """按 srt 块配对 ass 行，生成 PairedBlock 列表。"""
    paired = []
    used_ass = set()
    # 第一遍：±TIME_TOLERANCE 时间窗 + 文本双校验（原有行为）
    window_matched = {}       # srt_id -> [AssDialogue]
    for sb in srt_blocks:
        m = _match_by_time_and_text(sb, ass_blocks)
        if m:
            window_matched[sb.index] = m
    # 第二遍：顺序映射兜底（吸收剪辑点 / 行边界分歧）
    window_ids = set(window_matched)
    fallback_pairs = _monotonic_fallback(srt_blocks, ass_blocks, set())
    # 顺序映射是「块 ↔ 行」的全局解，可信度高于 ±0.5s 窗：窗口只比时间，
    # 遇到剪接点会把相邻那句当成本句配进去（S06E02 的 srt 852 就是这样被
    # 配到「it is an international job」的，文本比例 0.71 恰好过 0.6 部分匹配线）。
    #
    # 所以两边合成一张表，冲突时按**证据强度**裁决：
    #   顺序映射命中同一行 → 采纳映射（窗口那一票是时间巧合）；
    #   窗口命中的行已被映射认领、但本块映射指向别处 → 采映射；
    #   映射没覆盖本块 → 保留窗口结果（原有行为）。
    mapped_en = {id(v[0]) for v in fallback_pairs.values() if v[0] is not None}
    _fallback_lookup = {}
    for srt_id, (en_row, zh_row) in fallback_pairs.items():
        rows = [r for r in (en_row, zh_row) if r is not None]
        if not rows:
            continue
        # 窗口已经配到「同一轨道多行」= 真同时间戳重复行，`_match_by_time_and_text`
        # 在距离相同时会**全部保留**。这种块绝不能让顺序映射覆盖：
        # 映射是「块 -> 一行」的模型，覆盖后重复行被压成一行，
        # MULTI_SAME_LANG 就再也报不出来（C2 实测 anomalies=[]）。
        # 重复行的起点差本来就是 0，不需要兜底来救，窗口结果才是对的。
        win = window_matched.get(srt_id) or []
        _trk_count = {}
        for r in win:
            _trk_count[r.track] = _trk_count.get(r.track, 0) + 1
        if any(n > 1 for n in _trk_count.values()):
            continue
        _fallback_lookup[srt_id] = (rows, srt_id not in window_ids)

    for sb in srt_blocks:
        matched = window_matched.get(sb.index)
        fallback = False
        exact = False      # 时间窗命中（起点在 ±TIME_TOLERANCE 内），不是兜底猜的
        if sb.index in _fallback_lookup:
            matched, fallback = _fallback_lookup[sb.index]
        elif matched:
            # 映射没覆盖这个块：窗口命中的行若已被映射认领给别的块，
            # 说明这是跨块抢行，丢掉，留给兜底表报未配上。
            matched = [r for r in matched
                       if r.track != TRACK_EN or id(r) not in mapped_en]
        if matched:
            matched = list(matched)
            # 「顺序映射有没有覆盖本块」不等于「这一块是不是真超容差」。
            # 兜底表是按「条数相等就按序配」无条件配上的，最常见的命中恰恰是
            # **时间窗本来就能配上的正常块**（S06E02 全片 869 块里绝大多数）。
            # 若只看 `fallback` 标志，这些正常块会统统被打上 BOUNDARY_OFFSET
            # （tests/test_subtitle_polish_pairing_tags.py 的 P2 实测）。
            # 所以起点差以 ASS 侧实际行距为准，不用兜底标志推断。
            near = _nearest_ass_offset(sb, ass_blocks)
            # 阈值必须用 `TIME_TOLERANCE`，不能写字面量 0.5：有人调松容差时
            # 字面量这里会悄悄失效，正常块又被误标。
            exact = near is not None and abs(near) <= TIME_TOLERANCE
        else:
            matched = []
        # ONE_TO_MANY: 一个 srt 块配到多个时间戳相近但不同的行
        # 实际 matched 都是同时间戳的，MULTI_SAME_LANG 看 track 重复
        pb = PairedBlock(
            srt_id=sb.index,
            srt_start=sb.start,
            srt_end=sb.end,
            ass_time=f"{_ass_time_str(sb.start)}-{_ass_time_str(sb.end)}",
        )
        track_lines = {}
        anomalies = []
        for ab in matched:
            track_lines.setdefault(ab.track, []).append(ab)
            used_ass.add(id(ab))
        # 检查 MULTI_SAME_LANG
        for trk, lines in track_lines.items():
            if len(lines) > 1:
                anomalies.append("MULTI_SAME_LANG")
            # 合并文本
            joined = " ⏎ ".join(ln.text for ln in lines)
            if trk == TRACK_EN:
                pb.english = joined
            elif trk == TRACK_ZH:
                pb.chinese = joined
            elif trk == TRACK_NOTE:
                pb.note = joined
        # 英文行写中文（轨覆盖）检测
        if pb.english and any("一" <= c <= "鿿" for c in pb.english):
            anomalies.append("ASS_TRACK_OVERWRITE")
        # 时间戳对上但文本部分相似（ass 可能人工调轴）—— 只在英文 track 标
        en_lines = track_lines.get(TRACK_EN, [])
        if en_lines and not sb.is_sound_effect_only():
            srt_en = sb.english_text()
            for ab in en_lines:
                if not any("一" <= c <= "鿿" for c in ab.text):
                    ratio = _text_ratio(srt_en, ab.text)
                    if 0.6 <= ratio < TEXT_RATIO_THRESHOLD:
                        anomalies.append("TIME_TEXT_DRIFT")
                        break
        # 漏译：有英文无中文（音效块除外）。
        #
        # 「音效块除外」这一条**必须显式写上**，不能靠 `pb.english` 恰好为空来豁免。
        # 兜底表（_monotonic_fallback）会给音效块也配上英文行：
        # tests/test_subtitle_polish_pairing_tags.py 的 P4 夹具里 ASS 是
        # `[ENGINE REVS]`@1.0、SRT 是 `[ENGINE REVS]`@3.0，顺序映射把两者配上，
        # 于是 pb.english 非空、pb.chinese 为空，旧写法照样报 ZH_MISSING——
        # 而音效块本来就没有中文译文，这是**假漏译**。BOUNDARY_OFFSET 分支
        # 已经加了同样的排除，这里必须一致，否则修了一半、审计员仍会看到噪声。
        if pb.english and not pb.chinese and not sb.is_sound_effect_only():
            anomalies.append("ZH_MISSING")
        # 两边都没配上，且不是纯音效块 —— 必须再往下分两种（A1，issue v1.15）。
        #
        # 原本这两种共用一个 SRT_HAS_ASS_NONE，`pipeline-spec.md` 又把含义写成
        # 「漏译/丢行」，于是「没配上」被读成「漏译」，审计员照着去补内容。
        # S06E02 的 R5 p1 报出 38 条假漏译、重跑归零，根因就在这里。
        #
        # 第一版修正只把它们拆成 ZH_MISSING / PAIRING_FAILED 两个名字，**还不够**：
        # 实测 S06E02 全片 869 块里被标 PAIRING_FAILED 的 47 条，逐条回查 ASS
        # **全部都有完整中英对照**，一条都不是「两边都空」——它们是 srt 与 ass
        # 的起点差 0.50~1.92 s、超出了 ±0.5 s 容差窗。两类事故的处置完全相反：
        #   超容差     → 轴的问题，该放宽容差或先做轴校准，**绝不能补译**
        #   真的没有行 → 素材不同版/轨缺失，该换素材
        # 合成一个标签，读的人分不出来，只会一律当「漏译」处理。
        #
        # 四形态判别。顺序固定：先问「有没有内容」，再问「内容是错位还是缺失」，
        # 最后才问「配上但起点差多少」。
        #   PAIRING_FAILED            两边都空、附近根本没行 —— 素材不同版
        #   PAIRING_OUT_OF_TOLERANCE  两边都空、容差外有行 —— 轴有问题，要先校轴
        #   BOUNDARY_OFFSET           配上了、但起点差超容差 —— 行边界分歧，轴没毛病
        #   ZH_MISSING                有英文无中文
        # 后加的 BOUNDARY_OFFSET 由 index_align 补丁的顺序映射引入：以前
        # 「超容差但顺序/文本对得上」会落进「两边都空」被误报成要校轴，
        # 现在真的配上了，改报更精确的「切点不同」。三形态在「两边都空」这条
        # 路径上完整保留。
        if not pb.english and not pb.chinese and not sb.is_sound_effect_only():
            # 容差窗外最近的 ass 起点差多少：有值 → 是错位，不是缺失。
            near = _nearest_ass_offset(sb, ass_blocks)
            if near is not None and abs(near) <= TIME_TOLERANCE:
                # 窗内明明有行却没配上 = 文本对不上（真缺内容 / 素材不同版），
                # 不是轴错位。S06E02 那 47 条「配对失败」全是 off≥0.50，落不进这里。
                anomalies.append(f"PAIRING_FAILED(srt_id={sb.index})")
            elif near is not None:
                anomalies.append(f"PAIRING_OUT_OF_TOLERANCE(off={near:+.2f}s)")
            else:
                anomalies.append(f"PAIRING_FAILED(srt_id={sb.index})")
        elif fallback and not exact and not sb.is_sound_effect_only():
            # 顺序兜底配上的块，且起点差确实超容差：行边界 / 剪辑点分歧。
            # 不是漏译、也不是要修轴——单列标签，既不进未配上率门禁，
            # 也让审计员看得到这批块的起点差。
            near = _nearest_ass_offset(sb, ass_blocks)
            if near is not None:
                anomalies.append(f"BOUNDARY_OFFSET(off={near:+.2f}s)")
        pb.lines = track_lines
        pb.anomalies = anomalies
        paired.append(pb)
    # ASS_HAS_SRT_NONE: ass 行没被任何 srt 块匹配
    all_matched_ids = {id(ab) for pb in paired for trk in pb.lines.values() for ab in trk}
    ass_only = [ab for ab in ass_blocks if id(ab) not in all_matched_ids]
    # 这些在报告里单独输出
    return paired, ass_only


def pair_dirs(
    ass_dir: str, srt_dir: str, strip_suffix: Optional[List[str]] = None
) -> List[Tuple[str, str]]:
    """目录配对：默认同名（去扩展名）。strip_suffix 去指定后缀。"""
    def stem(name: str) -> str:
        s = name
        # 去扩展名
        s = re.sub(r"\.(ass|srt)$", "", s, flags=re.I)
        if strip_suffix:
            for suf in strip_suffix:
                s = re.sub(re.escape(suf) + r"[_-]?$", "", s, flags=re.I)
        return s.lower().strip()

    ass_files = [f for f in os.listdir(ass_dir) if f.lower().endswith(".ass")]
    srt_files = [f for f in os.listdir(srt_dir) if f.lower().endswith(".srt")]
    srt_stems = {stem(f): f for f in srt_files}
    pairs = []
    for af in sorted(ass_files):
        key = stem(af)
        if key in srt_stems:
            pairs.append((
                os.path.join(ass_dir, af),
                os.path.join(srt_dir, srt_stems[key]),
            ))
    return pairs


def pair_files(ass_path: str, srt_path: str) -> Tuple[List[AssDialogue], List[SrtBlock]]:
    """单文件配对：直接解析。"""
    return parse_ass(ass_path), parse_srt(srt_path)


def find_srt_ids_by_text(
    ass_path: str, srt_path: str, pattern: str, track: str = TRACK_ZH
) -> List[Tuple[int, str, str]]:
    """按文本 pattern 找含它的 srt_id 列表（用于术语统一前定位哪些行要改）。

    返回 [(srt_id, ass_time, current_text)]，current_text 是该 track 的清洗后文本。
    一个 srt_id 只记一次（即使该 track 有多行都含 pattern）。

    用途：审计后想统一某专名（如"情怀铁路"→"遗产铁路"），用本函数找出哪些 srt_id
    的中文行含该 pattern，再决定进 fixes.json 还是走 global_replace。避免手写
    timestamp 匹配脚本（实测 map_nr.py 改 6 版才跑通）。
    """
    ass_blocks, srt_blocks = pair_files(ass_path, srt_path)
    paired, _ = pair(ass_blocks, srt_blocks)
    out = []
    for pb in paired:
        lines = pb.lines.get(track, [])
        for ab in lines:
            if pattern in ab.text:
                out.append((pb.srt_id, pb.ass_time, ab.text))
                break
    return out

