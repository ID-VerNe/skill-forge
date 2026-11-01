# -*- coding: utf-8 -*-
"""round_orchestrator.py — 自动审校的轮次状态机 / 快照 / 整轮回滚 / 最终报告。

`auto-flow.md` 描述**一轮内部**的阶段 0→11；本脚本管理**轮次之间**的东西：
排哪几轮、每轮结果记成什么、哪一轮可以退回去、跑完出什么账。

设计边界（重要）：
- **不产生文本判据**。所有"没问题"的判断都来自 verify_fixes / cross_check /
  regression_check / timeline_gate 的退出码或输出，本脚本只做记账与分派。
- **回滚按快照，不按 log 逐条反向应用**。多轮叠加后逐条回滚会撞上 retime 浮点
  累积、delete 无法重建、global_replace 与 apply_fixes 交叉这三个既有限制
  （见 references/pipeline-spec.md 回滚节）。整文件还原是确定性的，且与
  「回到第 N 轮末」这个语义一一对应。
- **log 快照必须跟着 ASS 一起还原**。只还原 ASS 不还原 log.jsonl，后续
  `verify_fixes --all` / `regression_check` 会看到已被撤销的改动，台账就不干净了。

用法:
  # 1. 看这次会跑哪几轮（不建任何目录，纯计划）
  python round_orchestrator.py --ass E:/sub/S06E04.ass --srt E:/sub/S06E04.srt --plan

  # 2. 开跑：建 runs/<stamp>，写 manifest 与 r00 快照
  python round_orchestrator.py --ass ... --srt ... --init [--auto] [--with-low ...]

  # 3. 每轮结束记一笔（轮次执行由主 agent 按 auto-flow.md 驱动）
  python round_orchestrator.py --run <stamp> --record r03 \
      --batch-id 20261101_231512 --n-fixes 27 --verdict keep

  # 4. 出总账
  python round_orchestrator.py --run <stamp> --report

  # 5. 整轮回退
  python round_orchestrator.py --run <stamp> --rollback-to r03

退出码（与 lib/verdict.py 一致）:
  0  正常
  2  定格了（frozen）—— 后续轮次不应继续
  3  未验时间轴（UNVERIFIED，常见于无片源批次；不是错误）
  1  输入非法 / 状态不一致
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import verdict as V
from lib.log import read_log
from lib.paths import resolve_work_dir
import regression_check

#: 10(+1) 轮定义。顺序即依赖顺序，**不要重排**——依据见 references/rounds-spec.md §1.1
ROUNDS = [
    {"id": "r01", "name": "整体第1遍",    "scope": [1, 2, 3, 4, 5], "opt": None,
     "goal": "粗筛：大面积、跨行、跨集的问题"},
    {"id": "r02", "name": "整体第2遍",    "scope": [1, 2, 3, 4, 5], "opt": None,
     "goal": "只看 R1 残留 + 新发现"},
    {"id": "r03", "name": "整体第3遍",    "scope": [1, 2, 3, 4, 5], "opt": None,
     "goal": "收敛确认"},
    {"id": "r04", "name": "第1类专轮",    "scope": [1],              "opt": None,
     "goal": "结构性生产缺陷（错位/覆盖/重复）"},
    {"id": "r05", "name": "第2类专轮",    "scope": [2],              "opt": None,
     "goal": "漏译"},
    {"id": "r06", "name": "第3类专轮",    "scope": [3],              "opt": None,
     "goal": "语义反转"},
    {"id": "r07", "name": "第4类专轮",    "scope": [4],              "opt": None,
     "goal": "语境错译"},
    {"id": "r08", "name": "第5类专轮",    "scope": [5],              "opt": None,
     "goal": "专名错误/不一致"},
    {"id": "r09", "name": "第7类专轮",    "scope": [7],              "opt": "with_low",
     "goal": "低严重度（信达雅三轴）——**必须排在内容定稿之后**"},
    {"id": "r10", "name": "整体收口",     "scope": [1, 2, 3, 4, 5], "opt": None,
     "goal": "前 9 轮残留 + 交叉污染"},
    {"id": "r11", "name": "第8类专轮",    "scope": [8],              "opt": "with_inclusive",
     "goal": "性别中立/敏感词（清单驱动，建议为主）"},
]

#: 第 6 类（原文拼写）没有独立轮次，只并入 R1–R3 / R10
SPELLING_OPT = "with_spelling"
SPELLING_MERGE = {"r01", "r02", "r03", "r10"}

#: 改动率上限：一轮改掉三成以上的行，多半不是字幕错得多，是这轮盘面/提示词出了问题
MAX_CHURN = 0.30
#: 同一行连续被改几轮 → 冻结
FREEZE_AFTER = 3

VERDICTS = ("pending", "keep", "rollback", "skip", "no_finding")


# ── 计划 ────────────────────────────────────────────────────────────────────

def build_plan(*, with_low=False, with_inclusive=False, with_spelling=False) -> list:
    """按开关排出本次实际要跑的轮次。返回的每一轮都带了生效的 scope。"""
    opts = {"with_low": with_low, "with_inclusive": with_inclusive,
            "with_spelling": with_spelling}
    plan = []
    for r in ROUNDS:
        if r["opt"] and not opts.get(r["opt"]):
            continue
        item = dict(r)
        item["scope"] = list(r["scope"])
        if with_spelling and r["id"] in SPELLING_MERGE:
            item["scope"] = item["scope"] + [6]
        else:
            item["scope"] = [c for c in item["scope"] if c != 6]
        plan.append(item)
    return plan


def render_plan(plan: list, ass: str = "") -> str:
    L = []
    if ass:
        L.append(f"# 轮次计划 — {os.path.basename(ass)}")
        L.append("")
    L += ["| 轮 | 名称 | 审计类别 | 目标 |", "|---|---|---|---|"]
    for r in plan:
        L.append("| %s | %s | %s | %s |" % (
            r["id"], r["name"], ", ".join(str(c) for c in r["scope"]), r["goal"]))
    L += ["", f"共 {len(plan)} 轮。第 6 类（原文拼写）"
              f"{'已并入 R1–R3/R10' if any(6 in r['scope'] for r in plan) else '未跑（需 --with-spelling）'}；"
              f"第 7 类{'跑 R9' if any(r['id'] == 'r09' for r in plan) else '未跑（需 --with-low）'}；"
              f"第 8 类{'跑 R11' if any(r['id'] == 'r11' for r in plan) else '未跑（需 --with-inclusive）'}。"]
    return "\n".join(L)


# ── run 目录与 manifest ─────────────────────────────────────────────────────

def run_dir(wd: str, stamp: str) -> str:
    return os.path.join(wd, "runs", stamp)


def manifest_path(wd: str, stamp: str) -> str:
    return os.path.join(run_dir(wd, stamp), "manifest.json")


def load_manifest(wd: str, stamp: str) -> dict:
    p = manifest_path(wd, stamp)
    if not os.path.exists(p):
        raise SystemExit(f"[!] 找不到 manifest：{p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(wd: str, stamp: str, m: dict) -> None:
    m["updated"] = datetime.now().isoformat(timespec="seconds")
    p = manifest_path(wd, stamp)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def init_run(wd: str, ass: str, srt: str, plan: list, *,
             media: str = "", gated: bool = True, stamp: str = "") -> str:
    """建 runs/<stamp>：manifest + round-plan.json + r00 快照 + logs/r00.jsonl。"""
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    d = run_dir(wd, stamp)
    if os.path.isdir(d):
        raise SystemExit(f"[!] run 目录已存在：{d}\n    换个时间重跑，或指定 --stamp")
    for sub in ("rounds", "logs", "working"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)

    # r00 = 起点快照。用 shutil.copy2 保留 mtime；回滚时整文件还原，
    # 不做任何文本解析（解析就可能「顺手规范化」，回滚就不忠实了）。
    shutil.copy2(ass, os.path.join(d, "r00.ass"))
    src_log = os.path.join(wd, "log.jsonl")
    if os.path.exists(src_log):
        shutil.copy2(src_log, os.path.join(d, "logs", "r00.jsonl"))
    else:
        open(os.path.join(d, "logs", "r00.jsonl"), "w", encoding="utf-8").close()

    m = {
        "run": stamp,
        "ass": os.path.abspath(ass),
        "srt": os.path.abspath(srt) if srt else "",
        "media": os.path.abspath(media) if media else "",
        "opts": {
            "with_low": any(r["id"] == "r09" for r in plan),
            "with_inclusive": any(r["id"] == "r11" for r in plan),
            "with_spelling": any(6 in r["scope"] for r in plan),
            "gated": bool(gated),
        },
        "created": datetime.now().isoformat(timespec="seconds"),
        "frozen": None,
        "frozen_rows": [],
        "rounds": [{"id": r["id"], "name": r["name"], "scope": r["scope"],
                    "batch_id": "", "n_fixes": 0, "verdict": "pending",
                    "snapshot": "", "note": ""} for r in plan],
    }
    save_manifest(wd, stamp, m)
    with open(os.path.join(d, "round-plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    return stamp


# ── 记账 ────────────────────────────────────────────────────────────────────

def latest_snapshot(m: dict) -> str:
    """当前有效的快照文件名（最后一个 keep/no_finding 轮，没有则 r00）。"""
    for r in reversed(m["rounds"]):
        if r["verdict"] in ("keep", "no_finding") and r.get("snapshot"):
            return r["snapshot"]
    return "r00.ass"


def _log_snapshot_for(m: dict, snap: str) -> str:
    """快照名字（r03.ass）→ 对应的 log 快照（logs/r03.jsonl）。"""
    stem = os.path.splitext(snap)[0]
    return os.path.join("logs", stem + ".jsonl")


def record_round(wd: str, stamp: str, rid: str, *,
                 batch_id: str = "", n_fixes: int = 0, verdict: str = "",
                 note: str = "", freeze_rows=None) -> dict:
    """记一轮的结果。keep/no_finding 时把当前 ASS 存成本轮快照。

    `verdict` 不传时按 n_fixes 推断（0 → no_finding，>0 → keep），
    但 **rollback / skip 必须显式传**——这两种状态不能让调用方猜。
    """
    m = load_manifest(wd, stamp)
    if verdict and verdict not in VERDICTS:
        raise SystemExit(f"[!] verdict 非法：{verdict}（可选 {', '.join(VERDICTS)}）")

    target = next((r for r in m["rounds"] if r["id"] == rid), None)
    if target is None:
        raise SystemExit(f"[!] 本轮计划里没有 {rid}。先看 --show-plan")

    d = run_dir(wd, stamp)
    if not verdict:
        verdict = "no_finding" if n_fixes == 0 else "keep"

    target["batch_id"] = batch_id or target["batch_id"]
    target["n_fixes"] = int(n_fixes)
    target["verdict"] = verdict
    target["note"] = note

    if verdict in ("keep", "no_finding"):
        snap = f"{rid}.ass"
        shutil.copy2(m["ass"], os.path.join(d, snap))
        target["snapshot"] = snap
        # log 快照：working/log.jsonl 是本轮执行后的台账（--auto 隔离模式），
        # 没有 working 副本时（逐步模式）直接整本拷主 log。
        working = os.path.join(d, "working", "log.jsonl")
        src = working if os.path.exists(working) else os.path.join(wd, "log.jsonl")
        dst = os.path.join(d, "logs", f"{rid}.jsonl")
        if os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            open(dst, "w", encoding="utf-8").close()
    elif verdict == "rollback":
        # 回滚到上一轮有效快照；本轮不产生新快照
        prev = latest_snapshot(m)
        _restore(m, d, prev)
        target["note"] = (target["note"] + " | rolled back to " + prev).strip(" |")

    if freeze_rows:
        rows = [int(x) for x in freeze_rows]
        m["frozen_rows"] = sorted(set(m.get("frozen_rows", [])) | set(rows))

    save_manifest(wd, stamp, m)
    return m


def freeze_run(wd: str, stamp: str, at: str, reason: str) -> dict:
    """整体定格：`at` 之后仍是 pending 的轮次全部标 skip。

    `at` 可以是本轮轮 id，也可以是特殊值 `now`（当场定格，所有 pending 都 skip）。
    定格不是错误恢复手段，是**止损**：闸门判轴 FAIL 之后继续跑轮次，
    产出的每一轮都是叠在坏轴上的意见。
    """
    m = load_manifest(wd, stamp)
    m["frozen"] = {"at": at, "reason": reason,
                   "ts": datetime.now().isoformat(timespec="seconds")}
    if at == "now":
        for r in m["rounds"]:
            if r["verdict"] == "pending":
                r["verdict"] = "skip"
                r["note"] = (r["note"] or "") + f" | frozen: {reason}"
        save_manifest(wd, stamp, m)
        return m
    seen = False
    for r in m["rounds"]:
        if r["id"] == at:
            seen = True
            continue
        if seen and r["verdict"] == "pending":
            r["verdict"] = "skip"
            r["note"] = (r["note"] or "") + f" | frozen at {at}: {reason}"
    save_manifest(wd, stamp, m)
    return m


# ── 回滚 ────────────────────────────────────────────────────────────────────

def _restore(m: dict, d: str, snap: str) -> None:
    """把 ASS 与 log.jsonl 整本还原到快照 `snap`。

    两个文件**必须一起还原**：只还原 ASS 不还原 log，后续 `verify_fixes --all` /
    `regression_check` 会看到已被撤销的改动，台账就不干净了。
    """
    src = os.path.join(d, snap)
    if not os.path.exists(src):
        raise SystemExit(f"[!] 缺快照文件：{src}")
    shutil.copy2(src, m["ass"])
    log_src = os.path.join(d, _log_snapshot_for(m, snap))
    # 主 log 位置 = <work_dir>/log.jsonl；d = <work_dir>/runs/<stamp>
    log_dst = os.path.join(os.path.dirname(os.path.dirname(d)), "log.jsonl")
    if os.path.exists(log_src):
        shutil.copy2(log_src, log_dst)


def rollback_to(wd: str, stamp: str, rid: str) -> dict:
    """把 ASS 与 log.jsonl 整本还原到第 `rid` 轮末。"""
    m = load_manifest(wd, stamp)
    d = run_dir(wd, stamp)
    if rid in ("", "r00"):
        snap = "r00.ass"
    else:
        hit = next((r for r in m["rounds"] if r["id"] == rid), None)
        if hit is None:
            raise SystemExit(f"[!] 计划里没有 {rid}")
        if not hit.get("snapshot"):
            raise SystemExit(
                f"[!] {rid} 没有快照（verdict={hit['verdict']}）。"
                f"只能退到有快照的轮次："
                f"{', '.join(r['id'] for r in m['rounds'] if r.get('snapshot')) or 'r00'}")
        snap = hit["snapshot"]
    _restore(m, d, snap)
    _sync_working(d, snap if rid not in ("", "r00") else "r00")
    m["rolled_back_to"] = {"at": snap, "ts": datetime.now().isoformat(timespec="seconds")}
    save_manifest(wd, stamp, m)
    return m


def _sync_working(d: str, stem: str) -> None:
    """把 log 快照同步到 working/，让下一轮的起始台账是干净的那一份。"""
    src = os.path.join(d, "logs", stem + ".jsonl")
    dst = os.path.join(d, "working", "log.jsonl")
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


# ── 报告 ────────────────────────────────────────────────────────────────────

def _churn_by_batch(wd: str) -> dict:
    """batch → 沉住度（这一批改的行里，后来又被改过的比例）。

    复用 regression_check 的现成实现，不自造判据。读不到台账就返回空 dict，
    报告里如实写「台账为空」，不猜。
    """
    entries = read_log(wd)
    if not entries:
        return {}
    try:
        data = regression_check.build(entries, 0)
    except Exception:
        return {}
    return {r["batch"]: r for r in data.get("churn", [])}


def _conflicts(wd: str) -> list:
    entries = read_log(wd)
    if not entries:
        return []
    try:
        return regression_check.build(entries, 0).get("conflicts", [])
    except Exception:
        return []


def _parse_ledger(entries: list) -> list:
    """把 log 摊成「每行一条终态」的总账行。

    取每个 (file, srt_id, track) 的**第一条 old_text** 与**最后一条 new_text**，
    中间经历几轮一并记上——挑毛病时看的是「原译 → 终译」，不是过程。
    """
    rows = {}
    for e in sorted(entries, key=lambda x: x.get("ts", "")):
        if e.get("action") not in ("replace", "manual_edit"):
            continue
        if not e.get("srt_id"):
            continue
        key = (e.get("file", ""), int(e["srt_id"]), e.get("track", ""))
        r = rows.get(key)
        if r is None:
            rows[key] = {
                "file": e.get("file", ""), "srt_id": int(e["srt_id"]),
                "track": e.get("track", ""), "old": e.get("old_text", ""),
                "new": e.get("new_text", ""), "category": e.get("category", ""),
                "batches": [e.get("batch_id", "")],
            }
        else:
            r["new"] = e.get("new_text", "")
            r["category"] = e.get("category", "") or r["category"]
            if e.get("batch_id") and e["batch_id"] not in r["batches"]:
                r["batches"].append(e.get("batch_id", ""))
    return sorted(rows.values(), key=lambda r: (r["file"], r["srt_id"]))


def _rollback_cmd(ass: str, chat_id: str) -> str:
    return ("python <skill>/scripts/apply_fixes.py --rollback id=%s --file \"%s\""
            % (chat_id, ass))


def render_report(wd: str, stamp: str) -> str:
    m = load_manifest(wd, stamp)
    d = run_dir(wd, stamp)
    rounds = m["rounds"]
    done = [r for r in rounds if r["verdict"] != "pending"]
    kept = [r for r in rounds if r["verdict"] in ("keep", "no_finding")]
    rolled = [r for r in rounds if r["verdict"] == "rollback"]
    skipped = [r for r in rounds if r["verdict"] == "skip"]
    total = sum(r["n_fixes"] for r in kept)

    churn = _churn_by_batch(wd)
    conflicts = _conflicts(wd)
    ledger = _parse_ledger(read_log(wd))

    L = [f"# 最终报告 — {os.path.basename(m['ass'])}", ""]
    top = [f"轮次 {len(done)}/{len(rounds)} 已跑完"]
    if rolled:
        top.append(f"回滚 {len(rolled)}")
    if skipped:
        top.append(f"skip {len(skipped)}")
    top.append(f"净改动 {total} 条")
    if not m.get("media"):
        top.append("时间轴 UNVERIFIED（无片源）")
    if m.get("frozen"):
        top.append(f"**已定格于 {m['frozen']['at']}：{m['frozen']['reason']}**")
    L += ["> " + " / ".join(top), ""]

    L += ["## 逐轮摘要", "",
          "| 轮 | 名称 | 类别 | 改动 | verdict | 沉住度 | batch_id |",
          "|---|---|---|---|---|---|---|"]
    for r in rounds:
        c = churn.get(r["batch_id"])
        ch = "%d%%" % round(c["rate"] * 100) if c else "—"
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["name"], ",".join(str(x) for x in r["scope"]),
            r["n_fixes"], r["verdict"], ch, r["batch_id"] or "—"))
    L += ["", "> 沉住度 = 该轮改的行里后来又被改过的比例。某一类专轮常年 < 50%，"
              "说明那类的**判据**有问题，该改规则而不是继续跑轮次。", ""]

    L += ["## 争执行（被 ≥2 轮改过的行）", ""]
    if conflicts:
        L += ["| srt_id | 轨道 | 改过几轮 | 逐轮文本 | 回滚 |", "|---|---|---|---|---|"]
        for c in conflicts:
            sid = c["key"][1]
            trail = " → ".join(
                "「%s」" % (t.get("new", "")[:16] or "—") for t in c["trail"])
            L.append("| %s | %s | %s | %s | `--rollback id=%s` |" % (
                sid, c["key"][2], c["n_rounds"], trail, sid))
        L += ["", "> 这一节是给人裁的，不是结论。改回去有时是对的（上一轮确实改错了）。", ""]
    else:
        L += ["没有。", ""]

    if m.get("frozen_rows"):
        L += ["## 冻结行（连续 %d 轮被改，后续轮次已禁改）" % FREEZE_AFTER, ""]
        L += ["- srt_id: " + ", ".join(str(x) for x in m["frozen_rows"]), ""]

    L += ["## 改动总账", ""]
    if ledger:
        L += ["| srt_id | 轨道 | 原译 | 终译 | 类别 | 轮次 | 回滚 |",
              "|---|---|---|---|---|---|---|"]
        for r in ledger:
            L.append("| %s | %s | %s | %s | %s | %s | `--rollback id=%s` |" % (
                r["srt_id"], r["track"], r["old"][:20] or "—", r["new"][:20] or "—",
                r["category"] or "—", len(r["batches"]), r["srt_id"]))
        L.append("")
        L += ["整轮回退：",
              f"```bash",
              f"python <skill>/scripts/round_orchestrator.py --run {stamp} --rollback-to r03",
              f"```", ""]
    else:
        L += ["台账为空（本次没有改动）。", ""]

    wl_json = os.path.join(wd, "reports", "inclusive.json")
    L += ["## 白名单（第 8 类命中但未改）", ""]
    if os.path.exists(wl_json):
        try:
            with open(wl_json, "r", encoding="utf-8") as f:
                wl = json.load(f).get("whitelisted", [])
        except Exception:
            wl = []
        if wl:
            for w in wl[:50]:
                L.append("- `%s` @ %.2fs — 行业标准词/专名，改动即错" %
                         (w.get("term", ""), w.get("start", 0)))
        else:
            L.append("没有白名单命中。")
    else:
        L.append("未跑第 8 类扫描（R11 未开启或无候选）。")
    L += ["", "> 这一节防的是把「白名单拦住」误读成「漏改」。", ""]

    L += ["## 本次未覆盖", ""]
    scopes = set()
    for r in rounds:
        scopes |= set(r["scope"])
    gaps = []
    if 6 not in scopes:
        gaps.append("第 6 类（原文拼写）—— 改英文轨需显式 `--with-spelling`")
    if not any(r["id"] == "r09" for r in rounds):
        gaps.append("第 7 类（低严重度）—— 需显式 `--with-low`")
    if not any(r["id"] == "r11" for r in rounds):
        gaps.append("第 8 类（性别中立/敏感词）—— 需显式 `--with-inclusive`")
    if not m.get("media"):
        gaps.append("时间轴 —— 无片源，判 UNVERIFIED（不是通过）")
    L += [f"- {g}" for g in gaps] if gaps else ["无（本轮全部开启且有片源）。"]
    L += ["", "> 默认不跑的类别是**设计决定**，不是遗漏。不写出来，"
              "下一轮看到「跑完了」会以为这些也审过了。", ""]

    return "\n".join(L)


def write_report(wd: str, stamp: str) -> str:
    out = os.path.join(run_dir(wd, stamp), "final-report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_report(wd, stamp))
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="自动审校轮次编排：计划/快照/记账/回滚/总账")
    ap.add_argument("--ass", help="成品 ASS（--plan / --init 用）")
    ap.add_argument("--srt", default="", help="配对 SRT")
    ap.add_argument("--media", default="", help="片源（缺省则时间轴判 UNVERIFIED）")
    ap.add_argument("--work-dir", default=".subtitle-polish")
    ap.add_argument("--stamp", default="", help="--init 时指定 run 名（测试用）")

    ap.add_argument("--with-low", action="store_true", help="加 R9（第 7 类）")
    ap.add_argument("--with-inclusive", action="store_true", help="加 R11（第 8 类）")
    ap.add_argument("--with-spelling", action="store_true", help="第 6 类并入 R1–R3/R10")

    ap.add_argument("--plan", action="store_true", help="只打印轮次计划，不建目录")
    ap.add_argument("--init", action="store_true", help="建 runs/<stamp> 与 r00 快照")
    ap.add_argument("--run", default="", help="已有 run 的 stamp")
    ap.add_argument("--record", default="", help="记一轮结果，如 --record r03")
    ap.add_argument("--batch-id", default="")
    ap.add_argument("--n-fixes", type=int, default=0)
    ap.add_argument("--verdict", default="", help="keep|rollback|skip|no_finding")
    ap.add_argument("--note", default="")
    ap.add_argument("--freeze-rows", default="", help="冻结的 srt_id，逗号分隔")
    ap.add_argument("--freeze", action="store_true", help="整体定格（--record 时生效）")
    ap.add_argument("--report", action="store_true", help="写 final-report.md")
    ap.add_argument("--rollback-to", default="", help="整轮回退到某轮末，如 r03")
    ap.add_argument("--show-plan", action="store_true", help="打印已有 run 的轮次状态")
    args = ap.parse_args()

    wd = resolve_work_dir(args.work_dir)

    if args.plan or args.init:
        if not args.ass:
            ap.error("--plan / --init 需要 --ass")
        plan = build_plan(with_low=args.with_low,
                          with_inclusive=args.with_inclusive,
                          with_spelling=args.with_spelling)
        if args.plan:
            print(render_plan(plan, args.ass))
            return 0
        if not os.path.exists(args.ass):
            print(f"[!] ASS 不存在：{args.ass}", file=sys.stderr)
            return 1
        stamp = init_run(wd, args.ass, args.srt, plan, media=args.media,
                         stamp=args.stamp)
        print(f"[*] run {stamp} → {run_dir(wd, stamp)}")
        print(render_plan(plan, args.ass))
        return 0

    if not args.run:
        ap.error("需要 --plan / --init / --run")

    if args.record:
        rows = [x.strip() for x in args.freeze_rows.split(",") if x.strip()]
        m = record_round(wd, args.run, args.record,
                         batch_id=args.batch_id, n_fixes=args.n_fixes,
                         verdict=args.verdict, note=args.note, freeze_rows=rows)
        if args.freeze:
            reason = args.note or "manual freeze"
            m = freeze_run(wd, args.run, args.record, reason)
            print(f"[*] 定格于 {args.record}：{reason}（后续轮次标 skip）")
            print(write_report(wd, args.run))
            return V.FAIL
        print(f"[*] {args.record} → "
              f"{next(r for r in m['rounds'] if r['id'] == args.record)['verdict']}")
        return 0

    if args.freeze:
        reason = args.note or "manual freeze"
        freeze_run(wd, args.run, args.record or "r00", reason)
        print(f"[*] 定格：{reason}")
        print(write_report(wd, args.run))
        return V.FAIL

    if args.rollback_to:
        m = rollback_to(wd, args.run, args.rollback_to)
        print(f"[*] 已回滚到 {m['rolled_back_to']['at']}（ASS + log.jsonl 均还原）")
        return 0

    if args.report:
        out = write_report(wd, args.run)
        print(f"[*] 报告 {out}")
        return 0

    if args.show_plan:
        m = load_manifest(wd, args.run)
        print("| 轮 | 名称 | 类别 | 改动 | verdict |")
        print("|---|---|---|---|---|")
        for r in m["rounds"]:
            print("| %s | %s | %s | %s | %s |" % (
                r["id"], r["name"], ",".join(str(x) for x in r["scope"]),
                r["n_fixes"], r["verdict"]))
        return 0

    ap.error("无事可做：给 --record / --report / --rollback-to / --show-plan 之一")
    return 1


if __name__ == "__main__":
    sys.exit(main())
