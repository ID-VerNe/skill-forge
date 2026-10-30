# -*- coding: utf-8 -*-
"""回归测试:--manual-log 必须校验 --old 真的在盘上(issue #3)。

实测背景:本轮 S06E03 收尾时, agent 先跑 `--manual-log`、随后删除却没匹配上,
log.jsonl 留下 4 条指向不存在内容的脏记录(``old={\\be3}是的`` / ``new=""``),
只能手工清理。append_log 本身不做任何校验, 只 append。

修复:run_manual_log 写盘前调 _manual_log_check ——
  - --old 为空                → 直接失败
  - --old 在该位置找不到      → 直接失败(不会写进日志)
  - 新文本尚未落盘            → 警告, 需 --force
  - 同 srt_id 多条同时戳行    → 警告, 需 --force

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_manual_log_check.py
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

# srt 1 = 0:00:00-0:00:02, srt 2 = 0:00:02-0:00:04
# srt 2 中文轨故意放两条同时间戳行(一句被拆成多条 Dialogue 的形态)
ASS_BODY = """Dialogue: 0,0:00:00.00,0:00:02.00,英文,,0,0,0,,{\\be3}MX-5, yes.
Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,{\\be3}MX-5 是的
Dialogue: 0,0:00:02.00,0:00:04.00,英文,,0,0,0,,{\\be3}Right, walk me through this.
Dialogue: 0,0:00:02.00,0:00:04.00,中文,,0,0,0,,{\\be3}好了 再讲一遍
Dialogue: 0,0:00:02.00,0:00:04.00,中文,,0,0,0,,{\\be3}很多次了
"""

SRT = """1
00:00:00,000 --> 00:00:02,000
MX-5, yes.

2
00:00:02,000 --> 00:00:04,000
Right, walk me through this.
"""


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        FAIL += 1
    except Exception as e:
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        FAIL += 1
    else:
        print(f"  [PASS] {name}")
        PASS += 1


def _fixture(d):
    ass = os.path.join(d, "e.ass")
    srt = os.path.join(d, "e.srt")
    # 与生产一致: UTF-8 BOM + CRLF
    with open(ass, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(ASS_HEADER + ASS_BODY)
    with open(srt, "w", encoding="utf-8") as f:
        f.write(SRT)
    return ass, srt


def _log_lines(wd):
    p = os.path.join(wd, "log.jsonl")
    if not os.path.exists(p):
        return []
    return [l for l in open(p, encoding="utf-8") if l.strip()]


def _run(ass, wd, **kw):
    from apply_fixes import run_manual_log
    args = dict(batch_id="t", file=ass, srt_id=1, track="中文",
                old_text="{\\be3}MX-5 是的", new_text="{\\be3}MX-5 对的",
                category="c", reason="r")
    args.update(kw)
    return run_manual_log(wd, **args)


# ── 1. 本轮真实脏形态:--old 压根不在盘上, 必须拒写 ──
def test_rejects_missing_old():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd)
        # 本轮的原样: 记的 old 是 `{\be3}是的`(删碎片行之前的文本), 但盘上已变成
        # `MX-5 是的`; new 为空(delete 形态)
        raised = False
        try:
            _run(ass, wd, srt_id=1, old_text="{\\be3}是的", new_text="")
        except SystemExit:
            raised = True
        assert raised, "old 不存在时应直接失败"
        assert _log_lines(wd) == [], f"失败时不该写日志, 实际写了 {_log_lines(wd)}"
    finally:
        shutil.rmtree(d)


# ── 2. 空 --old 必须拒写 ──
def test_rejects_empty_old():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd)
        raised = False
        try:
            _run(ass, wd, old_text="")
        except SystemExit:
            raised = True
        assert raised, "空 old 应直接失败"
        assert _log_lines(wd) == []
    finally:
        shutil.rmtree(d)


# ── 3. 正常情形:old 在盘上 + new 已落盘 → 写入 ──
def test_accepts_valid_entry():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd)
        # 模拟手工已改好文件: 把 srt 2 的「很多次了」改成「来过好几次」
        content = open(ass, encoding="utf-8-sig").read()
        content = content.replace("{\\be3}很多次了", "{\\be3}来过好几次")
        open(ass, "w", encoding="utf-8-sig", newline="\r\n").write(content)

        # srt 2 有两条同时间戳中文行, 会多一条「多条同时间戳行」警告 → 需 --force
        _run(ass, wd, srt_id=2, old_text="{\\be3}很多次了",
             new_text="{\\be3}来过好几次", force=True)
        lines = _log_lines(wd)
        assert len(lines) == 1, f"应写入 1 条, 实际 {len(lines)}"
        rec = json.loads(lines[0])
        assert rec["action"] == "manual_edit"
        assert rec["srt_id"] == 2
        assert rec["old_text"] == "{\\be3}很多次了"
        assert rec["new_text"] == "{\\be3}来过好几次"
    finally:
        shutil.rmtree(d)


# ── 4. old 找不到但 new 已在盘上 → 判为重复补记, 需 --force ──
def test_warns_on_duplicate_or_unlanded():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd)
        raised = False
        try:
            # new 已在盘上, old 已不存在 → 重复补记
            _run(ass, wd, old_text="{\\be3}早先的旧文本", new_text="{\\be3}MX-5 是的")
        except SystemExit:
            raised = True
        assert raised, "old 找不到却 new 已落盘, 应警告并中止(除非 --force)"
        assert _log_lines(wd) == []

        # --force 才允许写入
        _run(ass, wd, old_text="{\\be3}早先的旧文本", new_text="{\\be3}MX-5 是的", force=True)
        assert len(_log_lines(wd)) == 1
    finally:
        shutil.rmtree(d)


# ── 5. 同 srt_id 多条同时戳行(list 不覆盖) → 警告 ──
def test_warns_on_ambiguous_multiline():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd)
        raised = False
        try:
            # srt 2 有两条中文行, 但 new 尚未落盘
            _run(ass, wd, srt_id=2, old_text="{\\be3}很多次了",
                 new_text="{\\be3}来过好几次")
        except SystemExit:
            raised = True
        assert raised, "新文本未落盘 + 多条同时间戳行, 应有警告并中止"
    finally:
        shutil.rmtree(d)


# ── 6. --force 到不了「old 找不到」这个致命分支 ──
def test_force_cannot_bypass_missing_old():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd)
        raised = False
        try:
            _run(ass, wd, old_text="{\\be3}彻底不存在", new_text="{\\be3}也不在盘上",
                 force=True)
        except SystemExit:
            raised = True
        assert raised, "--force 不该放过「old 和 new 都不在盘上」"
        assert _log_lines(wd) == []
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("--manual-log 校验回归测试 (issue #3)")
    print("=" * 70)
    test("A1 --old 不在盘上 → 拒写", test_rejects_missing_old)
    test("A2 空 --old → 拒写", test_rejects_empty_old)
    test("A3 正常情形 → 写入", test_accepts_valid_entry)
    test("A4 old 找不到但 new 已落盘 → 警告/需 --force", test_warns_on_duplicate_or_unlanded)
    test("A5 多条同时戳行 + new 未落盘 → 警告", test_warns_on_ambiguous_multiline)
    test("A6 --force 不能绕过 old/new 都不存在", test_force_cannot_bypass_missing_old)
    print()
    print(f"  通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
