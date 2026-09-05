# -*- coding: utf-8 -*-
"""ASS / SRT 时间格式互转。

ASS:  H:MM:SS.CC  (2 位毫秒)   例 0:01:23.45
SRT:  HH:MM:SS,CCC (3 位毫秒)  例 00:01:23,450
"""
from __future__ import annotations


def ass_to_seconds(ass_time: str) -> float:
    """ASS 时间 -> 秒。容错 H:MM:SS.CC 与 HH:MM:SS.CC。"""
    try:
        h, m, rest = ass_time.split(":")
        s, cs = rest.split(".")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0
    except (ValueError, IndexError):
        return 0.0


def srt_to_seconds(srt_time: str) -> float:
    """SRT 时间 (00:01:23,450) -> 秒。"""
    try:
        srt_time = srt_time.strip().replace(",", ".")
        h, m, rest = srt_time.split(":")
        s, ms = rest.split(".")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    except (ValueError, IndexError):
        return 0.0


def seconds_to_ass(seconds: float) -> str:
    """秒 -> ASS 时间 H:MM:SS.CC（毫秒截 2 位）。"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def seconds_to_srt(seconds: float) -> str:
    """秒 -> SRT 时间 HH:MM:SS,CCC（3 位毫秒）。"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_to_ass_time(srt_time: str) -> str:
    """SRT 时间串 -> ASS 时间串（直接转，毫秒截 2 位）。"""
    return seconds_to_ass(srt_to_seconds(srt_time))


def ass_to_srt_time(ass_time: str) -> str:
    """ASS 时间串 -> SRT 时间串。"""
    return seconds_to_srt(ass_to_seconds(ass_time))
