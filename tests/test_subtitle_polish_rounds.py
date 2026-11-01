# -*- coding: utf-8 -*-
"""轮次编排：计划 / 快照整轮回滚 / 定格 / 最终报告可操作性。

背景（skill-forge issue #15）——「10 轮跑完再挑」这个工作方式需要的不是"更强的
自动改"，而是三样确定性的东西：

  1. **每轮可回滚**：第 7 轮判错会污染第 8–10 轮的输入。回滚要能「回到第 N 轮末」，
     而不是人工拼 `--rollback batch=...` 的列表。
  2. **判据失败要定格**：闸门 FAIL 之后继续跑，产出的每一轮都是叠在坏状态上的意见。
  3. **最终报告可逐条否决**：每行要能看到「原译 → 终译 → 哪轮改的 → 一条命令退回去」。

本测试锁的是这三条。**不测"判据对不对"**——判据全在 verify_fixes / cross_check /
regression_check / timeline_gate 里，本脚本只做记账与分派。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_rounds.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import round_orchestrator as ro

PY = sys.executable
PASS = 0
FAIL = 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        FAIL += 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        FAIL += 1
    else:
        print(f"  [PASS] {name}")
        PASS += 1


ASS_HEADER = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ASS_BODY = """Dialogue: 0,0:00:00.00,0:00:02.00,英文,,0,0,0,,This is Phil's bag.
Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,这就是菲尔的地盘
Dialogue: 0,0:00:02.00,0:00:04.00,英文,,0,0,0,,Right, walk me through this.
Dialogue: 0,0:00:02.00,0:00:04.00,中文,,0,0,0,,好了 再讲一遍
"""


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


class Run:
    """临时工作区：<tmp>/.subtitle-polish + 一份 ASS。"""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="sp-rounds-")
        self.wd = os.path.join(self.root, ".subtitle-polish")
        os.makedirs(self.wd, exist_ok=True)
        self.ass = os.path.join(self.root, "e04.ass")
        self.srt = os.path.join(self.root, "e04.srt")
        with open(self.ass, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER + ASS_BODY)
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:02,000\nThis is Phil's bag.\n\n"
                    "2\n00:00:02,000 --> 00:00:04,000\nRight, walk me through this.\n")

    def log(self, entries):
        with open(os.path.join(self.wd, "log.jsonl"), "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def touch(self, text):
        """模拟 agent 改了字幕（直接写盘，不走 apply_fixes，保持测试独立）。"""
        with open(self.ass, "a", encoding="utf-8") as f:
            f.write(f"Dialogue: 0,9:59:00.00,9:59:02.00,中文,,0,0,0,,{text}\n")

    def init(self, **kw):
        plan = ro.build_plan(**kw)
        return ro.init_run(self.wd, self.ass, self.srt, plan, stamp="T1")

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _entry(batch, sid, old, new, ts="2026-11-01T10:00:00"):
    return {"ts": ts, "batch_id": batch, "action": "replace", "file": "",
            "srt_id": sid, "track": "中文", "old_text": old, "new_text": new,
            "category": "第4类", "reason": ""}


# ══════════════════════════════════════════════════════════════════
# 1. 计划（已决策的 4 条锁进测试）
# ══════════════════════════════════════════════════════════════════

def t_default_plan_9_rounds():
    """默认 9 轮：R1–R8 + R10。不含 R9 / R11，不含第 6 类。"""
    plan = ro.build_plan()
    ids = [r["id"] for r in plan]
    assert ids == ["r01", "r02", "r03", "r04", "r05", "r06", "r07", "r08", "r10"], ids
    scopes = set()
    for r in plan:
        scopes |= set(r["scope"])
    assert 6 not in scopes, "第 6 类不该默认出现"
    assert 7 not in scopes and 8 not in scopes, "第 7/8 类不该默认出现"


def t_low_is_r09():
    """第 7 类固定 R9（已决策：不放前面）。"""
    plan = ro.build_plan(with_low=True)
    hit = next(r for r in plan if r["scope"] == [7])
    assert hit["id"] == "r09", hit
    assert [r["id"] for r in plan].index("r09") > \
           [r["id"] for r in plan].index("r08"), "第 7 类跑到第 5 类专轮前面了"


def t_inclusive_is_r11():
    """第 8 类独立 R11，不并入 R10（已决策）。"""
    plan = ro.build_plan(with_inclusive=True)
    hit = next(r for r in plan if r["scope"] == [8])
    assert hit["id"] == "r11", hit
    assert [r["id"] for r in plan][-1] == "r11", "R11 不是最后一轮"
    r10 = next(r for r in plan if r["id"] == "r10")
    assert 8 not in r10["scope"], "第 8 类被并进收口轮了"


def t_spelling_merges():
    """第 6 类并入 R1–R3 / R10，不单开轮。"""
    plan = ro.build_plan(with_spelling=True)
    assert not any(r["scope"] == [6] for r in plan), "第 6 类开了独立轮"
    for rid in ("r01", "r02", "r03", "r10"):
        r = next(x for x in plan if x["id"] == rid)
        assert 6 in r["scope"], f"{rid} 没并进第 6 类：{r['scope']}"


def t_full_plan_11():
    plan = ro.build_plan(with_low=True, with_inclusive=True, with_spelling=True)
    assert len(plan) == 11, len(plan)
    assert [r["id"] for r in plan] == ["r%02d" % i for i in range(1, 12)], \
        [r["id"] for r in plan]


def t_scope_full_no_sampling():
    """类别专轮只改 scope，不裁剪切片——scope 必须恰好是那一类。"""
    plan = ro.build_plan()
    for r in plan:
        if r["id"] in ("r04", "r05", "r06", "r07", "r08"):
            assert len(r["scope"]) == 1, f"{r['id']} 的 scope 不是单类：{r['scope']}"


# ══════════════════════════════════════════════════════════════════
# 2. 快照与整轮回滚
# ══════════════════════════════════════════════════════════════════

def t_init_creates_r00():
    r = Run()
    try:
        before = sha(r.ass)
        stamp = r.init()
        d = ro.run_dir(r.wd, stamp)
        assert os.path.exists(os.path.join(d, "r00.ass"))
        assert sha(os.path.join(d, "r00.ass")) == before, "r00 快照与起点不一致"
        assert os.path.exists(os.path.join(d, "logs", "r00.jsonl"))
        m = ro.load_manifest(r.wd, stamp)
        assert len(m["rounds"]) == 9 and all(x["verdict"] == "pending"
                                             for x in m["rounds"])
    finally:
        r.close()


def t_rollback_byte_identical():
    """核心验收：回滚到 R2 → ASS 与 r02.ass 逐字节相同（含 log）。"""
    r = Run()
    try:
        stamp = r.init()
        r.log([_entry("B1", 1, "这就是菲尔的地盘", "这是菲尔的强项")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        r.touch("R2 加的")
        r.log([_entry("B1", 1, "这就是菲尔的地盘", "这是菲尔的强项"),
               _entry("B2", 2, "好了 再讲一遍", "来 给我讲讲")])
        ro.record_round(r.wd, stamp, "r02", batch_id="B2", n_fixes=1)
        r.touch("R3 加的")
        ro.record_round(r.wd, stamp, "r03", batch_id="B3", n_fixes=1)

        d = ro.run_dir(r.wd, stamp)
        want_ass = sha(os.path.join(d, "r02.ass"))
        want_log = sha(os.path.join(d, "logs", "r02.jsonl"))

        ro.rollback_to(r.wd, stamp, "r02")
        assert sha(r.ass) == want_ass, "ASS 没有逐字节还原"
        assert sha(os.path.join(r.wd, "log.jsonl")) == want_log, \
            "log.jsonl 没跟着还原（台账会含已撤销的改动）"
    finally:
        r.close()


def t_rollback_to_r00():
    r = Run()
    try:
        origin = sha(r.ass)
        stamp = r.init()
        r.touch("改了")
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=3)
        ro.rollback_to(r.wd, stamp, "r00")
        assert sha(r.ass) == origin, "退不回起点"
    finally:
        r.close()


def t_rollback_skipped_round_rejected():
    """skip 的轮没有快照，退过去要报错而不是静默退到别处。"""
    r = Run()
    try:
        stamp = r.init()
        ro.record_round(r.wd, stamp, "r01", verdict="skip",
                        note="gate_out failed")
        try:
            ro.rollback_to(r.wd, stamp, "r01")
        except SystemExit as e:
            assert "没有快照" in str(e), e
        else:
            raise AssertionError("skip 的轮居然能回滚")
    finally:
        r.close()


def t_rollback_record_verdict():
    """verdict=rollback 时自动还原到上一轮快照，且该轮不留快照。"""
    r = Run()
    try:
        stamp = r.init()
        r.touch("R1 的改动")
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=2)
        snap_after_r1 = sha(r.ass)
        r.touch("R2 的坏改动")
        m = ro.record_round(r.wd, stamp, "r02", batch_id="B2", n_fixes=5,
                            verdict="rollback", note="verify: 3 failed")
        assert sha(r.ass) == snap_after_r1, "rollback 没还原到 R1 末"
        r2 = next(x for x in m["rounds"] if x["id"] == "r02")
        assert r2["snapshot"] == "", "rollback 的轮不该留快照"
        assert "rolled back to r01.ass" in r2["note"], r2["note"]
    finally:
        r.close()


# ══════════════════════════════════════════════════════════════════
# 3. 定格
# ══════════════════════════════════════════════════════════════════

def t_freeze_skips_rest():
    """定格于 R4 → R5 之后全部 skip，R1–R4 的结论不动。"""
    r = Run()
    try:
        stamp = r.init()
        for rid in ("r01", "r02", "r03"):
            ro.record_round(r.wd, stamp, rid, batch_id=rid, n_fixes=1)
        ro.record_round(r.wd, stamp, "r04", batch_id="r04", n_fixes=0)
        m = ro.freeze_run(r.wd, stamp, "r04", "gate_axis FAIL: 中位极差 2.9s")
        verdicts = {x["id"]: x["verdict"] for x in m["rounds"]}
        for rid in ("r01", "r02", "r03"):
            assert verdicts[rid] == "keep", verdicts
        assert verdicts["r04"] == "no_finding", verdicts
        for rid in ("r05", "r06", "r07", "r08", "r10"):
            assert verdicts[rid] == "skip", f"{rid} 没被定格跳过：{verdicts}"
        assert m["frozen"]["reason"].startswith("gate_axis"), m["frozen"]
    finally:
        r.close()


def t_freeze_now():
    r = Run()
    try:
        stamp = r.init()
        m = ro.freeze_run(r.wd, stamp, "now", "人工止损")
        assert all(x["verdict"] == "skip" for x in m["rounds"]), m["rounds"]
    finally:
        r.close()


def t_freeze_rows_recorded():
    r = Run()
    try:
        stamp = r.init()
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1,
                        freeze_rows=["412", "987"])
        ro.record_round(r.wd, stamp, "r02", batch_id="B2", n_fixes=1,
                        freeze_rows=["987", "1001"])
        m = ro.load_manifest(r.wd, stamp)
        assert m["frozen_rows"] == [412, 987, 1001], m["frozen_rows"]
    finally:
        r.close()


# ══════════════════════════════════════════════════════════════════
# 4. 最终报告
# ══════════════════════════════════════════════════════════════════

def t_report_shape():
    r = Run()
    try:
        stamp = r.init()
        r.log([_entry("B1", 1, "这就是菲尔的地盘", "这是菲尔的强项"),
               {"ts": "2026-11-01T11:00:00", "batch_id": "B2", "action": "replace",
                "file": "", "srt_id": 1, "track": "中文",
                "old_text": "这是菲尔的强项", "new_text": "这就是菲尔的地盘",
                "category": "第7类", "reason": "润色"}])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        md = ro.render_report(r.wd, stamp)
        for kw in ("## 逐轮摘要", "## 争执行", "## 改动总账",
                   "## 白名单", "## 本次未覆盖"):
            assert kw in md, f"报告缺 {kw}"
        # 争执行必须真的抓到那行来回改的
        assert "| 1 |" in md, md[:2000]
        # 总账要能一条命令退回去
        assert "--rollback id=1" in md, "总账缺回滚命令"
        # 未覆盖要如实写默认没跑的类
        assert "第 6 类" in md and "第 7 类" in md and "第 8 类" in md, \
            "未覆盖没写全（会让人误以为这些也审过了）"
        assert "时间轴" in md, "无片源时未标注时间轴 UNVERIFIED"
    finally:
        r.close()


def t_report_no_media_says_unverified():
    r = Run()
    try:
        stamp = r.init()
        md = ro.render_report(r.wd, stamp)
        assert "UNVERIFIED" in md, "无片源却没写 UNVERIFIED"
        assert "通过" not in md.split("## 本次未覆盖")[0].split("> ")[1], \
            "无片源时顶栏不该出现「通过」"
    finally:
        r.close()


def t_report_frozen_at_top():
    r = Run()
    try:
        stamp = r.init()
        ro.freeze_run(r.wd, stamp, "now", "gate_axis FAIL")
        md = ro.render_report(r.wd, stamp)
        top = md.split("##")[0]
        assert "已定格" in top, f"定格信息没在顶栏：{top}"
    finally:
        r.close()


def t_cli_end_to_end():
    """真跑 CLI：--init → --record → --report → --rollback-to。"""
    r = Run()
    try:
        origin = sha(r.ass)
        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--ass", r.ass, "--srt", r.srt,
                            "--work-dir", r.wd, "--init", "--stamp", "CLI"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr
        r.touch("加上一句")
        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--run", "CLI", "--work-dir", r.wd,
                            "--record", "r01", "--batch-id", "B1", "--n-fixes", "1"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr
        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--run", "CLI", "--work-dir", r.wd, "--report"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr
        assert os.path.exists(os.path.join(ro.run_dir(r.wd, "CLI"), "final-report.md"))

        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--run", "CLI", "--work-dir", r.wd, "--rollback-to", "r00"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr
        assert sha(r.ass) == origin, "CLI 回滚没回到起点"
    finally:
        r.close()


def t_bad_verdict_rejected():
    r = Run()
    try:
        stamp = r.init()
        try:
            ro.record_round(r.wd, stamp, "r01", verdict="probably_ok")
        except SystemExit as e:
            assert "verdict 非法" in str(e), e
        else:
            raise AssertionError("非法 verdict 被接受了")
    finally:
        r.close()


if __name__ == "__main__":
    print("轮次编排：计划 / 快照回滚 / 定格 / 报告")
    for n, fn in (
        ("默认 9 轮且不含第 6/7/8 类", t_default_plan_9_rounds),
        ("第 7 类固定 R9", t_low_is_r09),
        ("第 8 类独立 R11", t_inclusive_is_r11),
        ("第 6 类并入 R1-R3/R10", t_spelling_merges),
        ("全开 11 轮", t_full_plan_11),
        ("类别专轮 scope 单类（全量不取样）", t_scope_full_no_sampling),
        ("init 建 r00 快照", t_init_creates_r00),
        ("整轮回滚逐字节一致（ASS+log）", t_rollback_byte_identical),
        ("回滚到 r00", t_rollback_to_r00),
        ("skip 的轮回滚要报错", t_rollback_skipped_round_rejected),
        ("rollback verdict 自动还原", t_rollback_record_verdict),
        ("定格后其余轮 skip", t_freeze_skips_rest),
        ("定格 now", t_freeze_now),
        ("冻结行累积", t_freeze_rows_recorded),
        ("报告五节齐全且可操作", t_report_shape),
        ("无片源写 UNVERIFIED", t_report_no_media_says_unverified),
        ("定格信息在顶栏", t_report_frozen_at_top),
        ("CLI 端到端", t_cli_end_to_end),
        ("非法 verdict 拒绝", t_bad_verdict_rejected),
    ):
        test(n, fn)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
