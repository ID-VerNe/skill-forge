# -*- coding: utf-8 -*-
"""回归测试:覆盖上一轮实测(session 1f4eff11,James May 字幕)暴露的三个脚本 bug。

bug A: apply_fixes._find_dialogue 的 ±0.5s 容差在相邻 srt 块时间差 < 0.5s 时撞车,
       两条 fix 写到同一物理行,第二条覆盖第一条(培根链 srt 361/362 隔 390ms)。
bug B: precheck_punct._delete_non_digit_eng_punct 缩写点保护用 isalpha(),
       Python 里中文字符也返回 True,导致中文间英文逗号被误判缩写保护、漏删。
bug C: ass_srt_pair._match_by_time_and_text 同 track 多候选全留,
       ±0.5s 容差在相邻块上产生 MULTI_SAME_LANG 误配,切片出现 ⏎ 假重复。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_bugs.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

PASS = 0
FAIL = 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  [PASS] {name}")
        PASS += 1
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        FAIL += 1
    except Exception as e:
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        FAIL += 1


# ─────────────────────────────────────────────────────────────
# 测试夹具:最小 ASS + SRT,复刻培根链 361/362 时间戳(390ms 间隔)
# ─────────────────────────────────────────────────────────────

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 注释,Arial,12,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,8,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# 复刻实测时间戳:361=0:16:21.56(981560ms), 362=0:16:21.95(981950ms), 间隔 390ms
# 用更小数字方便手算: srt 1 = 10.00s, srt 2 = 10.39s(间隔 390ms)
ASS_BODY = """Dialogue: 0,0:00:10.00,0:00:10.30,英文,,0,0,0,,{\\be3}Yeah.
Dialogue: 0,0:00:10.00,0:00:10.30,中文,,0,0,0,,{\\be3}是的
Dialogue: 0,0:00:10.39,0:00:11.50,英文,,0,0,0,,{\\be3}He has hardness.
Dialogue: 0,0:00:10.39,0:00:11.50,中文,,0,0,0,,{\\be3}它变硬了
"""

SRT_CONTENT = """1
00:00:10,000 --> 00:00:10,300
Yeah.

2
00:00:10,390 --> 00:00:11,500
He has hardness.
"""


def _write_fixture(d):
    ass_path = os.path.join(d, "jm.ass")
    srt_path = os.path.join(d, "jm.srt")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER + ASS_BODY)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(SRT_CONTENT)
    return ass_path, srt_path


# ─────────────────────────────────────────────────────────────
# bug A: _find_dialogue 撞车 — 修复后应取时间戳最近的,两条 fix 不撞同一行
# ─────────────────────────────────────────────────────────────

def test_find_dialogue_picks_nearest():
    """srt 1 (10.00s) 和 srt 2 (10.39s) 间隔 390ms < 0.5s 容差。
    修复前:两条都取第一个中文候选(10.00s 那条"是的"),互相覆盖。
    修复后:srt 1 → 10.00s "是的",srt 2 → 10.39s "它变硬了",各归各位。
    """
    import pysubs2
    from apply_fixes import _find_dialogue, _build_srt_index
    from lib.ass_srt_pair import parse_srt, parse_ass, TRACK_ZH

    d = tempfile.mkdtemp()
    try:
        ass_path, srt_path = _write_fixture(d)
        subs = pysubs2.load(ass_path, encoding="utf-8-sig")
        srt_blocks = parse_srt(srt_path)
        srt_index = _build_srt_index(srt_blocks)

        e1 = _find_dialogue(subs, srt_index, 1, TRACK_ZH)
        e2 = _find_dialogue(subs, srt_index, 2, TRACK_ZH)

        assert e1 is not None, "srt 1 中文行定位失败"
        assert e2 is not None, "srt 2 中文行定位失败"
        # 关键:两条不能是同一物理行
        assert e1 is not e2, (
            f"撞车未修:srt 1 和 srt 2 都定位到同一物理行 "
            f"(text={e1.text!r}),应取时间戳最近的各归各位"
        )
        # 各自文本正确
        assert "是的" in e1.text, f"srt 1 应是'是的',实际 {e1.text!r}"
        assert "它变硬了" in e2.text, f"srt 2 应是'它变硬了',实际 {e2.text!r}"
    finally:
        shutil.rmtree(d)


def test_dry_run_reports_collision_when_same_event():
    """构造真正撞车场景(两条 fix 的 srt_id 都映射到同一物理行)验证 dry-run 报警。
    用 srt 1 和 srt 2 但都改中文轨——修复后 _find_dialogue 取最近已不撞,
    所以这里人为构造同 srt_id 两条 fix 模拟撞车。"""
    import json
    from apply_fixes import run_dry_run

    d = tempfile.mkdtemp()
    try:
        ass_path, srt_path = _write_fixture(d)
        work_dir = os.path.join(d, ".subtitle-polish")
        fixes = [
            {"id": "jm#1a", "audit_id": "jm#1", "file": ass_path, "srt_id": 1,
             "track": "中文", "action": "replace", "final_new": "没错",
             "category": "语境错译", "enabled": True, "status": "accepted",
             "srt_path": srt_path},
            # 同 srt_id 又一条,不同 final_new —— 同一物理行被改两次
            {"id": "jm#1b", "audit_id": "jm#1", "file": ass_path, "srt_id": 1,
             "track": "中文", "action": "replace", "final_new": "对的",
             "category": "语境错译", "enabled": True, "status": "accepted",
             "srt_path": srt_path},
        ]
        out = run_dry_run(fixes, work_dir)
        with open(out, encoding="utf-8") as f:
            content = f.read()
        assert "撞车预警" in content, (
            f"dry-run 应报撞车预警(两条 fix 同 srt_id 写同一行),"
            f"实际输出:{content[:300]}"
        )
    finally:
        shutil.rmtree(d)


def test_dry_run_no_collision_for_fixed_neighbor():
    """修复后 srt 1/2(390ms 间隔)各自一条 fix,dry-run 不应报撞车。"""
    import json
    from apply_fixes import run_dry_run

    d = tempfile.mkdtemp()
    try:
        ass_path, srt_path = _write_fixture(d)
        work_dir = os.path.join(d, ".subtitle-polish")
        fixes = [
            {"id": "jm#1", "audit_id": "jm#1", "file": ass_path, "srt_id": 1,
             "track": "中文", "action": "replace", "final_new": "没错",
             "category": "语境错译", "enabled": True, "status": "accepted",
             "srt_path": srt_path},
            {"id": "jm#2", "audit_id": "jm#2", "file": ass_path, "srt_id": 2,
             "track": "中文", "action": "replace", "final_new": "硬得不行",
             "category": "语境错译", "enabled": True, "status": "accepted",
             "srt_path": srt_path},
        ]
        out = run_dry_run(fixes, work_dir)
        with open(out, encoding="utf-8") as f:
            content = f.read()
        assert "撞车预警" not in content, (
            f"修复后 srt 1/2 不该撞车,dry-run 仍报预警:\n{content[:400]}"
        )
    finally:
        shutil.rmtree(d)


# ─────────────────────────────────────────────────────────────
# bug B: precheck_punct 缩写保护 isalpha() 误判中文
# ─────────────────────────────────────────────────────────────

def test_precheck_punct_cjk_comma_deleted():
    """中文间的英文逗号应删成空格,不该被缩写点保护留下。
    修复前:isalpha() 对中文返回 True,'的,不' 被误判缩写保护,逗号留下。
    修复后:isascii()+isalpha(),只拉丁字母触发保护,中文间逗号删成空格。
    """
    from precheck_punct import _delete_non_digit_eng_punct, normalize_punct

    # 实测样本:'5号电池还挺贵的,不是吗?' → '的,不' 中文间英文逗号
    body = "5号电池还挺贵的,不是吗?"
    out = _delete_non_digit_eng_punct(body)
    assert "," not in out, (
        f"中文间英文逗号未被删(被缩写保护误留):输入 {body!r} 输出 {out!r}"
    )
    # 拉丁缩写 J.R. 的点应保留
    body2 = "J.R. 哈特利"
    out2 = _delete_non_digit_eng_punct(body2)
    assert "J.R." in out2, (
        f"拉丁缩写 J.R. 的点被误删:输入 {body2!r} 输出 {out2!r}"
    )
    # 数字间小数点保留
    body3 = "3.14 和 1,000"
    out3 = _delete_non_digit_eng_punct(body3)
    assert "3.14" in out3 and "1,000" in out3, (
        f"数字间 . , 被误删:输入 {body3!r} 输出 {out3!r}"
    )


def test_precheck_punct_find_issues_cjk_comma():
    """find_issues 对中文间英文逗号应报问题(修复前漏报)。"""
    from precheck_punct import find_issues

    issues = find_issues("{\\be3}5号电池还挺贵的,不是吗?", is_chinese=True)
    joined = " ".join(issues)
    assert "英文标点" in joined, (
        f"中文间英文逗号应报'英文标点'问题,实际 issues={issues}"
    )


# ─────────────────────────────────────────────────────────────
# bug C: ass_srt_pair._match_by_time_and_text 同 track 多候选误配
# ─────────────────────────────────────────────────────────────

def test_pair_no_false_multi_same_lang():
    """srt 1/2(390ms 间隔)各对应一条中文行,修复后 pair 不该标 MULTI_SAME_LANG。
    修复前:±0.5s 容差把两条中文行都配到两个 srt 块,切片出现 '是的 ⏎ 它变硬了' 假重复。
    """
    from lib.ass_srt_pair import parse_ass, parse_srt, pair

    d = tempfile.mkdtemp()
    try:
        ass_path, srt_path = _write_fixture(d)
        ass_blocks = parse_ass(ass_path)
        srt_blocks = parse_srt(srt_path)
        paired, ass_only = pair(ass_blocks, srt_blocks)
        assert len(paired) == 2, f"应有 2 个 paired block,实际 {len(paired)}"
        for pb in paired:
            assert "MULTI_SAME_LANG" not in pb.anomalies, (
                f"srt {pb.srt_id} 误标 MULTI_SAME_LANG(anomalies={pb.anomalies}),"
                f"390ms 间隔的同 track 多候选应取最近的、不该误配"
            )
        # 各 paired 的 chinese 字段应只含自己那行,不含 ⏎ 假重复
        assert "是的" in paired[0].chinese and "⏎" not in paired[0].chinese, (
            f"srt 1 chinese 应只含'是的',实际 {paired[0].chinese!r}"
        )
        assert "它变硬了" in paired[1].chinese and "⏎" not in paired[1].chinese, (
            f"srt 2 chinese 应只含'它变硬了',实际 {paired[1].chinese!r}"
        )
    finally:
        shutil.rmtree(d)


def test_pair_keeps_real_multi_same_lang():
    """真同时间戳重复行(两条中文行 start 完全相同)仍应标 MULTI_SAME_LANG。
    修复不能把真生产缺陷也吞掉——距离相同时全留。"""
    from lib.ass_srt_pair import parse_ass, parse_srt, pair

    d = tempfile.mkdtemp()
    try:
        ass_path = os.path.join(d, "dup.ass")
        srt_path = os.path.join(d, "dup.srt")
        # 两条中文行完全同时间戳(真重复)
        dup_ass = ASS_HEADER + """Dialogue: 0,0:00:10.00,0:00:10.30,英文,,0,0,0,,Yeah.
Dialogue: 0,0:00:10.00,0:00:10.30,中文,,0,0,0,,是的
Dialogue: 0,0:00:10.00,0:00:10.30,中文,,0,0,0,,是的
"""
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(dup_ass)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(SRT_CONTENT.split("\n\n")[0] + "\n")  # 只取 srt 1
        ass_blocks = parse_ass(ass_path)
        srt_blocks = parse_srt(srt_path)
        paired, _ = pair(ass_blocks, srt_blocks)
        assert len(paired) == 1
        # 真同时间戳重复 → MULTI_SAME_LANG 应标
        assert "MULTI_SAME_LANG" in paired[0].anomalies, (
            f"真同时间戳重复行应标 MULTI_SAME_LANG,实际 anomalies={paired[0].anomalies}"
        )
    finally:
        shutil.rmtree(d)


# ─────────────────────────────────────────────────────────────
# --manual-log 子命令
# ─────────────────────────────────────────────────────────────

def test_manual_log_appends():
    """破例 Edit 后 --manual-log 补记一条 manual_edit 日志,字段完整。"""
    import json
    import subprocess
    from lib.log import read_log

    d = tempfile.mkdtemp()
    try:
        ass_path, srt_path = _write_fixture(d)
        work_dir = os.path.join(d, ".subtitle-polish")
        os.makedirs(work_dir, exist_ok=True)
        apply_script = os.path.join(SKILL_ROOT, "scripts", "apply_fixes.py")
        r = subprocess.run(
            [sys.executable, apply_script, "--manual-log",
             "--file", ass_path, "--srt-id", "1", "--track", "中文",
             "--old", "是的", "--new", "没错",
             "--category", "语境错译", "--reason", "撞车兜底",
             "--batch-id", "20261002_111500_manual",
             "--work-dir", work_dir],
            capture_output=True, timeout=30,
        )
        # Windows 默认 gbk 解码 stderr 会炸（含中文），强制 utf-8
        stderr = r.stderr.decode("utf-8", errors="replace")
        stdout = r.stdout.decode("utf-8", errors="replace")
        assert r.returncode == 0, f"--manual-log 失败:stderr={stderr}"
        entries = read_log(work_dir)
        assert len(entries) == 1, f"应补记 1 条,实际 {len(entries)}"
        e = entries[0]
        assert e["action"] == "manual_edit", f"action 应是 manual_edit,实际 {e.get('action')}"
        assert e["batch_id"] == "20261002_111500_manual"
        assert e["srt_id"] == 1
        assert e["old_text"] == "是的"
        assert e["new_text"] == "没错"
    finally:
        shutil.rmtree(d)


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("subtitle-polish 回归测试 — session 1f4eff11 暴露的 bug")
    print("=" * 60)
    print()

    tests = [
        ("bug A1: _find_dialogue 取最近不撞车", test_find_dialogue_picks_nearest),
        ("bug A2: dry-run 报撞车预警(真撞车)", test_dry_run_reports_collision_when_same_event),
        ("bug A3: dry-run 不误报(390ms 邻居)", test_dry_run_no_collision_for_fixed_neighbor),
        ("bug B1: precheck_punct 删中文间英文逗号", test_precheck_punct_cjk_comma_deleted),
        ("bug B2: find_issues 报中文间英文逗号", test_precheck_punct_find_issues_cjk_comma),
        ("bug C1: pair 不误配 MULTI_SAME_LANG(390ms)", test_pair_no_false_multi_same_lang),
        ("bug C2: pair 保留真 MULTI_SAME_LANG(同时间戳)", test_pair_keeps_real_multi_same_lang),
        ("--manual-log 补记日志", test_manual_log_appends),
    ]

    for name, fn in tests:
        test(name, fn)

    print()
    print("=" * 60)
    print(f"结果: {PASS} 通过 / {FAIL} 失败")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
