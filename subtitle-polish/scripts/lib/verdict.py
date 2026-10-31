# -*- coding: utf-8 -*-
"""三态判定常量：全 skill 唯一来源。

为什么需要这个模块：时间轴相关的判定原本只有「过 / 不过」两种，而实际有
三种状态——验了过、验了不过、**没验**。第三种被并进了第一种，于是
「没验时间轴」也会被算成通过（skill-forge issue #10）。

四态与退出码：

    PASS        0   验了，过        允许结案
    FAIL        2   验了，不过      不许结案
    UNVERIFIED  3   没验 / 凭据失效  不许结案，只能标 UNVERIFIED 交付
    AMBIGUOUS   4   验了但判不出来   不许结案（如多条候选轴无法区分）

约定：所有脚本 `main()` 结束时用 `sys.exit(code)`，不要 `return`（`return`
在 `if __name__ == "__main__"` 里不会变成退出码）。诊断信息走 stderr，
判定结论走 stdout —— 这样 `| tee` 之后仍能读到结论。
"""
from __future__ import annotations

PASS = 0
FAIL = 2
UNVERIFIED = 3
AMBIGUOUS = 4

LABELS = {
    PASS: "PASS",
    FAIL: "FAIL",
    UNVERIFIED: "UNVERIFIED",
    AMBIGUOUS: "AMBIGUOUS",
}

#: 允许在结案报告里写「通过」的状态
OK_CODES = (PASS,)


def label(code: int) -> str:
    """退出码 -> 状态名。未知码原样返回，避免掩盖问题。"""
    return LABELS.get(code, "CODE_%s" % code)


def from_verdict(text: str) -> int:
    """凭据里的 verdict 字符串 -> 退出码。"""
    t = (text or "").strip().upper()
    if t == "PASS":
        return PASS
    if t == "FAIL":
        return FAIL
    if t in ("AMBIGUOUS", "AXIS_AMBIGUOUS"):
        return AMBIGUOUS
    return UNVERIFIED


def can_close(code: int) -> bool:
    """这条判定能不能用来结案。"""
    return code in OK_CODES
