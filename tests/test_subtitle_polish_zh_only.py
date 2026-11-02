# -*- coding: utf-8 -*-
"""回归测试:纯中字素材(无英文轨)上 index_align 必须能建成映射。

## 为什么要单开一个文件

`apply_fixes._build_index_alignment()` 上一版写死了 `pb.lines["英文"]`。
`pb.lines` 是 `ass_srt_pair.pair()` 动态建出来的 `{轨道名: [行]}`:有哪条轨
就**只有**哪个 key。素材没有英文轨时 `.get("英文")` 恒返回 `None`,于是
`out` 为空,调用方直接 `RuntimeError: index_align 构建失败` —— **整批 abort,
一集都跑不了**。这不是性能问题,是可用性问题:用户拿纯中字素材来,工具当场拒绝服务。

## 实测依据(测试 agent 报告 bug #5)

它在 `修车房测试核对` 下扫了全部 82 个 `.ass`/`.srt`,**没有一条纯中字无英文轨
的素材**(全是 `*.eng.*` 双语带英文轨),所以这条一直是「代码级推断 + 无样本可
验证」。本文件用**夹具**补上这个缺口:不依赖外部素材,直接构造纯中文轨的
ASS,任何环境都能跑。

真实素材侧的旁证(手工一次性验证,不进本测试):
把 `S06E02.eng.ass` 的英文轨摘掉后 `pair()` 产出 `lines` 的 key 只剩 `['中文']`,
869 块照样 869 块配上 —— 说明 `pair()` 本身没问题,写死的是 `apply_fixes` 那侧。

## 锁住的四件事

  Z1 纯中字素材不抛 RuntimeError,映射能建出来
  Z2 映射**逐块覆盖**全部 srt 块(869 块的缩小版:5 块全中)
  Z3 锚点取中文轨自己的起点,不是时间窗猜出来的
  Z4 双语素材上行为不变(回归对照,防止修 Z1 把正常路径改坏)

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_zh_only.py
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

from lib.ass_srt_pair import parse_ass, parse_srt  # noqa: E402
import apply_fixes as af  # noqa: E402

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
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        FAIL += 1
    else:
        print(f"  [PASS] {name}")
        PASS += 1


# ─────────────────────────────────────────────────────────────
# 夹具:同一份字幕内容,分别产出「纯中字」与「双语」两个 ASS
# ─────────────────────────────────────────────────────────────

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# (srt 起点秒, ASS 起点秒, 英文, 中文)。
#
# ## 偏移量为什么不取大值（实测得出的夹具约束）
#
# 本测试第一版把偏移设成 +1.4 / +3.2 / +5.8 秒，结果 `pair()` 只配上 2/5 块
# （`PAIRING_OUT_OF_TOLERANCE(off=+1.40s)` 等三条）。**这不是 bug，是纯中字
# 素材的固有约束**：
#
#   `_monotonic_fallback()` 靠「英文行 ↔ SRT 英文块」的文本 LCS 找锚点，再在
#   锚点之间按顺序一一对应。纯中字素材**没有英文轨**，文本相似度锚点全失，
#   兜底只能退回时间窗 —— 也就是 `TIME_TOLERANCE`(±0.5s)。偏移超过 0.5s 的块
#   在纯中字素材上**本来就配不上**，如实报 `PAIRING_OUT_OF_TOLERANCE` 是对的。
#
# 所以夹具的偏移一律放在容差内。这样测的才是「配上了之后，锚点能不能取到
# 中文轨」——这正是 bug #5 的范围。**把偏移调大来「凑 5/5」是错的**：那等于
# 要求配不上的块也硬配上，与方案甲的「不能无证据地猜」相抵触。
#
# 同时保留一个**容差外**的块（第 5 条，+3.2s），断言它如实报「未配上」而
# 不是被静默算成一对 —— 这条防的是「修 bug #5 时顺手放宽定位」。
CASES = [
    (1.00,  1.10, "Hello there.", "你好。"),
    (5.00,  5.10, "This is fine.", "这样挺好。"),
    (9.00,  9.20, "Out of tolerance.", "超出容差。"),
    (14.00, 14.05, "Almost the same.", "几乎一样。"),
]
# 容差外、配不上的块：单独列出来，只断言「不崩 + 如实报未配上」。
OUT_OF_TOLERANCE = (20.00, 25.80, "Way off in time.", "时间差得远。")


def _tc(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _srt_tc(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_zh_only(tmp):
    """只有中文轨,没有英文轨。SRT 仍是英文(原文),这符合真实工作流。"""
    ass = ASS_HEADER
    for srt_s, ass_s, _en, zh in CASES + [OUT_OF_TOLERANCE]:
        ass += (f"Dialogue: 0,{_tc(ass_s)},{_tc(ass_s + 1.5)},中文,,0,0,0,,{zh}\n")
    a = os.path.join(tmp, "zh_only.ass")
    with open(a, "w", encoding="utf-8") as f:
        f.write(ass)
    return a, _write_srt(tmp, "zh_only.srt")


def make_bilingual(tmp):
    """双语对照素材(英中双轨),用于回归对照。"""
    ass = ASS_HEADER
    for srt_s, ass_s, en, zh in CASES + [OUT_OF_TOLERANCE]:
        ass += (f"Dialogue: 0,{_tc(ass_s)},{_tc(ass_s + 1.5)},英文,,0,0,0,,{en}\n")
        ass += (f"Dialogue: 0,{_tc(ass_s)},{_tc(ass_s + 1.5)},中文,,0,0,0,,{zh}\n")
    a = os.path.join(tmp, "bilingual.ass")
    with open(a, "w", encoding="utf-8") as f:
        f.write(ass)
    return a, _write_srt(tmp, "bilingual.srt")


def _write_srt(tmp, name):
    out = []
    for i, (srt_s, _ass_s, en, _zh) in enumerate(CASES + [OUT_OF_TOLERANCE], 1):
        out.append(f"{i}\n{_srt_tc(srt_s)} --> {_srt_tc(srt_s + 1.5)}\n{en}\n")
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return p


def _index(ass_path, srt_path):
    blocks = parse_srt(srt_path)
    idx = af._build_srt_index(blocks)
    return af._build_index_alignment(ass_path, idx), idx


# ─────────────────────────────────────────────────────────────
# Z1~Z4
# ─────────────────────────────────────────────────────────────

def t_z1_no_runtime_error(tmp):
    """核心回归:纯中字素材不许抛 RuntimeError。

    修之前这里必然 `RuntimeError: index_align 构建失败`,因为
    `_anchor_rows` 的前身写死 `.get("英文")` 拿到 None。
    """
    a, s = make_zh_only(tmp)
    try:
        idx, _ = _index(a, s)
    except RuntimeError as e:
        raise AssertionError(
            f"纯中字素材上 index_align 构建失败(整批 abort 的根因):{e}") from e
    assert idx, "纯中字素材上映射为空 —— 等于没有定位能力"


def t_z2_full_coverage(tmp):
    """容差内的块必须**全部**配上并进映射。

    容差外的那条（OUT_OF_TOLERANCE）不在此列 —— 它配不上是正确行为，
    由 Z5 单独断言。
    """
    a, s = make_zh_only(tmp)
    idx, blocks = _index(a, s)
    want = sorted(range(1, len(CASES) + 1))
    got = sorted(k for k in idx if k <= len(CASES))
    assert got == want, f"映射覆盖不全:期望 {want},实得 {got}"
    # 容差外那条不许混进来冒充配上
    bad = len(CASES) + 1
    assert bad not in idx, (
        f"srt {bad} 起点差 4.8s、超 ±0.5s 容差,纯中字素材上配不上,"
        f"却被写进了映射 {idx[bad]}s —— 这是无证据的猜")


def t_z3_anchor_is_zh_start(tmp):
    """锚点必须等于中文轨自己的起点,不能是 SRT 起点(那是猜的)。

    这一条防的是「修了不崩,但退回去按 SRT 起点凑数」——那样就成了
    `srt_index[sid].start`,在断句点分歧素材上仍是错的。
    """
    a, s = make_zh_only(tmp)
    idx, blocks = _index(a, s)
    for i, (srt_s, ass_s, _en, _zh) in enumerate(CASES, 1):
        got = idx[i]
        assert abs(got - ass_s) < 0.01, (
            f"srt {i} 锚点应为中文轨起点 {ass_s}s,实得 {got}s")
        assert abs(got - srt_s) > 0.01, (
            f"srt {i} 锚点等于 SRT 起点 {srt_s}s —— 这是按序号凑数,不是配对定位")


def t_z4_bilingual_unchanged(tmp):
    """双语素材上锚点仍取英文轨起点(优先级 1),行为不变。

    双轨同起点,数值上中英相等,所以这里同时断言「两种素材的映射完全一致」
    ——纯中字修完后,同一份内容不该因为少了一条英文轨就得到不同的定位。
    """
    a_bi, s_bi = make_bilingual(tmp)
    a_zh, s_zh = make_zh_only(tmp)
    idx_bi, _ = _index(a_bi, s_bi)
    idx_zh, _ = _index(a_zh, s_zh)
    assert idx_bi, "双语素材映射为空"
    for k in range(1, len(CASES) + 1):
        assert k in idx_bi and k in idx_zh, (
            f"srt {k} 缺席:双语={sorted(idx_bi)},纯中字={sorted(idx_zh)}")
        assert abs(idx_bi[k] - idx_zh[k]) < 0.01, (
            f"srt {k} 双语锚点 {idx_bi[k]}s 与纯中字锚点 {idx_zh[k]}s 不一致")

    # 直接验锚点取自哪条轨:双语素材里英文与中文同起点,取谁数值都一样,
    # 所以改用「只有英文轨」的素材把优先级 1 单独钉住。
    a_en, s_en = _make_en_only(tmp)
    idx_en, _ = _index(a_en, s_en)
    assert idx_en, "只有英文轨时映射为空(优先级 1 失效)"
    for i, (_srt_s, ass_s, _en, _zh) in enumerate(CASES, 1):
        assert abs(idx_en[i] - ass_s) < 0.01, (
            f"srt {i} 只有英文轨时锚点应为 {ass_s}s,实得 {idx_en[i]}s")


def t_z5_out_of_tolerance_honest(tmp):
    """容差外的块要如实报「未配上」,不能被静默凑成一对。

    纯中字素材没有英文轨 → 文本锚点全失 → 兜底只能退回 ±0.5s 时间窗。
    偏移 4.8s 的块本来就配不上,如实 `PAIRING_OUT_OF_TOLERANCE` 才是对的。
    这条锁住「修 bug #5 时不要顺手把定位放宽」——那会退化成无证据的猜。
    """
    a, s = make_zh_only(tmp)
    from lib.ass_srt_pair import pair
    paired, _only = pair(parse_ass(a), parse_srt(s))
    bad = len(CASES) + 1
    p = [x for x in paired if x.srt_id == bad]
    assert p, f"配对结果里没有 srt {bad}"
    p = p[0]
    assert not (p.lines or {}), (
        f"srt {bad} 不该配上任何行,实得 {p.lines}")
    assert any(x.startswith("PAIRING_OUT_OF_TOLERANCE") for x in p.anomalies), (
        f"srt {bad} 应报 PAIRING_OUT_OF_TOLERANCE,实得 {p.anomalies}")


def _make_en_only(tmp):
    ass = ASS_HEADER
    for _srt_s, ass_s, en, _zh in CASES:
        ass += (f"Dialogue: 0,{_tc(ass_s)},{_tc(ass_s + 1.5)},英文,,0,0,0,,{en}\n")
    a = os.path.join(tmp, "en_only.ass")
    with open(a, "w", encoding="utf-8") as f:
        f.write(ass)
    return a, _write_srt(tmp, "en_only.srt")


# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("纯中字素材 index_align 回归测试 (issue v1.15 · bug #5)")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="zhonly_")
    try:
        test("Z1 纯中字素材不抛 RuntimeError", lambda: t_z1_no_runtime_error(tmp))
        test("Z2 映射覆盖全部 srt 块", lambda: t_z2_full_coverage(tmp))
        test("Z3 锚点取中文轨起点而非 SRT 起点", lambda: t_z3_anchor_is_zh_start(tmp))
        test("Z4 双语/单轨素材行为一致", lambda: t_z4_bilingual_unchanged(tmp))
        test("Z5 容差外块如实报未配上", lambda: t_z5_out_of_tolerance_honest(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print(f"通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
