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
- **快照只写一次**。`logs/rNN_<batch_or_none>.jsonl` 在 `--record rNN` 时封存；
  更晚轮次落盘后再补记早期轮次会被拒绝。
- **结构性改动必须入账**。`retime_curve` / `delete` / 手工兜底缺 batch 条目时
  `--record` 拒绝通过；手工兜底只能走 `apply_fixes --manual-log`。
- **建议未落盘要单列**。本轮产出 `optional-fixes.json` 但未 promote →
  `verdict=advisory`，报告写「本轮 N 条建议未落盘」。

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

  # 5. 整轮回退（先预演，确认后加 --yes）
  python round_orchestrator.py --run <stamp> --rollback-to r03
  python round_orchestrator.py --run <stamp> --rollback-to r03 --yes

退出码（与 lib/verdict.py 一致）:
  0  正常
  2  定格了（frozen）—— 后续轮次不应继续
  3  未验时间轴（UNVERIFIED，常见于无片源批次；不是错误）
  1  输入非法 / 状态不一致
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import verdict as V
from lib import credential as CRED
from lib.log import read_log
from lib.paths import (resolve_work_dir, orphan_logs, assert_no_orphan_log,
                       assert_report_location)
from lib import optional as OPT
from lib import report_state as RSTATE
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

VERDICTS = ("pending", "keep", "rollback", "skip", "no_finding", "advisory")

#: 会产生快照的 verdict。advisory（A1：本轮有建议未落盘）内容改动照样落盘，
#: 所以与 keep/no_finding 同等对待；区别只在报告里单列一节。
SNAPSHOT_VERDICTS = ("keep", "no_finding", "advisory")

#: 结构性改动：这类动作绕过 fixes.json 的撞车预检，**必须**带 batch 条目才能记轮次（B2）。
STRUCTURAL_ACTIONS = ("retime_curve", "delete", "manual_edit", "structural_change")


# ── 计划 ────────────────────────────────────────────────────────────────────

def build_plan(*, with_low=False, with_inclusive=False, with_spelling=None,
               asr_source=False) -> list:
    """按开关排出本次实际要跑的轮次。返回的每一轮都带了生效的 scope。

    `with_spelling` 是三态：
      - True  强制开启（CLI `--with-spelling`）
      - False 强制关闭（CLI `--no-with-spelling`）
      - None  按素材来源默认：英文轨来自 ASR/听写（`asr_source=True`）时默认开，
              有独立人工 SRT 时默认关

    `asr_source` 由调用方判定：没有独立 SRT，或显式 `--asr-transcribed`。
    第 6 类仍只并入 R1–R3/R10，不新增轮次、不新增门。
    """
    spelling = bool(asr_source) if with_spelling is None else bool(with_spelling)
    opts = {"with_low": with_low, "with_inclusive": with_inclusive,
            "with_spelling": spelling}
    plan = []
    for r in ROUNDS:
        if r["opt"] and not opts.get(r["opt"]):
            continue
        item = dict(r)
        item["scope"] = list(r["scope"])
        if spelling and r["id"] in SPELLING_MERGE:
            item["scope"] = item["scope"] + [6]
        else:
            item["scope"] = [c for c in item["scope"] if c != 6]
        plan.append(item)
    return plan


def render_plan(plan: list, ass: str = "", spelling_reason: str = "") -> str:
    L = []
    if ass:
        L.append(f"# 轮次计划 — {os.path.basename(ass)}")
        L.append("")
    L += ["| 轮 | 名称 | 审计类别 | 目标 |", "|---|---|---|---|"]
    for r in plan:
        L.append("| %s | %s | %s | %s |" % (
            r["id"], r["name"], ", ".join(str(c) for c in r["scope"]), r["goal"]))
    spelling_on = any(6 in r["scope"] for r in plan)
    if spelling_on:
        why = {"asr_default": "（ASR 素材默认开）",
               "derived_srt": "（SRT 与 ASS 英文轨逐字同源=派生，按 ASR 素材默认开）",
               "forced": "（--with-spelling 强制开）"}.get(spelling_reason, "")
        spell = f"已并入 R1–R3/R10{why}"
    else:
        why = {"disabled": "（--no-with-spelling 显式关闭）",
               "derived_srt": "（派生 SRT 与 ASS 英文轨同源，本应默认开；"
                              "--with-spelling 可强制开）",
               "human_srt": "（有独立 SRT 默认关闭；--with-spelling 可强制开）"
               }.get(spelling_reason, "（需 --with-spelling）")
        spell = f"未跑{why}"
    L += ["", f"共 {len(plan)} 轮。第 6 类（原文拼写）{spell}；"
              f"第 7 类{'跑 R9' if any(r['id'] == 'r09' for r in plan) else '未跑（需 --with-low）'}；"
              f"第 8 类{'跑 R11' if any(r['id'] == 'r11' for r in plan) else '未跑（需 --with-inclusive）'}。"]
    return "\n".join(L)


def spelling_reason(for_plan: bool, with_spelling, asr_source: bool,
                    srt_same: bool = False) -> str:
    """把「计划里第 6 类开没开」翻译成可写进 manifest/报告的原因标签。

    `srt_same` 是 issue #54 的根因修复：**有 SRT 文件不等于有人工 SRT**。
    派生 SRT（与 ASS 英文轨逐字同源）本质仍是 ASR 文本，第 6 类应默认开；
    只有内容确实不同、且经过人工审校的 SRT 才算独立权威源。
    """
    if not for_plan:
        if with_spelling is False:
            return "disabled"
        return "derived_srt" if srt_same else "human_srt"
    if with_spelling is True:
        return "forced"
    return "derived_srt" if srt_same else "asr_default"


def _norm_sub_text(text: str) -> str:
    """字幕文本归一化：去 ASS 标签、换行与多余空白，只留可比较的字面。

    两边首尾成对的引号也去掉：SSA/ASS 的 Text 字段允许用引号包住含逗号的
    文本，pysubs2 解析后可能把引号留在 `text` 里；SRT 侧通常不带引号。
    不归一化会让「文本完全相同」的两份文件同源率凭空变成 0（测试夹具实测）。
    """
    t = re.sub(r"\{[^}]*\}", "", text or "")
    t = t.replace("\\N", " ").replace("\\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    while len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        t = t[1:-1].strip()
    return t


def srt_same_source(ass: str, srt: str, *, min_ratio: float = 0.95,
                    min_rows: int = 10) -> dict:
    """判断外挂 SRT 是否只是 ASS 英文轨的**派生副本**（issue #54）。

    ## 为什么不能只看「有没有 SRT」

    `--init` 原来按「srt 路径非空 = 有人工 SRT」处理，于是把派生 SRT 当成
    独立权威源，默认关掉第 6 类。S06E04 实测：`S06E04.eng.srt` 与 ASS 英文轨
    **750 行里 748 行逐字相同**（另外 2 行是 ASS 侧的 `s***` 打码），它就是
    同一份 ASR 文本换了个容器。结果 319「Yeah. ,,,and look at that.」、
    649「Ooh, t's getting busy now.」这类 ASR 错字整集无人审。

    判定口径：按起点排序后逐行比较归一化文本，同源率 ≥ `min_ratio` 且
    行数 ≥ `min_rows` 才算派生。返回 `{"same", "ratio", "n", "n_srt"}`，
    读不出文件时 `same=False`（宁可退回旧口径，也不误开第 6 类）。
    """
    out = {"same": False, "ratio": 0.0, "n": 0, "n_srt": 0}
    if not (ass and srt) or not os.path.exists(ass) or not os.path.exists(srt):
        return out
    try:
        import pysubs2
        subs_a = pysubs2.load(ass, encoding="utf-8-sig")
        subs_s = pysubs2.load(srt, encoding="utf-8-sig")
    except Exception:  # noqa: BLE001
        return out

    en = [e for e in subs_a if (e.style or "").strip() == "英文"]
    if not en:      # 样式名不叫「英文」时，退回按字符集挑非中文行
        en = [e for e in subs_a
              if not any("\u4e00" <= c <= "\u9fff" for c in (e.text or ""))]
    en = sorted(en, key=lambda e: (e.start, e.end))
    sr = sorted([e for e in subs_s if (e.text or "").strip()],
                key=lambda e: (e.start, e.end))
    out["n"], out["n_srt"] = len(en), len(sr)
    if len(en) < min_rows or len(sr) < min_rows:
        return out
    n = min(len(en), len(sr))
    same = sum(1 for a, b in zip(en[:n], sr[:n])
               if _norm_sub_text(a.text) == _norm_sub_text(b.text))
    out["ratio"] = round(same / float(n), 4)
    out["same"] = out["ratio"] >= min_ratio
    return out


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
    # issue #27：`text=True` 会按 locale.getpreferredencoding() 解码子进程 stdout。
    # 中文 Windows 上那是 GBK(cp936)，而 structure_check 输出 UTF-8，中文会变乱码。
    # 退出码不受影响，但「为什么放行」这句给人看的摘要会不可读。显式按 UTF-8 解码。
    try:
        p = subprocess.run([sys.executable, script, "--ass", ass, "--quiet"],
                           capture_output=True, encoding="utf-8",
                           errors="replace", timeout=120)
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
             skip_structure_check: bool = False,
             asr_transcribed: bool = False,
             spelling_reason: str = "") -> str:
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

    # issue #54：有 SRT 路径 ≠ 有人工 SRT。派生 SRT 与 ASS 英文轨逐字同源，
    # 本质仍是 ASR 文本，第 6 类应按 ASR 素材默认开。
    same = srt_same_source(ass, srt)
    asr_source = bool(asr_transcribed or not (srt or "").strip() or same["same"])
    spelling_on = any(6 in r["scope"] for r in plan)
    if not spelling_reason:
        # 直接调 API 的调用方没传原因时，按 manifest 里能观察到的事实回填。
        if not spelling_on:
            if same["same"]:
                spelling_reason = "derived_srt"
            else:
                spelling_reason = "human_srt" if not asr_source else "unknown"
        else:
            spelling_reason = "asr_default" if asr_source else "forced"
    m = {
        "run": stamp,
        "ass": os.path.abspath(ass),
        "srt": os.path.abspath(srt) if srt else "",
        "media": os.path.abspath(media) if media else "",
        "opts": {
            "with_low": any(r["id"] == "r09" for r in plan),
            "with_inclusive": any(r["id"] == "r11" for r in plan),
            "with_spelling": spelling_on,
            "spelling_reason": spelling_reason,
            "gated": bool(gated),
            # issue #30：显式标记「英文轨是 ASR(whisper) 转录」。派生 SRT 场景下
            # srt 路径非空，仅凭路径分不出是不是听写结果，需要 init 时记一笔。
            "asr_transcribed": bool(asr_transcribed),
            # 第 6 类默认开关的依据：无独立 SRT 或显式标记都算 ASR 源。
            "asr_source": asr_source,
            # issue #54：SRT 与 ASS 英文轨的同源实测。`same=True` 表示这份 SRT
            # 只是派生副本，不能当作「独立人工审校源」来关掉第 6 类。
            "srt_same_source": bool(same["same"]),
            "srt_match_ratio": same["ratio"],
        },
        "created": datetime.now().isoformat(timespec="seconds"),
        "frozen": None,
        "frozen_rows": [],
        "rounds": [{"id": r["id"], "name": r["name"], "scope": r["scope"],
                    "batch_id": "", "n_fixes": 0, "verdict": "pending",
                    "snapshot": "", "log_snapshot": "", "optional_pending": 0,
                    "note": ""} for r in plan],
    }
    save_manifest(wd, stamp, m)
    with open(os.path.join(d, "round-plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    return stamp


# ── 记账 ────────────────────────────────────────────────────────────────────

def latest_snapshot(m: dict) -> str:
    """当前有效的快照文件名（最后一个 keep/no_finding/advisory 轮，没有则 r00）。"""
    for r in reversed(m["rounds"]):
        if r["verdict"] in SNAPSHOT_VERDICTS and r.get("snapshot"):
            return r["snapshot"]
    return "r00.ass"


def _snap_stem(rid: str, batch_id: str) -> str:
    """快照文件名主干：`r09_<batch_or_none>`。

    B4：文件名必须让「这一轮到底改没改」一眼可见——有 batch = 有改动，
    `_none` = 该轮没产出 batch（通常是 no_finding）。同时它也是写一次守卫的
    唯一标识：同一个 stem 对应的 ledger 快照不允许被第二次写入。
    """
    bid = (batch_id or "").strip() or "none"
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in bid)
    return f"{rid}_{safe}"


def _log_snapshot_rel(rid: str, batch_id: str) -> str:
    return os.path.join("logs", _snap_stem(rid, batch_id) + ".jsonl")


def _log_snapshot_of(m: dict, r: dict) -> str:
    """某轮 manifest 条目对应的 log 快照相对路径。"""
    if r.get("log_snapshot"):
        return r["log_snapshot"]
    # 旧 run 没有 log_snapshot 字段：按老命名 logs/rNN.jsonl 找。
    return os.path.join("logs", r["id"] + ".jsonl")


def _log_snapshot_for(m: dict, snap: str) -> str:
    """快照名字（r03.ass / r00.ass）→ 对应的 log 快照路径。"""
    if not snap or snap == "r00.ass":
        return os.path.join("logs", "r00.jsonl")
    hit = next((r for r in m["rounds"] if r.get("snapshot") == snap), None)
    if hit is not None:
        return _log_snapshot_of(m, hit)
    stem = os.path.splitext(os.path.basename(snap))[0]
    rid = stem.split("_")[0]
    return os.path.join("logs", f"{rid}.jsonl")


def _read_jsonl(p: str) -> list:
    """读 JSONL，坏行跳过（台账可能被手工追加过，不能让一行坏数据阻断记账）。"""
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


def _entry_key(e: dict) -> tuple:
    return (e.get("file", ""), e.get("srt_id"), e.get("track", ""),
            e.get("old_text", ""), e.get("new_text", ""), e.get("ts", ""))


def _count_dialogue(path: str) -> int:
    """数 ASS 的 Dialogue 行（回滚预演里的「行」）。"""
    n = 0
    if not os.path.exists(path):
        return n
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.lstrip().startswith("Dialogue:"):
                n += 1
    return n


def _guard_snapshot(m: dict, rid: str) -> None:
    """B4-1/B4-2：快照只允许在 `--record rNN` 那一刻写一次。

    - 更晚的轮次已经落盘（有快照）→ 拒绝补记，并指出是被哪一轮越过；
    - 本轮已有快照 → 拒绝二次写入。
    """
    idx = next(i for i, r in enumerate(m["rounds"]) if r["id"] == rid)
    later = [r for r in m["rounds"][idx + 1:] if r.get("snapshot")]
    if later:
        raise SystemExit(
            f"[x] {rid} 的台账快照已被 {later[0]['id']} 越过，无法补记。\n"
            f"    快照只允许在 --record {rid} 那一刻写一次；要重来请用 --init 开新 run。")
    target = m["rounds"][idx]
    if target.get("snapshot"):
        raise SystemExit(
            f"[x] {rid} 的快照已存在（{target['snapshot']}），只允许写一次；"
            f"要改判请用 --rollback-to，或 --init 开新 run。")


def _apply_advisory(wd: str, m: dict, verdict: str) -> tuple:
    """A1 尾巴：本轮产出过 optional-fixes.json 且未 promote → verdict=advisory。

    返回 (verdict, 未落盘条数)。用内容 sha 判断「这一轮产出的」：同一个文件
    在两轮之间没变过，就不能把上一轮的建议重复记到这一轮头上。
    """
    if verdict not in ("keep", "no_finding"):
        return verdict, 0
    p = OPT.optional_json_path(wd)
    if not os.path.exists(p):
        m.pop("optional_sha", None)
        return verdict, 0
    with open(p, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    changed = sha != m.get("optional_sha")
    m["optional_sha"] = sha
    pending = [x for x in OPT.load_optional(wd) if not x.get("batch_id")]
    if pending and changed:
        return "advisory", len(pending)
    return verdict, 0


def _assert_structural_accounted(wd: str, d: str, m: dict, rid: str,
                                 batch_id: str) -> None:
    """B2：retime_curve / delete / 手工兜底必须有 batch 条目，否则拒绝记账。

    取「本轮窗口」= 当前台账（主 + working）里、本轮之前快照中不存在的条目。
    只读，不先写入任何东西——校验失败时不能留下半截状态。
    """
    main = _read_jsonl(os.path.join(wd, "log.jsonl"))
    working = _read_jsonl(os.path.join(d, "working", "log.jsonl"))
    current, seen = [], set()
    for e in main + working:
        k = _entry_key(e)
        if k in seen:
            continue
        seen.add(k)
        current.append(e)

    prev_snap = latest_snapshot(m)
    prev = {_entry_key(e) for e in
            _read_jsonl(os.path.join(d, _log_snapshot_for(m, prev_snap)))}
    window = [e for e in current if _entry_key(e) not in prev]
    structural = [e for e in window if e.get("action") in STRUCTURAL_ACTIONS]
    if not structural:
        return

    no_batch = [e for e in structural if not str(e.get("batch_id") or "").strip()]
    if no_batch:
        detail = "\n".join(
            "      action=%s srt_id=%s batch=(空)" % (e.get("action"), e.get("srt_id"))
            for e in no_batch[:10])
        raise SystemExit(
            f"[x] {rid} 有 {len(no_batch)} 条结构性改动缺少 batch 条目，拒绝记账。\n"
            f"    retime_curve / delete / 手工兜底都必须带 batch_id：\n"
            f"      · retime_curve 由 align_patch --write 自动记（不要手补）\n"
            f"      · delete 由 apply_fixes --accept 自动记（不要手补）\n"
            f"      · 手工兜底只能走 --manual-log（唯一手工入口）：\n"
            f"      python <skill>/scripts/apply_fixes.py --manual-log --batch-id <batch> "
            f"--file \"<ass>\" --srt-id <id> --track 中文 --old \"<原文本>\" --new \"<新文本>\" "
            f"--reason \"<为什么破例>\"\n"
            f"    涉及条目：\n{detail}")
    if not batch_id:
        raise SystemExit(
            f"[x] {rid} 有 {len(structural)} 条结构性改动，--record 必须带 --batch-id，否则"
            f"这一轮无法在报告里按批回滚。\n"
            f"      python <skill>/scripts/round_orchestrator.py --run <stamp> "
            f"--record {rid} --batch-id <batch> --n-fixes <N> --verdict keep")


def record_round(wd: str, stamp: str, rid: str, *,
                 batch_id: str = "", n_fixes: int = 0, verdict: str = "",
                 note: str = "", freeze_rows=None) -> dict:
    """记一轮的结果。keep/no_finding/advisory 时把当前 ASS 存成本轮快照。

    `verdict` 不传时按 n_fixes 推断（0 → no_finding，>0 → keep），
    但 **rollback / skip 必须显式传**——这两种状态不能让调用方猜。

    B4：快照只允许写一次。更晚的轮次已落盘后再补记早期轮次会被拒绝，
    不再出现「r09 的台账快照被 r11 之后的改动覆盖」。
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

    # B4-1/B4-2：补记与覆盖守卫，必须在任何写盘动作之前。
    _guard_snapshot(m, rid)

    target["batch_id"] = batch_id or target["batch_id"]
    target["n_fixes"] = int(n_fixes)
    target["note"] = note

    if verdict in SNAPSHOT_VERDICTS:
        # A1 尾巴：本轮产出过建议但未 promote → advisory（报告必须单列）。
        verdict, pending = _apply_advisory(wd, m, verdict)
        target["verdict"] = verdict
        target["optional_pending"] = pending

        # B2：结构性改动必须有 batch 条目，否则拒绝记账（读校验，先于写盘）。
        _assert_structural_accounted(wd, d, m, rid, target["batch_id"])

        # B1：先把 working 台账归并回主台账，再拷快照。顺序不能反——先拷快照
        # 会把「还没归并」的 working 当成唯一证据，主台账依旧是空的。
        _merge_working_log(wd, d)

        # B4-3：快照文件名带 batch_id（rNN_<batch_or_none>），写一次即封存。
        stem = _snap_stem(rid, target["batch_id"])
        snap = f"{rid}.ass"
        log_rel = _log_snapshot_rel(rid, target["batch_id"])
        ass_dst = os.path.join(d, snap)
        log_dst = os.path.join(d, log_rel)
        for p in (ass_dst, log_dst):
            if os.path.exists(p):
                raise SystemExit(
                    f"[x] 快照已存在，拒绝覆盖：{p}\n"
                    f"    一个轮次的快照只允许写一次；要重来请 --init 开新 run。")
        shutil.copy2(m["ass"], ass_dst)
        # log 快照：working/log.jsonl 是本轮执行后的台账（--auto 隔离模式），
        # 没有 working 副本时（逐步模式）直接整本拷主 log。
        #
        # B1（issue #24）：`--auto` 隔离模式下 working/log.jsonl 必须**归并回**
        # 主 log.jsonl，否则主台账永远停留在 r00 的状态——74 条改动最后在报告
        # 里只剩 2 条，就是这么来的。归并在 `_merge_working_log()` 里做，
        # 这里只读归并后的主 log。
        working = os.path.join(d, "working", "log.jsonl")
        src = working if os.path.exists(working) else os.path.join(wd, "log.jsonl")
        if os.path.exists(src):
            shutil.copy2(src, log_dst)
        else:
            open(log_dst, "w", encoding="utf-8").close()
        target["snapshot"] = snap
        target["log_snapshot"] = log_rel
    else:
        target["verdict"] = verdict
        target["optional_pending"] = 0
        if verdict == "rollback":
            # 回滚到上一轮有效快照；本轮不产生新快照
            prev = latest_snapshot(m)
            _restore(m, d, prev)
            target["note"] = (target["note"] + " | rolled back to " + prev).strip(" |")

    if freeze_rows:
        rows = [int(x) for x in freeze_rows]
        m["frozen_rows"] = sorted(set(m.get("frozen_rows", [])) | set(rows))

    # 台账折算：回滚后「净改动」会小于「Σn_fixes」，差额记在本轮。
    # 这一步必须在 log 归并之后（否则读到的是上一轮的盘面）。
    _reconcile_ledger(m, wd, rid)

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
    log_src = os.path.join(d, _log_snapshot_for(m, snap))
    if not os.path.exists(log_src):
        raise SystemExit(
            f"[!] 缺台账快照：{log_src}\n"
            f"    只还原 ASS 不还原 log 会让后续校验看到已撤销的改动，拒绝半还原。")
    # 主 log 位置 = <work_dir>/log.jsonl；d = <work_dir>/runs/<stamp>
    log_dst = os.path.join(os.path.dirname(os.path.dirname(d)), "log.jsonl")
    shutil.copy2(src, m["ass"])
    shutil.copy2(log_src, log_dst)
    # 还原后盘面是旧快照，之前的 verify/cross_check 报告描述的是被撤销的那一版。
    # 作废它们，报告才会写「需重跑」而不是沿用旧绿（issue #45）。
    work_dir = os.path.dirname(os.path.dirname(d))
    RSTATE.invalidate(work_dir, "整轮还原到 %s" % snap)


def _resolve_snapshot(m: dict, rid: str) -> str:
    """把轮 id 解析成 ASS 快照文件名（回滚预演与执行共用同一套判定）。"""
    if rid in ("", "r00"):
        return "r00.ass"
    hit = next((r for r in m["rounds"] if r["id"] == rid), None)
    if hit is None:
        raise SystemExit(f"[!] 计划里没有 {rid}")
    if not hit.get("snapshot"):
        raise SystemExit(
            f"[!] {rid} 没有快照（verdict={hit['verdict']}）。"
            f"只能退到有快照的轮次："
            f"{', '.join(r['id'] for r in m['rounds'] if r.get('snapshot')) or 'r00'}")
    return hit["snapshot"]


def rollback_to(wd: str, stamp: str, rid: str) -> dict:
    """把 ASS 与 log.jsonl 整本还原到第 `rid` 轮末。"""
    m = load_manifest(wd, stamp)
    d = run_dir(wd, stamp)
    snap = _resolve_snapshot(m, rid)
    _restore(m, d, snap)
    _sync_working(d, _log_snapshot_for(m, snap))
    m["rolled_back_to"] = {"at": snap, "ts": datetime.now().isoformat(timespec="seconds")}
    save_manifest(wd, stamp, m)
    return m


def _sync_working(d: str, log_snapshot: str) -> None:
    """把 log 快照同步到 working/，让下一轮的起始台账是干净的那一份。"""
    src = os.path.join(d, log_snapshot)
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

    rollback 条目也参与「终译」：回滚日志的 new_text 就是还原后的文本。
    以前只认 replace/manual_edit，于是 apply_fixes --rollback 之后总账仍显示
    「原译 → 被撤回的新译」，配上一行「净改动 8 条」，整份报告都在说反话
    （issue #45，S06E04 实测）。
    """
    rows = {}
    for e in sorted(entries, key=lambda x: x.get("ts", "")):
        action = e.get("action")
        if action not in ("replace", "manual_edit", "rollback"):
            continue
        if not e.get("srt_id"):
            continue
        key = (e.get("file", ""), int(e["srt_id"]), e.get("track", ""))
        r = rows.get(key)
        if r is None:
            if action == "rollback":
                continue       # 只回滚、从未记过改动的行不成账
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


def _effective_net(ledger: list) -> int:
    """净改动 = 终译与首稿不同的行数（`--rollback` 已折算进终译）。

    不能直接用台账里的 n_fixes 相加：那是「这一轮写过几条」，不回答
    「现在盘面上还剩几条改动」。回滚过的批次两者会分叉。
    """
    return sum(1 for r in ledger
               if (r.get("new") or "") != (r.get("old") or ""))


def _ledger_total(rounds: list, only_kept: bool = False) -> int:
    """台账累计 = 各轮 n_fixes + 折算项（负值抵消被回滚的轮次）。

    `ledger_adjust` 由 `_reconcile_ledger()` 在每轮 `--record` 时写入：快照
    封存后不能再改早期轮次的 n_fixes（那是历史事实），但账要能对得上——把
    差额记成一条折算项，而不是回头篡改。
    """
    src = [r for r in rounds if r["verdict"] in SNAPSHOT_VERDICTS] if only_kept else rounds
    return sum(int(r.get("n_fixes") or 0) + int(r.get("ledger_adjust") or 0)
               for r in src)


def _reconcile_ledger(m: dict, wd: str, rid: str) -> None:
    """把「净改动」与「台账累计」的差额记到本轮，避免报告长期背着不一致告警。

    典型场景：r01 记了 8 条，随后整批回滚，`--record` 的 r01 快照已封存，
    不能改；于是每份报告都写「台账 11 / 净改动 3」。这里在**当前轮**记一条
    折算项（负数），让 `Σn_fixes + Σledger_adjust == 净改动`。

    本轮的 n_fixes 是「本轮实际写过几条」，不能拿折算去掩盖它；折算只吸收
    **不属于本轮**的历史差额（回滚、外部 apply、手工改盘）。
    """
    target = next(r for r in m["rounds"] if r["id"] == rid)
    target["ledger_adjust"] = 0
    net = _effective_net(_parse_ledger(read_log(wd)))
    total = _ledger_total(m["rounds"])
    target["ledger_adjust"] = net - total


def _ledger_suffix(net: int, total: int, base_total: int, carried: int) -> str:
    """顶栏「台账」那半句：净改动与台账必须对得上。

    对不上的唯一合法来源是「回滚折算」——早期轮次的 n_fixes 随快照封存，
    不能改，差额记成当前轮的 `ledger_adjust`。若折算之后仍对不上（回滚后
    直接出报告、没有新 `--record`），报告层按盘面折算一次并标明，**不写回
    manifest**（快照是历史事实，不篡改）。
    """
    if net == total:
        if carried:
            return "（台账 %d 条，含回滚折算 %+d 条）" % (total, carried)
        return ""
    return ("（台账 %d 条 = 原始累计 %d 条 + 回滚折算 %+d 条，已按盘面对齐）"
            % (net, base_total, net - base_total))


def _round_cell(row: dict, b2r: dict) -> str:
    """总账「轮次」列：真实轮次集合 + 非轮次批次/净零标注。

    以前这里写 `len(batches)`——那是「被几个批次碰过」，不是轮次号。
    一行被 r01 改过、又被两个回滚批次撤销，会显示 3，读起来像「第 3 轮」。
    """
    ids = []
    for b in row.get("batches") or []:
        rid = b2r.get(b)
        if rid and rid not in ids:
            ids.append(rid)
    stray = any(b and b not in b2r for b in row.get("batches") or [])
    txt = ", ".join(ids) if ids else "—"
    if stray:
        txt += "*"
    if (row.get("new") or "") == (row.get("old") or ""):
        txt += "（净零）"
    return txt


def _path_differs(a: str, b: str) -> bool:
    """两个路径是否指向不同文件（用于标注跨 run 的历史日志路径）。"""
    if not a or not b:
        return False
    try:
        return (os.path.normcase(os.path.abspath(a))
                != os.path.normcase(os.path.abspath(b)))
    except Exception:       # noqa: BLE001
        return True


def _script(name: str) -> str:
    """同目录脚本的实际路径（报告里的命令用真实路径，不写 `<skill>` 模板）。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def _rollback_cmd(ass: str, batch_id: str = "", srt_id=None,
                  work_dir: str = "") -> str:
    """生成回滚命令。**两个粒度不能混用**（B3）。

    以前这里写的是 `--rollback id=<batch_id> --file <ass>`：把批次标识填进了
    `id=`（那是 srt_id 的位置），生成的命令必然回滚错行——而且看起来还很正常，
    因为 `id=` 确实存在，只是语义错了。

    现在按粒度分开，且命令来自**本次实际使用的解释器与脚本路径**（不是
    `python <skill>/...` 这种模板）：
      - 整批：`--rollback batch=<batch_id>`（一次回滚这一轮的全部改动）
      - 单条：`--rollback id=<srt_id> --file <ass>`（精确到行，需限定文件）
    """
    py = sys.executable or "python"
    script = _script("apply_fixes.py")
    wd_part = f' --work-dir "{work_dir}"' if work_dir else ""
    if batch_id:
        return f'"{py}" "{script}" --rollback batch={batch_id}{wd_part}'
    if srt_id is not None:
        return (f'"{py}" "{script}" --rollback id={srt_id} --file "{ass}"{wd_part}')
    return "# 无可用回滚标识"


def _md_cell(text, limit: int = 0) -> str:
    """把任意文本塞进 Markdown 表格单元格（D1，issue v1.15）。

    这里是**去截断**，不是换一种截断：
      原来四处写着 `[:16]` / `[:18]` / `[:20]`，改动总账里「原译」和「终译」
      只显示前 20 个字。而这一列就是整份报告的存在理由——读报告的人要判断
      「这条改动对不对」，看的是完整的两句话。截到 20 字之后，「He was going
      to say」和「He was going to say something」在表里长得一模一样，两条
      不同的改动在视觉上无法区分。

    真正需要处理的不是长度，是表格抗性：
      - `|` 会被解析成分列符，整行错位 → 转义成 `\\|`
      - 换行会截断表格行 → 换成 `<br>`（Markdown 表格内可用）
      - `\\` 本身要先转义，否则会吃掉后面补的转义符
    limit 参数留给调用方显式限制，**默认 0 = 不限**——纪律是「默认给全」，
    要短得由调用方明说不说「顺便截一下」。
    """
    if text is None:
        return ""
    s = str(text)
    s = s.replace("\\", "\\\\")
    s = s.replace("|", "\\|")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\n", "<br>")
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return s


def _timeline_state(m: dict) -> dict:
    """报告里的时间轴结论：以 sidecar 凭据为准，manifest.media 只作补充。

    issue #28：`media` 是 `--init` 时冻结进 manifest 的。无片源开工、跑完文本轮
    之后才补验轴时，manifest 里永远是空，报告却一直写「UNVERIFIED（无片源）」。
    这里改读 `<episode>.ts.json`：

      1. 凭据存在且新鲜 -> 按 axis.verdict 写 PASS / FAIL / AMBIGUOUS；
      2. manifest 没记片源但凭据记过 -> 用凭据里的路径复核「没换片」；
      3. 两者都没有 -> 才写 UNVERIFIED。
    """
    ass = m.get("ass") or ""
    media = m.get("media") or ""
    data = CRED.load(ass) if ass else None
    if data and not media:
        rec = (data.get("media") or {}).get("path") or ""
        if rec:
            media = rec
    if not ass:
        return {"code": V.UNVERIFIED, "label": V.label(V.UNVERIFIED),
                "reason": "没有 ASS 路径，无法定位凭据", "has_credential": False,
                "media": "", "sidecar": ""}
    res = CRED.check(ass, media=media or None)
    code = res["verdict"]
    reasons = res.get("reasons") or []
    return {
        "code": code,
        "label": V.label(code),
        "reason": reasons[0] if reasons else "",
        "has_credential": bool(res.get("data")),
        "media": media,
        "sidecar": (res.get("detail") or {}).get("sidecar", ""),
        # 双对齐器互证的可信度附注。`spread_only` 不改变 code（PASS 仍是 PASS）；
        # `divergent` 已在凭据侧升格为 AMBIGUOUS，这里只把成因写清楚，
        # 交给人决定要不要抽查。
        "confidence": (res.get("detail") or {}).get("axis_confidence"),
        # 不影响判定但必须让人看见的事实（派生音频 vs 容器、表头重写等）。
        "notes": res.get("notes") or [],
    }


def _confidence_suffix(conf) -> str:
    """时间轴结论后面的可信度短句。没有互证记录就返回空串。"""
    if not conf:
        return ""
    status = conf.get("status")
    if status == "corroborated":
        return "；双对齐器已印证"
    if status == "spread_only":
        return ("；双对齐器整体一致，但少数行离散（P90 %s s），"
                "需抽查 worst_rows" % (conf.get("ts_p90", "—")))
    if status == "divergent":
        return ("；⚠ 未获双对齐器印证（divergent：%s），现有 PASS/FAIL 不可全信，"
                "建议抽查音频" % (conf.get("reason") or "两路结论不一致"))
    if status == "single_source":
        return "；单路对齐，未获双引擎印证"
    if status == "no_data":
        return "；两路均无足够锚点，未获双引擎印证"
    return ""


def _timeline_top_text(st: dict) -> str:
    """顶栏一句话。PASS/FAIL/AMBIGUOUS 与 UNVERIFIED 的成因要分开写。"""
    suffix = _confidence_suffix(st.get("confidence"))
    if st["code"] == V.PASS:
        return "时间轴 PASS（凭据已验）" + suffix
    if st["code"] == V.FAIL:
        return "时间轴 FAIL（凭据判轴有问题）" + suffix
    if st["code"] == V.AMBIGUOUS:
        return "时间轴 AMBIGUOUS（验了但判不出）" + suffix
    if st["has_credential"]:
        return "时间轴 UNVERIFIED（凭据失效：%s）" % (st["reason"] or "原因未记录")
    if st["media"]:
        return "时间轴 UNVERIFIED（有片源但未验轴）"
    return "时间轴 UNVERIFIED（无片源）"


def _timeline_gap_text(st: dict) -> str:
    """「本次未覆盖」里的时间轴条目。只有 UNVERIFIED 才算未覆盖。"""
    if st["has_credential"]:
        return ("时间轴 —— 凭据失效（%s），判 UNVERIFIED（不是通过）"
                % (st["reason"] or "原因未记录"))
    if st["media"]:
        return "时间轴 —— 有片源但未验轴，判 UNVERIFIED（不是通过）"
    return "时间轴 —— 无片源，判 UNVERIFIED（不是通过）"


def _is_asr_transcribed(m: dict) -> bool:
    """英文轨是不是 whisper/ASR 转录（issue #30）。

    两种来源都算：init 时显式 `--asr-transcribed`（派生 SRT 场景，路径非空但
    内容仍是听写结果），或根本没提供独立 SRT（没有权威英文源，只能是听写）。
    这种素材即使中文轨全对，第 6 类（原文拼写）不跑也会把 ASR 错误留在英文轨。

    issue #54：init 实测出 `srt_same_source=True`（SRT 与 ASS 英文轨逐字同源）
    同样算 ASR 源——有 SRT 文件不等于有人工审校。
    """
    if (m.get("opts") or {}).get("asr_transcribed"):
        return True
    if (m.get("opts") or {}).get("srt_same_source"):
        return True
    return not (m.get("srt") or "").strip()


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
    kept = [r for r in rounds if r["verdict"] in SNAPSHOT_VERDICTS]
    advisory = [r for r in rounds if r["verdict"] == "advisory"]
    rolled = [r for r in rounds if r["verdict"] == "rollback"]
    skipped = [r for r in rounds if r["verdict"] == "skip"]
    total = _ledger_total(rounds, only_kept=True)
    base_total = sum(int(r.get("n_fixes") or 0) for r in kept)
    carried = total - base_total

    churn = _churn_by_batch(wd)
    conflicts = _conflicts(wd)
    ledger = _parse_ledger(read_log(wd))
    # 「还剩几条改动」要从日志回算：apply_fixes --rollback 之后，台账里
    # 的 n_fixes 仍是「曾经写过几条」，不代表当前盘面（issue #45）。
    net = _effective_net(ledger)
    vst = RSTATE.state(wd)
    vnames = vst.get("names") or []
    vpath = os.path.join(wd, "reports", "verify-fixes.md")
    # issue #28：时间轴结论从 sidecar 凭据读，不再只看 init 时冻结的 media。
    tl = _timeline_state(m)

    L = [f"# 最终报告 — {os.path.basename(m['ass'])}", ""]
    top = [f"轮次 {len(done)}/{len(rounds)} 已跑完"]
    if rolled:
        top.append(f"回滚 {len(rolled)}")
    if skipped:
        top.append(f"skip {len(skipped)}")
    if advisory:
        top.append(f"建议未落盘 {sum(r.get('optional_pending', 0) for r in advisory)} 条")
    top.append(f"净改动 {net} 条" + (_ledger_suffix(net, total, base_total, carried)))
    top.append(_timeline_top_text(tl))
    if m.get("frozen"):
        top.append(f"**已定格于 {m['frozen']['at']}：{m['frozen']['reason']}**")
    L += ["> " + " / ".join(top), ""]
    if tl.get("notes"):
        L += ["> 注：" + "；".join(tl["notes"]), ""]
    if "verify-fixes.md" in vnames:
        L += ["> ⚠ 验证结论已作废：%s。回滚改变了盘面，旧的「通过」不再代表当前状态，"
              "必须重跑 `verify_fixes --all`。" % (vst.get("reason") or "回滚"), ""]
    elif not os.path.exists(vpath):
        L += ["> ⚠ 还没有 verify_fixes 报告：本次改动未做执行后验证，"
              "不能当作已通过。", ""]

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
                "「%s」" % (_md_cell(t.get("new", "")) or "—") for t in c["trail"])
            # B3：这一列以前硬写着 `--rollback id=N`，但只有 srt_id 没有 file，
            # 照着抄会回滚到**同号的所有文件**。走 _rollback_cmd() 统一生成，
            # 顺带把 file 带上。
            cmd = _rollback_cmd(m["ass"], srt_id=sid, work_dir=wd)
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
                _md_cell(s.get("old_text")) or "", _md_cell(s.get("new_text")) or "",
                _md_cell(s.get("reason")) or ""))
        if len(struct) > 40:
            L.append("| … | | | 其余 %d 条见 log.jsonl | |" % (len(struct) - 40))
        L += ["", "> 这些改动没有走 fixes.json 的撞车预检，冲突排查时优先看这里。", ""]

    L += ["## 改动总账", ""]
    if ledger:
        # batch_id -> 轮 id。这一列要写**真正的轮次号**，不是「被几个批次
        # 碰过」：R1 的 8 条改动还被两个回滚批次碰过，按批次数会显示 3，
        # 而它们其实只属于 r01。
        b2r = {r["batch_id"]: r["id"] for r in rounds if r.get("batch_id")}

        # issue #54：跨运行目录的**净零**历史条目不进总账。它们对净改动贡献 0，
        # 却会以旧 run 路径的形式出现在脚注里，看起来像一条能照抄的回滚命令
        # （S06E04 实测：8 条 r01 条目把 `20261104_131806` 路径打印了 8 次）。
        def _stray_zero(r):
            return (bool(r.get("file")) and _path_differs(r["file"], m["ass"])
                    and (r.get("new") or "") == (r.get("old") or ""))

        stray_zero = [r for r in ledger if _stray_zero(r)]
        stray_live = [r for r in ledger
                      if r.get("file") and _path_differs(r["file"], m["ass"])
                      and not _stray_zero(r)]
        ledger_show = [r for r in ledger if not _stray_zero(r)]

        L += ["| srt_id | 轨道 | 原译 | 终译 | 类别 | 轮次 | 回滚 |",
              "|---|---|---|---|---|---|---|"]
        for r in ledger_show:
            # 单条回滚必须指向**本次实际在用的** ASS：历史日志里的 file 是
            # 上一次 run 的路径，跨 run 复用时会回滚到别的目录。
            cmd = _rollback_cmd(m["ass"], srt_id=r["srt_id"], work_dir=wd)
            L.append("| %s | %s | %s | %s | %s | %s | `%s` |" % (
                r["srt_id"], r["track"], _md_cell(r["old"]) or "—", _md_cell(r["new"]) or "—",
                r["category"] or "—", _round_cell(r, b2r), cmd))
        L.append("")
        has_star = any(b and b not in b2r for r in ledger_show for b in r["batches"])
        has_zero = any((r.get("new") or "") == (r.get("old") or "") for r in ledger_show)
        if has_star or has_zero:
            L += ["> 「轮次」列：`*` = 该行另经过非轮次批次（回滚或外部 apply_fixes）；"
                  "「净零」= 终译与首稿相同（典型是已回滚）。", ""]
        if stray_zero:
            # 只报「有几条」，不打印旧路径：这些路径照抄会指到别的目录。
            L += ["> 另有 %d 条跨运行目录的历史日志（终译=首稿，净零，已并入本次基线），"
                  "未列入上表；它们不产生净改动，也没有可回滚的差异。"
                  % len(stray_zero), ""]
        if stray_live:
            L += ["> 表中 %d 行的历史日志记录在另一个运行目录；上表的回滚列已"
                  "统一指向本次 ASS，旧目录不可照抄。" % len(stray_live), ""]
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
                    _rollback_cmd(m["ass"], batch_id=r["batch_id"], work_dir=wd),
                    r["id"], r["name"], r["n_fixes"]))
            L += ["```", ""]
        # B3：整轮回退的目标取自**本次实际记到的最后一轮**，不再硬写 r03；
        # 命令里的解释器、脚本、run、work-dir 都是本次实际使用的值。
        last = kept[-1]["id"] if kept else "r00"
        L += ["整轮回退（ASS 与 log 一起退回某轮末，需 `--yes` 确认）：",
              "```bash",
              f'"{sys.executable or "python"}" "{_script("round_orchestrator.py")}" '
              f'--run {stamp} --rollback-to {last} --yes --work-dir "{wd}"',
              "```", ""]
    else:
        L += ["台账为空（本次没有改动）。", ""]

    # issue #54：英文轨改动必须同步 SRT，但 **skill 从不写 SRT**。这里只出清单，
    # 把「改了 ASS 但 SRT 没跟上」这件事显式交给人，而不是悄悄让两边发散。
    en_fixes = [r for r in ledger
                if "英文" in (r.get("track") or "")
                and (r.get("new") or "") != (r.get("old") or "")]
    if m.get("srt") and en_fixes:
        ratio = (m.get("opts") or {}).get("srt_match_ratio")
        L += ["## 英文轨改动 → SRT 需人工同步（skill 不写 SRT）", "",
              "| srt_id | 原文 | 新文 |", "|---|---|---|"]
        for r in en_fixes:
            L.append("| %s | %s | %s |" % (
                r["srt_id"], _md_cell(r.get("old")) or "—",
                _md_cell(r.get("new")) or "—"))
        note = ("> SRT 是权威英文源，**本 skill 不会写它**；请按上表人工同步，"
                "否则 ASS 英文轨与 SRT 会不一致。这些改动只动文本，"
                "不改变时间轴（指纹不变）。")
        if (m.get("opts") or {}).get("srt_same_source"):
            note += ("本次 init 实测 SRT 与 ASS 英文轨同源率 %s%%：它是派生副本，"
                     "不是独立人工审校源，因此第 6 类按 ASR 素材默认开启。"
                     % ("%.2f" % (ratio * 100) if isinstance(ratio, (int, float)) else "?"))
        L += ["", note, ""]

    # A1 尾巴：advisory 轮必须单列，写清「本轮 N 条建议未落盘」。
    # 只靠下面的「建议改动」一节不够——那一节不区分是哪一轮产出的，也不写
    # 「这些建议不在净改动里」，读报告的人会把建议数当成改动数。
    if advisory:
        n_all = sum(r.get("optional_pending", 0) for r in advisory)
        L += ["## 建议未落盘（advisory）", "",
              "| 轮 | 名称 | 建议条数 | batch_id |", "|---|---|---|---|"]
        for r in advisory:
            L.append("| %s | %s | %s | %s |" % (
                r["id"], r["name"], r.get("optional_pending", 0),
                r["batch_id"] or "—"))
        L += ["", "> 本轮 %d 条建议未落盘（verdict=advisory）：它们**不在「净改动」里**，"
                  "也**没有被写进 ASS**（本轮已执行的内容改动照常计入净改动）。采纳方式："
                  "`--promote <id>`，再 `apply_fixes --apply-batch <batch>`。" % n_all, ""]

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
        reason = (m.get("opts") or {}).get("spelling_reason", "")
        if reason == "disabled":
            gaps.append("第 6 类（原文拼写）—— 本次被 `--no-with-spelling` 显式关闭")
            if _is_asr_transcribed(m):
                gaps.append("英文轨为 whisper/ASR 转录：听写造成的词形/时态/功能词错误"
                            "未经第 6 类复核（专名拼写核实归第 5 类/R8，不在第 6 类）；"
                            "需要时用 `--with-spelling` 重开")
        elif reason == "derived_srt":
            gaps.append("第 6 类（原文拼写）—— 派生 SRT 与 ASS 英文轨逐字同源，"
                        "本应默认开启，但本次计划未包含；用 `--with-spelling` 重跑"
                        "（不是「有人工 SRT 所以不用审」）")
        elif _is_asr_transcribed(m):
            gaps.append("第 6 类（原文拼写）—— 英文轨为 whisper/ASR 转录，本应默认开启，"
                        "但本次计划未包含；建议检查 init 参数或以 `--with-spelling` 重跑"
                        "（专名拼写核实归第 5 类/R8）")
        else:
            gaps.append("第 6 类（原文拼写）—— 有独立人工 SRT，默认关闭；"
                        "`--with-spelling` 可强制开启")
    if not any(r["id"] == "r09" for r in rounds):
        gaps.append("第 7 类（低严重度）—— 需显式 `--with-low`")
    if not any(r["id"] == "r11" for r in rounds):
        gaps.append("第 8 类（性别中立/敏感词）—— 需显式 `--with-inclusive`")
    if tl["code"] == V.UNVERIFIED:
        gaps.append(_timeline_gap_text(tl))
    L += [f"- {g}" for g in gaps] if gaps else ["无（本轮全部开启且时间轴已验）。"]
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
         "| run | ASS | 时间轴 | 轮次 | 已跑 | 回滚 | skip | 净改动 | 定格 |",
         "|---|---|---|---|---|---|---|---|---|"]
    states = {}
    for m in sums:
        rounds = m["rounds"]
        done = [r for r in rounds if r["verdict"] != "pending"]
        # issue #28：时间轴按凭据写，不再用 manifest.media 的「有/无」代替结论。
        st = _timeline_state(m)
        states[m["stamp"]] = st
        L.append("| %s | %s | %s | %d | %d | %d | %d | %d | %s |" % (
            m["stamp"], os.path.basename(m.get("ass") or ""),
            st["label"],
            len(rounds), len(done),
            sum(1 for r in rounds if r["verdict"] == "rollback"),
            sum(1 for r in rounds if r["verdict"] == "skip"),
            _ledger_total(rounds, only_kept=True),
            "是" if m.get("frozen") else "—"))
    L += [""]

    warn = []
    if len({os.path.normcase(os.path.abspath(m.get("ass") or "")) for m in sums}) > 1:
        warn.append("各 run 的 ASS 不是同一个文件——净改动条数**不可直接相加**，"
                    "它们是不同输入上的改动，合并后只会得到没有意义的和。")
    codes = {st["code"] for st in states.values()}
    if len(codes) > 1:
        detail = "、".join("%s=%s" % (k, states[k]["label"])
                          for k in sorted(states))
        warn.append("时间轴结论不一致（%s）——UNVERIFIED 的那次没有被检查过，"
                    "不等于通过，不能与 PASS 相提并论。" % detail)
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
    sp = ap.add_mutually_exclusive_group()
    sp.add_argument("--with-spelling", dest="with_spelling", action="store_true",
                    default=None,
                    help="强制把第 6 类（原文拼写）并入 R1–R3/R10")
    sp.add_argument("--no-with-spelling", dest="with_spelling", action="store_false",
                    default=None,
                    help="显式关闭第 6 类（ASR 素材默认开启）")

    ap.add_argument("--plan", action="store_true", help="只打印轮次计划，不建目录")
    ap.add_argument("--init", action="store_true", help="建 runs/<stamp> 与 r00 快照")
    ap.add_argument("--run", default="", help="已有 run 的 stamp")
    ap.add_argument("--record", default="", help="记一轮结果，如 --record r03")
    ap.add_argument("--batch-id", default="")
    ap.add_argument("--n-fixes", type=int, default=0)
    ap.add_argument("--verdict", default="", help="keep|rollback|skip|no_finding|advisory")
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
    ap.add_argument("--asr-transcribed", action="store_true",
                    help="英文轨是 whisper/ASR 转录（无独立人工 SRT 源）。"
                         "与「无独立 SRT」一样，默认开启第 6 类（原文拼写）；"
                         "专名拼写核实归第 5 类/R8，不在第 6 类")
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
        # issue #30 建议 3：无独立 SRT，或显式标了 ASR 转录 → 默认开第 6 类。
        # issue #54：派生 SRT（与 ASS 英文轨逐字同源）同样按 ASR 素材处理。
        same = srt_same_source(args.ass, args.srt)
        asr_source = bool(args.asr_transcribed or not (args.srt or "").strip()
                          or same["same"])
        plan = build_plan(with_low=args.with_low,
                          with_inclusive=args.with_inclusive,
                          with_spelling=args.with_spelling,
                          asr_source=asr_source)
        reason = spelling_reason(any(6 in r["scope"] for r in plan),
                                 args.with_spelling, asr_source,
                                 srt_same=same["same"])
        if args.plan:
            print(render_plan(plan, args.ass, reason))
            return 0
        if not os.path.exists(args.ass):
            print(f"[!] ASS 不存在：{args.ass}", file=sys.stderr)
            return 1
        stamp = init_run(wd, args.ass, args.srt, plan, media=args.media,
                         stamp=args.stamp,
                         skip_structure_check=args.skip_structure_check,
                         asr_transcribed=args.asr_transcribed,
                         spelling_reason=reason)
        print(f"[*] run {stamp} → {run_dir(wd, stamp)}")
        print(render_plan(plan, args.ass, reason))
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
        hit = next(r for r in m['rounds'] if r['id'] == args.record)
        print(f"[*] {args.record} → {hit['verdict']}")
        if hit["verdict"] == "advisory":
            print(f"[!] 本轮 {hit.get('optional_pending', 0)} 条建议未落盘"
                  f"（verdict=advisory，报告会单列）")
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
        d = run_dir(wd, args.run)
        snap = _resolve_snapshot(m, args.rollback_to)
        x = _count_dialogue(os.path.join(d, snap))
        y = _count_dialogue(m["ass"])
        cur_log = _read_jsonl(os.path.join(wd, "log.jsonl"))
        old_log = _read_jsonl(os.path.join(d, _log_snapshot_for(m, snap)))
        z = max(0, len(cur_log) - len(old_log))
        print(f"[!] 将还原到 {x} 行 / 当前 {y} 行 / 影响 {z} 条",
              f"（{snap} → {os.path.basename(m['ass'])}；台账 {len(cur_log)} → {len(old_log)} 条）")
        eff = [r for r in m["rounds"]
               if r["verdict"] in SNAPSHOT_VERDICTS
               and r["id"] > args.rollback_to]
        n_fix = sum(r["n_fixes"] for r in eff)
        print(f"[!] 以下 {len(eff)} 轮的改动会被撤销（合计 {n_fix} 条）：")
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
