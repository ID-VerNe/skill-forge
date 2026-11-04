# -*- coding: utf-8 -*-
"""双对齐器时间戳互证（issue #30 建议 3 / C）。

## 它做什么

同一份**现成英文轨文本** + 同一段音频，交给两个**独立的强制对齐器**：

- 一路是 whisperX 的 wav2vec2 对齐器（`scripts/align_whisperx.py`，需在
  本机 whisperX 环境里跑，产出词级时间戳缓存）；
- 一路是 qwen3-forced-aligner（仓库内 `align_audit.py --engine qwen`）。

两路各自产出**词级时间戳**。本模块比较的是**时间戳**，不是文本：

1. `timestamp_delta`：同一行在两路下的起始时间差（median / P90 / max）；
2. `offset_diff` / `slope_diff`：两路各自用 `align_core.summarize` 算出的
   偏移中位与斜率，彼此是否接近；
3. `verdict_agree`：两路各自判出的时间轴结论是否一致。

> **这不是转录比对**。本能力不依赖任何独立转录：输入始终是同一份字幕文本，
> 两个引擎只是在做「文本 ↔ 音频」的强制对齐。whisper 一侧由 whisperX 的
> wav2vec2 对齐器承担，不是 faster-whisper 的 ASR 转写。

## 三态

- `corroborated`：两套偏移结论接近（阈值见 `THRESHOLDS`），高置信可放行；
- `divergent`：时间戳或结论明显不一致 → 现有单源 PASS/FAIL 不可信，
  报告里升格为「未获双引擎印证」，建议抽查音频；
- `single_source`：只有一路可用（另一路缺缓存/锚点不足）→ **不冒充双证**。

## 它不做什么

- 不改变 `stats` / `verdict` / `pairs` / `curve` 的任何数值，调用方只在报告
  独立小节与 json 的 `dual_aligner` 字段里放结果。
- 不碰 `align_anchors` / `robust_reject` 的阈值与曲线拟合口径。
- 不自动改写英文轨，不自动挑「哪一路更对」。
"""
from __future__ import annotations

import bisect
import json
import re

from . import align_core as ac

STATUS_CORROBORATED = "corroborated"
STATUS_DIVERGENT = "divergent"
STATUS_SINGLE = "single_source"
STATUS_NO_DATA = "no_data"

#: 一致性阈值。**保守默认值，待真实样片校准**。
#:
#: - `ts_median_s = 0.25`：两个对齐器对同一行起点的中位差。wav2vec2 与
#:   qwen 都是帧级（~20ms）输出，实测抖动主要来自词边界定义，0.25 s 足以
#:   覆盖正常分歧，又不至于放过真实偏移（单源 PASS 的容差是 0.3/0.5 s）。
#: - `ts_p90_s = 0.60`：允许 10% 的行有较大分歧（连读、切点、吞词）。
#: - `offset_diff_s = 0.25`：两路「字幕比音频晚/早多少」的中位结论差。
#: - `slope_diff = 0.002`：每秒钟的偏移差；1200 s 全片对应 2.4 s 总漂移。
#: - `min_rows = 10`：低于它与 `align_audit` 的锚点下限一致，不给结论。
THRESHOLDS = {
    "ts_median_s": 0.25,
    "ts_p90_s": 0.60,
    "offset_diff_s": 0.25,
    "slope_diff": 0.002,
    "min_rows": 10,
}

#: 供报告渲染用的人话阈值表
THRESHOLD_TEXT = {
    "ts_median_s": "逐行起点差中位 ≤ 0.25 s",
    "ts_p90_s": "逐行起点差 P90 ≤ 0.60 s",
    "offset_diff_s": "两路偏移中位之差 ≤ 0.25 s",
    "slope_diff": "两路斜率之差 ≤ 0.002 /s",
    "min_rows": "每路至少 10 个锚点",
}

#: 单个词的跨度上限。词级对齐的 token 超过它基本是模型把整段静音/换行
#: 并进了一个词（实测 whisperX 会把句末词拉到下一句开头，qwen 偶发把
#: 片头静音并进首个词）。这类 token 参与「行起点」计算会把起点拖到行外。
MAX_WORD_SPAN_S = 10.0

#: 说话人标记（`[SPEAKER_02]` / `SPEAKER02`）不是台词，是轨里的元数据。
#: 两个对齐器会把它当词对齐，且位置互不相同，必须先从时间戳比较里剔除。
_SPEAKER_RE = re.compile(r"^\[?\s*speaker[-_ ]?\d+\s*\]?$", re.I)


def sanitize(tokens) -> tuple:
    """时间戳互证用的最小清洗。返回 `(kept, stats)`。

    只剔除三类**明显不是词**的 token，并逐类计数，便于在报告里说明
    「比较的是哪些 token」：

    - `speaker`：说话人标记；
    - `span_out`：跨度 > `MAX_WORD_SPAN_S` 的异常 token；
    - `negative`：end < start 的反向 token（数据损坏）。

    零长度 token 保留：qwen 对部分词给出 `start == end`，那仍是有效的
    起点信息，直接丢掉会让整行失去起点。
    """
    kept = []
    st = {"n_in": len(tokens), "n_speaker": 0, "n_span_out": 0, "n_negative": 0}
    for s, e, t in tokens:
        s, e = float(s), float(e)
        if _SPEAKER_RE.match((t or "").strip()):
            st["n_speaker"] += 1
            continue
        if e < s:
            st["n_negative"] += 1
            continue
        if e - s > MAX_WORD_SPAN_S:
            st["n_span_out"] += 1
            continue
        kept.append((s, e, t))
    st["n_kept"] = len(kept)
    return kept, st


def load_tokens(path: str) -> list:
    """读词级缓存。兼容 `[[start,end,text], ...]` 与带 words/tokens 键的对象。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("words") or data.get("tokens") or data.get("asr_words") or []
    out = []
    for item in data:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            if isinstance(item, dict) and "start" in item and "end" in item:
                out.append((float(item["start"]), float(item["end"]),
                            str(item.get("text") or item.get("word") or "")))
            continue
        try:
            out.append((float(item[0]), float(item[1]), str(item[2])))
        except (TypeError, ValueError):
            continue
    return out


def _assign_tokens(rows, tokens) -> dict:
    """把每个 token 归到**它的起点所在**的行。

    返回 `{row_index: [token, ...]}`。按时间归位，不按文本匹配，否则
    「两路时间戳差得远」的行会先被文本筛掉，正好丢掉要看的证据。

    **必须用起点而不是「最大重叠」判定**：实测 whisperX 会把句末词的 end
    拉到下一句开头（`details. 41.734→62.241`），按重叠归行会让这一行
    认领下一行的词，把行起点前移十几秒——那不是对齐器分歧，是归行错误。
    """
    starts = [r[0] for r in rows]
    by_row: dict = {}
    for t in tokens:
        s, _, _ = t
        i = bisect.bisect_right(starts, s) - 1
        if 0 <= i < len(rows) and s < rows[i][1]:
            by_row.setdefault(i, []).append(t)
            continue
        # 起点落在行间空隙或首行之前：只在距行边界 ≤1s 时归入最近一行，
        # 否则丢弃（例如片头静音被并成 token 时，起点 0.0 离首行 23s）。
        near = min(range(len(rows)),
                   key=lambda j: min(abs(s - rows[j][1]), abs(s - rows[j][0])))
        gap = max(rows[near][0] - s, s - rows[near][1], 0.0)
        if gap <= 1.0:
            by_row.setdefault(near, []).append(t)
    return by_row


def row_starts(rows, tokens) -> dict:
    """每行在该路对齐结果下的起点：归到该行最早一个 token 的 start。"""
    by_row = _assign_tokens(rows, tokens)
    return {i: min(t[0] for t in ts) for i, ts in by_row.items()}


def _row_text(tokens) -> str:
    return " ".join(t[2] for t in sorted(tokens, key=lambda x: x[0]))


def _pct(vals, q):
    """简单分位数（最近秩），避免引入 numpy 只为算一个 P90。"""
    if not vals:
        return 0.0
    s = sorted(vals)
    k = int(round(q * (len(s) - 1)))
    return s[max(0, min(len(s) - 1, k))]


def _source_stats(rows, tokens, *, tol, window=180.0, min_n=5):
    """单路偏移结论：复用 `align_core`，与 align_audit 主判定同一套口径。"""
    pairs = ac.align_anchors(rows, tokens)
    if len(pairs) < THRESHOLDS["min_rows"]:
        return None, len(pairs)
    return ac.summarize(pairs, window, tol, min_n), len(pairs)


def compare(rows, tokens_a, tokens_b, *, label_a="aligner-a",
            label_b="aligner-b", stats_a=None, stats_b=None,
            tol_a=0.5, tol_b=0.3) -> dict:
    """两路对齐器互证。返回只读结论，不返回任何替换建议。

    `stats_a` / `stats_b` 可由调用方传入（避免重复计算主判定）；
    缺省时本模块按 `tol_a` / `tol_b` 各算一次。
    """
    n_rows = len(rows)
    toks_a, filter_a = sanitize(tokens_a) if tokens_a else ([], {"n_in": 0, "n_kept": 0})
    toks_b, filter_b = sanitize(tokens_b) if tokens_b else ([], {"n_in": 0, "n_kept": 0})
    ta = row_starts(rows, toks_a) if toks_a else {}
    tb = row_starts(rows, toks_b) if toks_b else {}
    common = sorted(set(ta) & set(tb))
    uncovered = n_rows - len(common)
    deltas = [ta[i] - tb[i] for i in common]
    adeltas = [abs(x) for x in deltas]

    def dist(vals):
        if not vals:
            return {"n": 0, "median": 0.0, "p90": 0.0, "max": 0.0, "unit": "s"}
        return {
            "n": len(vals),
            "median": round(ac.median(vals), 3),
            "p90": round(_pct(vals, 0.9), 3),
            "max": round(max(vals), 3),
            "unit": "s",
        }

    if stats_a is None and tokens_a:
        stats_a, n_a = _source_stats(rows, tokens_a, tol=tol_a)
    else:
        n_a = len(ac.align_anchors(rows, tokens_a)) if tokens_a else 0
    if stats_b is None and tokens_b:
        stats_b, n_b = _source_stats(rows, tokens_b, tol=tol_b)
    else:
        n_b = len(ac.align_anchors(rows, tokens_b)) if tokens_b else 0

    enough_a = bool(stats_a) and stats_a.get("n_pairs", 0) >= THRESHOLDS["min_rows"]
    enough_b = bool(stats_b) and stats_b.get("n_pairs", 0) >= THRESHOLDS["min_rows"]

    result = {
        "mode": "dual_aligner",
        "label_a": label_a,
        "label_b": label_b,
        "n_rows": n_rows,
        "n_compared": len(common),
        "n_uncovered": uncovered,
        "timestamp_delta": dist(adeltas),
        "thresholds": dict(THRESHOLDS),
        "threshold_text": dict(THRESHOLD_TEXT),
        "not_transcription": True,
        "note": ("只比对两路对齐器的时间戳：不比对转写文本，不自动改写英文轨，"
                 "不参与时间轴 PASS/FAIL 计算。"),
        "sources": {
            "a": dict(_src_view(label_a, stats_a, n_a, tol_a), filter=filter_a),
            "b": dict(_src_view(label_b, stats_b, n_b, tol_b), filter=filter_b),
        },
    }

    # 时间戳差最大的几行，用于人工抽查定位；只写事实，不评判谁对。
    top = sorted(common, key=lambda i: -abs(ta[i] - tb[i]))[:5]
    result["worst_rows"] = [
        {"row": i + 1,
         "delta": round(ta[i] - tb[i], 3),
         "a_start": round(ta[i], 3),
         "b_start": round(tb[i], 3),
         "row_start": round(rows[i][0], 3),
         "text": (rows[i][2] or "")[:60]}
        for i in top
    ]

    # 文本只留极次要的 sanity 计数（不参与状态判定）
    ba = _assign_tokens(rows, toks_a) if toks_a else {}
    bb = _assign_tokens(rows, toks_b) if toks_b else {}
    same = diff = 0
    for i in common:
        wa = ac.words_of(_row_text(ba.get(i, [])))
        wb = ac.words_of(_row_text(bb.get(i, [])))
        if not wa or not wb:
            continue
        if wa == wb:
            same += 1
        else:
            diff += 1
    result["text_sanity"] = {"n_same": same, "n_diff": diff,
                             "note": "仅 sanity check，不参与 corroborated/divergent 判定"}

    if not enough_a and not enough_b:
        result["status"] = STATUS_NO_DATA
        result["reason"] = "两路锚点都不足 %d 条，无法互证" % THRESHOLDS["min_rows"]
        result["criteria"] = []
        return result
    if not enough_a or not enough_b:
        result["status"] = STATUS_SINGLE
        result["reason"] = ("只有%s一路可用（另一路锚点不足 %d 条）——"
                            "不冒充双证，按单源结论使用"
                            % ("A" if enough_a else "B", THRESHOLDS["min_rows"]))
        result["criteria"] = []
        return result

    offset_a = float(stats_a.get("median") or 0.0)
    offset_b = float(stats_b.get("median") or 0.0)
    slope_a = float(stats_a.get("slope") or 0.0)
    slope_b = float(stats_b.get("slope") or 0.0)
    offset_diff = abs(offset_a - offset_b)
    slope_diff = abs(slope_a - slope_b)
    verdict_agree = (stats_a.get("verdict") == stats_b.get("verdict"))

    d_med = result["timestamp_delta"]["median"]
    d_p90 = result["timestamp_delta"]["p90"]
    criteria = [
        {"name": "ts_median", "value": d_med,
         "tol": THRESHOLDS["ts_median_s"], "pass": d_med <= THRESHOLDS["ts_median_s"]},
        {"name": "ts_p90", "value": d_p90,
         "tol": THRESHOLDS["ts_p90_s"], "pass": d_p90 <= THRESHOLDS["ts_p90_s"]},
        {"name": "offset_diff", "value": round(offset_diff, 3),
         "tol": THRESHOLDS["offset_diff_s"],
         "pass": offset_diff <= THRESHOLDS["offset_diff_s"]},
        {"name": "slope_diff", "value": round(slope_diff, 5),
         "tol": THRESHOLDS["slope_diff"], "pass": slope_diff <= THRESHOLDS["slope_diff"]},
        {"name": "verdict_agree", "value": verdict_agree,
         "tol": True, "pass": verdict_agree},
    ]
    result["offset_diff"] = round(offset_diff, 3)
    result["slope_diff"] = round(slope_diff, 5)
    result["verdict_agree"] = verdict_agree
    result["criteria"] = criteria

    if all(c["pass"] for c in criteria):
        result["status"] = STATUS_CORROBORATED
        result["reason"] = "两路偏移结论一致，互证通过"
    else:
        result["status"] = STATUS_DIVERGENT
        bad = "、".join("%s=%s（阈值 %s）" % (c["name"], c["value"], c["tol"])
                        for c in criteria if not c["pass"])
        result["reason"] = ("两路结论偏离：%s。现有单源 PASS/FAIL 不可信，"
                            "应报 AMBIGUOUS 或抽查音频" % bad)
    return result


def _src_view(label, stats, n_pairs, tol):
    if not stats:
        return {"label": label, "n_pairs": n_pairs, "usable": False, "tol": tol}
    return {
        "label": label,
        "usable": n_pairs >= THRESHOLDS["min_rows"],
        "n_pairs": stats.get("n_pairs", n_pairs),
        "median": round(float(stats.get("median") or 0.0), 3),
        "slope": round(float(stats.get("slope") or 0.0), 5),
        "window_span": round(float(stats.get("window_span") or 0.0), 3),
        "verdict": stats.get("verdict") or "UNVERIFIED",
        "tol": tol,
    }


_STATUS_TEXT = {
    STATUS_CORROBORATED: "✓ corroborated：两路独立对齐器的偏移结论一致",
    STATUS_DIVERGENT: ("⚠ divergent：两路结论不一致，**现有单源 PASS/FAIL 不可信**，"
                       "应报 AMBIGUOUS 或抽查音频"),
    STATUS_SINGLE: "· single_source：只有一路可用，**未获双引擎印证**",
    STATUS_NO_DATA: "· no_data：两路都没有足够锚点",
}


def render_section(dual) -> list:
    """报告小节。不启用时明确写「没跑」，避免读者误以为验过。"""
    if not dual:
        return ["## 双对齐器时间戳互证", "",
                "未启用（未提供第二路词级时间戳 `--asr-words-b`）。"
                "时间轴结论只基于单路对齐器。", ""]
    L = ["## 双对齐器时间戳互证（不参与 PASS/FAIL 计算）", "",
         "- 状态：%s" % _STATUS_TEXT.get(dual["status"], dual["status"]),
         "- 原因：%s" % dual.get("reason", "—"),
         "- 路 A：`%s`；路 B：`%s`" % (dual["label_a"], dual["label_b"]),
         "- 行数 %d；两路可比 %d；单路缺覆盖 %d"
         % (dual["n_rows"], dual["n_compared"], dual["n_uncovered"]), ""]

    sa, sb = dual["sources"]["a"], dual["sources"]["b"]
    L += ["| 指标 | 路 A | 路 B |", "|---|---|---|",
          "| 锚点数 | %s | %s |" % (sa.get("n_pairs", "—"), sb.get("n_pairs", "—")),
          "| 偏移中位 (s) | %s | %s |"
          % (("%+.3f" % sa["median"]) if sa.get("usable") else "不可用",
             ("%+.3f" % sb["median"]) if sb.get("usable") else "不可用"),
          "| 斜率 (/s) | %s | %s |"
          % (("%+.5f" % sa["slope"]) if sa.get("usable") else "—",
             ("%+.5f" % sb["slope"]) if sb.get("usable") else "—"),
          "| 窗间极差 (s) | %s | %s |"
          % (("%.3f" % sa["window_span"]) if sa.get("usable") else "—",
             ("%.3f" % sb["window_span"]) if sb.get("usable") else "—"),
          "| 单路判定 | %s | %s |"
          % (sa.get("verdict", "—"), sb.get("verdict", "—")), ""]

    d = dual["timestamp_delta"]
    L += ["逐行起点差：可比 %d 行；中位 %.3f s；P90 %.3f s；最大 %.3f s"
          % (d["n"], d["median"], d["p90"], d["max"]), ""]

    fa, fb = sa.get("filter") or {}, sb.get("filter") or {}
    if fa or fb:
        L += ["- token 清洗：路 A 输入 %s → 保留 %s（说话人标记 %s、跨度 >%.0fs %s）；"
              "路 B 输入 %s → 保留 %s（说话人标记 %s、跨度 >%.0fs %s）"
              % (fa.get("n_in", "—"), fa.get("n_kept", "—"),
                 fa.get("n_speaker", 0), MAX_WORD_SPAN_S, fa.get("n_span_out", 0),
                 fb.get("n_in", "—"), fb.get("n_kept", "—"),
                 fb.get("n_speaker", 0), MAX_WORD_SPAN_S, fb.get("n_span_out", 0)), ""]

    if dual.get("worst_rows"):
        L += ["| 行 | 字幕起点 (s) | 路 A (s) | 路 B (s) | 差 (s) | 文本 |",
              "|---|---|---|---|---|---|"]
        for w in dual["worst_rows"]:
            L.append("| %d | %.3f | %.3f | %.3f | %+.3f | %s |"
                     % (w["row"], w["row_start"], w["a_start"], w["b_start"],
                        w["delta"], (w["text"] or "").replace("|", "\\|")))
        L.append("")
    if dual.get("criteria"):
        L += ["| 判据 | 实测 | 阈值 |", "|---|---|---|"]
        for c in dual["criteria"]:
            L.append("| %s | %s | %s |" % (c["name"], c["value"], c["tol"]))
        L.append("")

    if dual["status"] == STATUS_DIVERGENT:
        L += ["> **两路不一致**：这不是「其中一路算错了」的证据，而是「这套轴目前"
              "不可信」。单源 PASS 不能直接放行，单源 FAIL 也不能直接拿去改轴——"
              "先在关键时段抽查音频。", ""]
    L += ["> 本小节只作可信度标注：`stats` / `verdict` / `pairs` / `curve` 一个都不改，"
          "`align_anchors` / `robust_reject` 的阈值与曲线拟合口径也不动。",
          "> 本能力**不依赖独立转录**：输入是同一份字幕文本，两路只是在做"
          "「文本 ↔ 音频」的强制对齐。", ""]
    return L


def confidence_label(dual) -> str:
    """给多 run / 轮次报告的「时间轴」结论用的短标签。"""
    if not dual:
        return ""
    st = dual.get("status")
    if st == STATUS_CORROBORATED:
        return "双对齐器已印证"
    if st == STATUS_DIVERGENT:
        return "未获双对齐器印证（divergent）"
    if st == STATUS_SINGLE:
        return "单路对齐（未获双证）"
    return "两路均无足够锚点"
