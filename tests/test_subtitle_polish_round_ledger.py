# -*- coding: utf-8 -*-
"""回归测试：总账三件事（轮次列 / 回滚命令路径 / 回滚后台账折算）。

背景（R2–R3 实测，S06E04 run b1）：

  P2 `改动总账` 的「轮次」列写的是 `len(batches)`——「被几个批次碰过」，
     不是轮次号。r01 的 8 条改动后来又被两个回滚批次碰过，于是显示 3，
     读起来像「第 3 轮改的」。
  P3 单条回滚命令的 `--file` 取历史日志里的 `file` 字段。跨 run 复用同一个
     `.subtitle-polish` 时，那是指向上一个 run 工作副本的路径，照抄会回滚错文件。
  P4 r01 记 `n_fixes=8` 后被整批回滚，`--record` 快照已封存改不了，于是每份
     报告都背「台账 11 / 净改动 3」的不一致告警。差额应当在后续轮次里记一条
     折算项，而不是回头篡改历史快照。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_round_ledger.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

import round_orchestrator as ro          # noqa: E402

PASS = 0
FAIL = 0

ASS_HEADER = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ASS_BODY = """Dialogue: 0,0:00:00.00,0:00:02.00,英文,,0,0,0,,Line one
Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,旧1
Dialogue: 0,0:00:02.00,0:00:04.00,英文,,0,0,0,,Line two
Dialogue: 0,0:00:02.00,0:00:04.00,中文,,0,0,0,,旧2
"""


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
    except AssertionError as e:
        FAIL += 1
        print("  [FAIL] %s\n         %s" % (name, e))
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        FAIL += 1
        print("  [ERR ] %s\n         %s: %s" % (name, type(e).__name__, e))
    else:
        PASS += 1
        print("  [ ok ] %s" % name)


class Env:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="sp-ledger-")
        self.wd = os.path.join(self.root, ".subtitle-polish")
        os.makedirs(self.wd, exist_ok=True)
        self.ass = os.path.join(self.root, "S06E04.eng.ass")
        self.srt = os.path.join(self.root, "S06E04.eng.srt")
        with open(self.ass, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER + ASS_BODY)
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:02,000\nLine one\n\n"
                    "2\n00:00:02,000 --> 00:00:04,000\nLine two\n")
        self.stamp = None

    def init(self):
        self.stamp = ro.init_run(self.wd, self.ass, self.srt,
                                 ro.build_plan(), stamp="T5")
        return self.stamp

    def log(self, entries):
        import json
        with open(os.path.join(self.wd, "log.jsonl"), "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def e(batch, sid, old, new, ts, action="replace", file=""):
    return {"ts": ts, "batch_id": batch, "action": action, "file": file,
            "srt_id": sid, "track": "中文", "old_text": old, "new_text": new,
            "category": "第4类", "reason": ""}


def _rollback_entries(batch, file="", ts="2026-11-04T11:00:00"):
    return [e(batch, 1, "新1", "旧1", ts, action="rollback", file=file),
            e(batch, 2, "新2", "旧2", ts, action="rollback", file=file)]


# ---------------------------------------------------------------- P2

def t_round_column_is_round_id():
    """R1 的改动 + 两个回滚批次：轮次列必须写 `r01*（净零）`，不是 3。"""
    r = Env()
    try:
        stamp = r.init()
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00"),
               e("B1", 2, "旧2", "新2", "2026-11-04T10:00:01")]
              + _rollback_entries("B9-1", ts="2026-11-04T10:30:00")
              + _rollback_entries("B9-2", ts="2026-11-04T10:40:00"))
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=2)
        md = ro.render_report(r.wd, stamp)
        assert "r01*（净零）" in md, "轮次列没写真实轮次/回滚标注：\n%s" % md
        # 旧实现会在这里显示批次数 3（B1 + 两个回滚批次）
        assert "| 3 |" not in md.split("## 改动总账")[1], "轮次列仍是批次数"
        assert "非轮次批次" in md, "缺 `*` 的图例"
    finally:
        r.close()


def t_multi_round_column_lists_ids():
    """一行被 r01 / r02 都改过：轮次列要同时列出，而不是显示 2 个批次。"""
    r = Env()
    try:
        stamp = r.init()
        r.log([e("B1", 1, "旧1", "新1a", "2026-11-04T10:00:00")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        r.log([e("B1", 1, "旧1", "新1a", "2026-11-04T10:00:00"),
               e("B2", 1, "新1a", "新1b", "2026-11-04T11:00:00")])
        ro.record_round(r.wd, stamp, "r02", batch_id="B2", n_fixes=1)
        md = ro.render_report(r.wd, stamp)
        assert "r01, r02" in md, "多轮碰过的行没列全轮次：\n%s" % md
    finally:
        r.close()


# ---------------------------------------------------------------- P3

def t_rollback_cmd_uses_current_ass():
    """历史日志的 file 指向别的目录：命令必须用当前 run 的 ASS，并标注来源。"""
    r = Env()
    try:
        stamp = r.init()
        hist = os.path.join(r.root, "old-run", "S06E04.eng.ass")   # 不存在的目录
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00", file=hist)])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        md = ro.render_report(r.wd, stamp)
        ledger = md.split("## 改动总账")[1]
        assert '--file "%s"' % r.ass in ledger, \
            "单条回滚命令没用当前 ASS：\n%s" % ledger
        assert '--file "%s"' % hist not in md, \
            "命令里还写着历史路径：\n%s" % ledger
        assert "历史日志记录在另一个文件" in ledger, \
            "没有标注来源差异：\n%s" % ledger
        assert os.path.basename(hist) in ledger, \
            "没列出具体是哪条改动的历史路径"
    finally:
        r.close()


# ---------------------------------------------------------------- P4

def t_ledger_reconciles_after_rollback():
    """r01 记 2 条 → 整批回滚 → r02 记 1 条：台账必须显示 1 条，不是 3 条。"""
    r = Env()
    try:
        stamp = r.init()
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00"),
               e("B1", 2, "旧2", "新2", "2026-11-04T10:00:01")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=2)

        # 外部整批回滚（不经过 --record）
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00"),
               e("B1", 2, "旧2", "新2", "2026-11-04T10:00:01")]
              + _rollback_entries("B9", ts="2026-11-04T10:30:00"))
        # r02 只改了 srt_id=1
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00"),
               e("B1", 2, "旧2", "新2", "2026-11-04T10:00:01")]
              + _rollback_entries("B9", ts="2026-11-04T10:30:00")
              + [e("B2", 1, "旧1", "新1b", "2026-11-04T11:00:00")])
        m = ro.record_round(r.wd, stamp, "r02", batch_id="B2", n_fixes=1)
        r2 = next(x for x in m["rounds"] if x["id"] == "r02")
        assert r2.get("ledger_adjust") == -2, \
            "r02 没记折算项（应为 -2），实际 %r" % r2.get("ledger_adjust")
        # 已封存的 r01 不许被改
        r1 = next(x for x in m["rounds"] if x["id"] == "r01")
        assert r1["n_fixes"] == 2, "改动了已封存快照的 n_fixes"

        md = ro.render_report(r.wd, stamp)
        top = md.split("\n")[2]
        assert "净改动 1 条" in top, top
        assert "台账 1 条" in top, "台账没折算到盘面：%s" % top
        assert "含回滚折算 -2 条" in top, top
        assert "台账与日志不一致" not in md, "折算后仍在不一致告警"
    finally:
        r.close()


def t_report_level_reconcile_without_record():
    """回滚后直接出报告（没有新 --record）：报告层也要对齐并说明。"""
    r = Env()
    try:
        stamp = r.init()
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00"),
               e("B1", 2, "旧2", "新2", "2026-11-04T10:00:01")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=2)

        # 回滚发生在 record 之后：没有新轮次来登记折算
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00"),
               e("B1", 2, "旧2", "新2", "2026-11-04T10:00:01")]
              + _rollback_entries("B9", ts="2026-11-04T10:30:00"))
        md = ro.render_report(r.wd, stamp)
        top = md.split("\n")[2]
        assert "净改动 0 条" in top, top
        assert "已按盘面对齐" in top, top
        assert "台账与日志不一致" not in md
    finally:
        r.close()


def t_no_adjust_when_consistent():
    """没有回滚时不该凭空多出折算项，顶栏保持简洁。"""
    r = Env()
    try:
        stamp = r.init()
        r.log([e("B1", 1, "旧1", "新1", "2026-11-04T10:00:00")])
        ro.record_round(r.wd, stamp, "r01", batch_id="B1", n_fixes=1)
        m = ro.load_manifest(r.wd, stamp)
        r1 = next(x for x in m["rounds"] if x["id"] == "r01")
        assert r1.get("ledger_adjust") == 0, r1
        md = ro.render_report(r.wd, stamp)
        assert "折算" not in md.split("## 逐轮摘要")[0], \
            "无回滚却出现了折算说明"
    finally:
        r.close()


if __name__ == "__main__":
    print("=" * 70)
    print("总账：轮次列 / 回滚路径 / 台账折算")
    print("=" * 70)
    test("P2-1 轮次列写真实轮次（R1 的 8 条不再显示 3）", t_round_column_is_round_id)
    test("P2-2 多轮碰过的行列全轮次", t_multi_round_column_lists_ids)
    test("P3-1 单条回滚命令用当前 ASS 并标注来源", t_rollback_cmd_uses_current_ass)
    test("P4-1 回滚后 record 折算 -> 台账=净改动", t_ledger_reconciles_after_rollback)
    test("P4-2 没有新 record 时报告层折算", t_report_level_reconcile_without_record)
    test("P4-3 无回滚时不产生折算项", t_no_adjust_when_consistent)
    print()
    print("  通过 %d / 失败 %d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)
