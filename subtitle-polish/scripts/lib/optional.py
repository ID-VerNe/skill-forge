# -*- coding: utf-8 -*-
"""optional-fixes：建议入账，但不落盘。

## 为什么需要这东西（issue #24 的 H1 / M7）

自动审校跑完，LLM 常常给出「这条可以更好，但不改也不算错」的意见。以前这类
意见和被执行的改动混在同一个 fixes.json 里，结果是：

1. 报告里的「净改动 N 条」把建议也算进去，改 3 条报 21 条；
2. 想过一遍建议就只能靠人肉翻 markdown，翻不完就静默丢掉；
3. `optional-fixes.md` 是 LLM 手写的，和 json 不同源，两边对不上。

所以拆成两个动作：

    optional-fixes.json  --promote-->  log.jsonl (applied=false)  --apply--> ASS

**默认谁也不改**。只有 `--promote` 显式点名的那条才进台账；台账里的记录带
`applied=false`，表示「已采纳为改动意图，但还没写进 ASS」，要等
`apply_fixes --apply-batch` 才真正落盘。

## 字段约定

每条至少要有 `srt_id`（int）和 `current`（该行在 ASS 里的**原文**）。
两者都是必填——缺 `current` 就无法回读校验，缺 `srt_id` 就无法回滚。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from .paths import resolve_work_dir


def optional_json_path(work_dir: str = "") -> str:
    return os.path.join(resolve_work_dir(work_dir), "reports", "optional-fixes.json")


def optional_md_path(work_dir: str = "") -> str:
    return os.path.join(resolve_work_dir(work_dir), "reports", "optional-fixes.md")


def load_optional(work_dir: str = "") -> list:
    """读 optional-fixes.json → list。文件不存在返回 []。"""
    p = optional_json_path(work_dir)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        items = data.get("items", [])
    else:
        items = data
    return [x for x in items if isinstance(x, dict)]


def validate_optional(items: list) -> tuple:
    """校验必填字段，返回 (ok, errors)。

    `current` 是**必需**的，不是可选装饰。没有它就不知道该行在 ASS 里的现状，
    promote 之后 apply 时只能靠 srt_id 盲定位——srt_id 在删除/合并后本身就会漂。
    """
    errs = []
    for i, it in enumerate(items):
        tag = it.get("id") or f"#{i}"
        sid = it.get("srt_id")
        if not isinstance(sid, int) or sid <= 0:
            errs.append(f"{tag}: srt_id 缺失或非法（{sid!r}），无法定位/回滚")
        cur = it.get("current")
        if not isinstance(cur, str) or not cur.strip():
            errs.append(f"{tag}: current 缺失，无法回读校验")
        new = it.get("suggested_new") or it.get("final_new") or ""
        if not str(new).strip():
            errs.append(f"{tag}: suggested_new 为空，无可采纳内容")
        if it.get("track") not in ("中文", "英文"):
            errs.append(f"{tag}: track 必须是「中文」或「英文」，收到 {it.get('track')!r}")
    return (not errs), errs


def save_optional(work_dir: str, items: list) -> str:
    """写回 optional-fixes.json，并**同步重建 markdown**（两者同源）。"""
    ok, errs = validate_optional(items)
    if not ok:
        raise SystemExit("[!] optional-fixes 校验失败：\n" + "\n".join(f"    {e}" for e in errs))

    p = optional_json_path(work_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    payload = {"generated": datetime.now().isoformat(timespec="seconds"),
               "count": len(items), "items": items}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    write_optional_md(work_dir, items)
    return p


def write_optional_md(work_dir: str, items: list) -> str:
    """由 json 渲染 markdown。**不允许手写 md**——手写就会和 json 不同源。"""
    p = optional_md_path(work_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    L = ["# 建议改动（未执行）", "",
         "> 这些是「可以更好，但不改也不算错」的意见。**默认一条都不改。**",
         "> 要采纳某条，用：",
         "> `python <skill>/scripts/round_orchestrator.py --promote <id>`",
         ""]
    if not items:
        L += ["（本次没有建议。）", ""]
    else:
        L += ["| id | srt_id | 轨道 | 原文 | 建议 | 类别 | 采纳 |",
              "|---|---|---|---|---|---|---|"]
        for it in items:
            L.append("| %s | %s | %s | %s | %s | %s | `--promote %s` |" % (
                it.get("id", ""), it.get("srt_id", ""), it.get("track", ""),
                _cell(it.get("current", "")), _cell(it.get("suggested_new", "")),
                it.get("category", "—"), it.get("id", "")))
        L.append("")
        L.append(f"共 {len(items)} 条。")
        L.append("")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return p


def _cell(s: str, n: int = 40) -> str:
    s = str(s).replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def md_in_sync(work_dir: str = "") -> bool:
    """交叉校验：md 里的 id 集合 == json 里的 id 集合。

    防的是「有人手改了 md」。不同源时报告里那节会显示 ⚠，而不是假装一致。
    """
    jp, mp = optional_json_path(work_dir), optional_md_path(work_dir)
    if not os.path.exists(jp) and not os.path.exists(mp):
        return True
    if os.path.exists(jp) != os.path.exists(mp):
        return False
    try:
        ids_json = {str(x.get("id", "")) for x in load_optional(work_dir)}
    except Exception:
        return False
    ids_md = set()
    with open(mp, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("| ") and line.count("|") >= 7:
                parts = [c.strip() for c in line.strip().strip("|").split("|")]
                if parts and parts[0] and parts[0] != "id" and set(parts[0]) != {"-"}:
                    ids_md.add(parts[0])
    return ids_json == ids_md


def promote(work_dir: str, ids: list, batch_id: str = "") -> list:
    """把指定 id 的建议提升进台账（applied=false，尚未落盘）。

    返回被提升的条目。已提升过的会跳过（幂等），不会重复记账。
    """
    from .log import append_raw, read_log

    items = load_optional(work_dir)
    if not items:
        raise SystemExit("[!] 没有 optional-fixes.json 或内容为空，无可提升")
    by_id = {str(it.get("id", "")): it for it in items}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit("[!] 这些建议不存在：%s\n    可用的 id：%s"
                         % (", ".join(missing), ", ".join(sorted(by_id))))

    existing = {(e.get("action"), e.get("srt_id"), e.get("new_text"))
                for e in read_log(work_dir) if e.get("action") == "optional_promote"}
    bid = batch_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    out = []
    for i in ids:
        it = by_id[i]
        key = ("optional_promote", it["srt_id"], it.get("suggested_new", ""))
        if key in existing:
            print(f"[=] {i} 已提升过，跳过")
            continue
        append_raw(work_dir, {
            "batch_id": bid,
            "action": "optional_promote",
            "file": it.get("file", ""),
            "srt_id": it["srt_id"],
            "track": it.get("track", "中文"),
            "old_text": it["current"],          # 这是 ASS 里的原文（必填字段）
            "new_text": it.get("suggested_new", ""),
            "category": it.get("category", ""),
            "reason": it.get("reason", "") or "optional",
            "optional_id": i,
            "applied": False,                   # 关键：已采纳意图，未写 ASS
        })
        it["status"] = "accepted"
        it["batch_id"] = bid
        out.append(it)
    if out:
        _write_json_only(work_dir, items)
    print(f"[*] 提升 {len(out)} 条到台账（applied=false，尚未写入 ASS）")
    print(f"    落盘：python <skill>/scripts/apply_fixes.py --apply-batch {bid}")
    return out


def _write_json_only(work_dir: str, items: list) -> None:
    p = optional_json_path(work_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now().isoformat(timespec="seconds"),
                   "count": len(items), "items": items},
                  f, ensure_ascii=False, indent=2)
    write_optional_md(work_dir, items)


def render_md_section(work_dir: str = "") -> list:
    """给 final-report.md 用的一节。没有建议时也返回一句，避免被误读成「没有未覆盖项」。"""
    items = load_optional(work_dir)
    if not items:
        return []
    L = ["## 建议改动（未执行，%d 条）" % len(items), ""]
    if not md_in_sync(work_dir):
        L += ["> ⚠ optional-fixes.md 与 optional-fixes.json 不同源（疑似手改），"
              "以下以 json 为准。", ""]
    L += ["| id | srt_id | 原文 | 建议 | 类别 |", "|---|---|---|---|---|"]
    for it in items[:60]:
        L.append("| %s | %s | %s | %s | %s |" % (
            it.get("id", ""), it.get("srt_id", ""),
            _cell(it.get("current", ""), 22), _cell(it.get("suggested_new", ""), 22),
            it.get("category", "—")))
    if len(items) > 60:
        L.append("| … | | | 其余 %d 条见 reports/optional-fixes.json | |" % (len(items) - 60))
    L += ["",
          "> 这些**不在「净改动」里**，ASS 也没有改动。采纳方式："
          "`--promote <id>`，再 `apply_fixes --apply-batch <batch>`。", ""]
    return L
