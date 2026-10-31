# -*- coding: utf-8 -*-
"""时间轴凭据（sidecar）：把「这条字幕的轴凭什么可信」变成一个可校验的文件。

背景（skill-forge issue #9）：`SKILL.md` 的输入契约写了「ASS + SRT」，对时间轴
一个字没要求，于是「时间轴是对的」退化成了常识假设——常识假设没人验。8 集里
3 集偏 2.4~2.9 秒而全流程全绿，就是因为这个状态在流程里不存在。

本模块把状态存成 `<episode>.ts.json`，并给出**唯一一处**判定逻辑 `check()`：

    1. 凭据不存在                        -> UNVERIFIED
    2. 凭据绑定了片源但没给 --media        -> UNVERIFIED   无法确认没换片
    3. media.sha1 与当前片源不符           -> UNVERIFIED   换片了
    4. files[].sha1 与当前文件不符         -> UNVERIFIED   文件被外部改过
    5. files[].patched_at > computed_at   -> UNVERIFIED   改过时间轴但没复测
    6. axis.verdict 不是 PASS            -> 按原样透传 FAIL(2) / AMBIGUOUS(4)
    7. 其余                               -> PASS

**顺序有意义**：陈旧性（2~5）必须排在 verdict（6）前面。一份写着 PASS 的凭据，
如果文件之后又被改过，它描述的是过去的状态——此时原来 PASS 还是 FAIL 都不作数。
顺序写反会得到「凭据过期了但照样放行」。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from typing import Optional

from . import verdict as V

SIDECAR_SUFFIX = ".ts.json"
SCHEMA_VERSION = 1


# ---------------------------------------------------------------- 基础

def sidecar_path(sub_path: str) -> str:
    """`S06E01.ass` -> 同目录 `S06E01.ts.json`。

    取「第一个点之前」的部分做 stem：`S06E01.eng.ass` 与 `S06E01.srt` 会落到
    同一个 sidecar——它们本来就共用一条轴，分开存会得到两份可能互相矛盾的凭据。
    """
    d = os.path.dirname(os.path.abspath(sub_path))
    base = os.path.basename(sub_path)
    stem = base.split(".")[0] if "." in base else base
    return os.path.join(d, stem + SIDECAR_SUFFIX)


def sha1_of(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def fingerprint(path: str) -> dict:
    """片源指纹：size + sha1。

    size 先比是为了省时间——换片源最常见的情形是大小不同，那时不必读几个 GB。
    """
    if not os.path.exists(path):
        return {"path": os.path.abspath(path), "size": -1, "sha1": ""}
    st = os.stat(path)
    return {"path": os.path.abspath(path), "size": st.st_size, "sha1": sha1_of(path)}


def probe_duration(path: str) -> Optional[float]:
    """时长（秒）。wav 走标准库，其余走 ffprobe；取不到返回 None。"""
    if not path or not os.path.exists(path):
        return None
    if path.lower().endswith(".wav"):
        try:
            import wave
            with wave.open(path, "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:
            pass
    ff = shutil.which("ffprobe")
    if not ff:
        return None
    try:
        out = subprocess.run(
            [ff, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60)
        return float((out.stdout or "").strip())
    except Exception:
        return None


def episode_of(path: str) -> str:
    base = os.path.basename(path)
    return base.split(".")[0] if "." in base else base


def _now() -> str:
    # 微秒精度不是洁癖：`align_patch` 与 `align_audit` 在自动化脚本里可能落在
    # 同一秒内，秒级精度会让「改过没复测」判不出来。
    return datetime.now().isoformat(timespec="microseconds")


def _parse_ts(text: str):
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except Exception:
        return None


def _newer(a: str, b: str) -> bool:
    """a 是否晚于 b。任一侧解析不了时退回字符串比较（同格式下等价）。"""
    ta, tb = _parse_ts(a), _parse_ts(b)
    if ta and tb:
        # 一边带时区一边不带会抛 TypeError，退回字符串比较
        try:
            return ta > tb
        except TypeError:
            pass
    return str(a) > str(b)


# ---------------------------------------------------------------- 读写

def load(sub_path: str) -> Optional[dict]:
    """读凭据；不存在或读不出返回 None（不抛，让调用方决定怎么报）。"""
    p = sidecar_path(sub_path)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save(sub_path: str, data: dict) -> str:
    p = sidecar_path(sub_path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    data["version"] = SCHEMA_VERSION
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return p


def build(sub_path: str, stats: dict, engine: str, media: Optional[str] = None,
          source: Optional[dict] = None, l0: Optional[dict] = None,
          cross_checked: bool = False) -> dict:
    """由一次 align_audit 的结果组装凭据。

    `files[]` 保留此前记录过、且当前仍与盘面一致的条目：同一个 episode 的
    ASS 与 SRT 可能分别被审计/修改过，每次重建只留当前文件会把另一条悄悄删掉。
    已经变过的旧条目则丢弃——留着它就等于留下一句假话。
    """
    name = os.path.basename(sub_path)
    files = []
    if os.path.exists(sub_path):
        files.append({
            "path": name,
            "sha1": sha1_of(sub_path),
            "patched_at": None,
            "max_shift": 0.0,
            "patches": 0,
        })
    prev = load(sub_path) or {}
    base_dir = os.path.dirname(os.path.abspath(sub_path))
    for f in prev.get("files") or []:
        p = f.get("path") or ""
        if not p or p == name:
            continue
        full = p if os.path.isabs(p) else os.path.join(base_dir, p)
        if not os.path.exists(full):
            continue
        if f.get("sha1") and sha1_of(full) != f["sha1"]:
            continue          # 已经变了，别把旧结论带进新凭据
        files.append(f)
    data = {
        "version": SCHEMA_VERSION,
        "episode": episode_of(sub_path),
        "media": {
            "path": os.path.abspath(media) if media else None,
            "sha1": "",
            "duration": None,
        },
        "source": source or {"kind": "unknown", "index": None, "title": None,
                             "family": "unknown"},
        "axis": {
            "engine": engine,
            "anchors": stats.get("n_pairs"),
            "total": None,
            "mad": stats.get("mad"),
            "drift": stats.get("drift"),
            "window_span": stats.get("window_span"),
            # 跨分块复核（qwen）：两种分块各给一个极差，判定看两者是否一致
            "window_spans": stats.get("window_spans"),
            "chunks": stats.get("chunks"),
            "verdict_reason": stats.get("verdict_reason"),
            "tol": stats.get("tol"),
            # 这里不能用 `"PASS" if ok else "FAIL"`：四态里还有 AMBIGUOUS，
            # 那样写会把它压成 FAIL，而「测不准」和「验出来是错的」不是一回事。
            "verdict": stats.get("verdict") or ("PASS" if stats.get("ok") else "FAIL"),
            "cross_checked": bool(cross_checked),
            "l0": l0,
        },
        "files": files,
        "computed_at": _now(),
    }
    if media and os.path.exists(media):
        fp = fingerprint(media)
        data["media"]["sha1"] = fp["sha1"]
        data["media"]["duration"] = probe_duration(media)
    return data


def touch_patch(sub_path: str, max_shift: float, n_events: int = 0) -> Optional[str]:
    """记一次时间轴改动：写 patched_at 并同步文件 sha1。

    同步 sha1 是必须的：`align_patch` 改完盘面，凭据里的旧 sha1 立刻不符，
    否则就会先触发「文件被外部改过」而不是更准确的「改过没复测」。

    没有凭据时静默返回 None —— 翻译前的第 0 步本来就没有审计结果，
    不该因为「还没有凭据」而挡住建轴。
    """
    data = load(sub_path)
    if not data:
        return None
    now = _now()
    name = os.path.basename(sub_path)
    cur = sha1_of(sub_path) if os.path.exists(sub_path) else ""
    hit = None
    for f in data.get("files") or []:
        if f.get("path") == name:
            hit = f
            break
    if hit is None:
        hit = {"path": name, "sha1": cur, "patched_at": None,
               "max_shift": 0.0, "patches": 0}
        data.setdefault("files", []).append(hit)
    hit["sha1"] = cur
    hit["patched_at"] = now
    hit["max_shift"] = round(float(max_shift), 4)
    hit["patches"] = int(hit.get("patches") or 0) + 1
    if n_events:
        hit["n_events"] = int(n_events)
    return save(sub_path, data)


# ---------------------------------------------------------------- 判定

def check(sub_path: str, media: Optional[str] = None) -> dict:
    """凭据是否可用于结案。

    返回 dict：verdict(退出码) / reasons(list) / detail(dict) / data(凭据或 None)

    核心原则：**凭据声明了什么，就必须验证什么。** 凭据里记了 media.sha1，
    这次却没给片源，就不能假装验过了——按 UNVERIFIED 处理。
    """
    reasons = []
    detail = {}

    data = load(sub_path)
    if not data:
        return {
            "verdict": V.UNVERIFIED,
            "reasons": ["无凭据：%s 不存在" % sidecar_path(sub_path)],
            "detail": {"sidecar": sidecar_path(sub_path)},
            "data": None,
        }

    detail["sidecar"] = sidecar_path(sub_path)
    detail["computed_at"] = data.get("computed_at")
    detail["axis_verdict"] = (data.get("axis") or {}).get("verdict")
    stale = False

    # --- 2. 片源绑定
    rec_media = data.get("media") or {}
    if rec_media.get("sha1"):
        if not media:
            stale = True
            reasons.append("凭据绑定了片源（%s…），但本次未提供 --media，"
                           "无法确认没换片"
                           % str(rec_media.get("sha1"))[:8])
        elif not os.path.exists(media):
            stale = True
            reasons.append("片源不存在：%s" % media)
        else:
            cur = fingerprint(media)
            if cur["sha1"] != rec_media["sha1"]:
                stale = True
                reasons.append("片源已换（sha1 %s → %s），凭据失效，须重验"
                               % (str(rec_media.get("sha1"))[:8], cur["sha1"][:8]))
            detail["media_sha1"] = cur["sha1"]

    # --- 3/4. 文件与复测时间
    base_dir = os.path.dirname(os.path.abspath(sub_path))
    files = data.get("files") or []
    if not files:
        stale = True
        reasons.append("凭据里没有 files[]，无法确认成品文件未变")
    for f in files:
        p = f.get("path") or ""
        full = p if os.path.isabs(p) else os.path.join(base_dir, p)
        if not os.path.exists(full):
            stale = True
            reasons.append("凭据记录的文件不存在：%s" % p)
            continue
        if f.get("sha1") and sha1_of(full) != f["sha1"]:
            stale = True
            reasons.append("文件内容已变（%s），凭据描述的是旧版本" % p)
        patched, computed = f.get("patched_at"), data.get("computed_at")
        if patched and computed and _newer(patched, computed):
            stale = True
            reasons.append("改过时间轴但未复测（patched_at %s > computed_at %s）"
                           % (patched, computed))

    if stale:
        return {"verdict": V.UNVERIFIED, "reasons": reasons,
                "detail": detail, "data": data}

    # --- 5. verdict
    av = (data.get("axis") or {}).get("verdict")
    code = V.from_verdict(av)
    if code != V.PASS:
        reasons.append("凭据判定为 %s（极差 %s s / 阈值 %s s）"
                       % (av or "缺失",
                          _num((data.get("axis") or {}).get("window_span")),
                          _num((data.get("axis") or {}).get("tol"))))
        return {"verdict": code, "reasons": reasons, "detail": detail, "data": data}

    return {"verdict": V.PASS, "reasons": [], "detail": detail, "data": data}


def _num(x) -> str:
    try:
        return "%.2f" % float(x)
    except (TypeError, ValueError):
        return "—"


def render(res: dict) -> str:
    """把 check() 结果渲染成几行文本（stdout 用）。"""
    code = res["verdict"]
    data = res.get("data") or {}
    d = res.get("detail") or {}
    ax = data.get("axis") or {}
    lines = []
    lines.append("凭据  %s" % (d.get("sidecar") or "（无）"))
    if data:
        lines.append("      计算于 %s · 引擎 %s · 锚点 %s"
                     % (d.get("computed_at") or "—", ax.get("engine") or "—",
                        ax.get("anchors") if ax.get("anchors") is not None else "—"))
        lines.append("      极差 %s s / 阈值 %s s · MAD %s -- %s"
                     % (_num(ax.get("window_span")), _num(ax.get("tol")),
                        _num(ax.get("mad")), ax.get("verdict") or "—"))
        src = data.get("source") or {}
        if src.get("family") and src.get("family") != "unknown":
            lines.append("      来源流 %s%s"
                         % (("#%s " % src["index"]) if src.get("index") is not None else "",
                            src.get("family")))
        if ax.get("cross_checked") is False:
            lines.append("      ⚠ 仅一条候选，未经交叉验证（cross_checked=false）")
    for r in res.get("reasons") or []:
        lines.append("  ✗ " + r)
    lines.append("判定  %s" % V.label(code))
    return "\n".join(lines)

