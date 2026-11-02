# -*- coding: utf-8 -*-
"""回归测试:配对异常标记必须区分「漏译 / 轴错位 / 真缺内容」三种形态。

实测背景(issue v1.15 · A1):
S06E02 的 R5 p1 读到 38 行空单元格,据此报出 38 条「漏译」,重跑后归零。
它没有幻觉——是 `ass_srt_pair.py` 把「有英文无中文」和「两边都没配上」
打成了同一个 `SRT_HAS_ASS_NONE`,而 `pipeline-spec.md` 又把含义写成
「漏译/丢行」,等于二次确认了错误语义。

第一版修正把它们拆成 `ZH_MISSING` / `PAIRING_FAILED` 两个名字,**还不够**:
实测 S06E02 全片 869 块里被标「配对失败」的 47 条,逐条回查 ASS
**全部都有完整中英对照**——它们是 srt 与 ass 起点差 0.50~1.92 s、
超出 ±0.5 s 容差窗,一条真缺失都没有。

于是本文件锁住三件事:

  P1 有英文无中文         -> ZH_MISSING,不能是别的
  P2 两边都空但容差外有行 -> notes 里 BOUNDARY_OFFSET(off=…),不能是 ZH_MISSING
  P3 两边都空且附近没行   -> PAIRING_FAILED
  P4 音效块               -> 一个 pairing 标记都不打
  P5 门禁按「未配上」算,两种形态都算进分子
  P6 门禁在写盘之前 abort,不留下半份切片
  P7 BOUNDARY_OFFSET 只进 notes,不进 anomalies(分级,issue #24)

关于 P2 的期望值为什么从 PAIRING_OUT_OF_TOLERANCE 改成 BOUNDARY_OFFSET
────────────────────────────────────────────────────────────────────
建本文件时(issue v1.15)ass_srt_pair 只有三形态,靠「两边都空 + 起点差超容差」
来认超容差块。后来为 S06E02 的断句点分歧打了 index_align 补丁,`pair()` 新增
`_monotonic_fallback()`(LCS 锚点 + 顺序映射):凡是顺序和文本都对得上、只是行
边界不同的块,现在会被**真的配上**,不再落进「两边都空」。于是判别段多出第四
形态:

  PAIRING_OUT_OF_TOLERANCE  两边都空、容差外有行 —— 轴有问题,要先校轴
  BOUNDARY_OFFSET           配上了、但起点差超容差 —— 行边界/剪辑点分歧,轴没问题
  PAIRING_FAILED            两边都空、附近根本没行 —— 素材不同版
  ZH_MISSING                有英文无中文

夹具里 srt 3@10.0 对 ASS@11.2、两边文本一致,补丁后会走顺序映射配上,所以它
现在属于 BOUNDARY_OFFSET 而不是 PAIRING_OUT_OF_TOLERANCE。这个改动**不是给实现
让路**:BOUNDARY_OFFSET 的含义更精确(「配上了、轴没毛病、只是切点不同」),若仍
报成「超容差」,审计员会去校轴,而校轴解决不了断句点分歧。三形态在「两边都空」
这条路径上仍然完整保留,P3/P5 仍然锁着它们。

关于 P7:为什么光有 P2 还不够
────────────────────────────
P2 原本查的是 `pb.anomalies`,v1.16 改查 `pb.notes`。**这不是「换个地方找同一个
东西」,而是分级本身被改了**:BOUNDARY_OFFSET 从「要处理的问题」降为「仅需知情
的信息」,标识符名字保持不变(v1.15 裁决:只降级不改名)。

依据是实测数量级差:S06E02 上它出现 **495 次**,而真正的配对失败是 **0 次**。
混在同一个字段里,任何「有 anomalies 就 abort / 人工复核」的规则都会在 S06E02
上每次都全量阻断——等于变相让 727 个**已经配上**的块一起 abort。

P7 因此是**双向**断言:notes 里必须有、anomalies 里必须没有。只写前一半的话,
一个手滑同时往两个列表 append 的实现照样能过。


跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_pairing_tags.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from lib import ass_srt_pair as ap  # noqa: E402

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
# 夹具:最小 ASS / SRT,不依赖真实字幕文件
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


def _ass(start, end, style, text):
    return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}\n"


def _srt(blocks):
    """blocks: [(idx, 'HH:MM:SS,mmm', 'HH:MM:SS,mmm', text)]"""
    out = []
    for i, st, en, tx in blocks:
        out.append(f"{i}\n{st} --> {en}\n{tx}\n")
    return "\n".join(out)


def make_case(tmp):
    """三块 srt,分别命中三种形态。返回 (ass_path, srt_path)。

    srt 1 @ 0:00:01.00  英文 ass 在 1.00,中文在 1.00          -> 正常
    srt 2 @ 0:00:05.00  英文 ass 在 5.00,中文行被删掉         -> ZH_MISSING
    srt 3 @ 0:00:10.00  ass 起点在 11.20(差 +1.20s,超容差)   -> OUT_OF_TOLERANCE
    srt 4 @ 0:05:00.00  ass 附近什么都没有                     -> PAIRING_FAILED
    """
    ass = ASS_HEADER
    ass += _ass("0:00:01.00", "0:00:02.00", "英文", "Hello there.")
    ass += _ass("0:00:01.00", "0:00:02.00", "中文", "你好。")
    # srt 2:只有英文,中文行缺失
    ass += _ass("0:00:05.00", "0:00:06.00", "英文", "This is fine.")
    # srt 3:中英都在,但整体晚了 1.20 s(容差 0.5 s 之外)
    ass += _ass("0:00:11.20", "0:00:12.20", "英文", "Out of tolerance.")
    ass += _ass("0:00:11.20", "0:00:12.20", "中文", "超出容差。")

    srt = _srt([
        (1, "00:00:01,000", "00:00:02,000", "Hello there."),
        (2, "00:00:05,000", "00:00:06,000", "This is fine."),
        (3, "00:00:10,000", "00:00:11,000", "Out of tolerance."),
        (4, "00:05:00,000", "00:05:01,000", "Nothing here at all."),
    ])

    a = os.path.join(tmp, "case.ass")
    s = os.path.join(tmp, "case.srt")
    with open(a, "w", encoding="utf-8") as f:
        f.write(ass)
    with open(s, "w", encoding="utf-8") as f:
        f.write(srt)
    return a, s


def _pair(tmp):
    a, s = make_case(tmp)
    return ap.pair(ap.parse_ass(a), ap.parse_srt(s))[0]


def _tags(pb):
    """该块命中的「要处理的」配对标记。

    只查 anomalies、**故意不查 notes**:notes 里的 BOUNDARY_OFFSET 不是问题,
    把它算进来会让 P1/P4 这类「不该有任何配对问题」的断言失去意义。
    """
    return [x for x in pb.anomalies if x.startswith("PAIRING")
            or x == "ZH_MISSING"]


# ─────────────────────────────────────────────────────────────
# P1~P4:三形态判别
# ─────────────────────────────────────────────────────────────

def t_p1_missing_translation(tmp):
    paired = _pair(tmp)
    p = [x for x in paired if x.srt_id == 2][0]
    assert "ZH_MISSING" in p.anomalies, f"srt 2 应有 ZH_MISSING,实得 {p.anomalies}"
    assert not _tags(p)[1:], f"漏译不该带 pairing 标记:{p.anomalies}"


def t_p2_boundary_offset(tmp):
    """两边文本对得上、只是起点差 1.20s(超 ±0.5s 容差)。

    期望 BOUNDARY_OFFSET 而不是 PAIRING_OUT_OF_TOLERANCE:index_align 补丁的顺序
    映射会把它**配上**,「两边都空」的前提已不成立。详见文件头 P2 说明。

    ⚠️ 从 v1.16 起 BOUNDARY_OFFSET 记在 `pb.notes` 而不是 `pb.anomalies`
    (issue #24 / bug #8)。本测试查的是 notes——不是「换个地方找同一个东西」,
    而是锁住分级本身:它**不该**出现在 anomalies 里。见 P7。
    """
    paired = _pair(tmp)
    p = [x for x in paired if x.srt_id == 3][0]
    assert "ZH_MISSING" not in p.anomalies, (
        f"srt 3 在 ASS 里有完整中英对照,不能报漏译:{p.anomalies}")
    # 顺序映射配上之后不该再报「未配上」——这是本次改动最要紧的一条:
    # 配上却报未配上,门禁会拿假数据 abort 整轮。
    assert not [a for a in p.anomalies if a.startswith("PAIRING_FAILED")], (
        f"srt 3 已被顺序映射配上,不该报未配上:{p.anomalies}")
    off_tags = [a for a in p.notes if a.startswith("BOUNDARY_OFFSET")]
    assert off_tags, f"srt 3 的 notes 应有 BOUNDARY_OFFSET,实得 notes={p.notes}"
    # 偏移量必须带出来,否则读的人只知道「有分歧」不知道「差多少」
    m = re.search(r"off=([+-]?[\d.]+)s", off_tags[0])
    assert m, f"标记里没有 off 值:{off_tags[0]}"
    off = float(m.group(1))
    assert abs(off - 1.20) < 0.02, f"偏移应为 +1.20s,实得 {off}"


def t_p3_pairing_failed(tmp):
    paired = _pair(tmp)
    p = [x for x in paired if x.srt_id == 4][0]
    assert "ZH_MISSING" not in p.anomalies, (
        f"srt 4 英文也没有,不能报漏译:{p.anomalies}")
    assert not [a for a in p.anomalies if a.startswith("PAIRING_OUT_OF_TOLERANCE")], (
        f"srt 4 附近 5 分钟无任何 ass 行,不该算超容差:{p.anomalies}")
    hard = [a for a in p.anomalies if a.startswith("PAIRING_FAILED")]
    assert hard, f"srt 4 应报 PAIRING_FAILED,实得 {p.anomalies}"


def t_p4_sound_effect_not_flagged(tmp):
    """纯音效块两边都空是正常的,不该打 pairing 标记。"""
    ass = ASS_HEADER + _ass("0:00:01.00", "0:00:02.00", "英文", "[ENGINE REVS]")
    srt = _srt([(1, "00:00:03,000", "00:00:04,000", "[ENGINE REVS]")])
    a = os.path.join(tmp, "sfx.ass")
    s = os.path.join(tmp, "sfx.srt")
    open(a, "w", encoding="utf-8").write(ass)
    open(s, "w", encoding="utf-8").write(srt)
    paired = ap.pair(ap.parse_ass(a), ap.parse_srt(s))[0]
    p = paired[0]
    bad = [x for x in p.anomalies if x.startswith("PAIRING") or x == "ZH_MISSING"]
    assert not bad, f"音效块不该被标配对异常:{p.anomalies}"


# ─────────────────────────────────────────────────────────────
# P5~P6:门禁
# ─────────────────────────────────────────────────────────────

class _PB:
    def __init__(self, sid, tag):
        self.srt_id = sid
        self.anomalies = [tag] if tag else []


def t_p5_gate_counts_both_shapes(tmp):
    """门禁的分子必须包含两种形态。只统计 PAIRING_FAILED 等于形同虚设——
    S06E02 那 47 条全是超容差,一条 PAIRING_FAILED 都没有。"""
    import extract_slice as es
    oot = "PAIRING_OUT_OF_TOLERANCE(off=+1.20s)"
    paired = [_PB(i, None) for i in range(10)]
    paired[1].anomalies = [oot]
    paired[2].anomalies = [oot]
    paired[3].anomalies = ["PAIRING_FAILED(srt_id=3)"]
    ids = es.pairing_failed_ids(paired)
    assert sorted(ids) == [1, 2, 3], f"应统计到 3 条未配上,实得 {ids}"
    # 只算真缺失时必须只剩 1 条
    hard_only = es.pairing_failed_ids(paired, tags="PAIRING_FAILED")
    assert hard_only == [3], f"按形态筛应只剩 [3],实得 {hard_only}"
    # 3/10 = 30% > 10% 必须 abort
    try:
        es.assert_pairing_ok(paired, "x.ass", "x.srt", label="t")
    except SystemExit:
        pass
    else:
        raise AssertionError("未配上 30% 竟然没 abort")


def t_p6_gate_before_write(tmp):
    """门禁必须在建目录之前。写出去再检查,坏切片已经在下一道工序手上了。"""
    # 12 块里 6 块超容差(50%),非空率同样会低——但这里只看目录有没有被建出来
    ass = ASS_HEADER
    srt_blocks = []
    for i in range(1, 13):
        st = i * 10
        # ass 全部挪到 +3s(超容差),srt 留在原位
        ass += _ass("0:%02d:%02d.00" % (st // 60, st % 60 + 3), "", "英文", "x")
        ass = ass.replace(",0:02:03.00,", ",0:02:04.00,")  # 修掉空 end
        srt_blocks.append((i, "00:%02d:%02d,000" % (st // 60, st % 60),
                           "00:%02d:%02d,000" % (st // 60, st % 60 + 1),
                           f"line {i}"))
    a = os.path.join(tmp, "g.ass")
    s = os.path.join(tmp, "g.srt")
    open(a, "w", encoding="utf-8").write(ass)
    open(s, "w", encoding="utf-8").write(_srt(srt_blocks))
    out = os.path.join(tmp, "slices_should_not_exist")
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "extract_slice.py"),
                        a, s, "--out", out],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode != 0, "坏素材竟然切成功了"
    assert not os.path.exists(out), (
        f"门禁 abort 了却已经把目录建出来:{os.listdir(out) if os.path.exists(out) else ''}")


# ─────────────────────────────────────────────────────────────
# P7:分级(issue #24 / bug #8)
# ─────────────────────────────────────────────────────────────

def t_p7_boundary_offset_is_info_not_problem(tmp):
    """BOUNDARY_OFFSET 必须是 info,不能进 anomalies。

    ## 为什么这条要单独锁

    它是本文件里唯一「断言某个标记**不存在**于 anomalies」的测试。
    P2 只能证明「标志出现在 notes 里」——但一个手滑同时往两个列表里 append
    的实现照样能过 P2,而后果是致命的:S06E02 实测 BOUNDARY_OFFSET 495 次、
    真失败 0 次,同时进 anomalies 就等于「有 anomalies 就 abort」的规则
    每次都全量阻断。

    所以这里**双向**锁死:notes 里必须有,anomalies 里必须没有。
    只改分级不改名是 v1.15 的明确裁决,标识符本身保持 BOUNDARY_OFFSET。
    """
    paired = _pair(tmp)
    p = [x for x in paired if x.srt_id == 3][0]
    assert [a for a in p.notes if a.startswith("BOUNDARY_OFFSET")], (
        f"srt 3 的 notes 里应有 BOUNDARY_OFFSET,实得 notes={p.notes}")
    leaked = [a for a in p.anomalies if a.startswith("BOUNDARY_OFFSET")]
    assert not leaked, (
        f"BOUNDARY_OFFSET 混进了 anomalies:{leaked}。"
        f"它不是要处理的事——S06E02 上它出现 495 次、真失败 0 次,"
        f"进 anomalies 会让门禁每次都全量阻断。")
    # 反向保险:真问题仍然必须在 anomalies 里,别把整个 anomalies 清空了事
    p1 = [x for x in paired if x.srt_id == 2][0]
    assert "ZH_MISSING" in p1.anomalies, (
        f"srt 2 的 ZH_MISSING 被误降级了:{p1.anomalies}")
    p3 = [x for x in paired if x.srt_id == 4][0]
    assert [a for a in p3.anomalies if a.startswith("PAIRING_FAILED")], (
        f"srt 4 的 PAIRING_FAILED 被误降级了:{p3.anomalies}")


# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("配对异常标记回归测试 (issue v1.15 · A1 三形态 + index_align 第四形态)")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="pairtag_")
    try:
        test("P1 有英文无中文 -> ZH_MISSING", lambda: t_p1_missing_translation(tmp))
        test("P2 起点差超容差 -> notes 带 BOUNDARY_OFFSET 与 off", lambda: t_p2_boundary_offset(tmp))
        test("P3 附近无行 -> PAIRING_FAILED", lambda: t_p3_pairing_failed(tmp))
        test("P4 音效块不打配对标记", lambda: t_p4_sound_effect_not_flagged(tmp))
        test("P5 门禁分子含两种形态", lambda: t_p5_gate_counts_both_shapes(tmp))
        test("P6 门禁在写盘前 abort", lambda: t_p6_gate_before_write(tmp))
        test("P7 BOUNDARY_OFFSET 只进 notes 不进 anomalies",
             lambda: t_p7_boundary_offset_is_info_not_problem(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print(f"通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
