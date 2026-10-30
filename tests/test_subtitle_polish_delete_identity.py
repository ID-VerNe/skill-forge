# -*- coding: utf-8 -*-
"""回归测试：apply_fixes 在「同一 srt_id 有多条同轨行」时的删除/合并行为。

实测背景（issue #2）：生产环节会把一句中文字幕拆成多条独立 Dialogue（同
start/end、同 track）。此时修一则要「1 条 replace 合并 + N 条 delete 删碎片」，
原实现有三处坑：

  bug H: subs.events.remove(e) 按 == 删，而 pysubs2 的 SSAEvent.__eq__ 只比
         start/end，不看 text/style —— 删的是同时间戳的第一行（往往是英文行），
         目标碎片行原样留着。log 记的 old_text 是对的，盘面是错的。
  bug I: _find_dialogue 无状态，replace 之后再 delete 会重复命中同一行。
  bug J: fix 里的 current 字段从不被读取，删哪一条不可控。
  bug K: 撞车预警只进 dry-run.md，--accept 照跑，退出码 0。

跑法：
  cd <skill-forge>
  python tests/test_subtitle_polish_delete_identity.py
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

PASS = 0
FAIL = 0

HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1
Style: 中文,微软雅黑,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
SRT = """1
00:00:10,000 --> 00:00:12,000
All right, MX-5.

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


def make_fixture(d, events):
    os.makedirs(d, exist_ok=True)
    ass = os.path.join(d, "c.ass")
    srt = os.path.join(d, "c.srt")
    with open(ass, "w", encoding="utf-8", newline="") as f:
        f.write(HEAD + "\n".join(events) + "\n")
    with open(srt, "w", encoding="utf-8", newline="") as f:
        f.write(SRT)
    return ass, srt


def rows(ass):
    out = []
    with open(ass, encoding="utf-8") as f:
        for l in f.read().splitlines():
            if l.startswith("Dialogue:"):
                p = l.split(",", 9)
                out.append(p[3] + " | " + p[9])
    return out


EV3 = [
    "Dialogue: 0,0:00:10.00,0:00:12.00,英文,,0,0,0,,All right, MX-5. Yeah.",
    "Dialogue: 0,0:00:10.00,0:00:12.00,中文,,0,0,0,,是",
    "Dialogue: 0,0:00:10.00,0:00:12.00,中文,,0,0,0,,是的",
]


def run_case(events, fixes_fn, batch):
    import apply_fixes as A
    d = tempfile.mkdtemp(prefix="sp_" + batch + "_")
    try:
        ass, srt = make_fixture(d, events)
        fixes = fixes_fn(ass, srt)
        try:
            A.run_accept(fixes, d, batch)
            raised = False
        except SystemExit:
            raised = True
        return rows(ass), raised
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_merge_with_current():
    """bug H/I/J: 英文行必须保留，两条中文合并成一条。"""
    def fx(ass, srt):
        return [
            {"id": "a1", "srt_id": 1, "track": "中文", "action": "replace",
             "current": "是", "suggested_new": "是 是的",
             "file": ass, "srt_path": srt},
            {"id": "a2", "srt_id": 1, "track": "中文", "action": "delete",
             "current": "是的", "file": ass, "srt_path": srt},
        ]
    got, _ = run_case(EV3, fx, "bH")
    assert got == ["英文 | All right, MX-5. Yeah.", "中文 | 是 是的"], got


def test_delete_first_order_independent():
    """delete 排在 replace 之前也必须得到同一结果。"""
    def fx(ass, srt):
        return [
            {"id": "c1", "srt_id": 1, "track": "中文", "action": "delete",
             "current": "是的", "file": ass, "srt_path": srt},
            {"id": "c2", "srt_id": 1, "track": "中文", "action": "replace",
             "current": "是", "suggested_new": "是 是的",
             "file": ass, "srt_path": srt},
        ]
    got, _ = run_case(EV3, fx, "bI")
    assert got == ["英文 | All right, MX-5. Yeah.", "中文 | 是 是的"], got


def test_two_deletes_same_srt_id():
    """一条保留 + 两条碎片（真实 e03#594 形态）。"""
    ev = [
        "Dialogue: 0,0:00:10.00,0:00:12.00,英文,,0,0,0,,Loads of times.",
        "Dialogue: 0,0:00:10.00,0:00:12.00,中文,,0,0,0,,我自己去过 Caffeine&Machine 很多次了",
        "Dialogue: 0,0:00:10.00,0:00:12.00,中文,,0,0,0,,Caffeine&Machine",
        "Dialogue: 0,0:00:10.00,0:00:12.00,中文,,0,0,0,,很多次了",
    ]

    def fx(ass, srt):
        return [
            {"id": "d1", "srt_id": 1, "track": "中文", "action": "delete",
             "current": "Caffeine&Machine", "file": ass, "srt_path": srt},
            {"id": "d2", "srt_id": 1, "track": "中文", "action": "delete",
             "current": "很多次了", "file": ass, "srt_path": srt},
        ]
    got, _ = run_case(ev, fx, "bJ")
    assert got == ["英文 | Loads of times.",
                   "中文 | 我自己去过 Caffeine&Machine 很多次了"], got


def test_collision_blocks_accept():
    """bug K: 无 current 的撞车必须拒写，文件保持原样。"""
    def fx(ass, srt):
        return [
            {"id": "b1", "srt_id": 1, "track": "中文", "action": "replace",
             "suggested_new": "是 是的", "file": ass, "srt_path": srt},
            {"id": "b2", "srt_id": 1, "track": "中文", "action": "delete",
             "file": ass, "srt_path": srt},
        ]
    got, raised = run_case(EV3, fx, "bK")
    assert raised, "撞车应 SystemExit，实际照写了"
    assert got == ["英文 | All right, MX-5. Yeah.", "中文 | 是", "中文 | 是的"], got


def test_remove_event_identity():
    """护栏: _remove_event 必须按身份删,不能受 SSAEvent.__eq__ 影响。"""
    import apply_fixes as A
    import pysubs2
    e1 = pysubs2.SSAEvent(start=10000, end=12000, style="中文", text="A")
    e2 = pysubs2.SSAEvent(start=10000, end=12000, style="中文", text="B")
    assert e1 == e2, "pysubs2 的 __eq__ 只比时间戳,本测试前提变了"
    subs_obj = pysubs2.SSAFile()
    subs_obj.events = [e1, e2]
    assert A._remove_event(subs_obj, e2) is True
    assert subs_obj.events == [e1], f"应按身份删 e2,实际剩 {subs_obj.events!r}"


if __name__ == "__main__":
    print("apply_fixes 同 srt_id 多行删除/合并回归 (issue #2)")
    test("bug H 英文行不被误删(合并碎片行)", test_merge_with_current)
    test("bug I 顺序无关(delete 在前)", test_delete_first_order_independent)
    test("bug J 两条 delete 同 srt_id", test_two_deletes_same_srt_id)
    test("bug K 撞车拒绝 accept", test_collision_blocks_accept)
    test("护栏 _remove_event 按身份删", test_remove_event_identity)
    print(f"\n  通过 {PASS} / 失败 {FAIL}")
    sys.exit(1 if FAIL else 0)
