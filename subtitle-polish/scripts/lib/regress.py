# -*- coding: utf-8 -*-
"""跨轮次回归判定：把 log.jsonl 变成「这几行最近被改过什么」。

背景（skill-forge issue #5 / #6）：审计 agent 每轮拿到的只有**当前盘面 + 英文源**，
它不知道哪些行上周刚改过、为什么改。于是同一个 srt_id 可能被连续几轮来回改，
而 `verify_fixes` 每轮都是 0 失败、`cross_check` 每轮都是 0 预警——**没有任何
信号能发现这个矛盾**。

这里只用字符串判据，不需要模型：

  - **连续改动**：同一 (file, srt_id, track) 被 ≥2 个 batch 先后改过
  - **疑似反向**：新译文与**更早**版本的相似度 > 与**上一轮**版本的相似度
  - **已收敛**：连续两个 batch 给出相同的 new_text
  - **疑似回归**：本轮的 old_text 命中了历史某轮的 new_text（被改回去）

它们都只是「值得看一眼」的线索，不是结论。改回去有时是对的（上一轮确实改错了），
冻成硬门会制造新的「错误无法修正」。
"""
from __future__ import annotations

import difflib
import re

#: 算作「文本改动」的 action。retime / retime_curve 不参与——它们不动文本。
TEXT_ACTIONS = ("replace", "swap", "insert", "manual_edit")

_TAG_RE = re.compile(r"\{[^}]*\}")
_WS_RE = re.compile(r"\s+")


def clean(text: str) -> str:
    """去 ASS 覆盖标签 + 归一化空白。比较文本用，不用于写盘。"""
    if not text:
        return ""
    return _WS_RE.sub("", _TAG_RE.sub("", text)).strip()


def ratio(a: str, b: str) -> float:
    a, b = clean(a), clean(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def history(entries: list, file: str = "") -> dict:
    """log -> {(file, srt_id, track): [按时间序的改动]}。

    每条改动保留 batch_id，用来回溯「当时那条理由」。
    """
    out = {}
    for e in sorted(entries, key=lambda x: x.get("ts", "")):
        if e.get("action") not in TEXT_ACTIONS:
            continue
        if not e.get("srt_id"):
            continue
        if file and e.get("file") != file:
            continue
        key = (e.get("file", ""), int(e["srt_id"]), e.get("track", ""))
        out.setdefault(key, []).append({
            "batch": e.get("batch_id", ""),
            "ts": e.get("ts", ""),
            "old": e.get("old_text", ""),
            "new": e.get("new_text", ""),
            "category": e.get("category", ""),
            "reason": e.get("reason", ""),
        })
    return out


def conflicts(hist: dict, window: int = 3) -> list:
    """同一行被 ≥2 个 batch 先后改过。"""
    out = []
    for key, hs in hist.items():
        rounds = []
        for h in hs:
            if h["batch"] not in rounds:
                rounds.append(h["batch"])
        if len(rounds) < 2:
            continue
        use = hs if not window else hs[-window:]
        out.append({"key": key, "rounds": rounds, "trail": use,
                    "n_rounds": len(rounds)})
    out.sort(key=lambda x: (-x["n_rounds"], x["key"][1]))
    return out


def reversals(trail: list, min_sim: float = 0.85, edge: float = 0.15) -> list:
    """疑似「翻回去了」：新译文更像更早那版，而不是上一版。"""
    out = []
    for i in range(2, len(trail)):
        a, b, c = trail[i - 2]["new"], trail[i - 1]["new"], trail[i]["new"]
        s_ac, s_bc = ratio(a, c), ratio(b, c)
        if s_ac >= min_sim and s_ac > s_bc + edge:
            out.append({"at": i, "round": trail[i]["batch"],
                        "prev_round": trail[i - 1]["batch"],
                        "earlier_round": trail[i - 2]["batch"],
                        "sim_earlier": round(s_ac, 3),
                        "sim_prev": round(s_bc, 3),
                        "text": c})
    return out


def converged(trail: list) -> bool:
    """连续两轮给出相同结论。"""
    if len(trail) < 2:
        return False
    return clean(trail[-1]["new"]) == clean(trail[-2]["new"]) and trail[-1]["batch"] != \
        trail[-2]["batch"]


def find_regressions(current: list, past: list, floor: float = 0.55) -> list:
    """本轮的 old_text 命中历史某轮的 new_text —— 被改回去了。

    `floor` 沿用 cross_check 的撞车阈值 0.55，两个判据口径一致才不会一个报一个不报。

    取**最匹配**的那条历史，不是第一条过阈值的：issue #6 的轨迹里
    R6 与 R8 的文本相似度 0.62（过阈值），R7 与 R8 **完全相同**。
    先撞上 R6 就停会报出「near 0.62 R6」，而真正的证据是「exact R7」——
    指向错的那一轮，读报告的人会去查 R6 的理由，而该查的是 R7。
    """
    out = []
    for c in current:
        if c.get("action") not in TEXT_ACTIONS:
            continue
        old = c.get("old_text", "")
        if not clean(old):
            continue
        best = None
        for p in past:
            if p.get("batch_id") == c.get("batch_id"):
                continue
            if int(p.get("srt_id", 0)) != int(c.get("srt_id", -1)):
                continue
            if p.get("track") != c.get("track"):
                continue
            new_hist = p.get("new_text", "")
            if not clean(new_hist):
                continue
            if clean(old) == clean(new_hist):
                best = {"kind": "exact", "sim": 1.0, "cur": c, "hist": p}
                break  # 不可能比 1.0 更高
            s = ratio(old, new_hist)
            if s >= floor and (best is None or s > best["sim"]):
                best = {"kind": "near", "sim": round(s, 3), "cur": c, "hist": p}
        if best:
            out.append(best)
    return out


def ledger(hist: dict, window: int = 3) -> list:
    """给审计 prompt 用的台账行（最近 window 个 batch 的改动）。"""
    rows = []
    for key, hs in hist.items():
        use = hs[-window:] if window else hs
        for h in use:
            rows.append({
                "srt_id": key[1], "track": key[2], "file": key[0],
                "batch": h["batch"], "old": h["old"], "new": h["new"],
                "category": h["category"], "reason": h["reason"],
            })
    rows.sort(key=lambda r: (r["srt_id"], r["batch"]))
    return rows
