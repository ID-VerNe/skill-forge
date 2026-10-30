# -*- coding: utf-8 -*-
"""回归测试:verify_fixes 只比对 log 与盘面,无法发现「写入成功但译文错位」。

实测背景(issue #1):S06E04 双语 ASS 一轮 99 条 fix,verify 报 104 通过 / 0 失败,
事后对比快照发现其中 15 条把原本正确的译文换成了邻行的/同场景另一句的译文。
verify 全部通过,因为 verify 比的是「盘面 == log 里的 new_text」,恒等式。

本文件复刻最小场景,验证修复后应有的行为(已修,全部应为 PASS):

  bug D: verify_entry 对「new_text 与英文对不上」的条目仍报通过
  bug E: 没有「与邻块译文撞车」的检查
  bug F: dry-run 对撞车条目没有预警

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_verify_blindspot.py

注:本文件只依赖 stdlib + pysubs2,用最小夹具,不需要真实字幕文件。
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
XFAIL = 0


def test(name, fn, expect_fail=False):
    """expect_fail=True:这是 issue 描述的现状,修好后应变成 PASS。"""
    global PASS, FAIL, XFAIL
    try:
        fn()
    except AssertionError as e:
        if expect_fail:
            print(f"  [XFAIL] {name}  (issue 未修:{e})")
            XFAIL += 1
        else:
            print(f"  [FAIL] {name}: {e}")
            FAIL += 1
    except Exception as e:
        if expect_fail:
            print(f"  [XFAIL] {name}  (issue 未修:{type(e).__name__}: {e})")
            XFAIL += 1
        else:
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            FAIL += 1
    else:
        if expect_fail:
            print(f"  [XPASS] {name}  (已修复,请把 expect_fail 改成 False)")
            PASS += 1
        else:
            print(f"  [PASS] {name}")
            PASS += 1


# ─────────────────────────────────────────────────────────────
# 夹具:复刻 e04#343 / #344 的真实错位
#   343 EN = to promote his Japanese car meet.
#   343 正确译文 = 来宣传他的日本车友聚会
#   343 被错写成 = 好了 刘易斯 再把流程跟我讲一遍 (= 344 的内容)
# ─────────────────────────────────────────────────────────────

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

# 343 已经「写坏」:中文是 344 的内容
ASS_BODY_CORRUPT = """Dialogue: 0,0:21:05.56,0:21:08.36,英文,,0,0,0,,{\\be3}to promote his Japanese car meet.
Dialogue: 0,0:21:05.56,0:21:08.36,中文,,0,0,0,,{\\be3}好了 刘易斯 再把流程跟我讲一遍
Dialogue: 0,0:21:08.36,0:21:11.00,英文,,0,0,0,,{\\be3}Right, Lewis, walk me through this again.
Dialogue: 0,0:21:08.36,0:21:11.00,中文,,0,0,0,,{\\be3}好了 刘易斯 再跟我讲讲这是怎么回事
"""

SRT_CONTENT = """343
00:21:05,560 --> 00:21:08,360
to promote his Japanese car meet.

344
00:21:08,360 --> 00:21:11,000
Right, Lewis, walk me through this again.
"""


def _fixture(d):
    ass = os.path.join(d, "e04.ass")
    srt = os.path.join(d, "e04.srt")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER + ASS_BODY_CORRUPT)
    with open(srt, "w", encoding="utf-8") as f:
        f.write(SRT_CONTENT)
    return ass, srt


def _make_log(d, ass, srt, new_text):
    """造一条 apply 日志:宣称把 srt 343 写成了 new_text。"""
    import time
    wd = os.path.join(d, ".subtitle-polish")
    os.makedirs(wd, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "batch_id": "fixture",
        "action": "replace",
        "file": ass,
        "srt_path": srt,
        "srt_id": 343,
        "track": "中文",
        "old_text": "{\\be3}来宣传他的日本车友聚会",
        "new_text": new_text,
        "category": "信达雅（低）",
        "reason": "walk me through 是「把流程讲一遍」",
    }
    with open(os.path.join(wd, "log.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return wd, entry


# ─────────────────────────────────────────────────────────────
# bug D: 写坏的译文,verify 仍报通过
# ─────────────────────────────────────────────────────────────

def test_verify_rejects_text_mismatching_english():
    """复刻实测:343 被写成 344 的内容,verify 应力判失败。

    现状:verify_entry 只比对 log 的 new_text 与盘面,两者都是
    「好了 刘易斯 再把流程跟我讲一遍」,于是返回 True。
    修复后:应引入与英文源的对照,判定这条译文没有表达
    「to promote his Japanese car meet」,返回 False。
    """
    import verify_fixes

    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        bad_text = "{\\be3}好了 刘易斯 再把流程跟我讲一遍"
        wd, entry = _make_log(d, ass, srt, bad_text)

        import pysubs2
        from lib.ass_srt_pair import parse_srt
        from apply_fixes import _build_srt_index
        subs = pysubs2.load(ass, encoding="utf-8-sig")
        srt_index = _build_srt_index(parse_srt(srt))

        ok, actual, detail = verify_fixes.verify_entry(entry, subs, srt_index)
        assert not ok, (
            f"verify 应为这条错位译文判失败,实际 ok={ok} detail={detail!r}。"
            f"译文 {actual!r} 与英文 'to promote his Japanese car meet.' 毫无关系"
        )
    finally:
        shutil.rmtree(d)


def test_verify_still_accepts_correct_text():
    """对照组:译文正确时,verify 必须报通过(不能修成一律失败)。"""
    import verify_fixes
    import pysubs2
    from lib.ass_srt_pair import parse_srt

    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd, entry = _make_log(d, ass, srt, "{\\be3}好了 刘易斯 再把流程跟我讲一遍")

        # 把盘面改成正确译文,log 也改成正确译文
        content = open(ass, encoding="utf-8").read()
        content = content.replace(
            "{\\be3}好了 刘易斯 再把流程跟我讲一遍\nDialogue: 0,0:21:08.36",
            "{\\be3}来宣传他的日本车友聚会\nDialogue: 0,0:21:08.36",
            1,
        )
        open(ass, "w", encoding="utf-8").write(content)
        entry["new_text"] = "{\\be3}来宣传他的日本车友聚会"

        subs = pysubs2.load(ass, encoding="utf-8-sig")
        from apply_fixes import _build_srt_index
        srt_index = _build_srt_index(parse_srt(srt))
        ok, actual, detail = verify_fixes.verify_entry(entry, subs, srt_index)
        assert ok, f"正确译文被判失败,说明修正过头:detail={detail!r}, actual={actual!r}"
    finally:
        shutil.rmtree(d)


# ─────────────────────────────────────────────────────────────
# bug E: 缺「与邻块译文撞车」检查
# ─────────────────────────────────────────────────────────────

def test_neighbor_duplicate_detected():
    """新译文与 ±3 邻块现有译文高度相似,应有独立报警入口。

    实测:坏 15 条里 4 条的邻块相似度 >= 0.60(#619↔#618 0.67,
    #351↔#352 0.62,#512↔#511 0.61,#343↔#344 0.60),
    而好的 84 条在 0.50 以上 0 命中——误报率为 0。
    修复后:verify_fixes 应暴露一个可调用的邻块撞车检测函数。
    """
    assert hasattr(verify_fixes_mod(), "detect_neighbor_duplicate"), (
        "verify_fixes 未提供邻块撞车检测(如 detect_neighbor_duplicate)。"
        "实测该判据:坏条命中 4/15,好条误报 0/84,值得加"
    )


def verify_fixes_mod():
    import importlib
    import verify_fixes
    return importlib.reload(verify_fixes)


# ─────────────────────────────────────────────────────────────
# bug F: dry-run 对撞车条目不预警
# ─────────────────────────────────────────────────────────────

def test_dry_run_warns_on_cross_block_copy():
    """dry-run 应把「suggested_new 与邻块现有译文高度相似」标为撞车预警。

    实测 345 就是这种形态。dry-run 已有「撞车预警」通道(用于
    时间戳 < 0.5s 场景),应复用同一通道提示这类条目。
    """
    from apply_fixes import run_dry_run

    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        # 343 的新译文 = 344 的现有译文
        fixes = [{
            "id": "e04#343", "audit_id": "e04#343", "file": ass,
            "srt_path": srt, "srt_id": 343, "track": "中文",
            "action": "replace", "final_new": "好了 刘易斯 再跟我讲讲这是怎么回事",
            "category": "信达雅（低）", "enabled": True, "status": "accepted",
        }]
        out = run_dry_run(fixes, wd)
        content = open(out, encoding="utf-8").read()
        assert "撞车预警" in content, (
            "dry-run 未对「新译文等于邻块译文」预警。"
            f"该条正是实测中把 343 改成 344 内容的形态。输出:\n{content[:400]}"
        )
    finally:
        shutil.rmtree(d)


# ─────────────────────────────────────────────────────────────
# G: cross_check 的撞车检测必须能抓到「抄邻块」这类错位
#    (issue #1 的止血手段,已在 skill 中实现,这条防它被改坏)
# ─────────────────────────────────────────────────────────────

def test_cross_check_flags_neighbor_copy():
    """343 写成 344 的内容时,collision_score 必须给出 >= 0.55 并指向 344。"""
    from cross_check import load_pairs, collision_score

    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        rows = load_pairs(ass, srt)
        idx = [i for i, r in enumerate(rows) if r["srt_id"] == 343][0]
        score, nbr = collision_score(rows, idx, window=3, floor=0.55)
        assert nbr == 344, f"应指向 344,实际 {nbr}"
        assert score >= 0.55, f"相似度应 >=0.55,实际 {score:.2f}"
    finally:
        shutil.rmtree(d)


def test_cross_check_quiet_on_normal_pair():
    """对照组:两个互不相干的译文,不应报撞车(防误报)。"""
    from cross_check import load_pairs, collision_score

    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        # 把 343 改成与 344 完全无关的正确译文
        content = open(ass, encoding="utf-8").read().replace(
            "{\\be3}好了 刘易斯 再把流程跟我讲一遍\nDialogue: 0,0:21:08.36",
            "{\\be3}来宣传他的日本车友聚会\nDialogue: 0,0:21:08.36", 1)
        open(ass, "w", encoding="utf-8").write(content)

        rows = load_pairs(ass, srt)
        idx = [i for i, r in enumerate(rows) if r["srt_id"] == 343][0]
        _score, nbr = collision_score(rows, idx, window=3, floor=0.55)
        assert nbr is None, f"正确译文不该报撞车,却指向 {nbr}"
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("verify_fixes 盲区回归测试 (issue #1)")
    print("  已修(2026-10-30):D1/E/F 由 XFAIL 转为 PASS")
    print("=" * 70)


    test("D1 verify 应拒绝与英文对不上的译文", test_verify_rejects_text_mismatching_english)
    test("D2 对照组:正确译文必须判通过", test_verify_still_accepts_correct_text)
    test("E  应提供邻块撞车检测", test_neighbor_duplicate_detected)
    test("F  dry-run 应对跨块复制预警", test_dry_run_warns_on_cross_block_copy)
    test("G1 cross_check 应抓到抄邻块", test_cross_check_flags_neighbor_copy)
    test("G2 cross_check 对照组:正常译文不报", test_cross_check_quiet_on_normal_pair)

    print()
    print(f"  通过 {PASS} / 失败 {FAIL} / 待修 {XFAIL}")
    sys.exit(0 if FAIL == 0 else 1)
