# -*- coding: utf-8 -*-
"""回归测试:check_fluency.py 的「书面语残留」规则要查英文来源(issue #7)。

背景:S06E04 精校第 8 轮实测。

    修复前(纯中文子串匹配):
      中文含「所以」→ 全部报「书面语残留」

    但 53 条「所以」的英文原句**全部**含 `So`/`so`:
      "So that serves as a calling card that generates work."
        → 「所以这就相当于 一张活招牌 能给我们带来生意」
    这是话语标记的忠实直译,不是翻译腔。一集 63 条命中里 61 条假阳性,
    精度 3%,规则失去可用性(用户按「翻译腔」批量改会把对的改错)。

修复口径(issue #7):
  - FORMAL_WORDS 从 list 改成 dict: 中文书面语词 → 英文字段来源正则
  - 中文出现该词 **且** 英文无对应来源 → 才报(忠实直译不算翻译腔)
  - 值为 None = 无英文字面对应物(如「进行」是空动词)→ 照报,
    但标 confidence=medium 提示看语境;有来源正则的标 high

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_fluency.py
"""
from __future__ import annotations

import os
import sys

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


def _hits(en, zh):
    from check_fluency import check_line
    return check_line(en, zh)


def _formal(en, zh):
    return [h for h in _hits(en, zh) if h["rule"] == "书面语残留"]


# ── 1. 忠实直译不报：So → 所以 ──
def test_so_to_suoyi_is_not_flagged():
    hits = _formal("So that serves as a calling card that generates work.",
                   "所以这就相当于 一张活招牌 能给我们带来生意")
    assert hits == [], f"So→所以 是忠实直译，不该报翻译腔，实际: {hits}"


# ── 2. 句中 So 同样不报 ──
def test_midsentence_so_not_flagged():
    hits = _formal("But I have done that once before and it doesn't feel nice, "
                   "so I'm ruling it out.",
                   "我以前这么干过一次 感觉可不好受 所以我排除这个选项")
    assert hits == [], f"句中 so→所以 不该报，实际: {hits}"


# ── 3. 英文无对应来源时照报（真阳性）──
def test_well_to_raner_is_flagged():
    # S06E04 #386：Well 是语气词，译成「然而」是转折义误加
    hits = _formal("Well, Jamie and John were absent from the workshop all morning,",
                   "然而 杰米和约翰一整个上午 都不在修车房")
    assert len(hits) == 1, f"应报 1 条，实际: {hits}"
    assert "然而" in hits[0]["detail"], hits[0]["detail"]
    assert hits[0]["confidence"] == "high", \
        f"有英文字段来源对照的应标 high，实际 {hits[0]['confidence']}"


# ── 4. 有来源正则的词，英文对上了就不报 ──
def test_matching_source_suppresses_but():
    hits = _formal("But it's not what he wants.", "然而这不是他想要的")
    assert hits == [], f"but→然而 有英文字段来源，不该报，实际: {hits}"


# ── 5. 无英文字面对应物 → 报但标 medium（#527 空动词「进行」）──
def test_empty_verb_jinxing_flagged_medium():
    hits = _formal("Jamie and Roy have now had a more considered look at it.",
                   "杰米和罗伊现在 对它进行了更仔细的查看")
    assert len(hits) == 1, f"应报 1 条，实际: {hits}"
    assert "进行" in hits[0]["detail"], hits[0]["detail"]
    assert hits[0]["confidence"] == "medium", \
        f"无英文字面对应物应标 medium，实际 {hits[0]['confidence']}"


# ── 6. 中文没这个词，英文有对应源也不报 ──
def test_no_formal_word_no_hit():
    hits = _formal("So we go there.", "那我们去那儿")
    assert hits == [], f"中文不含黑名单词，不该报，实际: {hits}"


# ── 7. 每个黑名单词都有明确的来源口径（None 或正则）──
def test_formal_words_is_dict():
    from check_fluency import FORMAL_WORDS
    import re
    assert isinstance(FORMAL_WORDS, dict), "FORMAL_WORDS 应为 dict（词 → 英文来源正则）"
    for w, pat in FORMAL_WORDS.items():
        assert pat is None or isinstance(pat, str), f"{w} 的来源应为 None 或正则串"
        if isinstance(pat, str):
            re.compile(pat)  # 必须能编译


# ── 8. 一集级回归：So 短语全部不报，只留真阳性 ──
def test_batch_so_lines_all_clean():
    from check_fluency import check_line
    so_lines = [
        ("So I'm gonna go and visit them and find out how they do it.",
         "所以我要去拜访他们 看看他们是怎么做的"),
        ("Okay. So I've had bikes since I was 17,", "好的 所以我从17岁起 就开始骑摩托车了"),
        ("So if you've cracked your bumper,", "所以如果你的保险杠裂了"),
        ("I think so. So spicing up the events that we already do,",
         "我觉得行 所以把我们这里 已经办的活动搞得更有声有色"),
        ("So Operation Diversicog starts here.", "所以「小齿轮多元化行动」就从这里开始"),
    ]
    bad = []
    for en, zh in so_lines:
        hits = [h for h in check_line(en, zh) if h["rule"] == "书面语残留"]
        if hits:
            bad.append((en, hits))
    assert not bad, f"这些 So→所以 的忠实直译不该命中: {bad}"


if __name__ == "__main__":
    print("=" * 70)
    print("check_fluency 书面语规则回归测试 (issue #7)")
    print("=" * 70)
    test("F1 So→所以 忠实直译不报", test_so_to_suoyi_is_not_flagged)
    test("F2 句中 so→所以 不报", test_midsentence_so_not_flagged)
    test("F3 Well→然而 无来源照报(high)", test_well_to_raner_is_flagged)
    test("F4 but→然而 有来源不报", test_matching_source_suppresses_but)
    test("F5 空动词「进行」报但标 medium", test_empty_verb_jinxing_flagged_medium)
    test("F6 中文无黑名单词不报", test_no_formal_word_no_hit)
    test("F7 FORMAL_WORDS 结构合法", test_formal_words_is_dict)
    test("F8 一集级 So 短语全清", test_batch_so_lines_all_clean)
    print()
    print(f"  通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
