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
import re
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

# 12 行英文轨：同源检测的默认最少行数是 10，夹具必须够长才能测到派生判定。
_EN_LINES = [
    "This is Phil's bag.",
    "Right, walk me through this.",
    "So the deal is simple.",
    "You bring the car in.",
    "I tell you what it needs.",
    "Then we agree on a price.",
    "No haggling after that.",
    "That is the whole point.",
    "Most folks hate that part.",
    "But it saves everyone time.",
    "So sign here, please.",
    "And we are done for today.",
]
ASS_BODY = "".join(
    "Dialogue: 0,0:00:%02d.00,0:00:%02d.00,英文,,0,0,0,,%s\n"
    "Dialogue: 0,0:00:%02d.00,0:00:%02d.00,中文,,0,0,0,,中文第%d句\n"
    % (i * 2, i * 2 + 2, t, i * 2, i * 2 + 2, i + 1)
    for i, t in enumerate(_EN_LINES))


def _srt_of(lines):
    return "".join("%d\n00:00:%02d,000 --> 00:00:%02d,000\n%s\n\n"
                   % (i + 1, i * 2, i * 2 + 2, t) for i, t in enumerate(lines))


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
        # 同源 SRT（逐字等于 ASS 英文轨）。issue #54：这不是「人工 SRT」，
        # 而是派生副本，第 6 类应按 ASR 素材默认开。
        with open(self.ass, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER + ASS_BODY)
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write(_srt_of(_EN_LINES))
        # 独立人工 SRT：内容与 ASS 英文轨明显不同（这里模拟人工润色过的文本）。
        self.human_srt = os.path.join(self.root, "e04.human.srt")
        with open(self.human_srt, "w", encoding="utf-8") as f:
            f.write(_srt_of(["Human rewrite %d: the bag story." % (i + 1)
                             for i in range(len(_EN_LINES))]))

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


def t_asr_source_defaults_spelling_on():
    """无独立 SRT / --asr-transcribed → 第 6 类默认并入，轮数仍是 9。"""
    plan = ro.build_plan(asr_source=True)
    assert len(plan) == 9, len(plan)
    for rid in ("r01", "r02", "r03", "r10"):
        r = next(x for x in plan if x["id"] == rid)
        assert 6 in r["scope"], f"{rid} 没默认并进第 6 类：{r['scope']}"
    assert not any(r["scope"] == [6] for r in plan), "第 6 类开了独立轮"


def t_no_with_spelling_overrides_asr():
    """ASR 素材也能显式关闭第 6 类。"""
    plan = ro.build_plan(with_spelling=False, asr_source=True)
    assert len(plan) == 9, len(plan)
    assert not any(6 in r["scope"] for r in plan), "显式关闭没生效"


def t_cli_plan_spelling_switch():
    """CLI 判定：无 SRT 默认开；**派生 SRT** 也默认开；独立人工 SRT 默认关。

    issue #54：旧断言是「有 SRT 文件 → 默认关」。S06E04 实测那份 SRT 与 ASS
    英文轨 748/750 行逐字相同，是派生副本；按旧口径关掉第 6 类，319/649 这类
    ASR 错字就整集无人审。新口径：有 SRT 但同源率 ≥95% → 仍按 ASR 素材默认开；
    只有内容确实不同（人工审校）才默认关。
    """
    r = Run()
    try:
        script = os.path.join(SCRIPTS, "round_orchestrator.py")

        def run(*args):
            p = subprocess.run([sys.executable, script, "--plan", "--ass", r.ass]
                               + list(args), capture_output=True, text=True,
                               encoding="utf-8")
            assert p.returncode == 0, p.stderr
            return p.stdout

        out = run()
        assert "ASR 素材默认开" in out, out
        # 派生 SRT：开了，并标明「逐字同源=派生」
        out = run("--srt", r.srt)
        assert "逐字同源" in out and "默认开" in out, out
        # 独立人工 SRT：仍然默认关
        out = run("--srt", r.human_srt)
        assert "有独立 SRT 默认关闭" in out, out
        out = run("--srt", r.human_srt, "--with-spelling")
        assert "--with-spelling 强制开" in out, out
        out = run("--no-with-spelling")
        assert "--no-with-spelling 显式关闭" in out, out
    finally:
        r.close()


def t_srt_same_source_detection():
    """issue #54：同源率实测能把「派生 SRT」和「人工 SRT」分开。"""
    r = Run()
    try:
        d = ro.srt_same_source(r.ass, r.srt)
        assert d["same"] is True and d["ratio"] == 1.0, d
        assert d["n"] == len(_EN_LINES), d
        h = ro.srt_same_source(r.ass, r.human_srt)
        assert h["same"] is False and h["ratio"] == 0.0, h
        # 缺失文件不能误判成同源（否则会误开第 6 类）
        miss = ro.srt_same_source(r.ass, os.path.join(r.root, "nope.srt"))
        assert miss["same"] is False, miss
    finally:
        r.close()


def t_derived_srt_manifest_recorded():
    """issue #54：init 把同源实测写进 manifest，供报告/事后核对。"""
    r = Run()
    try:
        stamp = r.init()
        m = ro.load_manifest(r.wd, stamp)
        assert m["opts"]["srt_same_source"] is True, m["opts"]
        assert m["opts"]["srt_match_ratio"] == 1.0, m["opts"]
        assert ro._is_asr_transcribed(m) is True, "派生 SRT 没被当作 ASR 源"
    finally:
        r.close()


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
        m = ro.load_manifest(r.wd, stamp)
        r02 = next(x for x in m["rounds"] if x["id"] == "r02")
        want_log = sha(os.path.join(d, ro._log_snapshot_of(m, r02)))

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

        # B4：整轮回退是**不可逆**的（ASS 与 log.jsonl 一起被覆盖），不带 --yes 必须拒绝。
        # 先锁住这个负例，再跑正例——否则哪天有人把确认删了，这条用例只验「能回滚」，
        # 验不到「该拦的时候拦得住」。
        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--run", "CLI", "--work-dir", r.wd, "--rollback-to", "r00"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode != 0, "整轮回退不带 --yes 竟然成功了"
        assert "--yes" in (p.stdout + p.stderr), \
            f"拒绝理由里应提示 --yes：{p.stdout!r} {p.stderr!r}"
        assert sha(r.ass) != origin, "被拒绝的回滚不该动 ASS"

        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--run", "CLI", "--work-dir", r.wd,
                            "--rollback-to", "r00", "--yes"],
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


def t_snapshot_name_has_batch():
    """B4：快照文件名带 batch_id，`_none` 让「这轮没改动」在文件名上可见。"""
    r = Run()
    try:
        stamp = r.init()
        r.touch("改一句")
        r.log([_entry("B1", 1, "旧", "新")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        ro.record_round(r.wd, stamp, "r02", n_fixes=0)

        m = ro.load_manifest(r.wd, stamp)
        r01 = next(x for x in m["rounds"] if x["id"] == "r01")
        r02 = next(x for x in m["rounds"] if x["id"] == "r02")
        assert r01["log_snapshot"] == os.path.join("logs", "r01_B1.jsonl"), r01
        assert r02["log_snapshot"] == os.path.join("logs", "r02_none.jsonl"), r02
        d = ro.run_dir(r.wd, stamp)
        assert os.path.exists(os.path.join(d, r01["log_snapshot"]))
        assert os.path.exists(os.path.join(d, r02["log_snapshot"]))
    finally:
        r.close()


def t_late_record_rejected():
    """B4：r11 落盘后再补记 r09，必须拒绝并点名越过者。"""
    r = Run()
    try:
        stamp = r.init(with_low=True, with_inclusive=True)
        ro.record_round(r.wd, stamp, "r11", batch_id="B11", n_fixes=0)
        r.touch("晚轮改的")
        try:
            ro.record_round(r.wd, stamp, "r09", batch_id="B09", n_fixes=1)
        except SystemExit as e:
            assert "r09 的台账快照已被 r11 越过，无法补记" in str(e), e
        else:
            raise AssertionError("更晚轮次落盘后，r09 竟然还能补记")
        d = ro.run_dir(r.wd, stamp)
        assert not os.path.exists(os.path.join(d, "logs", "r09_B09.jsonl")), \
            "被拒绝的补记不该写快照"
    finally:
        r.close()


def t_record_twice_rejected():
    """B4：同一轮记两次必须拒绝，快照不允许覆盖。"""
    r = Run()
    try:
        stamp = r.init()
        r.touch("改一句")
        r.log([_entry("B1", 1, "旧", "新")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        try:
            ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        except SystemExit as e:
            assert "只允许写一次" in str(e), e
        else:
            raise AssertionError("同一轮被重复记账并覆盖快照")
    finally:
        r.close()


def t_rollback_preview_numbers():
    """B4：--rollback-to 预演必须给出「将还原到 X 行 / 当前 Y 行 / 影响 Z 条」。"""
    r = Run()
    try:
        r.init()
        r.touch("改一句")
        r.log([_entry("B1", 1, "旧", "新")])
        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--run", "T1", "--work-dir", r.wd,
                            "--record", "r01", "--batch-id", "B1", "--n-fixes", "1"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr

        origin = sha(r.ass)
        p = subprocess.run([PY, os.path.join(SCRIPTS, "round_orchestrator.py"),
                            "--run", "T1", "--work-dir", r.wd,
                            "--rollback-to", "r00"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode != 0, "不带 --yes 的整轮回滚竟然成功"
        assert re.search(r"将还原到 \d+ 行 / 当前 \d+ 行 / 影响 \d+ 条", p.stdout), \
            f"预演数字缺失：{p.stdout!r}"
        assert sha(r.ass) == origin, "预演不该改动 ASS"
    finally:
        r.close()


def t_structural_without_batch_rejected():
    """B2：结构性改动缺 batch 条目 → --record 拒绝，并给出 --manual-log 正确写法。"""
    r = Run()
    try:
        stamp = r.init()
        r.touch("删了一行")
        e = _entry("", 2, "旧", "新")
        e["action"] = "delete"
        r.log([e])
        try:
            ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        except SystemExit as ex:
            msg = str(ex)
            assert "结构性改动缺少 batch" in msg, msg
            assert "--manual-log" in msg, msg
        else:
            raise AssertionError("缺 batch 的结构性改动被记账通过了")
        m = ro.load_manifest(r.wd, stamp)
        r01 = next(x for x in m["rounds"] if x["id"] == "r01")
        assert r01["verdict"] == "pending", "被拒绝的轮次不该落成 keep"
        d = ro.run_dir(r.wd, stamp)
        assert not os.path.exists(os.path.join(d, "logs", "r01_B1.jsonl"))
    finally:
        r.close()


def t_structural_requires_record_batch():
    """B2：结构性改动有 batch，但 --record 没带 --batch-id → 也要拒绝。"""
    r = Run()
    try:
        stamp = r.init()
        r.touch("删了一行")
        e = _entry("B1", 2, "旧", "新")
        e["action"] = "retime_curve"
        r.log([e])
        try:
            ro.record_round(r.wd, stamp, "r01", n_fixes=1)
        except SystemExit as ex:
            assert "必须带 --batch-id" in str(ex), ex
        else:
            raise AssertionError("有结构性改动却不带 --batch-id 也通过了")
    finally:
        r.close()


def t_optional_pending_is_advisory():
    """A1：产出 optional-fixes 但未 promote → verdict=advisory，报告单列一节。"""
    r = Run()
    try:
        stamp = r.init()
        r.touch("改一句")
        r.log([_entry("B1", 1, "旧", "新")])
        os.makedirs(os.path.join(r.wd, "reports"), exist_ok=True)
        with open(os.path.join(r.wd, "reports", "optional-fixes.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"items": [{
                "id": "L1", "srt_id": 1, "track": "中文",
                "current": "这就是菲尔的地盘", "suggested_new": "这是菲尔的包",
                "category": "第7类"}]}, f, ensure_ascii=False)

        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        m = ro.load_manifest(r.wd, stamp)
        r01 = next(x for x in m["rounds"] if x["id"] == "r01")
        assert r01["verdict"] == "advisory", r01
        assert r01["optional_pending"] == 1, r01

        md = ro.render_report(r.wd, stamp)
        assert "## 建议未落盘（advisory）" in md, md
        assert "本轮 1 条建议未落盘" in md, md

        # 文件没变 → 下一轮不能把上一轮的建议重复记成 advisory
        ro.record_round(r.wd, stamp, "r02", n_fixes=0)
        m = ro.load_manifest(r.wd, stamp)
        assert next(x for x in m["rounds"] if x["id"] == "r02")["verdict"] \
            == "no_finding"
    finally:
        r.close()


def t_report_commands_are_real():
    """B3：报告命令来自本次实际使用的解释器/脚本/run/批次，且区分 batch= 与 id=。"""
    r = Run()
    try:
        stamp = r.init()
        r.touch("改一句")
        r.log([_entry("B1", 2, "旧", "新")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        md = ro.render_report(r.wd, stamp)

        assert "<skill>" not in md, "报告里还有模板占位符 <skill>"
        assert "--rollback batch=B1" in md, md
        assert '--rollback id=2 --file' in md, md
        assert f"--run {stamp} --rollback-to r01 --yes" in md, md
        assert os.path.join(SCRIPTS, "apply_fixes.py") in md, \
            "报告命令没用本次实际脚本路径"
    finally:
        r.close()


def t_report_no_stale_paths():
    """issue #54：跨 run 的净零历史日志不进总账，报告不打印旧 run 路径。"""
    r = Run()
    try:
        stamp = r.init()
        old = os.path.join("C:\\old_run_20261104_131806", "S06E04.eng.ass")
        entries = []
        for sid in range(1, 9):
            e = _entry("B_old", sid, "same", "same")
            e["file"] = old            # 旧 run 的日志路径
            entries.append(e)
        entries.append(_entry("B1", 2, "旧", "新"))
        r.log(entries)
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        md = ro.render_report(r.wd, stamp)
        assert "131806" not in md, "报告里仍打印了旧 run 路径（会被当成可照抄的命令）"
        assert "跨运行目录的历史日志" in md, md
        assert "8 条" in md, md
        assert "旧" in md and "新" in md, "真实改动不该被过滤掉"
    finally:
        r.close()


def t_report_srt_sync_list():
    """issue #54：英文轨改动单列 SRT 同步清单，且明确 skill 不写 SRT。"""
    r = Run()
    try:
        stamp = r.init()           # 派生 SRT → srt_same_source=True
        e = _entry("B1", 1, "Yeah. ,,,and look at that.",
                   "Yeah. And look at that.")
        e["track"] = "英文"
        r.log([e])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        md = ro.render_report(r.wd, stamp)
        assert "SRT 需人工同步" in md, md
        assert "Yeah. ,,,and look at that." in md, md
        assert "本 skill 不会写它" in md, md
        assert "同源率" in md, md
    finally:
        r.close()


if __name__ == "__main__":
    print("轮次编排：计划 / 快照回滚 / 定格 / 报告")
    for n, fn in (
        ("默认 9 轮且不含第 6/7/8 类", t_default_plan_9_rounds),
        ("ASR 素材默认开第 6 类", t_asr_source_defaults_spelling_on),
        ("--no-with-spelling 可关 ASR 默认", t_no_with_spelling_overrides_asr),
        ("CLI 第 6 类开关判定", t_cli_plan_spelling_switch),
        ("派生 SRT 同源率实测", t_srt_same_source_detection),
        ("派生 SRT 写进 manifest", t_derived_srt_manifest_recorded),
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
        ("快照名带 batch_id", t_snapshot_name_has_batch),
        ("更晚轮次落盘后拒绝补记", t_late_record_rejected),
        ("同一轮重复记账拒绝", t_record_twice_rejected),
        ("回滚预演三数字", t_rollback_preview_numbers),
        ("结构性改动缺 batch 拒绝", t_structural_without_batch_rejected),
        ("结构性改动要求 --batch-id", t_structural_requires_record_batch),
        ("建议未落盘记 advisory", t_optional_pending_is_advisory),
        ("报告命令来自实际路径", t_report_commands_are_real),
        ("报告不打印旧 run 路径", t_report_no_stale_paths),
        ("报告单列 SRT 同步清单", t_report_srt_sync_list),
    ):
        test(n, fn)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
