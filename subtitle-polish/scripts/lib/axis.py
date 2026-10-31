# -*- coding: utf-8 -*-
"""轴归属判定：从多条候选基准里选出哪一条与音频同轴。

旧实现是 `min(mad)` —— **排序问题**。排序永远有答案，于是四条流全是 0.62 时
它照样宣布「最贴合的是 s1.us」；0.220 vs 0.240 也会判出一个明确的赢家，而
whisper 的 MAD 噪声带就是 0.15~0.25。

判轴实际是**假设检验问题**：可以失败。本模块就为了留出这个出口
（skill-forge issue #11）。

四态：

    RESOLVED      绝对门过 + 裕度门过，chosen 可信
    AMBIGUOUS     有候选过绝对门，但没有明确赢家 —— 不许猜
    NO_CANDIDATE  没有任何候选过绝对门 —— 全是错的
    SINGLE_PASS   只有一条候选且它过 —— 放行，但记录「没交叉验证」

拿错轴的后果不是「没修好」，是**把对的改坏**。所以宁可判 AMBIGUOUS 让人来看。
"""
from __future__ import annotations

import re

from . import verdict as V

#: 绝对差下限：低于这个差值，两条候选在 whisper 噪声内不可区分
MIN_MARGIN = 0.10
#: 相对差：0.60 vs 0.72 绝对差 0.12 过得了 0.10，但相对只差 20%，不该算判出来
REL_MARGIN = 0.40
#: 同族阈值：MAD 与锚点数都相同，说明是同一条轴的不同变体（如 SDH / 非 SDH）
FAMILY_TOL = 0.02


def parse_stream_tag(name: str) -> dict:
    """从文件名里认流信息：`S06E01.s0.uk.srt` -> {index: 0, family: "UK", sdh: False}。

    `extract_subs` 抽流时按 `<stem>.s<k>.<tag>.<ext>` 命名，所以这里能反解。
    认不出就返回 unknown —— 不猜。
    """
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    out = {"index": None, "family": "unknown", "sdh": False, "file": base}
    m = re.search(r"\.s(\d+)\.", base)
    if m:
        out["index"] = int(m.group(1))
    low = base.lower()
    if re.search(r"(^|[._-])uk([._-]|$)|united[ ._-]?kingdom", low):
        out["family"] = "UK"
    elif re.search(r"(^|[._-])us([._-]|$)|united[ ._-]?states", low):
        out["family"] = "US"
    if "sdh" in low:
        out["sdh"] = True
    return out


def families(cands: list) -> list:
    """把候选按「同一条轴」聚类。

    判据：MAD 差 < FAMILY_TOL 且锚点数相同。实测 s0.uk 与 s2.uk.sdh 的 MAD、
    锚点数逐位相同（SDH 只是多了音效描述行），它们不是两个选项。
    """
    out = []
    for c in sorted(cands, key=lambda x: x["mad"]):
        for fam in out:
            rep = fam[0]
            if (abs(c["mad"] - rep["mad"]) < FAMILY_TOL
                    and c.get("n_pairs") == rep.get("n_pairs")):
                fam.append(c)
                break
        else:
            out.append([c])
    return out


def adjudicate(cands: list, min_margin: float = MIN_MARGIN,
               rel_margin: float = REL_MARGIN) -> dict:
    """cands: [{"label", "mad", "ok", "n_pairs"}] -> 判定 dict。

    `ok` 是候选自己的绝对门（分时段极差 ≤ tol）。没有它，`min(mad)` 会把
    「四条都错」也判出一个赢家。
    """
    cands = [c for c in (cands or []) if c.get("mad") is not None]
    if not cands:
        return {"verdict": "NO_CANDIDATE", "code": V.UNVERIFIED, "chosen": None,
                "reason": "没有可比较的候选（--compare 全部锚点不足）",
                "families": []}

    fams = families(cands)
    # 族代表 = 族内 MAD 最小者
    reps = [min(f, key=lambda x: x["mad"]) for f in fams]
    feasible = [r for r in reps if r.get("ok")]
    detail = {"families": [[c["label"] for c in f] for f in fams],
              "reps": [{"label": r["label"], "mad": r["mad"]} for r in reps]}

    if not feasible:
        best = min(reps, key=lambda x: x["mad"])
        return dict(detail, verdict="NO_CANDIDATE", code=V.FAIL, chosen=None,
                    mad=best["mad"], runner_up=None, runner_mad=None, margin=None,
                    reason="%d 条候选全部未过绝对门（最低 MAD %.3f），没有可信基线"
                           % (len(cands), best["mad"]))

    if len(reps) == 1:
        r = reps[0]
        return dict(detail, verdict="SINGLE_PASS", code=V.PASS, chosen=r["label"],
                    mad=r["mad"], runner_up=None, runner_mad=None, margin=None,
                    cross_checked=False,
                    reason="只有一条候选，未经交叉验证")

    best = min(feasible, key=lambda x: x["mad"])
    others = [r for r in reps if r["label"] != best["label"]]
    runner = min(others, key=lambda x: x["mad"])
    margin = runner["mad"] - best["mad"]
    need = max(min_margin, best["mad"] * rel_margin)
    base = dict(detail, chosen=best["label"], mad=best["mad"],
                runner_up=runner["label"], runner_mad=runner["mad"],
                margin=round(margin, 4), margin_need=round(need, 4),
                cross_checked=True)

    if margin >= need:
        return dict(base, verdict="RESOLVED", code=V.PASS,
                    reason="%s（MAD %.3f）领先次优 %.3f ≥ %.3f"
                           % (best["label"], best["mad"], margin, need))

    return dict(base, verdict="AMBIGUOUS", code=V.AMBIGUOUS, chosen=None,
                reason="%s（%.3f）与 %s（%.3f）差 %.3f < %.3f，在噪声内不可区分"
                       % (best["label"], best["mad"], runner["label"],
                          runner["mad"], margin, need))


def render(res: dict) -> str:
    """判定 -> 几行可读文本。"""
    L = []
    fams = res.get("families") or []
    if fams:
        L.append("  轴族 %d 个：" % len(fams))
        for f in fams:
            L.append("    " + "  ".join(f))
    L.append("  判定 %s —— %s" % (res["verdict"], res.get("reason", "")))
    return "\n".join(L)
