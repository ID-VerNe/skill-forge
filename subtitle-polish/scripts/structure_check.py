# -*- coding: utf-8 -*-
"""结构粗检：中英双轨「有没有坏」的开工前门禁（issue #24 的 C1 + C3b）。

## 它解决什么

E03 实测：中文轨从第 149 行起整体错位，最大偏差 39.84 秒。根因是一条**零时长
碎片**（`#149 "是的"` 与 `#148` 起点同为 430.72s），插入后使后续所有行错开一位，
偏差一路累积。

这类缺陷 LLM **永远发现不了**——它看到的是「这句译得好不好」，不是「这句和英文
是不是同一句」。而它会静默污染所有需要中英对照的判据（长度比、漏译检测、语气词
还原、`check_fluency` 的「英文没有对应来源」对照）。结果是**整轮审校的结论全部
不可信，而报告上看不出任何异常**。

所以本模块的定位不是「审校」，是**开工前的门禁**：先保证轨没坏，再谈轴准不准。

## 边界

- **不依赖 ASR，秒级**。不是 `align_audit` 的替代品（那个对音频），是它的前置筛查。
- **只输出观测值 + SUSPECT/ABORT，不给修法**。「怎么修」是判断，归 LLM。
- 退出码：0 = 可开工；20 = ABORT（结构性错误，不许开工）；
  21 = 有 SUSPECT 但无 ABORT（可开工，但要在报告里写明风险）。

## 与 C1 原设计的一处偏离

issue 里「索引时间差」按「同索引 `|zh.start − en.start|`」算。实测发现 ASS 里
中英两轨的行数本来就不等（中文被并句/拆句），同索引对齐会把「第 3 条英文 vs
第 3 条中文」凑成一对，量的其实是**断句差异**而不是**轨错位**。

所以这里改成**按时间轴各自排序后量最近邻起点偏差**（与 `lib/current.py` 的
`alignment_profile()` 同一口径）。判据阈值沿用 issue 的 p50 > 0.5s / max > 5s，
但量的东西从「同索引」变成「最近的」。E03 那种阶跃在两种口径下都能抓到，
而 E02 那种「中文被重新断句、偏差均匀铺开 0–1.5s」只会污染同索引口径。
"""
from __future__ import annotations

import argparse
import bisect
import os
import re
import sys
from difflib import SequenceMatcher
from typing import List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from lib.ass_srt_pair import (  # noqa: E402
    TRACK_EN, TRACK_ZH, clean_ass_text, normalize_for_compare,
    parse_ass, style_to_track,
)
from lib.time_fmt import seconds_to_ass  # noqa: E402


# ── 判据阈值（集中在这里，报告里会原样引用，避免「凭感觉拦」） ──────────────

# C3b 门禁：零时长行。起点/终点相同即结构性错误，直接 ABORT。
ZERO_DUR_MAX = 1e-6

# C1：单条时长异常。合并 / 误切。
DUR_SUSPECT_HIGH = 10.0
DUR_SUSPECT_LOW = 0.2

# C1：残片重复。去标签后相似度。
DUP_RATIO = 0.90

# C1：中英最近邻起点偏差分布
OFF_P50_SUSPECT = 0.5
OFF_MAX_SUSPECT = 5.0

# C1：轨条数不等
COUNT_DIFF_SUSPECT = 1

# C1：跨轨末条时间差（累计漂移）
TAIL_DRIFT_SUSPECT = 5.0

# C3b：track 字段合法枚举值。**精确匹配，不做「含『中』和『文』」的容错**——
# E03 有一行被污染成 `中nning? It's runni文`，容错匹配会让它静默通过。
VALID_TRACKS = (TRACK_EN, TRACK_ZH)


class _Observations:
    """收集观测值。报告只读它，不读中间状态。"""

    def __init__(self, path: str):
        self.path = path
        self.aborts: List[dict] = []
        self.suspects: List[dict] = []
        self.notes: List[str] = []
        self.metrics: dict = {}

    def abort(self, kind: str, rows: list, msg: str) -> None:
        self.aborts.append({"kind": kind, "rows": rows, "msg": msg})

    def suspect(self, kind: str, rows: list, msg: str) -> None:
        self.suspects.append({"kind": kind, "rows": rows, "msg": msg})


def _pct(vals: list, q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, int(len(s) * q))
    return s[i]


# ── C3b：门禁级检查（结构性错误 → ABORT） ──────────────────────────────────

def check_track_enum(events, obs: _Observations) -> None:
    """track 必须精确等于已知枚举值。

    `style_to_track()` 本身是容错映射（`"英" in style` 就判英文），这在**解析**
    场景是对的，在**门禁**场景是错的：一条被污染的样式名会静默归到某条轨，
    于是后面的所有对照都在和脏数据比。这里不做映射，直接比对 style 的
    归一化结果是否落在枚举里。
    """
    bad = []
    for i, e in enumerate(events, 1):
        raw = (e.style or "").strip()
        mapped = style_to_track(raw)
        # 判据：映射结果必须恰好是枚举值**且** style 本身没有混入其他字符。
        # 纯 style 落到枚举的路径有两条：直接命中 STYLE_TRACK_MAP，或含关键字。
        # 后者正是污染能钻进来的地方，所以这里要求 style 长度 <= 4 且不含
        # 拉丁字母/数字/标点（合法的中文样式名最多「简体中文」这种长度）。
        ok = mapped in VALID_TRACKS and len(raw) <= 4 and \
            not re.search(r"[A-Za-z0-9]", raw)
        if not ok:
            bad.append({"srt_id": i, "style": raw, "mapped": mapped,
                        "text": e.text[:30]})
    if bad:
        obs.metrics["bad_track_rows"] = len(bad)
        obs.abort(
            "track_enum", [b["srt_id"] for b in bad],
            "样式名（track）不是已知枚举值 %s，共 %d 行。"
            "容错匹配会让这类污染静默通过，后续所有中英对照都会拿脏数据比。"
            % ("/".join(VALID_TRACKS), len(bad)))


def check_zero_duration(events, obs: _Observations) -> None:
    """同轨起点重合 / 零时长行 → ABORT。

    E03 的根因就是这个：`#148 "MX-5"` 与 `#149 "是的"` 起点**同为 430.72s**。
    注意它不是零时长（两条都是 430.72→432.31，时长 1.59s 正常）——
    issue 原文写「零时长碎片」，实测形态是「**起点完全重合**」。两者都会让
    「第几行」这个坐标系错开一位，然后偏差一路累积到 39.84 秒，所以一起查。

    只看同轨：中英两轨起点相同是**正常**的（同一句话的两个语种版本必然同步起止），
    把它们算进去会把每一行都报成违规。
    """
    same_start, zero_dur = [], []
    last_by_track: dict = {}
    for i, e in enumerate(events, 1):
        if e.end - e.start <= ZERO_DUR_MAX:
            zero_dur.append({"srt_id": i, "start": e.start, "track": e.track,
                             "text": e.text[:30]})
        prev = last_by_track.get(e.track)
        if prev is not None and abs(e.start - prev[1]) <= ZERO_DUR_MAX:
            same_start.append({"srt_id": i, "prev_id": prev[0], "start": e.start,
                               "track": e.track, "text": e.text[:30],
                               "prev_text": prev[2][:30]})
        last_by_track[e.track] = (i, e.start, e.text)

    if zero_dur:
        obs.metrics["zero_dur_rows"] = len(zero_dur)
        shown = ", ".join("#%d" % b["srt_id"] for b in zero_dur[:10])
        more = "" if len(zero_dur) <= 10 else " …共 %d 行" % len(zero_dur)
        obs.abort(
            "zero_duration", [b["srt_id"] for b in zero_dur],
            "零时长行（起点 = 终点）：%s%s。" % (shown, more))
    if same_start:
        obs.metrics["same_start_rows"] = len(same_start)
        shown = "; ".join("#%d 与 #%d 同为 %.2fs（%s / %s）" % (
            b["prev_id"], b["srt_id"], b["start"], b["prev_text"], b["text"])
            for b in same_start[:6])
        more = "" if len(same_start) <= 6 else " …共 %d 处" % len(same_start)
        obs.abort(
            "same_start", [b["srt_id"] for b in same_start],
            "同轨起点完全重合：%s%s。"
            "两条共用一个起点时，「第几行」这个坐标系就错开了一位，"
            "后续偏差会一路累积（E03 就是这么错到 39.84 秒的），"
            "而单看任何一行都完全正常。" % (shown, more))


# ── C1：观测级检查（值得看，但不必停 → SUSPECT） ───────────────────────────

def check_track_counts(by_track: dict, obs: _Observations) -> None:
    n_zh, n_en = len(by_track.get(TRACK_ZH, [])), len(by_track.get(TRACK_EN, []))
    obs.metrics["count_zh"], obs.metrics["count_en"] = n_zh, n_en
    obs.metrics["count_diff"] = n_zh - n_en
    if abs(n_zh - n_en) > COUNT_DIFF_SUSPECT:
        obs.suspect(
            "track_count", [],
            "中英条数不等且差 > %d（中 %d / 英 %d，差 %d）。"
            "注意：**差 1–2 条通常是正常的**（中文并句、尾部版权行），"
            "差得多要看是不是缺行/多行。"
            % (COUNT_DIFF_SUSPECT, n_zh, n_en, n_zh - n_en))


def check_offset_profile(by_track: dict, obs: _Observations) -> None:
    """中英两轨起点偏差的分布（最近邻口径）。"""
    zh = sorted((e.start for e in by_track.get(TRACK_ZH, [])))
    en = sorted((e.start for e in by_track.get(TRACK_EN, [])))
    if not zh or not en:
        obs.notes.append("轨不足两条，跳过中英偏差分布检查。")
        return
    devs = []
    for s in zh:
        i = bisect.bisect_left(en, s)
        cand = []
        if i < len(en):
            cand.append(en[i] - s)
        if i > 0:
            cand.append(en[i - 1] - s)
        if cand:
            devs.append(min(cand, key=abs))
    if not devs:
        return
    absd = [abs(d) for d in devs]
    p50, p90, mx = _pct(absd, 0.5), _pct(absd, 0.9), max(absd)
    obs.metrics["off_p50"] = round(p50, 2)
    obs.metrics["off_p90"] = round(p90, 2)
    obs.metrics["off_max"] = round(mx, 2)
    # 有符号中位：整轨平移会让它显著偏离 0，而阶跃会让 p90 远大于 p50。
    obs.metrics["off_signed_p50"] = round(_pct(devs, 0.5), 2)
    if p50 > OFF_P50_SUSPECT or mx > OFF_MAX_SUSPECT:
        obs.suspect(
            "offset_profile", [],
            "中英起点偏差偏大：p50 %.2fs / p90 %.2fs / max %.2fs"
            "（阈值 p50 > %.1fs 或 max > %.1fs）。"
            "p90 远超 p50 通常是**阶跃**（中段起整体错位），"
            "有符号中位大幅偏离 0 则是**整轨平移**。"
            % (p50, p90, mx, OFF_P50_SUSPECT, OFF_MAX_SUSPECT))


def check_fragment_dups(by_track: dict, obs: _Observations) -> None:
    """残片重复：某行与相邻行相似度 > 0.9。

    `#371` 那类重复残片——同一句话被拆成两行插在同一位置，字幕上看起来是
    「卡了一下」，机器看不出，人眼也只是觉得别扭。
    """
    hits = []
    for track in (TRACK_ZH, TRACK_EN):
        evs = by_track.get(track, [])
        for i in range(1, len(evs)):
            a = normalize_for_compare(evs[i - 1].text)
            b = normalize_for_compare(evs[i].text)
            if not a or not b:
                continue
            r = SequenceMatcher(None, a, b).ratio()
            if r > DUP_RATIO and abs(evs[i].start - evs[i - 1].start) < 0.05:
                hits.append({"track": track, "prev": evs[i - 1].text[:20],
                             "cur": evs[i].text[:20], "ratio": round(r, 2),
                             "start": evs[i].start})
    if hits:
        obs.metrics["dup_rows"] = len(hits)
        obs.suspect(
            "fragment_dup", [],
            "相邻残片高度相似且起点几乎重合，共 %d 处（例：%s @ %.2fs，"
            "相似度 %.2f）。" % (len(hits), hits[0]["cur"], hits[0]["start"],
                                hits[0]["ratio"]))


def check_durations(by_track: dict, obs: _Observations) -> None:
    too_long, too_short = [], []
    for track in (TRACK_ZH, TRACK_EN):
        for e in by_track.get(track, []):
            d = e.end - e.start
            if d > DUR_SUSPECT_HIGH:
                too_long.append((e.start, d, e.text[:20]))
            elif 0 < d < DUR_SUSPECT_LOW:
                too_short.append((e.start, d, e.text[:20]))
    obs.metrics["dur_long"] = len(too_long)
    obs.metrics["dur_short"] = len(too_short)
    if too_long:
        obs.suspect("duration_long", [],
                    "时长 > %.0fs 的条目 %d 条（例：%.2fs @ %.2fs「%s」）。"
                    "通常是两条被合并成一条。" % (
                        DUR_SUSPECT_HIGH, len(too_long),
                        too_long[0][1], too_long[0][0], too_long[0][2]))
    if too_short:
        obs.suspect("duration_short", [],
                    "时长 < %.1fs 的条目 %d 条（例：%.2fs @ %.2fs「%s」）。"
                    "可能是误切。" % (
                        DUR_SUSPECT_LOW, len(too_short),
                        too_short[0][1], too_short[0][0], too_short[0][2]))


def check_tail_drift(by_track: dict, obs: _Observations) -> None:
    zh = by_track.get(TRACK_ZH, [])
    en = by_track.get(TRACK_EN, [])
    if not zh or not en:
        return
    z_end, e_end = max(e.end for e in zh), max(e.end for e in en)
    drift = z_end - e_end
    obs.metrics["tail_drift"] = round(drift, 2)
    if abs(drift) > TAIL_DRIFT_SUSPECT:
        obs.suspect(
            "tail_drift", [],
            "中英末条时间差 %.2fs（> %.0fs）。可能是累计漂移，也可能是中文轨尾部"
            "多出「字幕由…提供」这类版权行。" % (drift, TAIL_DRIFT_SUSPECT))


# ── 编排 ───────────────────────────────────────────────────────────────────

def check(ass_path: str) -> _Observations:
    obs = _Observations(ass_path)
    if not os.path.exists(ass_path):
        obs.abort("missing_file", [], "文件不存在：%s" % ass_path)
        return obs

    events = parse_ass(ass_path)
    obs.metrics["events"] = len(events)
    if not events:
        obs.abort("no_events", [], "解析出 0 条 Dialogue。这不是「干净」，是没读到。")
        return obs

    by_track: dict = {}
    for e in events:
        by_track.setdefault(e.track, []).append(e)
    for k in by_track:
        by_track[k].sort(key=lambda x: x.start)
    obs.metrics["tracks"] = {k: len(v) for k, v in by_track.items()}

    # 门禁级（ABORT）先跑：轨坏了就不必再谈偏差分布——那些数字本身就是脏的。
    check_track_enum(events, obs)
    check_zero_duration(events, obs)
    if obs.aborts:
        return obs

    check_track_counts(by_track, obs)
    check_offset_profile(by_track, obs)
    check_fragment_dups(by_track, obs)
    check_durations(by_track, obs)
    check_tail_drift(by_track, obs)
    return obs


def render(obs: _Observations) -> str:
    """人读的报告。ABORT 在前，SUSPECT 在后，观测值附在末尾。"""
    L = ["# 结构粗检 — %s" % os.path.basename(obs.path), ""]
    if obs.aborts:
        L += ["> **结论：ABORT** — 轨是坏的，先修轨再谈审校。", ""]
        L += ["## 必须修（ABORT）", ""]
        for a in obs.aborts:
            rows = a["rows"]
            shown = ", ".join("#%d" % r for r in rows[:12])
            more = "" if len(rows) <= 12 else " …共 %d 行" % len(rows)
            L += ["### %s" % a["kind"], "",
                  a["msg"], "",
                  "- 违规行：%s%s" % (shown or "（无行号）", more), ""]
        L += ["> 这些是**结构性**错误，脚本不给修法。零时长碎片怎么处理、"
                  "污染行按哪条重排，都要看上下文——那是判断，归审计。", ""]
    else:
        L += ["> **结论：可开工**%s" % ("（有 SUSPECT，见下）" if obs.suspects else ""),
              ""]

    if obs.suspects:
        L += ["## 值得看（SUSPECT）", ""]
        L += ["| 判据 | 观测 |", "|---|---|"]
        for s in obs.suspects:
            L.append("| %s | %s |" % (s["kind"], s["msg"].replace("\n", " ")))
        L += ["", "> SUSPECT 不是错误，是「这个数字不对劲，值得看一眼」。"
                  "看完认为没事，请在报告里写一句为什么，别让它变成没人管的告警。", ""]

    L += ["## 观测值", "", "| 项 | 值 |", "|---|---|"]
    m = obs.metrics
    for k in ("events", "tracks", "count_zh", "count_en", "count_diff",
              "off_p50", "off_p90", "off_max", "off_signed_p50",
              "dur_long", "dur_short", "dup_rows", "tail_drift",
              "zero_dur_rows", "same_start_rows", "bad_track_rows"):
        if k in m:
            v = m[k]
            if k == "tracks" and isinstance(v, dict):
                v = " / ".join("%s %d" % (a, b) for a, b in v.items())
            L.append("| %s | %s |" % (k, v))
    L.append("")
    for n in obs.notes:
        L.append("- " + n)
    return "\n".join(L)


EXIT_OK, EXIT_ABORT, EXIT_SUSPECT = 0, 20, 21


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="中英双轨结构粗检（开工前门禁）。只观测，不给修法。")
    ap.add_argument("--ass", required=True, help="待检 ASS")
    ap.add_argument("--report", default="", help="把报告写到这个路径")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args(argv)

    obs = check(args.ass)
    text = render(obs)
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text)
    if args.quiet:
        if obs.aborts:
            print("ABORT %d 项结构错误：%s" % (
                len(obs.aborts), ", ".join(a["kind"] for a in obs.aborts)))
        elif obs.suspects:
            print("SUSPECT %d 项：%s" % (
                len(obs.suspects), ", ".join(s["kind"] for s in obs.suspects)))
        else:
            print("OK 结构正常")
    else:
        print(text)

    if obs.aborts:
        return EXIT_ABORT
    return EXIT_SUSPECT if obs.suspects else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
