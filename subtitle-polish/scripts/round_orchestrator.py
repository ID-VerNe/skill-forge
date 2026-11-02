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
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import verdict as V
from lib.log import read_log
from lib.paths import (resolve_work_dir, orphan_logs, assert_no_orphan_log,
                       assert_report_location)
from lib import optional as OPT
import regression_check
import structure_check as SC

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


def _structure_gate(ass: str) -> bool:
    """跑 `structure_check`，返回是否放行（C3b）。

    只在 ABORT 时拦；SUSPECT 放行但把摘要打出来——SUSPECT 是「值得看一眼」，
    不是「不许开工」。把 SUSPECT 也做成门禁会让门禁被习惯性绕过，那就白做了。

    结构检查本身崩溃时**放行并告警**，不拦：门禁工具的 bug 不应该阻断整条流水线。
    但要把「没检成」写清楚，不能让人以为「检过了、没问题」。
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "structure_check.py")
    if not os.path.exists(script):
        print("[!] 找不到 structure_check.py，跳过结构门禁（不等于通过）",
              file=sys.stderr)
        return True
    try:
        p = subprocess.run([sys.executable, script, "--ass", ass, "--quiet"],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:            # noqa: BLE001
        print(f"[!] 结构检查未能执行（{e}），跳过门禁（不等于通过）",
              file=sys.stderr)
        return True

    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if p.returncode == SC.EXIT_OK:
        print(f"[*] 结构门禁通过：{out}")
        return True
    if p.returncode == SC.EXIT_SUSPECT:
        print(f"[*] 结构门禁放行（有 SUSPECT，请看一眼）：{out}")
        return True
    # ABORT：把完整报告打出来，不要只报第一条。
    print(out or err, file=sys.stderr)
    return False


def init_run(wd: str, ass: str, srt: str, plan: list, *,
             media: str = "", gated: bool = True, stamp: str = "",
             skip_structure_check: bool = False) -> str:
    """建 runs/<stamp>：manifest + round-plan.json + r00 快照 + logs/r00.jsonl。

    ## R0 之前先过结构门禁（C3b）

    这一条**必须在建任何轮次之前**跑。理由：轨坏了之后，所有需要中英对照的判据
    （长度比、漏译、语气词还原）都会拿错位的数据比对，跑完 10 轮得到的是一份
    「看起来正常、结论全错」的报告。E03 的中文轨从第 149 行起错位 39.84 秒，
    单看任何一行都正常——这是最贵的一类缺陷，因为它不报错。
    """
    if gated and not skip_structure_check and not _structure_gate(ass):
        raise SystemExit(
            "[x] 结构门禁未通过，未建 run。\n"
            "    轨是坏的，跑轮次只会得到「看起来正常、结论全错」的报告。\n"
            "    修完轨后重跑；若确认是误报，加 --skip-structure-check 放行"
            "（放行决定请写进报告）。")

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
        # B1：先把 working 台账归并回主台账，再拷快照。顺序不能反——先拷快照
        # 会把「还没归并」的 working 当成唯一证据，主台账依旧是空的。
        _merge_working_log(wd, d)
        snap = f"{rid}.ass"
        shutil.copy2(m["ass"], os.path.join(d, snap))
        target["snapshot"] = snap
        # log 快照：working/log.jsonl 是本轮执行后的台账（--auto 隔离模式），
        # 没有 working 副本时（逐步模式）直接整本拷主 log。
        #
        # B1（issue #24）：`--auto` 隔离模式下 working/log.jsonl 必须**归并回**
        # 主 log.jsonl，否则主台账永远停留在 r00 的状态——74 条改动最后在报告
        # 里只剩 2 条，就是这么来的。归并在 `_merge_working_log()` 里做，
        # 这里只读归并后的主 log。
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


def _merge_working_log(wd: str, d: str) -> int:
    """把 working/log.jsonl 归并回主 `<wd>/log.jsonl`，返回新增条数（B1）。

    ## 为什么必须有这一步

    `--auto` 为了「一轮失败能干净重来」，把 apply_fixes 的 `--work-dir` 指到
    `runs/<stamp>/working/`，改动先记在那本台账上。跑完如果不归并，主台账
    永远停在 r00——报告读主台账，于是 74 条改动在报告里只剩 2 条。

    归并按条目去重（同 file/srt_id/track/old/new/ts 视为同一条），归并后
    主台账行数必须 ≥ 归并前 + 归并前 working 里的新增数，否则说明有记录被
    覆盖了，直接报错。

    `_restore()` 走的是整本还原，不经过这里——回滚语义就是「退回某个时刻」，
    不能把后来的记录合并进去。
    """
    working = os.path.join(d, "working", "log.jsonl")
    canon = os.path.join(wd, "log.jsonl")
    if not os.path.exists(working):
        return 0

    def _read(p):
        out = []
        if not os.path.exists(p):
            return out
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def _key(e):
        return (e.get("file", ""), e.get("srt_id"), e.get("track", ""),
                e.get("old_text", ""), e.get("new_text", ""), e.get("ts", ""))

    main = _read(canon)
    wk = _read(working)
    before_main, before_wk = len(main), len(wk)
    seen = {_key(e) for e in main}
    added = [e for e in wk if _key(e) not in seen]

    if not added:
        return 0
    allrows = main + added
    allrows.sort(key=lambda e: e.get("ts", ""))
    tmp = canon + ".tmp"
    os.makedirs(os.path.dirname(canon) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        for e in allrows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, canon)

    # 断言：主台账行数 ≥ 原有 + 新增。写坏了就立刻停，不带着脏台账继续跑。
    if len(allrows) < before_main + min(len(added), before_wk):
        raise SystemExit(
            f"[!] log 归并异常：主台账 {before_main} 条 → {len(allrows)} 条，"
            f"working {before_wk} 条中应有 {len(added)} 条新增。停下核对。")
    print(f"[*] 归并 working/log.jsonl → 主台账：+{len(added)} 条"
          f"（{before_main} → {len(allrows)}）")
    return len(added)


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


def _rollback_cmd(ass: str, batch_id: str = "", srt_id=None) -> str:
    """生成回滚命令。**两个粒度不能混用**（B3）。

    以前这里写的是 `--rollback id=<batch_id> --file <ass>`：把批次标识填进了
    `id=`（那是 srt_id 的位置），生成的命令必然回滚错行——而且看起来还很正常，
    因为 `id=` 确实存在，只是语义错了。

    现在按粒度分开：
      - 整批：`--rollback batch=<batch_id>`（一次回滚这一轮的全部改动）
      - 单条：`--rollback id=<srt_id> --file <ass>`（精确到行，需限定文件）
    """
    if batch_id:
        return ("python <skill>/scripts/apply_fixes.py --rollback batch=%s"
                % batch_id)
    if srt_id is not None:
        return ("python <skill>/scripts/apply_fixes.py --rollback id=%s --file \"%s\""
                % (srt_id, ass))
    return "# 无可用回滚标识"


def render_report(wd: str, stamp, extra_stamps=None) -> str:
    """出总账。`stamp` 可传单个 run 名，也可传列表（D3：`--runs a,b`）。

    多 run 时的口径**固定**为：逐轮摘要与改动总账按「合并去重」呈现，
    并在最前面加一张横向对比表 + 不可比提示。不做两次报告再拼一起——
    那样读的人要自己算差异，而这个 skill 的难点从来不是算数。
    """
    if isinstance(stamp, (list, tuple)):
        stamps = list(stamp)
    else:
        stamps = _norm_merge_stamps(extra_stamps, stamp)
    stamps = [s for s in stamps if s]
    if not stamps:
        raise SystemExit("[!] 没有指定 run")
    if len(stamps) > 1:
        return _render_multi_report(wd, stamps)
    return _render_single_report(wd, stamps[0])


def _render_multi_report(wd: str, stamps) -> str:
    """多次跑测合并成一份。见 `render_report` 的口径说明。"""
    missing = [s for s in stamps if not os.path.exists(os.path.join(run_dir(wd, s),
                                                                   "manifest.json"))]
    if missing:
        raise SystemExit(f"[!] 这些 run 不存在：{', '.join(missing)}"
                         f"（看 {os.path.join(wd, 'runs')}）")
    sums = []
    for s in stamps:
        m = load_manifest(wd, s)
        m["stamp"] = s
        sums.append(m)

    L = [f"# 合并报告 — {len(stamps)} 次跑测", ""]
    L += _render_cross_run(sums)
    L += ["---", ""]

    for i, s in enumerate(stamps, 1):
        L += [f"## 跑测 {i}：`{s}`", "", "```"]
        L += [render_report(wd, s)]
        L += ["```", ""]

    L += ["> 合并报告只做并排呈现，**不做跨 run 的自动裁决**。"
          "两次跑测该以哪次为准，要看片源与开关是否一致——"
          "这属于判断，不是汇总。", ""]
    return "\n".join(L)


def _render_single_report(wd: str, stamp: str) -> str:
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
            # B3：这一列以前硬写着 `--rollback id=N`，但只有 srt_id 没有 file，
            # 照着抄会回滚到**同号的所有文件**。走 _rollback_cmd() 统一生成，
            # 顺带把 file 带上。
            cmd = _rollback_cmd(c.get("file") or m["ass"], srt_id=sid)
            L.append("| %s | %s | %s | %s | `%s` |" % (
                sid, c["key"][2], c["n_rounds"], trail, cmd))
        L += ["", "> 这一节是给人裁的，不是结论。改回去有时是对的（上一轮确实改错了）。", ""]
    else:
        L += ["没有。", ""]

    if m.get("frozen_rows"):
        L += ["## 冻结行（连续 %d 轮被改，后续轮次已禁改）" % FREEZE_AFTER, ""]
        L += ["- srt_id: " + ", ".join(str(x) for x in m["frozen_rows"]), ""]

    # 结构性改动（B2）：手工 Edit / 曲线重建 / 删行这类不走 fixes.json 的动作，
    # 必须单列。它们绕过了 fixes 的撞车预检，是「为什么这一行和上一轮不一样」
    # 最常见的解释来源。
    struct = [e for e in read_log(wd) if e.get("action") == "structural_change"]
    if struct:
        L += ["## 结构性改动（绕过 fixes.json 的动作）", ""]
        L += ["| 类型 | srt_id | 轨道 | 原 → 新 | 原因 |", "|---|---|---|---|---|"]
        for s in struct[:40]:
            L.append("| %s | %s | %s | %s → %s | %s |" % (
                s.get("kind", "?"), s.get("srt_id", ""), s.get("track", ""),
                (s.get("old_text") or "")[:18], (s.get("new_text") or "")[:18],
                (s.get("reason") or "")[:20]))
        if len(struct) > 40:
            L.append("| … | | | 其余 %d 条见 log.jsonl | |" % (len(struct) - 40))
        L += ["", "> 这些改动没有走 fixes.json 的撞车预检，冲突排查时优先看这里。", ""]

    L += ["## 改动总账", ""]
    if ledger:
        L += ["| srt_id | 轨道 | 原译 | 终译 | 类别 | 轮次 | 回滚 |",
              "|---|---|---|---|---|---|---|"]
        for r in ledger:
            cmd = _rollback_cmd(r.get("file") or m["ass"], srt_id=r["srt_id"])
            L.append("| %s | %s | %s | %s | %s | %s | `%s` |" % (
                r["srt_id"], r["track"], r["old"][:20] or "—", r["new"][:20] or "—",
                r["category"] or "—", len(r["batches"]), cmd))
        L.append("")
        # B3：整批回滚给的是 batch_id，不是轮 id——两者长得像（都在 --run 上下文里），
        # 混用会回滚错一整轮。这里按「每轮一行」列出来，抄一行就是一轮。
        bt = [r for r in kept if r["batch_id"]]
        if bt:
            L += ["按批回滚（一次撤销一整轮的改动）：", "", "```bash"]
            seen_b = set()
            for r in bt:
                if r["batch_id"] in seen_b:
                    continue
                seen_b.add(r["batch_id"])
                L.append("%s  # %s %s，%d 条" % (
                    _rollback_cmd(m["ass"], batch_id=r["batch_id"]),
                    r["id"], r["name"], r["n_fixes"]))
            L += ["```", ""]
        L += ["整轮回退（ASS 与 log 一起退回某轮末，需 `--yes` 确认）：",
              "```bash",
              f"python <skill>/scripts/round_orchestrator.py --run {stamp} --rollback-to r03",
              "```", ""]
    else:
        L += ["台账为空（本次没有改动）。", ""]

    # 建议改动（A1）：必须单列，且必须说明「不在净改动里」。以前建议和被执行的
    # 改动混在一起，报告写「净改动 21 条」而 ASS 只改了 3 条。
    L += OPT.render_md_section(wd)

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


def _adopt_orphan_logs(work_dir: str) -> int:
    """把孤儿 log.jsonl 合并进 `<work_dir>/log.jsonl`（A4 / M1）。

    ## 孤儿是怎么来的

    历史上 `round_orchestrator --auto` 在 cwd 直接跑 `apply_fixes`，而
    `apply_fixes` 的 `--work-dir` 默认是相对路径 `.subtitle-polish`——子进程的
    cwd 若与主流程不同，就会在**另一个目录**建一本 log.jsonl。结果：报告读
    A 本、脚本写 B 本，74 条改动在报告里只剩 2 条。

    ## 合并规则

    规范台账在前、孤儿台账在后（孤儿记录必然更晚，或本来就是漏记的），按
    `(file, srt_id, track, old_text, new_text)` 去重。合并后把孤儿文件改名成
    `.adopted` 而不是删除——它是唯一的历史证据，删掉就再也说不清发生了什么。
    """
    orp = orphan_logs(work_dir)
    wd = resolve_work_dir(work_dir)
    canon = os.path.join(wd, "log.jsonl")
    if not orp:
        print("[=] 没有孤儿 log.jsonl，无需处理")
        return 0

    def _key(e):
        return (e.get("file", ""), e.get("srt_id"), e.get("track", ""),
                e.get("old_text", ""), e.get("new_text", ""), e.get("ts", ""))

    merged = []
    seen = set()
    for p in [canon] + orp:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = _key(e)
                if k in seen:
                    continue
                seen.add(k)
                merged.append(e)
    merged.sort(key=lambda e: e.get("ts", ""))

    os.makedirs(os.path.dirname(canon), exist_ok=True)
    with open(canon, "w", encoding="utf-8") as f:
        for e in merged:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    for p in orp:
        dst = p + ".adopted"
        # 不能直接 os.replace：第二次 --adopt 会把第一次的证据覆盖掉，
        # 而「谁什么时候并进来的」恰恰是最该留下的信息。重名就加序号。
        if os.path.exists(dst):
            n = 2
            while os.path.exists(f"{p}.adopted.{n}"):
                n += 1
            dst = f"{p}.adopted.{n}"
        os.replace(p, dst)
        print(f"    孤儿已改名保留：{dst}（未删除，作为历史证据）")
    print(f"[*] 合并完成：{len(merged)} 条 → {canon}")
    return 0


def write_report(wd: str, stamp, extra_stamps=None) -> str:
    """写 final-report.md。

    单 run → 写进该 run 目录；多 run → 写进 `runs/_merged/<a>+<b>/final-report.md`。
    **多 run 报告不写进任何单个 run 目录**：写进去之后，那个 run 的
    「这是一次独立跑测的结论」就被污染了，下次有人 `--run a --report` 会读到
    一份包含 b 的报告。
    """
    stamps = ([s for s in stamp if s] if isinstance(stamp, (list, tuple))
              else _norm_merge_stamps(extra_stamps, stamp))
    if len(stamps) > 1:
        if not os.path.isdir(run_dir(wd, stamps[0])):
            raise SystemExit(f"[!] run 不存在：{stamps[0]}")
        d = os.path.join(wd, "runs", "_merged", "+".join(stamps))
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "final-report.md")
        text = render_report(wd, stamps)
    else:
        out = os.path.join(run_dir(wd, stamps[0]), "final-report.md")
        text = render_report(wd, stamps[0])
    # D4：落点校验。加了 --runs 之后合并报告会写到 runs/_merged/…，
    # 那是个新目录，不校验的话下次很容易顺手加出第三个落点。
    assert_report_location(out, wd)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return out


def _norm_merge_stamps(stamps, run: str) -> list:
    """把 `--runs a,b` 与 `--run x` 合成一个有序去重列表。

    允许 `--runs r1,r2` 独立使用，也允许 `--run a --runs a,b`（此时 a 排最前）。
    顺序**保留用户给的顺序**，不排序：批次是有时间先后的，重排会让「a 覆盖了 b」
    还是「b 覆盖了 a」读反。
    """
    out = []
    for s in ([run] if run else []) + [x.strip() for x in (stamps or "").split(",")]:
        if s and s not in out:
            out.append(s)
    return out


def _render_cross_run(sums) -> list:
    """多 run 合并报告头：把几次跑测放在一张表里横向比。

    为什么值得单独写：单 run 报告回答不了「这一版比上一版好还是差」。
    而比大小之前必须先把**可比性**说清楚——两次跑测的轮次表不同（开关不同）、
    片源有没有给不同、台账是不是同一份，这些不一样的时候，净改动条数不可比。
    所以这张表把「不可比」先摆在最前面，而不是让人自己发现。
    """
    L = ["## 本次合并了 %d 次跑测" % len(sums), "",
         "| run | ASS | 片源 | 轮次 | 已跑 | 回滚 | skip | 净改动 | 定格 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for m in sums:
        rounds = m["rounds"]
        done = [r for r in rounds if r["verdict"] != "pending"]
        L.append("| %s | %s | %s | %d | %d | %d | %d | %d | %s |" % (
            m["stamp"], os.path.basename(m.get("ass") or ""),
            "有" if m.get("media") else "**无（UNVERIFIED）**",
            len(rounds), len(done),
            sum(1 for r in rounds if r["verdict"] == "rollback"),
            sum(1 for r in rounds if r["verdict"] == "skip"),
            sum(r["n_fixes"] for r in rounds
                if r["verdict"] in ("keep", "no_finding")),
            "是" if m.get("frozen") else "—"))
    L += [""]

    warn = []
    if len({os.path.normcase(os.path.abspath(m.get("ass") or "")) for m in sums}) > 1:
        warn.append("各 run 的 ASS 不是同一个文件——净改动条数**不可直接相加**，"
                    "它们是不同输入上的改动，合并后只会得到没有意义的和。")
    if len({m.get("media") and os.path.normcase(os.path.abspath(m["media"])) or ""
            for m in sums}) > 1:
        warn.append("片源不一致（含「有的有、有的无」）——时间轴结论不可比，"
                    "UNVERIFIED 的那次没有被检查过，不等于通过。")
    plans = {tuple(r["id"] for r in m["rounds"]) for m in sums}
    if len(plans) > 1:
        warn.append("轮次表不同（`--with-low/--with-inclusive/--with-spelling` 开关不一致）"
                    "——两次跑的覆盖面不一样，「跑了几轮」不能直接比。")
    if warn:
        L += ["### 合并前须知（这几条不成立时，下面的数字不可比）", ""]
        L += [f"- {w}" for w in warn]
        L += [""]
    return L


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
    ap.add_argument("--runs", default="",
                    help="D3：合并多个 run 出报告，逗号分隔（--report 时生效）。"
                         "可与 --run 并用，--run 那个排最前。多 run 报告写到 "
                         "runs/_merged/<a>+<b>/final-report.md，不污染单个 run 目录")
    ap.add_argument("--rollback-to", default="", help="整轮回退到某轮末，如 r03")
    ap.add_argument("--show-plan", action="store_true", help="打印已有 run 的轮次状态")
    ap.add_argument("--promote", default="",
                    help="采纳建议：把 optional-fixes 里指定 id 提升进台账（不写 ASS）")
    ap.add_argument("--promote-all", action="store_true",
                    help="采纳全部建议（慎用，通常应逐条看）")
    ap.add_argument("--adopt", action="store_true",
                    help="把孤儿 log.jsonl 合并进规范台账（M1 修复）")
    ap.add_argument("--yes", action="store_true", help="跳过确认（--rollback-to 用）")
    ap.add_argument("--skip-structure-check", action="store_true",
                    help="放行结构门禁（C3b）。仅在确认 ABORT 是误报时用，"
                         "放行理由写进报告")
    args = ap.parse_args()

    wd = resolve_work_dir(args.work_dir)

    if args.adopt:
        return _adopt_orphan_logs(args.work_dir)

    if args.promote or args.promote_all:
        ids = ([x.strip() for x in args.promote.split(",") if x.strip()]
               if args.promote else [str(x.get("id")) for x in OPT.load_optional(wd)])
        if not ids:
            print("[!] 没有可提升的建议", file=sys.stderr)
            return 1
        assert_no_orphan_log(args.work_dir)
        OPT.promote(wd, ids, args.batch_id)
        return 0

    # A4：**记账和出报告的路径统统先过孤儿检测**。以前只在 --promote 上查，
    # 于是 --report 能在一本孤儿台账并存的情况下照常出报告——报告里的数字
    # 究竟来自哪本账，谁也说不清。两本账并存不是警告，是必须停下。
    if args.report or args.record or args.rollback_to or args.show_plan or args.freeze:
        assert_no_orphan_log(args.work_dir)

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
                         stamp=args.stamp,
                         skip_structure_check=args.skip_structure_check)
        print(f"[*] run {stamp} → {run_dir(wd, stamp)}")
        print(render_plan(plan, args.ass))
        return 0

    # D3：`--report --runs a,b` 不需要 --run，所以这里要把 --runs 也算进「有 run」。
    # 只看 args.run 会把合法的纯 --runs 用法挡在门外，而那正是「合并两次跑测」的
    # 主要写法（两次跑测本来就各有自己的 run 名）。
    if not args.run and not (args.report and args.runs.strip()):
        ap.error("需要 --plan / --init / --run（或 --report --runs a,b）")

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
        # B4：整轮回退是不可逆的（ASS 与 log 一起被覆盖），先打印影响面再要 --yes。
        m = load_manifest(wd, args.run)
        eff = [r for r in m["rounds"]
               if r["verdict"] in ("keep", "no_finding")
               and r["id"] > args.rollback_to]
        n_fix = sum(r["n_fixes"] for r in eff)
        print(f"[!] 将回滚到 {args.rollback_to}，以下 {len(eff)} 轮的改动会被撤销"
              f"（合计 {n_fix} 条）：")
        for r in eff:
            print(f"      {r['id']} {r['name']}  {r['n_fixes']} 条  batch={r['batch_id'] or '—'}")
        if not args.yes:
            print("    这是不可逆操作（ASS 与 log.jsonl 会一起被覆盖）。确认加 --yes。")
            return 1
        m = rollback_to(wd, args.run, args.rollback_to)
        print(f"[*] 已回滚到 {m['rolled_back_to']['at']}（ASS + log.jsonl 均还原）")
        return 0

    if args.report:
        # D3：--runs a,b 可独立用（不需要 --run），也可与 --run 并用。
        stamps = _norm_merge_stamps(args.runs, args.run)
        if not stamps:
            ap.error("--report 需要 --run 或 --runs")
        out = write_report(wd, stamps)
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
