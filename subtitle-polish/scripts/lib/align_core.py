# -*- coding: utf-8 -*-
"""align_core.py — 音频对齐审计与修复的共用底座。

核心量：

    delta = 语音发声时刻 − 字幕显示时刻

正常应 +0.10 ~ +0.20 s（字幕略早于发声）。**判据不是「delta 是否为 0」，
而是「分时段 delta 中位数是否平坦」**——窗间极差即该集最大系统性残差。

本模块只做「读字幕 / 对齐词流 / 算统计」，不 import 任何音频库。
ASR 转录与强制对齐由 align_audit.py 注入统一的词级时间戳 tokens：

    tokens = [(start_sec, end_sec, text), ...]

读字幕两套路径，各有分工：
  - `load_rows()` 走 pysubs2，供审计（只读，要容错）；
  - `read_ass_raw()` 走行级原样读，供 align_patch 做「只改时间字段」的
    字节安全写回（pysubs2 保存会重排样式段、丢注释，改时间不该付这个代价）。
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess

import pysubs2

from .ass_srt_pair import TRACK_EN, style_to_track
from .time_fmt import seconds_to_ass, seconds_to_srt

AUDIO_EXT = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
SUB_EXT = {".ass", ".ssa", ".srt"}

_TS_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})[,.:](\d{1,3})$")
_TAG_RE = re.compile(r"\{[^}]*\}")
_APOS_RE = re.compile(r"[\u2018\u2019\u02bc]")
_WORD_JUNK_RE = re.compile(r"[^a-z0-9' ]+")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------- 时间戳

def ts_to_sec(text: str) -> float:
    """ASS `0:01:23.45` / SRT `00:01:23,450` -> 秒。"""
    m = _TS_RE.match((text or "").strip())
    if not m:
        raise ValueError("无法解析时间戳: %r" % (text,))
    h, mi, se, frac = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(frac) / (10 ** len(frac))


def sec_to_ass(sec: float) -> str:
    return seconds_to_ass(sec)


def sec_to_srt(sec: float) -> str:
    return seconds_to_srt(sec)


# ---------------------------------------------------------------- 文本

def clean_text(text: str) -> str:
    """去 ASS 标签、换行符、音符、破折号，合并空白。"""
    t = _TAG_RE.sub("", text or "")
    t = t.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    for ch in ("♪", "♫", "—", "–", "\u00a0"):
        t = t.replace(ch, " ")
    return _WS_RE.sub(" ", t).strip()


def words_of(text: str):
    """英文词序列：小写、直引号、去标点。"""
    t = _APOS_RE.sub("'", clean_text(text).lower())
    t = _WORD_JUNK_RE.sub(" ", t)
    return [w for w in t.split() if w]


# ---------------------------------------------------------------- 读取

def load_rows(path: str, track=TRACK_EN):
    """读字幕为 [(start_sec, end_sec, text)]，按起始时间排序。

    .ass/.ssa：按 track 过滤（`track=None` 表示不过滤，取全部对白）。
    .srt/.vtt：全量。注释行跳过。
    """
    subs = pysubs2.load(path, encoding="utf-8-sig")
    is_ass = path.lower().endswith((".ass", ".ssa"))
    rows = []
    for ev in subs:
        if getattr(ev, "is_comment", False):
            continue
        if is_ass and track and style_to_track(ev.style) != track:
            continue
        rows.append((ev.start / 1000.0, ev.end / 1000.0, ev.text))
    rows.sort(key=lambda r: r[0])
    return rows


def read_ass_raw(path: str):
    """行级原样读取 ASS，返回 (lines, events)。

    events 保留 `parts`（Dialogue: 后按 9 段切分）与 `line_no`，
    写回时只替换 parts[1](start) / parts[2](end)，其余字符原样不动。
    """
    lines, events, in_events, fmt = [], [], False, None
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            lines.append(line)
            st = line.strip()
            if st.startswith("[") and st.endswith("]"):
                in_events = st.lower() == "[events]"
                continue
            if not in_events:
                continue
            if line.startswith("Format:"):
                fmt = [x.strip().lower() for x in line[7:].split(",")]
                continue
            if line.startswith("Dialogue:") and fmt:
                parts = line[9:].split(",", 9)
                d = dict(zip(fmt, parts))
                try:
                    events.append({
                        "line_no": len(lines) - 1,
                        "parts": parts,
                        "style": d.get("style", ""),
                        "start": ts_to_sec(d["start"]),
                        "end": ts_to_sec(d["end"]),
                    })
                except (ValueError, KeyError):
                    continue
    return lines, events


def read_srt_raw(path: str):
    """行级原样读取 SRT，返回 (lines, blocks)。

    blocks: [{'line_no': 时间行下标, 'start': s, 'end': s}]。
    """
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        lines = [ln.rstrip("\r\n") for ln in f]
    blocks = []
    for i, line in enumerate(lines):
        if "-->" not in line:
            continue
        try:
            a, b = [x.strip() for x in line.split("-->", 1)]
            blocks.append({"line_no": i, "start": ts_to_sec(a), "end": ts_to_sec(b)})
        except ValueError:
            continue
    return lines, blocks


def write_lines(path: str, lines, newline: str):
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        for ln in lines:
            f.write(ln + "\n")


# ---------------------------------------------------------------- 词流对齐

def flatten_rows(rows):
    """字幕行 -> 词流 (+ 每个词归属的行号)。"""
    words, owner = [], []
    for i, (_st, _en, tx) in enumerate(rows):
        for w in words_of(tx):
            words.append(w)
            owner.append(i)
    return words, owner


def flatten_tokens(tokens):
    """词级时间戳 -> 词流 (+ 每个词归属的 token 下标)。"""
    words, src = [], []
    for j, (_st, _en, tx) in enumerate(tokens):
        ws = words_of(tx)
        if not ws:
            continue
        words.append(ws[0])  # 一个 token 多词时取首词，保持 1:1 便于回溯时间
        src.append(j)
    return words, src


def align_anchors(rows, tokens, min_block=1):
    """把外部词级时间戳对齐到字幕行。

    返回 `[(row_start, delta, row_idx)]`，每行只取**最早匹配到的词**作锚点：

        delta = token.start − row.start

    min_block: LCS 匹配块的最小词数（默认 1；调大可压制单词偶合噪声）。
    """
    sub_words, owner = flatten_rows(rows)
    tok_words, src = flatten_tokens(tokens)
    if not sub_words or not tok_words:
        return []
    sm = difflib.SequenceMatcher(None, sub_words, tok_words, autojunk=False)
    best = {}  # row_idx -> (token_start, sub_word_pos)
    for blk in sm.get_matching_blocks():
        if blk.size < min_block:
            continue
        for k in range(blk.size):
            si, ti = blk.a + k, blk.b + k
            ri = owner[si]
            if ri not in best or si < best[ri][1]:
                best[ri] = (tokens[src[ti]][0], si)
    return sorted((rows[i][0], best[i][0] - rows[i][0], i) for i in best)


def anchor_ratio(pairs, rows):
    return (len(pairs) / len(rows)) if rows else 0.0


# ---------------------------------------------------------------- 统计

def median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[len(s) // 2]


def mad_of(vals, center):
    if not vals:
        return 0.0
    return median([abs(v - center) for v in vals])


def robust_reject(pairs, k_mad=6.0, floor=1.5):
    """按中位/MAD 剔除「文本与音频不一致」的离群点。

    剔除对象是 ASR 听错、译文漏词、片头片尾噪声等——它们的 delta 不代表
    时间轴，留着会把回归斜率拉飞（实测未剔除时 E08 首跑斜率 +0.000660，
    真实值 −0.000080）。

    返回 (keep, info)。
    """
    ys = [p[1] for p in pairs]
    if not ys:
        return [], {"med": 0.0, "mad": 0.0, "thr": 0.0, "dropped": 0}
    med = median(ys)
    mad = mad_of(ys, med)
    thr = max(floor, k_mad * mad)
    keep = [p for p in pairs if abs(p[1] - med) <= thr]
    return keep, {"med": med, "mad": mad, "thr": thr, "dropped": len(pairs) - len(keep)}


def linear_fit(pairs):
    """最小二乘 y = kx + b。返回 (k, b, n, x_span)。"""
    n = len(pairs)
    if n < 2:
        return 0.0, 0.0, n, 0.0
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0
    return k, my - k * mx, n, xs[-1] - xs[0]


def window_table(pairs, window=180.0, min_n=5):
    """分时段 delta 中位数。返回 [{'lo','hi','n','median'}]。"""
    if not pairs:
        return []
    tmax = max(p[0] for p in pairs)
    out, lo = [], 0.0
    while lo <= tmax:
        hi = lo + window
        vals = [p[1] for p in pairs if lo <= p[0] < hi]
        if len(vals) >= min_n:
            out.append({"lo": lo, "hi": hi, "n": len(vals), "median": median(vals)})
        lo = hi
    return out


def summarize(pairs, window=180.0, tol=0.3, min_n=5):
    """一次算齐判据所需全部指标。

    判定用 `window_span`（分时段中位数极差），**不是** delta 是否接近 0：
    delta 有 +0.1~0.2s 的天然提前量，绝对值无意义，平坦度才有意义。
    """
    keep, rej = robust_reject(pairs)
    k, b, n, x_span = linear_fit(keep)
    win = window_table(keep, window, min_n)
    meds = [w["median"] for w in win]
    win_span = (max(meds) - min(meds)) if meds else 0.0
    center = median(meds) if meds else 0.0
    worst = max(win, key=lambda w: abs(w["median"] - center)) if win else None
    deltas = [p[1] for p in keep]
    return {
        "n_pairs": len(pairs),
        "n_keep": n,
        "reject": rej,
        "median": median(deltas),
        "mad": mad_of(deltas, median(deltas)),
        "slope": k,
        "intercept": b,
        "x_span": x_span,
        "drift": k * x_span,
        "window": window,
        "windows": win,
        "window_span": win_span,
        "worst_window": worst,
        "tol": tol,
        "ok": win_span <= tol,
    }


# ---------------------------------------------------------------- 媒体

def wav_duration(path: str):
    """wav 时长（秒）；读不出返回 None。"""
    try:
        import wave

        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None


def media_to_wav(media: str, out_dir: str, sr: int = 16000) -> str:
    """媒体文件 -> 单声道 16k wav（带缓存，媒体更新则重抽）。

    音频文件原样返回；视频/容器用 ffmpeg 抽轨。ffmpeg 不在 PATH 时报错退出。
    """
    ext = os.path.splitext(media)[1].lower()
    if ext in AUDIO_EXT:
        return media
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, "%s.%dk.wav" % (os.path.splitext(os.path.basename(media))[0], sr // 1000))
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(media):
        return dst
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("未找到 ffmpeg：抽音轨需要它。可先自行转成 wav 再用 --media 指过去。")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", media,
           "-vn", "-ac", "1", "-ar", str(sr), dst]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("ffmpeg 抽音轨失败：\n" + (proc.stderr or "")[-800:])
    return dst


# ---------------------------------------------------------------- 偏移函数

def offset_at(spec, t: float) -> float:
    """按 offset spec 求 t 时刻应施加的偏移（秒）。

    spec 三种：
      {"kind": "linear", "slope": k, "origin": t0}   -> k * (t - t0)
      {"kind": "curve",  "segments": [[t0, off], ...]} -> 阶梯取值
      {"kind": "step",   "points": [[t, off], ...]}    -> 同 curve（别名）
    """
    kind = (spec or {}).get("kind", "linear")
    if kind == "linear":
        return float(spec.get("slope", 0.0)) * (t - float(spec.get("origin", 0.0)))
    segs = spec.get("segments") or spec.get("points") or []
    if not segs:
        return 0.0
    cur = float(segs[0][1])
    for start, off in segs:
        if t >= float(start):
            cur = float(off)
        else:
            break
    return cur


def spec_from_linear(slope: float, origin: float):
    return {"kind": "linear", "slope": float(slope), "origin": float(origin)}


def spec_from_pairs(pairs, nseg=0):
    """把逐条偏移拟合成分段常数曲线（单调不减 + 首段归零）。

    单调约束：剪辑点只会让偏移单向累加，不会回退。
    首段归零：ASR/对齐器与字幕起点存在系统性偏置（实测 base −0.279s），
    不减去它就会把整集平推一段，反而制造新偏移。
    """
    segs = _segfit(pairs, nseg)
    if not segs:
        return {"kind": "curve", "segments": []}, 0.0
    run, fixed = -1e9, []
    for t0, t1, c in segs:
        run = max(run, c)
        fixed.append((t0, t1, run))
    base = fixed[0][2]
    return ({"kind": "curve",
             "segments": [[round(t0, 2), round(c - base, 4)] for t0, _t1, c in fixed]},
            base)


def _segfit(pairs, nseg=0, max_seg=9):
    """分段常数拟合：枚举段数，取 BIC 最小者。返回 [(t0, t1, const)]。"""
    import math

    pts = sorted(pairs)
    n = len(pts)
    if n < 8:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    def fit(k):
        # DP：把 n 个点切成 k 段，最小化各段内平方误差
        pre = [0.0] * (n + 1)
        pre2 = [0.0] * (n + 1)
        for i, y in enumerate(ys):
            pre[i + 1] = pre[i] + y
            pre2[i + 1] = pre2[i] + y * y

        def cost(i, j):  # [i, j)
            m = j - i
            s = pre[j] - pre[i]
            return (pre2[j] - pre2[i]) - s * s / m

        INF = float("inf")
        dp = [[INF] * (n + 1) for _ in range(k + 1)]
        bk = [[0] * (n + 1) for _ in range(k + 1)]
        dp[0][0] = 0.0
        for seg in range(1, k + 1):
            for j in range(seg, n + 1):
                best_v, best_i = INF, seg - 1
                for i in range(seg - 1, j):
                    v = dp[seg - 1][i] + cost(i, j)
                    if v < best_v:
                        best_v, best_i = v, i
                dp[seg][j] = best_v
                bk[seg][j] = best_i
        out, j = [], n
        for seg in range(k, 0, -1):
            i = bk[seg][j]
            m = j - i
            out.append((xs[i], xs[j - 1], (pre[j] - pre[i]) / m))
            j = i
        return list(reversed(out))

    candidates = [nseg] if nseg else list(range(2, max_seg + 1))
    best = None
    for k in candidates:
        if k >= n:
            continue
        segs = fit(k)
        rss = 0.0
        for t0, t1, c in segs:
            rss += sum((y - c) ** 2 for x, y in pts if t0 <= x <= t1)
        rss = max(rss, 1e-9)
        bic = n * math.log(rss / n) + 3 * k * math.log(n)
        if best is None or bic < best[0]:
            best = (bic, segs)
    return best[1] if best else []
