# -*- coding: utf-8 -*-
"""回归测试:current 对不上时不许「兜底改写」,回滚失败必须带非 0 退出码。

## H-1：唯一会主动写坏成品的路径

现场形态（第五轮测试 agent 在 S06E02 复现）：

    track=英文，current='我明白了'          ← 中文译文写进了英文轨
    → [?] 声明 current 在 track=英文 的行组里找不到，改用 ASS 实读值
    → 写入 1 条，退出码 0

根因是 `_find_dialogue` 里 `track` **只用来过滤候选行**，没有任何一步校验
「current 是不是这一轨的语言」。于是「该轨找不到 current」被当成「只是没精确
命中」，退回时间窗，命中同起点的英文行，把中文写进去。

而且它**接不住**：下游撞车预检里那条 `if not any(clean_ass_text(x) == want …)`
检查的是**改写后**的 current，改写让它恒真 —— 那道 `raise SystemExit(1)`
从来没生效过。

## 第二道更阴：子串 current，不用写错任何字段

    current='最基本的清理'
    实读   ='我会做最基本的清理 但它确实…'
    → 整行被换成 5 个字，后半句蒸发

这里 current、track、srt_id 全都「看起来对」，只是 current 不是逐字整行。
旧实现认命写盘，成品里那句话的后半截永久消失，而 verify 看「新文本是否落盘」
（落盘了就是 PASS），cross_check 看重复/相似（不报），两道检查都过。

## 本文件锁住的事

  N1 track=英文 + 中文 current      → reject，文件逐字未动，RC=1
  N2 子串 current（非整行）          → reject，文件逐字未动，RC=1
  N3 自洽的 fix 不被误伤（反向对照）  → 正常写入，RC=0
  N4 行内片段 current 且确实在行组里  → 放行（碎片行 delete 的合法形态）

## M-2：回滚的「全有或全无」

上一版是「能定位的照常写盘」：CASE-B 实测 `回滚 1 条，失败 1 条` 然后
`subs.save()`，成品里一半是新文本、一半是原文 —— 两份文本混在同一个文件里，
而调用方只看到一行「回滚 1 条」。

这比「全失败」危险得多：全失败至少是「什么都没做」，半成功是「做了一半、
且没人知道是哪一半」。回滚的语义是「退回到某个时刻」—— 一个时刻要么到达、
要么没到达，没有「到了 60%」这种状态。

  M1 一条定位失败 → 整个文件拒绝写盘，已定位成功的那条也不写
  M2 此时 `run_rollback` 抛 SystemExit(非 0)，`return count` 不再吞掉失败

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_current_strict.py
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

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

# 同起点的英中两行 —— 这正是 H-1 会走错的布局：track 过滤后仍有候选，
# current 对不上时退回时间窗就只需要「同起点的另一条」。
ASS_BODY = (
    "Dialogue: 0,0:00:10.00,0:00:12.00,英文,,0,0,0,,Now let's get serious.\n"
    "Dialogue: 0,0:00:10.00,0:00:12.00,中文,,0,0,0,,现在该正经起来了\n"
    "Dialogue: 0,0:00:20.00,0:00:22.00,中文,,0,0,0,,我会做最基本的清理 但它确实很脏\n"
    "Dialogue: 0,0:00:30.00,0:00:32.00,中文,,0,0,0,,我自己去过 Caffeine&Machine 很多次了\n"
    "Dialogue: 0,0:00:30.00,0:00:32.00,中文,,0,0,0,,很多次了\n"
)

SRT = """1
00:00:10,000 --> 00:00:12,000
Now let's get serious.

2
00:00:20,000 --> 00:00:22,000
I'll do the basic cleanup but it really is filthy.

3
00:00:30,000 --> 00:00:32,000
I've been to Caffeine&Machine loads of times.
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
    with open(srt, "w", encoding="utf-8") as f:
        f.write(SRT)
    return ass, srt


def _md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def _accept(fixes, wd, batch="b1"):
    """跑 run_accept，返回 (是否抛 SystemExit, 退出码, stderr 文本)。"""
    import apply_fixes as af
    err = io.StringIO()
    out = io.StringIO()
    code = None
    with redirect_stdout(out), redirect_stderr(err):
        try:
            af.run_accept(fixes, wd, batch)
        except SystemExit as e:
            code = e.code
    return (code is not None), code, err.getvalue() + out.getvalue()


def _fixes(ass, srt, rows):
    for r in rows:
        r.setdefault("file", ass)
        r.setdefault("srt_path", srt)
        r.setdefault("action", "replace")
    return rows


# ── N1：track 与 current 语种矛盾 ────────────────────────────────
def test_lang_mismatch_rejected():
    """track=英文 + 中文 current：不许写盘，且必须带非 0 退出码。

    这是 H-1 的原始形态。修好之前它的结果是「中文译文写进英文轨、RC=0、
    verify PASS」—— 唯一会主动写坏成品的路径。
    """
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        before = _md5(ass)
        raised, code, log = _accept(_fixes(ass, srt, [
            {"id": "h1", "srt_id": 1, "track": "英文",
             "current": "我明白了", "final_new": "I see."},
        ]), d)
        assert _md5(ass) == before, "语言矛盾时文件被改了 —— 这正是 H-1"
        assert raised, f"语言矛盾必须让它失败退出，实际正常返回。输出:\n{log}"
        assert code not in (0, None), f"退出码应为非 0，实际 {code!r}"
        assert "中文" in log and "英文" in log, \
            f"报错里要同时点明「声明是中文」和「track 要英文」，实际:\n{log}"
    finally:
        shutil.rmtree(d)


# ── N2：子串 current（非逐字整行）────────────────────────────────
def test_substring_current_rejected():
    """current 只是行内片段：不许把整行替换掉。

    修好之前的形态更阴：**不需要写错任何字段**，只要 current 不是逐字整行。
    `current='最基本的清理'` 对上 `'我会做最基本的清理 但它确实很脏'` 时，
    整行被换成 5 个字，后半句蒸发。
    """
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        before = _md5(ass)
        raised, code, log = _accept(_fixes(ass, srt, [
            {"id": "nsub", "srt_id": 2, "track": "中文",
             "current": "最基本的清理", "final_new": "我会做最基本的清理"},
        ]), d)
        assert _md5(ass) == before, (
            "子串 current 把整行换掉了 —— 后半句『但它确实很脏』蒸发")
        assert raised, f"子串 current 必须失败退出，实际正常返回。输出:\n{log}"
        assert code not in (0, None), f"退出码应为非 0，实际 {code!r}"
    finally:
        shutil.rmtree(d)


# ── N3：反向对照，自洽的 fix 不许被误伤 ──────────────────────────
def test_self_consistent_still_writes():
    """中文轨 + 逐字整行的中文 current：必须照常写入、RC=0。

    没有这一条，上面两道检查可以靠「全部 reject」轻松通过 ——
    验收要的是「坏的拦住、好的放过」，只测一半等于没测。
    """
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        before = _md5(ass)
        raised, code, log = _accept(_fixes(ass, srt, [
            {"id": "ok1", "srt_id": 3, "track": "中文",
             "current": "我自己去过 Caffeine&Machine 很多次了",
             "final_new": "我去过 Caffeine&Machine 很多次"},
        ]), d)
        assert not raised, f"自洽的 fix 不该失败，输出:\n{log}"
        assert _md5(ass) != before, "自洽的 fix 应该真的写进去了"
        import pysubs2
        texts = [e.text for e in pysubs2.load(ass, encoding="utf-8-sig").events]
        assert "我去过 Caffeine&Machine 很多次" in texts, \
            f"新文本没落盘，现有:\n{texts}"
    finally:
        shutil.rmtree(d)


# ── N4：合法的行内片段（碎片行定位）不许误杀 ─────────────────────
def test_inline_fragment_delete_allowed():
    """current 是行内片段、但确实是该行组里的**一整条碎片行** → 放行。

    与 N2 的区别在于「这一串字符在行组里是不是一行独立的那条行」：
      N2：'最基本的清理' 不是任何一行的完整文本 → 拒
      N4：'很多次了'   是同 srt_id 下一条独立Dialogue → 是合法定位，必须准许

    不区分这两者，碎片行合并（1 replace + N delete，S06E02 实测每天都有）
    会被整批误杀。
    """
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        before = _md5(ass)
        raised, code, log = _accept(_fixes(ass, srt, [
            {"id": "frag", "srt_id": 3, "track": "中文",
             "action": "delete", "current": "很多次了"},
        ]), d)
        assert not raised, f"碎片行 delete 被误杀，输出:\n{log}"
        assert _md5(ass) != before, "碎片行 delete 应该真的删掉了"
        import pysubs2
        texts = [e.text for e in pysubs2.load(ass, encoding="utf-8-sig").events]
        assert "很多次了" not in texts, f"碎片行没被删，现有:\n{texts}"
        assert "我自己去过 Caffeine&Machine 很多次了" in texts, (
            f"删错了 —— 保留行被删掉了。现有:\n{texts}")
    finally:
        shutil.rmtree(d)


# ── M1：回滚全有或全无 ──────────────────────────────────────────
def _seed_log(wd, batch, rows):
    from lib.log import append_log
    from lib.paths import resolve_work_dir
    for r in rows:
        append_log(resolve_work_dir(wd), batch, r["action"], r["file"],
                   r["srt_id"], r.get("track", "中文"),
                   r["old_text"], r["new_text"],
                   r.get("category", ""), r.get("reason", ""))


def test_rollback_all_or_nothing():
    """一条定位失败 → 整个文件拒绝写盘，已定位成功的也不写。

    上一版是「能定位的照常写盘」，成品里一半新文本一半原文，而汇总只写
    「回滚 1 条，失败 1 条」—— 调用方看不出文件其实已经被写了一半。
    """
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        # 先真的改一行，让回滚有东西可还原
        import pysubs2
        subs = pysubs2.load(ass, encoding="utf-8-sig")
        tgt = [e for e in subs.events if e.text == "现在该正经起来了"][0]
        tgt.text = "现在得认真点了"
        subs.save(ass, encoding="utf-8")

        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd, exist_ok=True)
        _seed_log(wd, "bv", [
            # 这条能定位（现在躺着 new_text）
            {"action": "replace", "file": ass, "srt_id": 1, "track": "中文",
             "old_text": "现在该正经起来了", "new_text": "现在得认真点了"},
            # 这条定位不到（srt_id 根本不存在）
            {"action": "replace", "file": ass, "srt_id": 99, "track": "中文",
             "old_text": "根本没有这句", "new_text": "也没有这句"},
        ])
        before = _md5(ass)

        import apply_fixes as af
        from lib.paths import resolve_work_dir
        err = io.StringIO()
        raised = False
        code = None
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            try:
                af.run_rollback(resolve_work_dir(wd), batch_id="bv")
            except SystemExit as e:
                raised = True
                code = e.code
        log = err.getvalue()

        assert _md5(ass) == before, (
            "全有或全无：有失败时整个文件都不该写盘。实际文件被改了 —— "
            f"这就是「一半新一半旧」。输出:\n{log}")
        assert raised, f"回滚有失败必须带非 0 退出码，实际正常返回。输出:\n{log}"
        assert code not in (0, None), f"退出码应为非 0，实际 {code!r}"
        assert "拒绝写盘" in log, f"要明确说明「整个文件拒绝写盘」，实际:\n{log}"
    finally:
        shutil.rmtree(d)


def test_rollback_clean_succeeds():
    """反向对照：全部能定位时，回滚正常写盘且 RC=0（不许被全有或全无误伤）。"""
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        import pysubs2
        subs = pysubs2.load(ass, encoding="utf-8-sig")
        tgt = [e for e in subs.events if e.text == "现在该正经起来了"][0]
        tgt.text = "现在得认真点了"
        subs.save(ass, encoding="utf-8")

        wd = os.path.join(d, ".subtitle-polish")
        os.makedirs(wd, exist_ok=True)
        _seed_log(wd, "bg", [
            {"action": "replace", "file": ass, "srt_id": 1, "track": "中文",
             "old_text": "现在该正经起来了", "new_text": "现在得认真点了"},
        ])
        import apply_fixes as af
        from lib.paths import resolve_work_dir
        raised = False
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                n = af.run_rollback(resolve_work_dir(wd), batch_id="bg")
            except SystemExit:
                raised = True
        assert not raised, "全部能定位时不该失败退出"
        texts = [e.text for e in pysubs2.load(ass, encoding="utf-8-sig").events]
        assert "现在该正经起来了" in texts, f"没还原，现有:\n{texts}"
        assert "现在得认真点了" not in texts, f"新文本还在:\n{texts}"
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("current 严格化 + 回滚全有或全无 回归测试 (issue v1.15 · H-1/M-1/M-2)")
    print("=" * 70)
    test("N1 track/current 语种矛盾 -> reject 且 RC=1", test_lang_mismatch_rejected)
    test("N2 子串 current -> reject 且 RC=1", test_substring_current_rejected)
    test("N3 自洽 fix 不被误伤（反向对照）", test_self_consistent_still_writes)
    test("N4 合法行内碎片 delete 放行", test_inline_fragment_delete_allowed)
    test("M1 回滚有失败 -> 整文件拒写 + RC=1", test_rollback_all_or_nothing)
    test("M2 回滚全部成功 -> 正常写盘", test_rollback_clean_succeeds)
    print(f"\n  通过 {PASS} / 失败 {FAIL}")
    sys.exit(1 if FAIL else 0)
