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
    """时间戳模糊匹配 + 文本双校验，返回匹配的 ass 行。"""
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
            # 文本对不上且非覆盖 -> 不配对，可能是错位
        else:
            # 中文/注释行，时间戳对上就算配对
            matched.append(ab)
    return matched


def pair(ass_blocks: List[AssDialogue], srt_blocks: List[SrtBlock]) -> List[PairedBlock]:
    """按 srt 块配对 ass 行，生成 PairedBlock 列表。"""
    paired = []
    used_ass = set()
    for sb in srt_blocks:
        matched = _match_by_time_and_text(sb, ass_blocks)
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
        # 漏译：有英文无中文（音效块除外）
        if pb.english and not pb.chinese:
            anomalies.append("SRT_HAS_ASS_NONE")  # 中文行缺失
        if not pb.english and not pb.chinese and not sb.is_sound_effect_only():
            # 非音效却两边都没匹配，标 SRT_HAS_ASS_NONE
            anomalies.append("SRT_HAS_ASS_NONE")
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
