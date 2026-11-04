# -*- coding: utf-8 -*-
"""下游验证报告的「作废」状态（issue #45 的机制部分）。

回滚 / 整轮还原会改盘面，但 `reports/verify-fixes.md` 与 `reports/cross-check.md`
是**上一次盘面**的结论。它们留在原处，下一次 `--report` 就会把旧结论当成当前
状态读走——S06E04 实测回滚后 final-report 仍写「净改动 8 条」、验证仍显示旧绿，
根因就是残留文件，而不是某一行代码写错。

作废动作：
  1. 旧报告改名为 `<name>.stale-<时间戳>.md`（保留取证价值，不再被当作当前结论）；
  2. 写 `reports/verify-state.json`，记下作废时间、原因、涉及的报告。

重跑 verify / cross_check 时各清自己那一项；读取方只看原文件名 + 状态文件：
看到作废就写「已作废，需重跑」，而不是沿用旧数字。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

STATE_NAME = "verify-state.json"
DEFAULT_REPORTS = ("verify-fixes.md", "cross-check.md")


def _reports_dir(work_dir: str) -> str:
    return os.path.join(work_dir, "reports")


def _state_path(work_dir: str) -> str:
    return os.path.join(_reports_dir(work_dir), STATE_NAME)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def state(work_dir: str) -> dict:
    """读作废状态；没有则返回空 dict。"""
    p = _state_path(work_dir)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(work_dir: str, data: dict) -> None:
    p = _state_path(work_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not data.get("names"):
        if os.path.exists(p):
            os.remove(p)
        return
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def invalidate(work_dir: str, reason: str, names=DEFAULT_REPORTS) -> list:
    """把 `names` 指的报告标为作废，返回实际改名的文件列表。

    文件不存在也照样登记——「回滚后没跑过 verify」和「跑过但报告被删了」
    对读取方是同一件事：当前没有可信的验证结论。
    """
    rd = _reports_dir(work_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = []
    for name in names:
        src = os.path.join(rd, name)
        if not os.path.exists(src):
            continue
        stem, ext = os.path.splitext(name)
        dst = os.path.join(rd, f"{stem}.stale-{stamp}{ext}")
        try:
            os.replace(src, dst)
            moved.append(dst)
        except OSError:
            pass
    st = state(work_dir)
    merged = sorted(set((st.get("names") or []) + list(names)))
    _write_state(work_dir, {"invalidated_at": _now(), "reason": reason,
                            "names": merged, "archived": moved})
    return moved


def mark_fresh(work_dir: str, name: str) -> None:
    """某份报告刚被重写：把它从作废名单里去掉。"""
    st = state(work_dir)
    names = [n for n in (st.get("names") or []) if n != name]
    if not names:
        _write_state(work_dir, {})
        return
    st["names"] = names
    _write_state(work_dir, st)


def is_stale(work_dir: str) -> tuple:
    """(是否有作废标记, 说明)。给报告用。"""
    st = state(work_dir)
    names = st.get("names") or []
    if not names:
        return False, ""
    return True, ("%s 已被作废（%s）：%s"
                  % ("、".join(names), st.get("invalidated_at") or "时间未记录",
                     st.get("reason") or "原因未记录"))
