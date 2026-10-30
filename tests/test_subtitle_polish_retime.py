# -*- coding: utf-8 -*-
"""回归测试:retime action —— 合并分块后需要调时间轴(issue #3)。

背景:S06E04 精校第 6 轮真实遇到。

    修复前:
      390  1422.12 - 1425.43   but, um, it would be great
      391  1425.44 - 1428.91   if you didn't do things that interfered ...

    replace 只改文本、不动 start/end,所以「390 改成整句 + 删 391」之后
    整句仍只有 3.3 秒显示时间。fixes.json 里没有任何 action 能动时间戳,
    最后只能 --manual-log 绕开脚本手改。

修复口径(issue #3 选 A):
  - 新增 `"action": "retime"`,`new_start` / `new_end` 用**秒**(与 srt 块 start
    一致;pysubs2 内部毫秒,写盘时 *1000,这是已知坑)
  - 时间串复用 log 的 old_text / new_text 字段,格式 '1422.12-1425.43'
  - rollback 解析 old_text 时间串写回
  - verify_fixes 对 retime 条目核对时间轴而非可见文本

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_retime.py
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

PASS = 0
FAIL = 0

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# srt 1 = 1422.12-1425.43, srt 2 = 1425.44-1428.91
# 生产环节把一句拆成了两条独立 Dialogue(390 / 391 的形态)
ASS_BODY = (
    "Dialogue: 0,0:23:42.12,0:23:45.43,英文,,0,0,0,,{\\be3}but, um, it would be great\n"
    "Dialogue: 0,0:23:42.12,0:23:45.43,中文,,0,0,0,,{\\be3}不过 嗯 那就太好了\n"
    "Dialogue: 0,0:23:45.44,0:23:48.91,英文,,0,0,0,,{\\be3}if you didn't do things that interfered with productivity.\n"
    "Dialogue: 0,0:23:45.44,0:23:48.91,中文,,0,0,0,,{\\be3}如果你没做那些妨碍效率的事\n"
)

SRT = """1
00:23:42,120 --> 00:23:45,430
but, um, it would be great

2
00:23:45,440 --> 00:23:48,910
if you didn't do things that interfered with productivity.
"""


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


def _fixture(d):
    ass = os.path.join(d, "e.ass")
    srt = os.path.join(d, "e.srt")
    with open(ass, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(ASS_HEADER + ASS_BODY)
    # 时间戳对齐真实秒数,解析时直接给出秒
    with open(srt, "w", encoding="utf-8") as f:
        f.write(SRT)
    return ass, srt


def _reload(ass):
    import pysubs2
    return pysubs2.load(ass, encoding="utf-8-sig")


def _zh_at(subs, start_s, tol=0.02):
    """取该时间点开始的第一个中文行。"""
    for e in subs.events:
        if e.style == "中文" and abs(e.start / 1000.0 - start_s) <= tol:
            return e
    return None


def _log_json(wd):
    p = os.path.join(wd, "log.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def _run(ass, srt, wd, fixes, batch="b1"):
    from apply_fixes import run_accept
    for fx in fixes:
        fx.setdefault("file", ass)
        fx.setdefault("srt_path", srt)
    run_accept(fixes, wd, batch)


# ── 1. retime 生效：时间轴真的被改了，文本不动 ──
def test_retime_applies():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        _run(ass, srt, d, [{"action": "retime", "srt_id": 1,
                            "track": "中文",
                            "new_start": 1422.12, "new_end": 1428.91,
                            "category": "合并调轴", "reason": "t"}])
        e = _zh_at(_reload(ass), 1422.12)
        assert e is not None, "该行应仍存在"
        assert abs(e.start / 1000.0 - 1422.12) < 0.002, f"start 应保持 1422.12, 实际 {e.start/1000}"
        assert abs(e.end / 1000.0 - 1428.91) < 0.002, f"end 应延到 1428.91, 实际 {e.end/1000}"
        assert "{\\be3}不过 嗯 那就太好了" == e.text, f"文本不该被改: {e.text!r}"
    finally:
        shutil.rmtree(d)


# ── 2. log 的时间串字段正确 ──
def test_retime_logs_timespec():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        _run(ass, srt, d, [{"action": "retime", "srt_id": 1,
                            "track": "中文",
                            "new_start": 1422.12, "new_end": 1428.91}])
        rows = _log_json(d)
        assert len(rows) == 1, f"应写 1 条日志, 实际 {len(rows)}"
        r = rows[0]
        assert r["action"] == "retime", r["action"]
        assert r["old_text"] == "1422.12-1425.43", f"old 时间串错: {r['old_text']!r}"
        assert r["new_text"] == "1422.12-1428.91", f"new 时间串错: {r['new_text']!r}"
    finally:
        shutil.rmtree(d)


# ── 3. rollback 精确恢复时间轴 ──
def test_rollback_restores_timeline():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        _run(ass, srt, d, [{"action": "retime", "srt_id": 1,
                            "track": "中文",
                            "new_start": 1422.12, "new_end": 1428.91}],
             batch="b1")
        e = _zh_at(_reload(ass), 1422.12)
        assert abs(e.end / 1000.0 - 1428.91) < 0.002

        from apply_fixes import run_rollback
        n = run_rollback(d, batch_id="b1")
        assert n == 1, f"应回滚 1 条, 实际 {n}"
        e = _zh_at(_reload(ass), 1422.12)
        assert e is not None, "回滚后该行不该消失（retime 的 new_text 是时间串，不能按文本误删）"
        assert abs(e.end / 1000.0 - 1425.43) < 0.002, \
            f"end 应恢复 1425.43, 实际 {e.end/1000}"
        assert "不过 嗯 那就太好了" in e.text, "回滚不该动文本"
    finally:
        shutil.rmtree(d)


# ── 4. 非法时段被拒，文件保持原样 ──
def test_rejects_invalid_range():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        _run(ass, srt, d, [{"action": "retime", "srt_id": 1,
                            "track": "中文",
                            "new_start": 1430.0, "new_end": 1420.0}])
        assert _log_json(d) == [], "非法时段不该写日志"
        e = _zh_at(_reload(ass), 1422.12)
        assert abs(e.end / 1000.0 - 1425.43) < 0.002, "非法时段不该改动文件"
    finally:
        shutil.rmtree(d)


# ── 5. 缺 new_start/new_end 被拒 ──
def test_rejects_missing_fields():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        _run(ass, srt, d, [{"action": "retime", "srt_id": 1, "track": "中文"}])
        assert _log_json(d) == [], "缺时段不该写日志"
        e = _zh_at(_reload(ass), 1422.12)
        assert abs(e.end / 1000.0 - 1425.43) < 0.002
    finally:
        shutil.rmtree(d)


# ── 6. 完整合并场景：replace + retime + delete，rollback 整体还原 ──
def test_merge_scenario_roundtrip():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        merged = "{\\be3}不过 嗯 那就太好了 如果你没做那些妨碍效率的事"
        _run(ass, srt, d, [
            {"id": "f1", "action": "replace", "srt_id": 1, "track": "中文",
             "current": "不过 嗯 那就太好了",
             "final_new": merged, "category": "合并"},
            {"id": "f2", "action": "retime", "srt_id": 1, "track": "中文",
             "new_start": 1422.12, "new_end": 1428.91, "category": "合并调轴"},
            {"id": "f3", "action": "delete", "srt_id": 2, "track": "中文",
             "current": "如果你没做那些妨碍效率的事", "category": "合并"},
        ], batch="merge1")

        subs = _reload(ass)
        zh = [e for e in subs.events if e.style == "中文"]
        assert len(zh) == 1, f"应只剩 1 条中文行, 实际 {len(zh)}"
        assert clean_zh(zh[0].text) == clean_zh(merged), zh[0].text
        assert abs(zh[0].end / 1000.0 - 1428.91) < 0.002, \
            f"合并后 end 应延到 1428.91, 实际 {zh[0].end/1000}"

        from apply_fixes import run_rollback
        run_rollback(d, batch_id="merge1")
        subs = _reload(ass)
        zh = [e for e in subs.events if e.style == "中文"]
        # delete 回滚不能自动重建（已知限制），故只验 390 那行被还原
        assert len(zh) == 1, f"delete 无法重建，应剩 1 条, 实际 {len(zh)}"
        assert clean_zh(zh[0].text) == "不过 嗯 那就太好了", zh[0].text
        assert abs(zh[0].end / 1000.0 - 1425.43) < 0.002, \
            f"回滚后 end 应恢复 1425.43, 实际 {zh[0].end/1000}"
    finally:
        shutil.rmtree(d)


def clean_zh(t):
    from lib.ass_srt_pair import clean_ass_text
    return clean_ass_text(t)


# ── 7. verify_fixes 认 retime：时间轴一致判通过 ──
def test_verify_accepts_retime():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        _run(ass, srt, d, [{"action": "retime", "srt_id": 1,
                            "track": "中文",
                            "new_start": 1422.12, "new_end": 1428.91}])
        import verify_fixes
        import pysubs2
        from apply_fixes import _build_srt_index, _find_paired_srt
        subs = pysubs2.load(ass, encoding="utf-8-sig")
        sp = _find_paired_srt(ass)
        from lib.ass_srt_pair import parse_srt
        idx = _build_srt_index(parse_srt(sp))
        rows = _log_json(d)
        ok, actual, detail = verify_fixes.verify_entry(rows[0], subs, idx)
        assert ok, f"retime 条目应判通过，实际 detail={detail} actual={actual}"
        assert "时间轴一致" in detail, detail
    finally:
        shutil.rmtree(d)


# ── 8. verify_fixes 能抓到时间轴被改坏 ──
def test_verify_detects_wrong_timeline():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        _run(ass, srt, d, [{"action": "retime", "srt_id": 1,
                            "track": "中文",
                            "new_start": 1422.12, "new_end": 1428.91}])
        # 事后再手改回去，验 verify 会报失败
        import pysubs2
        subs = pysubs2.load(ass, encoding="utf-8-sig")
        for e in subs.events:
            if e.style == "中文" and abs(e.start / 1000.0 - 1422.12) < 0.02:
                e.end = 1425430
        subs.save(ass, encoding="utf-8")

        import verify_fixes
        from apply_fixes import _build_srt_index, _find_paired_srt
        from lib.ass_srt_pair import parse_srt
        subs = pysubs2.load(ass, encoding="utf-8-sig")
        idx = _build_srt_index(parse_srt(_find_paired_srt(ass)))
        ok, actual, detail = verify_fixes.verify_entry(_log_json(d)[0], subs, idx)
        assert not ok, "时间轴被改坏时应判失败"
        assert "时间轴不符" in detail, detail
    finally:
        shutil.rmtree(d)


# ── 9. dry-run 对「显著变长但未带 retime」给出提示 ──
def test_dry_run_warns_on_lengthening():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        from apply_fixes import run_dry_run
        merged = "{\\be3}不过 嗯 那就太好了 如果你没做那些妨碍效率的事"
        p = run_dry_run([{"id": "f1", "action": "replace", "srt_id": 1,
                          "track": "中文", "current": "不过 嗯 那就太好了",
                          "final_new": merged, "file": ass, "srt_path": srt}], d)
        md = open(p, encoding="utf-8").read()
        assert "未带 retime" in md, f"应提示补 retime，实际:\n{md}"
    finally:
        shutil.rmtree(d)


# ── 10. dry-run 展示 retime 的旧时段 → 新时段 ──
def test_dry_run_shows_retime():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        from apply_fixes import run_dry_run
        p = run_dry_run([{"id": "f2", "action": "retime", "srt_id": 1,
                          "track": "中文", "new_start": 1422.12,
                          "new_end": 1428.91, "file": ass, "srt_path": srt}], d)
        md = open(p, encoding="utf-8").read()
        assert "1422.12-1425.43" in md and "1422.12-1428.91" in md, md
        assert "未带 retime" not in md, "retime 条目自己不该被提示缺 retime"
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("retime action 回归测试 (issue #3)")
    print("=" * 70)
    test("R1 retime 生效且不动文本", test_retime_applies)
    test("R2 日志存时间串", test_retime_logs_timespec)
    test("R3 rollback 精确恢复时间轴", test_rollback_restores_timeline)
    test("R4 非法时段被拒", test_rejects_invalid_range)
    test("R5 缺 new_start/new_end 被拒", test_rejects_missing_fields)
    test("R6 合并场景 replace+retime+delete 往返", test_merge_scenario_roundtrip)
    test("R7 verify 认 retime", test_verify_accepts_retime)
    test("R8 verify 抓时间轴被改坏", test_verify_detects_wrong_timeline)
    test("R9 dry-run 提示文本变长缺 retime", test_dry_run_warns_on_lengthening)
    test("R10 dry-run 展示 retime 新旧时段", test_dry_run_shows_retime)
    print()
    print(f"  通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
