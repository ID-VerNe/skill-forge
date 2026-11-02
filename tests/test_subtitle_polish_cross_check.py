# -*- coding: utf-8 -*-
"""cross_check.py 的报告可信度测试（issue #24 / bug #7、#9）。

## 为什么这个脚本需要单独的测试

cross_check 的产出是**给人读的报告**，不是给人跑的代码。所以它错了不会崩、
不会报错、退出码照样 0——只是报告里每个标题都写着错的素材代号，或者撞车
预警里混着十几条「这两句本来就该像」。人读两遍就开始整份跳过，这份报告就
等于不存在了。这类失效没法靠 `assert 退出码 == 0` 抓到，只能断言内容。

本文件锁两件事：

  X1 报告标题的素材代号从成品文件名推导，不写死 `e04`
  X2 撞车预警有起点差门槛：序号相邻但时间隔很远的块不算撞车

## X1 的原 bug

`manual-flow.md` 已经写死约定：`id = audit_id = <shortname>#<srt_id>`，
短名从文件名取（如 `e04#16`）。但 `cross_check.py` 上一版把 `e04` 硬编码在
三个 f-string 里（`:190/:199/:203`），于是**任何素材**跑出来都叫 `e04#`。
报告要进 log、要跨批次对账，代号错了就对不上——而它看起来完全正常。

## X2 的原 bug

原实现只按块序号取 ±window，不看时间。「相邻」在快节奏对白里确实等于
「紧挨着的两句」，但长镜头下相邻两块的起点可以差 20 秒，那是两个不相干的
场景。两份无关译文相似度高只可能是句式巧合（「我知道了」「好的，谢谢」
这类高频短句），不是抄错。

注意这不是「误报率高低」的问题：撞车预警的价值全在于**人能逐条读完**。
实测 S06E04 一轮 99 条 fix 里真错位 15 条，若再叠上十几条长镜头伪相邻，
人就开始整份跳过，那 15 条也就没人看了。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_cross_check.py
"""
from __future__ import annotations

import os
import sys

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

from cross_check import _shortname, collision_score, COLLISION_MAX_GAP  # noqa: E402

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
# X1:素材代号推导
# ─────────────────────────────────────────────────────────────

def t_x1_shortname_from_filename():
    """短名必须来自文件名，且各种常见后缀都要去干净。"""
    cases = [
        (r"C:\work\S06E02.ass", "S06E02"),
        (r"C:\work\e04.srt", "e04"),
        ("S06E04.zh.ass", "S06E04"),
        ("show_chs.ass", "show"),
        ("plain.ass", "plain"),
        # 实测踩到的：素材目录里成品叫 `S06E02.eng.ass`（英文轨底稿）。
        # 只剥一层的话短名会变成 `S06E02.eng`，报告标题就成了
        # `## S06E02.eng#343`——代号里带了个假后缀，跨批次对账照样对不上。
        ("S06E02.eng.ass", "S06E02"),
        ("S06E02.eng.fin.ass", "S06E02"),
    ]
    for path, want in cases:
        got = _shortname(path)
        assert got == want, f"{path!r} 的短名应为 {want!r}，实得 {got!r}"


def t_x1_shortname_never_hardcodes_e04():
    """绝不回退到 `e04`——那是把 bug 伪装成默认值。

    空路径给中性前缀 `sub`：空串会产出 `#343` 这种没有主体的标题，
    比带个中性前缀更难读。但无论如何**不能**是 e04。
    """
    for path in ("", None, ".ass", r"C:\x\.ass"):
        got = _shortname(path)
        assert got != "e04", f"{path!r} 回退成了 e04——这正是要修的 bug"
        assert got, f"{path!r} 返回了空短名，标题会变成 `#343`"


# ─────────────────────────────────────────────────────────────
# X2:撞车预警的时间门槛
# ─────────────────────────────────────────────────────────────

def _rows(specs):
    """specs: [(srt_id, start_sec, zh)] -> load_pairs 形状的行列表。"""
    return [{"srt_id": s, "start": st, "end": st + 1.0, "en": "", "zh": zh}
            for s, st, zh in specs]


def t_x2_near_duplicate_still_reported():
    """紧挨着的两句、译文几乎一样 -> 仍要报。门槛不能把真撞车一起滤掉。"""
    # 起点隔 2.0s，落在门槛内
    rows = _rows([
        (10, 100.0, "我知道了，马上就去办这件事"),
        (11, 102.0, "我知道了，马上就去办这位事"),
    ])
    score, nbr = collision_score(rows, 0, window=3, floor=0.55)
    assert nbr == 11, f"紧邻高相似应报 11，实得 {nbr}（score={score:.2f}）"


def t_x2_distant_duplicate_not_reported():
    """序号相邻但时间隔了 20s(长镜头跨场景) -> 不报。

    两条中文相似度 0.9+，纯靠字符串判据必然命中；靠时间门槛挡掉。
    """
    rows = _rows([
        (10, 100.0, "我知道了，马上就去办这件事"),
        (11, 120.0, "我知道了，马上就去办这位事"),
    ])
    score, nbr = collision_score(rows, 0, window=3, floor=0.55)
    assert nbr is None, (
        f"起点隔 20s 不该算撞车，却报了 {nbr}（score={score:.2f}）。"
        f"长镜头跨场景的伪相邻会挤掉真撞车。")


def t_x2_gap_boundary():
    """门槛边界：正好等于门槛算候选，超一点就不算。

    用 > 而不是 >= 是有意的：门槛写的是「上限」，10.0 秒本身在限内。
    这类边界最容易在重构时被写成 >=，于是 10.0s 这一档悄悄消失。
    """
    rows = _rows([
        (10, 100.0, "我知道了，马上就去办这件事"),
        (11, 100.0 + COLLISION_MAX_GAP, "我知道了，马上就去办这位事"),
    ])
    _, nbr = collision_score(rows, 0, window=3, floor=0.55)
    assert nbr == 11, f"起点差正好 {COLLISION_MAX_GAP}s 应算候选，实得 {nbr}"

    rows = _rows([
        (10, 100.0, "我知道了，马上就去办这件事"),
        (11, 100.0 + COLLISION_MAX_GAP + 0.5, "我知道了，马上就去办这位事"),
    ])
    _, nbr = collision_score(rows, 0, window=3, floor=0.55)
    assert nbr is None, f"起点差超门槛 0.5s 应被挡掉，实得 {nbr}"


def t_x2_gap_can_be_disabled():
    """max_gap=None 关闭时间过滤（保留旧行为的逃生口）。

    没有这个口子的话，碰上「字幕块很少但句子极短」的特殊素材，
    有人会想去改门槛常量本身——那是把局部特例写进全局默认值。
    """
    rows = _rows([
        (10, 100.0, "我知道了，马上就去办这件事"),
        (11, 500.0, "我知道了，马上就去办这位事"),
    ])
    _, nbr = collision_score(rows, 0, window=3, floor=0.55, max_gap=None)
    assert nbr == 11, f"关掉时间过滤后应报 11，实得 {nbr}"


def t_x2_picks_nearest_within_gap():
    """同侧有近有远时，近的相似度也够 -> 报近的，不报远的。

    防止实现改成「先过滤再取最高相似度」时把远的捡回来：
    过滤必须真的把它们排除，不是只在最后判断一次距离。
    """
    rows = _rows([
        (10, 100.0, "我知道了，马上就去办这件事"),
        (11, 100.5, "我明白了，立刻就去做这件事情"),   # 近，相似度中等
        (12, 400.0, "我知道了，马上就去办这件事啊"),   # 远，相似度极高
    ])
    score, nbr = collision_score(rows, 0, window=3, floor=0.55)
    assert nbr == 11, (
        f"应报时间上最近的 11，实得 {nbr}（score={score:.2f}）。"
        f"远的那个相似度更高，但它根本不是同一处。")


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 66)
    print("cross_check 报告可信度测试 (issue #24 / bug #7、#9)")
    print("=" * 66)
    print()

    tests = [
        ("X1 短名从文件名推导", t_x1_shortname_from_filename),
        ("X1 绝不回退到 e04", t_x1_shortname_never_hardcodes_e04),
        ("X2 紧邻高相似仍报", t_x2_near_duplicate_still_reported),
        ("X2 跨 20s 伪相邻不报", t_x2_distant_duplicate_not_reported),
        ("X2 门槛边界 10.0s 含 / +0.5s 不含", t_x2_gap_boundary),
        ("X2 max_gap=None 可关闭过滤", t_x2_gap_can_be_disabled),
        ("X2 门槛内取最近的，不取最像的", t_x2_picks_nearest_within_gap),
    ]

    for name, fn in tests:
        test(name, fn)

    print()
    print("=" * 66)
    print(f"通过 {PASS} / 失败 {FAIL}")
    print("=" * 66)
    sys.exit(0 if FAIL == 0 else 1)
