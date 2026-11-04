"""双源交叉校验（issue #30 建议 2 的 C 部分）。

## 它做什么

把**两份独立的词级时间戳缓存**分别落到同一批字幕行上，逐行比较词形。
同一行两源不一致 → 标 `dual_source_mismatch`，只作提示与待人工确认；
一致 → 视为高置信、可放行。**不写 ASS，不改任何判定。**

## 它不做什么

- 不改变时间轴 PASS/FAIL。调用方（`align_audit.py`）把结果放在报告的独立小节
  和 json 的 `dual_source` 字段里，`stats` / `verdict` / `pairs` 一个都不动。
- 不碰 `align_anchors` / `robust_reject` 的阈值与口径。
- 不自动挑「哪一源更对」——两源都可能是错的，判断交人。

## 能力边界（必须写在报告里）

当前仓库里两个「引擎」角色并不对等：

- whisper（`tokens_whisper`）是**独立转录器**：只吃音频，自己产出文本；
- qwen3-forced-aligner（`tokens_qwen`）是**强制对齐器**：必须喂入字幕文本
  `rows` 才产出时间戳，它的 token 文本是输入文本的回声，**不能独立产出原文**。

因此本模块只提供**通用的两源比对**：能比对任何两份词级缓存（例如两次 whisper
不同参数、whisper + 人工校对的词表、或未来接入的第二套 ASR）。是否真的来自
两个独立引擎，由调用方保证；本模块无法验证。报告里的 `real_dual_engine` 字段
固定为 `False`，避免把「接线」说成「已端到端双引擎验证」。
"""
from __future__ import annotations

import bisect
import json
from difflib import SequenceMatcher

from . import align_core as ac


def load_tokens(path: str) -> list:
    """读词级缓存。兼容 `[[start,end,text], ...]` 与带 words/tokens 键的对象。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("words") or data.get("tokens") or data.get("asr_words") or []
    out = []
    for item in data:
        if not item or len(item) < 3:
            continue
        try:
            out.append((float(item[0]), float(item[1]), str(item[2])))
        except (TypeError, ValueError):
            continue
    return out


def _assign_tokens(rows, tokens) -> dict:
    """把每个 token 归到重叠最多的一行；无重叠时归最近的 1 秒内邻行。

    返回 `{row_index: [token, ...]}`。不依赖 `align_anchors`：文本比较不该
    被「文本相似度匹配」预先筛一遍，否则不一致的行会先被丢掉。
    """
    starts = [r[0] for r in rows]
    by_row: dict = {}
    for t in tokens:
        s, e, _ = t
        mid = (s + e) / 2.0
        i = bisect.bisect_right(starts, mid) - 1
        cand = [j for j in (i, i + 1) if 0 <= j < len(rows)]
        best, best_ov = None, 0.0
        for j in cand:
            rs, re, _ = rows[j]
            ov = min(e, re) - max(s, rs)
            if ov > best_ov:
                best, best_ov = j, ov
        if best is None:
            # 落在行间空隙：归最近的一行，但只接受 1 秒内的相邻行。
            near = min(range(len(rows)),
                       key=lambda j: min(abs(s - rows[j][1]), abs(e - rows[j][0])))
            rs, re, _ = rows[near]
            gap = max(rs - e, s - re, 0.0)
            if gap <= 1.0:
                best = near
        if best is not None:
            by_row.setdefault(best, []).append(t)
    return by_row


def _row_text(tokens) -> str:
    return " ".join(t[2] for t in sorted(tokens, key=lambda x: x[0]))


def _ratio(a: list, b: list) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def compare(rows, tokens_a, tokens_b, *, label_a="source-a",
            label_b="source-b") -> dict:
    """逐行比对两源。返回结构化提示，不返回任何「应该怎么改」。"""
    ba = _assign_tokens(rows, tokens_a)
    bb = _assign_tokens(rows, tokens_b)
    mismatches, n_agree, n_uncovered = [], 0, 0
    for i, (rs, _re, _text) in enumerate(rows):
        text_a = _row_text(ba.get(i, []))
        text_b = _row_text(bb.get(i, []))
        wa, wb = ac.words_of(text_a), ac.words_of(text_b)
        if not wa or not wb:
            # 缺覆盖不是「不一致」：可能 VAD 吞词/对齐失败。单列计数，不制造假冲突。
            n_uncovered += 1
            continue
        if wa == wb:
            n_agree += 1
            continue
        mismatches.append({
            "srt_id": i + 1,
            "start": round(rs, 3),
            "text_a": text_a,
            "text_b": text_b,
            "ratio": round(_ratio(wa, wb), 3),
        })

    return {
        "mode": "two_caches",
        "label_a": label_a,
        "label_b": label_b,
        "n_rows": len(rows),
        "n_compared": n_agree + len(mismatches),
        "n_agree": n_agree,
        "n_mismatch": len(mismatches),
        "n_uncovered": n_uncovered,
        "mismatches": mismatches,
        "real_dual_engine": False,
        "limitation": (
            "只比对两份词级缓存，无法确认它们是否来自两个独立引擎。"
            "qwen3-forced-aligner 是强制对齐器，token 文本是输入字幕的回声，"
            "不能独立转录；本环境未做真实双引擎端到端验证。"),
        "note": "仅提示与待人工确认：不自动改写英文轨，不参与时间轴 PASS/FAIL。",
    }


def render_section(dual) -> list:
    """报告小节。调用方负责把它拼进 md；为空时明确写「没跑」。"""
    if not dual:
        return ["## 双源交叉校验", "",
                "未启用（未提供 `--asr-words-b`）。时间轴判定只基于单一词级缓存。", ""]
    L = ["## 双源交叉校验（仅提示，不参与 PASS/FAIL）", ""]
    L += ["- 源 A：`%s`" % dual["label_a"],
          "- 源 B：`%s`" % dual["label_b"],
          "- 行数：%d；可比 %d；一致 %d；不一致 **%d**；单源缺覆盖 %d"
          % (dual["n_rows"], dual["n_compared"], dual["n_agree"],
             dual["n_mismatch"], dual["n_uncovered"]), ""]
    if dual["mismatches"]:
        L += ["| srt_id | start(s) | 源 A | 源 B | 词序列相似度 |",
              "|---|---|---|---|---|"]
        for m in dual["mismatches"]:
            L.append("| %d | %.3f | %s | %s | %.3f |"
                     % (m["srt_id"], m["start"], m["text_a"], m["text_b"],
                        m["ratio"]))
        L.append("")
    L += ["> **只作提示**：不一致行需人工或审计轮确认，**不自动改写英文轨**；"
          "一致行视为高置信，但也不等于绝对正确。",
          "> 本小节不改变 `align_anchors` / `robust_reject` 的口径，也不改变"
          " PASS/FAIL。", "",
          "> 能力边界：%s" % dual["limitation"], ""]
    return L
