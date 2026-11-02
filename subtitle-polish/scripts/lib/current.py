# -*- coding: utf-8 -*-
"""从 ASS 回读 current：修 fixes 时**不许**抄审计 JSON 的原文。

## 为什么（issue #24 的 H2）

`make_fixes_r11.py` 曾经这么写：

    cur = zh[srt_id - 1].text          # 抄的是审计 JSON 里的镜像文本

问题是审计 JSON 里的「原文」是审计员当时**看到并可能已改写**的文本（典型污染：
审计员把「别太生意人」写进了 current）。抄它 → current 与 ASS 实际内容不一致
→ `apply_fixes` 的 current 精确匹配失败，或者更糟：匹配上了另一行。

所以规则只有一条：**current 一律从 ASS 按 srt_id 回读**。fixes.json 里带的
current 降级为「审计员看到的原文，仅供参考」，落盘前必须被这里的结果覆盖。

## 定位规则

1. 优先按 srt_id → SRT 的 (start, end) → 在 ASS 同轨里找时间戳覆盖该区间的行；
2. 同一时间戳命中多行（碎片行）时，用 `prefer_text` 或「时长最长」挑一条；
3. **绝不按行下标配对**——E03 的中文轨从 #149 起多一条零时长碎片，下标配对
   会让后面全部错位（最大 39.84s），两个不相干的句子被拼一起。
"""
from __future__ import annotations

import bisect
import os
from typing import Optional


TRACK_ZH = "中文"
TRACK_EN = "英文"


def style_to_track(style: str) -> str:
    """ASS style → 轨道名。style 通常就叫「中文」/「英文」，也可能前缀变体。"""
    s = (style or "").strip()
    if "中" in s:
        return TRACK_ZH
    if "英" in s or "en" in s.lower():
        return TRACK_EN
    return s


def iter_events(subs):
    """(index, event) 序列，index 是 ASS 内部顺序（不是 srt_id）。"""
    for i, e in enumerate(subs.events):
        yield i, e


def alignment_profile(subs, srt_blocks: list, track: str) -> dict:
    """量出这份文件「ASS 起点 vs SRT 起点」的对齐画像。

    ## 为什么需要画像而不是固定容差

    实测（S06E02/E03/E04，各 750–869 行）：

        E02  最近偏差分布 0.0s:222  0.5s:279  1.0s:227  1.5s:80  >2s:61
             → 均匀铺开在 0–1.5s，说明**中文轨被重新断句**（并句/拆句），
               start 本来就对不齐。这是正常工序，不是缺陷。
        E03  全部 0.00s，但内容错位 39.84s（轨错位）
        E04  全部 0.00s，内容也对

    所以「偏差小」完全不能证明「配对了」，反过来也一样。容差必须按文件
    自己的分布定：取 p90 作为「这份文件的正常范围」，再留 1.0s 余量。

    返回 {"p50", "p90", "p99", "tol"}，tol = max(2.0, p90 + 1.0)。
    """
    evs = sorted((e for _, e in iter_events(subs)
                  if style_to_track(e.style) == track), key=lambda x: x.start)
    starts = [e.start / 1000.0 for e in evs]
    if not starts or not srt_blocks:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "tol": 3.0}
    devs = []
    for b in srt_blocks:
        s0 = float(b.start)
        i = bisect.bisect_left(starts, s0)
        cand = []
        if i < len(starts):
            cand.append(starts[i] - s0)
        if i > 0:
            cand.append(starts[i - 1] - s0)
        if cand:
            devs.append(abs(min(cand, key=abs)))
    devs.sort()
    n = len(devs)
    p50 = devs[n // 2] if n else 0.0
    p90 = devs[min(n - 1, int(n * 0.9))] if n else 0.0
    p99 = devs[min(n - 1, int(n * 0.99))] if n else 0.0
    return {"p50": round(p50, 2), "p90": round(p90, 2), "p99": round(p99, 2),
            "tol": round(max(2.0, p90 + 1.0), 2)}


def read_current(subs, srt_blocks: list, srt_id: int, track: str,
                 tol: float = 1.5, base: Optional[float] = None,
                 starts: Optional[dict] = None) -> Optional[str]:
    """按 srt_id + track 从 ASS 回读该行原文。

    `srt_blocks` 是 parse_srt 的结果，每个元素需有 `.start` / `.end`（秒）。
    `base` 是该文件的中位偏差（见 `median_offset`）：给了就按「偏差 − base」
    判定，未给则按绝对偏差判。返回 None 表示定位失败，调用方必须当错误处理。

    ## `starts`：按「这一句在 ASS 里的实际起点」定位（index_align 补丁）

    默认走 SRT 起点 + `tol` 窗。这在 S06E02 上会取错行：ASS 中文轨按语音节奏
    重切，与 SRT 的句边界不同，按序号硬配对后起点差 >0.5s 的有 727/869、中位
    3.08s，±0.5s 窗准确率只有 142/869。传 `starts`（{srt_id: ass 起点秒}）后
    改用**精确起点**定位，容差收到 0.002s，准确率 869/869。

    为什么容差是 0.002 而不是 0：起点是 ASS 里读出来的浮点秒（毫秒/1000），
    再与 `e.start / 1000.0` 比较，同一条记录两边都是同一串毫秒除出来的，
    理论差为 0；留 0.002 只为吃掉浮点表示误差，不是为了「容忍偏差」。
    """
    if not isinstance(srt_id, int) or srt_id <= 0:
        return None
    idx = srt_id - 1
    if idx < 0 or idx >= len(srt_blocks):
        return None
    sb = srt_blocks[idx]
    start = float(sb.start)
    off = base or 0.0
    if starts and srt_id in starts:
        # 映射给了精确起点，就不要再用 SRT 起点 ±tol 去找——那样会在
        # 断句点分歧的素材上取到相邻句（apply_fixes 会照着改错的句子）。
        start = float(starts[srt_id])
        off = 0.0
        tol = 0.002
    best = None
    best_score = None
    for _, e in iter_events(subs):
        if style_to_track(e.style) != track:
            continue
        es, ee = e.start / 1000.0, e.end / 1000.0
        d = abs((es - start) - off)
        if d > tol:
            continue
        score = (round(d, 3), -(ee - es))
        if best_score is None or score < best_score:
            best, best_score = e, score
    return best.text if best is not None else None


def read_current_strict(subs, srt_blocks: list, srt_id: int, track: str,
                        tol: float = 1.5, base: Optional[float] = None,
                        starts: Optional[dict] = None):
    """同 read_current，但把失败原因也返回：(text, reason)。

    reason ∈ {"", "bad_id", "id_out_of_range", "no_event"}
    """
    if not isinstance(srt_id, int) or srt_id <= 0:
        return None, "bad_id"
    if srt_id > len(srt_blocks):
        return None, "id_out_of_range"
    t = read_current(subs, srt_blocks, srt_id, track, tol=tol, base=base,
                     starts=starts)
    if t is None:
        return None, "no_event"
    return t, ""


def load_blocks(srt_path: str) -> list:
    """容错地读 SRT 块。srt 不存在返回 []。"""
    if not srt_path or not os.path.exists(srt_path):
        return []
    try:
        from .ass_srt_pair import parse_srt
    except Exception:
        try:
            from ass_srt_pair import parse_srt   # type: ignore
        except Exception:
            return []
    try:
        return parse_srt(srt_path)
    except Exception:
        return []
