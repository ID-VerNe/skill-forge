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
  P2 两边都空但容差外有行 -> PAIRING_OUT_OF_TOLERANCE(off=…),不能是 ZH_MISSING
  P3 两边都空且附近没行   -> PAIRING_FAILED
  P4 音效块               -> 一个 pairing 标记都不打
  P5 门禁按「未配上」算,两种形态都算进分子
  P6 门禁在写盘之前 abort,不留下半份切片

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


def t_p2_out_of_tolerance(tmp):
    paired = _pair(tmp)
    p = [x for x in paired if x.srt_id == 3][0]
    assert "ZH_MISSING" not in p.anomalies, (
        f"srt 3 在 ASS 里有完整中英对照,不能报漏译:{p.anomalies}")
    oot = [a for a in p.anomalies if a.startswith("PAIRING_OUT_OF_TOLERANCE")]
    assert oot, f"srt 3 应报 PAIRING_OUT_OF_TOLERANCE,实得 {p.anomalies}"
    # 偏移量必须带出来,否则读的人只知道「超了」不知道「超多少」
    m = re.search(r"off=([+-]?[\d.]+)s", oot[0])
    assert m, f"标记里没有 off 值:{oot[0]}"
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

def main():
    print("=" * 70)
    print("配对异常标记三形态回归测试 (issue v1.15 · A1)")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="pairtag_")
    try:
        test("P1 有英文无中文 -> ZH_MISSING", lambda: t_p1_missing_translation(tmp))
        test("P2 超容差 -> PAIRING_OUT_OF_TOLERANCE 且带 off", lambda: t_p2_out_of_tolerance(tmp))
        test("P3 附近无行 -> PAIRING_FAILED", lambda: t_p3_pairing_failed(tmp))
        test("P4 音效块不打配对标记", lambda: t_p4_sound_effect_not_flagged(tmp))
        test("P5 门禁分子含两种形态", lambda: t_p5_gate_counts_both_shapes(tmp))
        test("P6 门禁在写盘前 abort", lambda: t_p6_gate_before_write(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print(f"通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
