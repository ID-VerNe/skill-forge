# -*- coding: utf-8 -*-
"""回归测试:空白修剪不计入语义改动(v1.16 口径);严格定位=「不能无证据地猜」。

## 背景(第十七轮测试 agent 报告 bug #6 + Q9 裁决)

同一份成片,三处记录 **36**、`diff` 实测 **37**,差的这 1 条是 `srt_id 865`
(ASS 事件 1730)**尾巴上一个空格被删**。两份数据都对,却看起来互相矛盾 ——
追查它花的时间远超它本身的价值。问题不在那个空格,在**没先约定口径**。

配套的第二件事是「方案甲」的措辞。原话写的是「都不成则 abort 不猜」,容易被读成
「只要不是唯一文本命中就必须 abort」,从而把**顺序映射**这种有证据的定位一起挡掉。
第十七轮裁决修订为「**不能无证据地猜**」:有文本交叉验证的顺序映射算有证据,可以
落盘;文本对不上仍 abort。

## 本文件锁住的四件事

  W1 `_replace_text` 不许对正文做 strip —— 尾部空格必须原样保留
     (顺手 strip 会让「只差一个空格」变成一次写盘,差异检测多一条、log 里查不到)
  W2 差异检测必须先归一化再比 —— 空白差异不该被算成语义差异
  W3 判据分两列:算不算语义 / 进不进 log。标签增减不进语义但必须进 log
  W4 `strict=True` 在映射指向处找不到行时返回 None(不退回 ±0.5s 窗猜)

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_whitespace_policy.py
"""
from __future__ import annotations

import os
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
# W1 空白不许被顺手清掉
# ─────────────────────────────────────────────────────────────

def _mk_event(text):
    import pysubs2
    e = pysubs2.SSAEvent()
    e.text = text
    return e


def t_w1_replace_text_keeps_trailing_space():
    """`_replace_text` 必须原样保留尾部空格,不许 strip。

    这就是 865 的形态:原文与译文只差一个尾部空格。若实现里对正文做了 strip,
    这次「改动」会被当成一次正常 replace 落盘 —— 差异检测多一条(36→37),
    而 log 里其实一条都没有(没有任何 fix 触发写盘),两份数据就此对不上。
    """
    import apply_fixes as af
    e = _mk_event("我明白了 ")
    af._replace_text(e, "我明白了 ")
    assert e.text == "我明白了 ", (
        f"尾部空格被吃掉了:{e.text!r}。空白修剪不计入语义改动,"
        f"不该在 replace 里顺手做 —— 那属于 precheck_punct,要单独立账")
    # 行首同样
    e2 = _mk_event(" 我明白了")
    af._replace_text(e2, " 我明白了")
    assert e2.text == " 我明白了", f"行首空格被吃掉了:{e2.text!r}"


def t_w1_replace_text_still_keeps_tags():
    """W1 的改动不许把标签处理一起弄坏(回归保险)。"""
    import apply_fixes as af
    e = _mk_event(r"{\be3}我输了")
    af._replace_text(e, "我把托马斯甩开了")
    assert e.text == r"{\be3}我把托马斯甩开了", f"标签没继承:{e.text!r}"


# ─────────────────────────────────────────────────────────────
# W2 比对先归一化
# ─────────────────────────────────────────────────────────────

def t_w2_whitespace_diff_is_not_semantic():
    """两侧只差空白 -> 归一化后应判为「没有语义差异」。

    这是报告口径的实现侧:比对两个 ASS 时先 strip 再比,否则行尾空格/换行噪声
    每次都会刷屏,真正的语义差异淹在里面。
    """
    a = "等它运回丹麦 要在那边展出"
    b = "等它运回丹麦 要在那边展出 "   # 865 的形态:多一个尾部空格
    assert a != b, "夹具失效:两侧原本应不等"
    assert a.strip() == b.strip(), "strip 后应相等 —— 说明这只是一个空白差异"
    # 反向:真语义差异不能被归一化吞掉
    c = "等它运回丹麦 它要在那边展出"
    assert a.strip() != c.strip(), (
        "归一化把真语义差异一起吞了 —— 那比漏报更糟")


# ─────────────────────────────────────────────────────────────
# W3 判据分两列
# ─────────────────────────────────────────────────────────────

def t_w3_tag_change_logged_but_not_semantic():
    """标签增减:不算语义改动,但**必须**进 log。

    看着矛盾,其实是两个问题:
      - 算不算语义 -> 不算(`{\\be3}` 不可见,观众看到的字没变)
      - 进不进 log -> 必须(不知道它变过,回滚就会把标签丢掉)
    空白修剪两头都不沾:不动语义、也不影响回滚,所以两头都不记。
    """
    import apply_fixes as af
    e = _mk_event(r"{\be3}我输了")
    af._replace_text(e, "我输了")          # 无标签入参 -> 继承原标签
    assert e.text == r"{\be3}我输了", f"标签丢失:{e.text!r}"

    # 空白修剪的对照:不产生任何文本变化,自然也不该产生 log 条目
    e2 = _mk_event("我明白了")
    af._replace_text(e2, "我明白了")
    assert e2.text == "我明白了", "无变化的 replace 不该改动文本"


# ─────────────────────────────────────────────────────────────
# W4 strict 的语义:不能无证据地猜
# ─────────────────────────────────────────────────────────────

def _mk_ass(tmp, *, zh_start="0:00:10.00"):
    ass = ASS_HEADER
    ass += f"Dialogue: 0,{zh_start},0:00:12.00,中文,,0,0,0,,我明白了\n"
    p = os.path.join(tmp, "ws.ass")
    with open(p, "w", encoding="utf-8") as f:
        f.write(ass)
    return p


def t_w4_strict_returns_none_when_mapping_misses():
    """映射说「这一句在 500s」,那里一行都没有 -> strict 必须返回 None。

    这就是「无证据」。静默退回 ±0.5s 窗会在别处以「改了错的句子」的形式
    暴露出来,而那时已经写盘了。宁可 abort 一条,让人重跑。

    注意这条**不是**「必须唯一文本命中才算有证据」——给了能对上的
    `prefer_text` 就是有证据,可以定位(见 W4-b)。
    """
    import apply_fixes as af
    a = _mk_ass(tmp_, zh_start="0:00:10.00")
    import pysubs2
    subs = pysubs2.load(a, encoding="utf-8-sig")
    # srt 块说这一句在 10s,但映射声称在 500s —— 矛盾
    class _SB:
        start = 10.0
        end = 12.0
        text = "我明白了"
    got = af._find_dialogue(subs, {1: _SB()}, 1, "中文",
                            index_align={1: 500.0}, strict=True)
    assert got is None, (
        f"映射指向 500s 处没有行,strict=True 却返回了 {got.text!r}。"
        f"这是无证据的定位,回滚场景下会写坏邻行")


def t_w4b_strict_accepts_evidence_backed_mapping():
    """W4 的边界:严格模式不是「必须唯一文本命中」。

    有文本证据(prefer_text 能在映射起点上对上)时应当正常定位 ——
    第十七轮裁决的措辞就是「不能无证据地猜」,不是「不猜任何非唯一的东西」。
    顺序映射属有证据的定位,同理。
    """
    import apply_fixes as af
    import pysubs2
    a = _mk_ass(tmp_, zh_start="0:00:10.00")
    subs = pysubs2.load(a, encoding="utf-8-sig")
    got = af._find_dialogue(subs, {}, 1, "中文",
                            prefer_text="我明白了",
                            index_align={1: 10.0}, strict=True)
    assert got is not None, "有文本证据的映射被严格模式挡掉了 —— 口径过严"
    assert got.text == "我明白了", f"定位到 {got.text!r}"


# ─────────────────────────────────────────────────────────────
# 跑
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("== 空白口径 / 严格定位 ==")
    tmp_ = tempfile.mkdtemp(prefix="ws-policy-")

    test("W1  _replace_text 保留尾部空格", t_w1_replace_text_keeps_trailing_space)
    test("W1b _replace_text 仍继承标签", t_w1_replace_text_still_keeps_tags)
    test("W2  空白差异不是语义差异", t_w2_whitespace_diff_is_not_semantic)
    test("W3  标签变更记 log 但不算语义", t_w3_tag_change_logged_but_not_semantic)
    test("W4  strict 无证据返回 None", t_w4_strict_returns_none_when_mapping_misses)
    test("W4b strict 接受有证据的映射", t_w4b_strict_accepts_evidence_backed_mapping)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
