# -*- coding: utf-8 -*-
"""回归测试:回滚定位必须落在**正确的那一行**,不许猜、不许污染邻行。

## 背景(测试 agent 报告 bug #1/#2/#3/#4,实测可 1:1 复现)

在 `S06E02实测` 那一轮,日志里 srt_id 476 只有 `replace(r02) → rollback` 两步,
最终却落盘了被替换的文本。测试 agent 在 `%TEMP%/opencode/q1repro` 复现出:

    apply 之前      md5 a1c9100f104e3d1567559fe5f11faa46
    apply 之后      md5 7feee3d5416f2f48c1fee8000c94148c
    --rollback 之后 md5 7feee3d5416f2f48c1fee8000c94148c   ← 一个字节都没写回

残留差异里最要命的一条不是「没还原」,而是**污染了邻行**:

    事件 #988  srt 476  仍是 new_text      ← 该行原文没回来
    事件 #990  srt 477  `等它运回丹麦…`   ← 这是 476 的文本,477 本该是
                                            `问题是 万一有一丁点小瑕疵`

即「改错 1 行」在回滚后变成「改错 1 行 + 写坏 1 行」。

## 根因链(三处单独看都说得通,串起来就写坏数据)

    run_rollback -> _find_dialogue(..., fallback_text=new_text)   ← 没传 prefer_text
                 -> _row_at_start() 只按 start±0.002s 过滤,然后 rows[0]
                 -> _build_index_alignment() 给了个稍偏的起点

映射偏一点点 → 窄窗恰好套住隔壁行 → 因为没有文本判别,直接采信 → 写坏邻行。

## 本文件锁住的五件事

  K1 同起点多行 + 无文本证据 -> **判失败,不许取 rows[0]**(bug #3 的核心)
  K2 同起点多行 + new_text 能唯一认出 -> 落在**那一条**上,不是第一条
  K3 回滚成功时目标行还原、邻行逐字未动(bug #1 正面防线)
  K4 回滚定位失败时**拒绝写盘**,文件保持原样(bug #4)
  K5 回滚结束必须显式报「与回滚前 md5 是否一致」

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_rollback_identity.py
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


# ─────────────────────────────────────────────────────────────
# 夹具:复刻 476/477 的形态 —— 两句时间挨着、中文轨各一条
# ─────────────────────────────────────────────────────────────

def make_ass(tmp, *, collide_start=False):
    """collide_start=True 时把两句中文**放到同一起点**,制造「候选不唯一」。

    真实故障里起点是被映射算偏的,但落在下游看来就是「窄窗套住了 2 条」,
    这里直接构造同一个效果,让测试不依赖具体映射数值。
    """
    ass = ASS_HEADER
    zh_476 = "等它运回丹麦 要在那边展出"
    zh_477 = "问题是 万一有一丁点小瑕疵"
    en_476 = "It's being shipped back to Denmark to be displayed."
    en_477 = "The thing is, what if there's a tiny flaw"
    s476 = "0:24:20.60"      # 1460.6s，与实测里被算偏的那个值一致
    s477 = "0:24:20.60" if collide_start else "0:24:23.40"
    e476 = "0:24:23.40"
    e477 = "0:24:27.10"
    ass += f"Dialogue: 0,{s476},{e476},英文,,0,0,0,,{en_476}\n"
    ass += f"Dialogue: 0,{s476},{e476},中文,,0,0,0,,{zh_476}\n"
    ass += f"Dialogue: 0,{s477},{e477},英文,,0,0,0,,{en_477}\n"
    ass += f"Dialogue: 0,{s477},{e477},中文,,0,0,0,,{zh_477}\n"
    p = os.path.join(tmp, "rb.ass")
    with open(p, "w", encoding="utf-8") as f:
        f.write(ass)
    return p, zh_476, zh_477


def _load(path):
    import pysubs2
    return pysubs2.load(path, encoding="utf-8-sig")


def _zh_texts(path):
    return [e.text for e in _load(path).events if "中文" in (e.style or "")]


# ─────────────────────────────────────────────────────────────
# K1~K5
# ─────────────────────────────────────────────────────────────

def t_k1_ambiguous_no_guess(tmp):
    """候选不唯一又无文本证据 -> 必须返回 None,不许取 rows[0]。

    这是 bug #3 的核心:上一版 `else: return rows[0]` 直接采信事件表顺序,
    而顺序既不稳定也不是语义。返回 None 后调用方报错,用户能看见;
    返回 rows[0] 则静默写坏一行。
    """
    import apply_fixes as af
    a, zh476, zh477 = make_ass(tmp, collide_start=True)
    subs = _load(a)
    # 映射说「srt 476 在 1460.6s」,那里有中英各一条同起点
    index_align = {476: 1460.6}
    got = af._find_dialogue(subs, {}, 476, "中文", index_align=index_align)
    assert got is None, (
        f"同起点有多个候选、又没给 prefer_text,却返回了 {got.text!r}。"
        f"这就是「无证据地猜」,会写坏邻行")

    # 给了对得上的文本才允许定位
    got2 = af._find_dialogue(subs, {}, 476, "中文", index_align=index_align,
                             prefer_text=zh476)
    assert got2 is not None, "给了能对上的 prefer_text 反而定位不到"
    assert got2.text == zh476, f"定位到 {got2.text!r},应为 {zh476!r}"


def t_k2_prefer_text_picks_right_row(tmp):
    """new_text 能唯一认出时,必须落在**那一条**,不是事件表第一条。

    真实回滚的形态:ASS 里现在躺着 new_text,拿它当判别依据。
    上一版 run_rollback 不传 prefer_text,所以完全没用上这条证据。
    """
    import apply_fixes as af
    a, _zh476, zh477 = make_ass(tmp, collide_start=True)
    subs = _load(a)
    index_align = {477: 1460.6}
    got = af._find_dialogue(subs, {}, 477, "中文", index_align=index_align,
                            prefer_text=zh477)
    assert got is not None, "给了唯一能对上的文本却定位失败"
    assert got.text == zh477, (
        f"定位到 {got.text!r} —— 这是同起点的另一条(476 的行),"
        f"写坏邻行就是这么来的")


def t_k3_rollback_restores_and_keeps_neighbors(tmp):
    """回滚后:目标行还原成 old_text,邻行逐字未动。

    bug #1 的正面防线。实测里 477 被写成了 476 的文本,而日志记「回滚成功」。
    """
    import apply_fixes as af
    from lib.log import append_log
    from lib.paths import resolve_work_dir

    # 造一个标准工作目录
    tmp_root = tmp
    wd = os.path.join(tmp_root, ".subtitle-polish")
    os.makedirs(wd, exist_ok=True)
    a, _zh476, zh477 = make_ass(tmp)
    # 模拟「已 apply 过」:476 那行现在是 new_text
    subs = _load(a)
    target = None
    for e in subs.events:
        if "中文" in (e.style or "") and e.start == 1460600:
            target = e
            break
    assert target is not None, "夹具没造出 1460.6s 的中文行"
    old_text = target.text
    new_text = "等它运回丹麦 它要在那边展出"
    target.text = new_text
    subs.save(a, encoding="utf-8")

    append_log(resolve_work_dir(wd), "b1", "replace", a, 476, "中文",
               old_text, new_text, "test", "rollback identity")

    af.run_rollback(resolve_work_dir(wd), batch_id="b1")

    texts = _zh_texts(a)
    assert old_text in texts, (
        f"回滚后目标行没还原成 {old_text!r},现有中文行: {texts}")
    assert zh477 in texts, (
        f"邻行 477 被改坏了!现有中文行: {texts}")
    assert new_text not in texts, (
        f"回滚后 new_text 还在: {texts}")


def t_k4_refuse_write_on_failed_locate(tmp):
    """定位失败时必须拒绝写盘,文件内容保持原样(bug #4)。

    上一版定位失败只 continue,然后照样 subs.save() —— 也就是说「什么都没改成」
    也会重存一遍文件,把表头 Aegisub 改成 pysubs2,还让用户以为回滚跑过了。
    这版断言失败即 skip 写盘。
    """
    import apply_fixes as af
    from lib.log import append_log
    from lib.paths import resolve_work_dir

    wd = os.path.join(tmp, ".subtitle-polish")
    os.makedirs(wd, exist_ok=True)
    a, _zh476, _zh477 = make_ass(tmp)
    before = open(a, "rb").read()

    # 记一条**根本不存在**的 srt_id,并声明一个 ASS 里没有的 new_text
    append_log(resolve_work_dir(wd), "b9", "replace", a, 999, "中文",
               "根本不存在的原文", "根本不存在的当前文本", "test", "phantom")

    af.run_rollback(resolve_work_dir(wd), batch_id="b9")
    after = open(a, "rb").read()
    assert before == after, (
        "定位失败的条目不该触发写盘 —— 文件被重存了(内容或表头已变)")


def t_k5_md5_report_emitted(tmp):
    """回滚结束必须显式说明「与回滚前是否一致」,不能沉默。

    实测中最糟的一点是:md5 一个字节没变,脚本什么都没说。
    """
    import io
    from contextlib import redirect_stdout
    import apply_fixes as af
    from lib.log import append_log
    from lib.paths import resolve_work_dir

    wd = os.path.join(tmp, ".subtitle-polish")
    os.makedirs(wd, exist_ok=True)
    a, _zh476, zh477 = make_ass(tmp)
    append_log(resolve_work_dir(wd), "b2", "replace", a, 477, "中文",
               zh477, zh477, "test", "noop")

    buf = io.StringIO()
    with redirect_stdout(buf):
        af.run_rollback(resolve_work_dir(wd), batch_id="b2")
    out = buf.getvalue()
    assert "md5" in out, f"回滚结束没有输出 md5 结论,实际输出:\n{out}"
    assert ("已变" in out) or ("未变" in out), (
        f"md5 结论不明确(既没说变了也没说没变):\n{out}")


# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("回滚定位身份回归测试 (issue v1.15 · bug #1/#2/#3/#4)")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="rbident_")
    try:
        test("K1 候选不唯一 -> 不许猜 rows[0]", lambda: t_k1_ambiguous_no_guess(tmp))
        test("K2 prefer_text 认出正确那一条", lambda: t_k2_prefer_text_picks_right_row(tmp))
        test("K3 回滚还原目标行且不碰邻行", lambda: t_k3_rollback_restores_and_keeps_neighbors(tmp))
        test("K4 定位失败拒绝写盘", lambda: t_k4_refuse_write_on_failed_locate(tmp))
        test("K5 回滚结束报 md5 结论", lambda: t_k5_md5_report_emitted(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print(f"通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
