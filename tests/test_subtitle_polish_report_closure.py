# -*- coding: utf-8 -*-
"""回归测试：报告闭环（issue #44 / #45）。

## 背景（S06E04 真实整集实测暴露的两个「报告不可信」）

  #45 回滚后 verify_fixes 直接崩：`_build_index_alignment()` 收到的是刚加载的
      `SSAFile` 对象，函数内部却按**路径**重新 `pysubs2.load()`，于是抛
      `SystemExit`。崩溃发生在「有失败明细」才走的分支——恰好是回滚后必走的
      那条路。旧 verify-fixes.md（一屏绿）原地不动，报告继续写「净改动 8 条」。

  #44 同一状态两套结论：`timeline_gate` PASS（凭据文件都在），
      `--report` 却 UNVERIFIED「片源已换（09fc0ba3 → 1f1c8a97）」。根因是
      验轴用的是派生 WAV、init 冻结的却是 MKV，两个哈希必然不同；报告把
      「容器 vs 派生音频」误报成换片。另一头，pysubs2 回滚重存会改表头，
      raw sha1 变了而事件内容一字不差，也被判成「文件内容已变」。

## 本文件锁住的六件事

  R1 回滚后重跑 verify **不崩**，且能如实报出「落盘与日志不符」
  R2 回滚/还原会**作废旧验证报告**（改名归档 + 状态文件），重跑 verify 后清除
  R3 净改动从日志回算：rollback 后的行不计入「还剩几条改动」
  R4 片源：同一路径被替换 -> UNVERIFIED「片源已换」
  R5 片源：本次给的是派生音频、凭据绑定的文件仍在 -> PASS + 说明（不是换片）
  R6 文件：raw sha1 变了但事件内容未变 -> PASS + 说明；事件真变了 -> UNVERIFIED

跑法:
  python tests/test_subtitle_polish_report_closure.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from lib import credential as cred          # noqa: E402
from lib import report_state as RSTATE      # noqa: E402
from lib import verdict as V                # noqa: E402
import verify_fixes                          # noqa: E402

PASS = 0
FAIL = 0

ASS_HEADER = """[Script Info]
; 测试用最小 ASS（表头留一行注释，方便模拟「重写表头但不动事件」）
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ASS_EVENTS = """Dialogue: 0,0:00:01.00,0:00:03.00,英文,,0,0,0,,Hello there
Dialogue: 0,0:00:01.00,0:00:03.00,中文,,0,0,0,,你好
Dialogue: 0,0:00:04.00,0:00:06.00,英文,,0,0,0,,Second line
Dialogue: 0,0:00:04.00,0:00:06.00,中文,,0,0,0,,旧译B
"""

SRT_BODY = """1
00:00:01,000 --> 00:00:03,000
Hello there

2
00:00:04,000 --> 00:00:06,000
Second line
"""


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
    except AssertionError as e:
        FAIL += 1
        print("  [FAIL] %s\n         %s" % (name, e))
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print("  [ERR ] %s\n         %s: %s" % (name, type(e).__name__, e))
    else:
        PASS += 1
        print("  [ok  ] " + name)


def make_env(tmp):
    """ass + srt + 工作目录，返回 (ass_path, work_dir)。"""
    ass = os.path.join(tmp, "ep.ass")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER + ASS_EVENTS)
    with open(os.path.join(tmp, "ep.srt"), "w", encoding="utf-8") as f:
        f.write(SRT_BODY)
    wd = os.path.join(tmp, ".subtitle-polish")
    os.makedirs(os.path.join(wd, "reports"), exist_ok=True)
    return ass, wd


def entry(ass, sid=2, new="新译B"):
    return {"file": ass, "srt_id": sid, "track": "中文", "action": "replace",
            "old_text": "旧译B", "new_text": new,
            "batch_id": "r01", "category": "语义"}


# ---------------------------------------------------------------- R1
def test_verify_fail_branch_no_crash():
    """回滚后日志写「新译」，盘面是「旧译」：必须报失败，不能崩。"""
    tmp = tempfile.mkdtemp()
    try:
        ass, wd = make_env(tmp)
        ok, fail = verify_fixes.run([entry(ass, 2, "新译B")], wd, "r01")
        assert fail == 1, "应报 1 条失败，实际 ok=%s fail=%s" % (ok, fail)
        body = open(os.path.join(wd, "reports", "verify-fixes.md"),
                    encoding="utf-8").read()
        assert "失败明细" in body and "旧译B" in body, "报告没写出实际落盘内容"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- R2
def test_invalidate_then_fresh():
    """旧绿必须被归档，重跑 verify 后状态清空。"""
    tmp = tempfile.mkdtemp()
    try:
        ass, wd = make_env(tmp)
        old = os.path.join(wd, "reports", "verify-fixes.md")
        with open(old, "w", encoding="utf-8") as f:
            f.write("## 验证结果: 全部通过 (8 条)\n")
        moved = RSTATE.invalidate(wd, "批量回滚 8 条（batch）")
        assert moved, "没有归档旧报告"
        assert not os.path.exists(old), "旧报告还在原位置，会被当当前结论读走"
        stale, why = RSTATE.is_stale(wd)
        assert stale and "verify-fixes.md" in why

        verify_fixes.run([entry(ass, 2, "旧译B")], wd, "r01")  # 这次是 pass
        assert "verify-fixes.md" not in (RSTATE.state(wd).get("names") or []), \
            "重跑 verify 后作废标记没清"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- R3
def test_net_after_rollback():
    """台账 8 条 + 8 条 rollback -> 净改动 0。"""
    import round_orchestrator as ro
    logs = []
    for sid in range(1, 3):
        logs.append({"ts": "2026-01-01T10:00:0%d" % sid, "file": "a.ass",
                     "srt_id": sid, "track": "中文", "action": "replace",
                     "old_text": "旧%d" % sid, "new_text": "新%d" % sid})
    for sid in range(1, 3):
        logs.append({"ts": "2026-01-01T10:01:0%d" % sid, "file": "a.ass",
                     "srt_id": sid, "track": "中文", "action": "rollback",
                     "old_text": "", "new_text": "旧%d" % sid})
    ledger = ro._parse_ledger(logs)
    assert len(ledger) == 2, "总账行数应为 2，实际 %d" % len(ledger)
    assert all(r["new"] == r["old"] for r in ledger), "终译没有回滚到原译"
    assert ro._effective_net(ledger) == 0, "净改动应为 0"


# ---------------------------------------------------------------- R4/R5/R6
def _build(ass, media=None):
    data = cred.build(ass, {"n_pairs": 10, "ok": True}, "qwen", media=media)
    cred.save(ass, data)
    return data


def test_media_same_path_replaced():
    tmp = tempfile.mkdtemp()
    try:
        ass, _wd = make_env(tmp)
        wav = os.path.join(tmp, "audio.wav")
        with open(wav, "wb") as f:
            f.write(b"RIFF0000")
        _build(ass, media=wav)
        with open(wav, "wb") as f:
            f.write(b"RIFF9999")          # 同一路径，内容换了 = 真换片
        r = cred.check(ass, media=wav)
        assert r["verdict"] == V.UNVERIFIED, r
        assert any("片源已换" in x for x in r["reasons"]), r["reasons"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_media_derived_audio_is_not_swap():
    """init 冻结 MKV、验轴用 WAV：不能报「片源已换」。"""
    tmp = tempfile.mkdtemp()
    try:
        ass, _wd = make_env(tmp)
        wav = os.path.join(tmp, "audio.wav")
        mkv = os.path.join(tmp, "ep.mkv")
        with open(wav, "wb") as f:
            f.write(b"RIFF0000")
        with open(mkv, "wb") as f:
            f.write(b"MATROSKA")
        _build(ass, media=wav)
        r = cred.check(ass, media=mkv)
        assert r["verdict"] == V.PASS, "派生音频被判成换片：%s" % r["reasons"]
        assert any("派生" in n for n in r["notes"]), "没说清为什么哈希不同"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_header_rewrite_is_not_content_change():
    tmp = tempfile.mkdtemp()
    try:
        ass, _wd = make_env(tmp)
        _build(ass)
        # 只改表头注释（模拟 pysubs2 重存），事件逐字不动
        text = open(ass, encoding="utf-8").read()
        text = text.replace("; 测试用最小 ASS", "; 被 pysubs2 重写过")
        with open(ass, "w", encoding="utf-8") as f:
            f.write(text)
        r = cred.check(ass, media=None)
        assert r["verdict"] == V.PASS, "表头重写被判成内容变更：%s" % r["reasons"]
        assert any("事件内容未变" in n for n in r["notes"]), "没有说明差异来源"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_text_change_keeps_pass():
    """改文本不再作废轴证据 —— 这是批次 5 的核心口径变化。

    旧口径按整文件 sha1 绑定，改一个中文字就 UNVERIFIED，文本轮每天都在
    改文案，等于把对齐证据废掉。新口径只绑「时间轴事实」：文本改了要
    **保持 PASS**，并写明「文本已改 N 条，时间轴证据沿用」。
    """
    tmp = tempfile.mkdtemp()
    try:
        ass, _wd = make_env(tmp)
        _build(ass)
        text = open(ass, encoding="utf-8").read()
        text = text.replace("你好", "您好")
        with open(ass, "w", encoding="utf-8") as f:
            f.write(text)
        r = cred.check(ass, media=None)
        assert r["verdict"] == V.PASS, "文本改动不该作废轴证据：%s" % r["reasons"]
        assert any("文本已改" in n and "时间轴证据沿用" in n for n in r["notes"]), \
            r["notes"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("== 报告闭环（#44 / #45）==")
    test("R1 回滚后 verify 失败分支不崩", test_verify_fail_branch_no_crash)
    test("R2 回滚作废旧报告 / 重跑清标记", test_invalidate_then_fresh)
    test("R3 净改动从日志回算", test_net_after_rollback)
    test("R4 同一路径换片仍判 UNVERIFIED", test_media_same_path_replaced)
    test("R5 派生音频不报换片", test_media_derived_audio_is_not_swap)
    test("R6a 表头重写不算内容变更", test_header_rewrite_is_not_content_change)
    test("R6b 改文本不再作废轴证据（PASS + 沿用说明）", test_text_change_keeps_pass)
    print("\n通过 %d / 失败 %d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
