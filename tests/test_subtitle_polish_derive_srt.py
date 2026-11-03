# -*- coding: utf-8 -*-
"""回归测试:无独立 SRT 源时从 ASS 英文轨派生 SRT（issue #26）。

场景：用户手上的字幕没有独立 .srt，ASS 里的 `英文` 轨本身就是 whisper
转录的权威英文。旧版 SKILL.md 写死「无 SRT 源 = 拒绝运行」，逼用户手工
拆 ASS 英文轨（时间格式/序号/BOM 都容易出错）。

本文件锁住四件事：

  D1 正常派生          -> SRT 块数与 ASS 英文轨逐行对应，只含英文
  D2 时间格式与序号    -> HH:MM:SS,CCC、序号从 1 连续、可被 parse_srt 回读
  D3 无英文轨          -> 报错清晰（退出码非 0 + 指明「没有英文轨」）
  D4 已提供 srt        -> 不重复派生，也不在 .subtitle-polish/derived 留文件
  D5 管线自动派生      -> extract_slice 省略 srt 时自动派生并正常切片
  D6 可复现            -> 同一 ASS 派生两次逐字节相同
  D7 显式关闭          -> --no-derive-srt 时无 SRT 源直接拒绝
  D8 不改原文件/不进成品 -> ASS md5 不变，派生物只在工作目录

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_derive_srt.py
"""
from __future__ import annotations

import hashlib
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
from lib.time_fmt import srt_to_seconds  # noqa: E402

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


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 注释,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass(start, end, style, text):
    return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}\n"


def make_ass(tmp, name="ep.ass", with_english=True):
    """最小双语 ASS：三句英文 + 对应中文 + 一条注释。

    时间刻意跨过 1 小时，并带厘秒，用来验 SRT 的 3 位毫秒与补零。
    """
    ass = ASS_HEADER
    if with_english:
        ass += _ass("0:00:01.00", "0:00:03.00", "英文", "Hello there.")
        ass += _ass("0:00:05.50", "0:00:07.40", "英文", "This is a car.")
        ass += _ass("1:02:03.45", "1:02:05.10", "英文", "The engine revs.")
    # 中文/注释轨始终存在：派生物绝不该带上它们
    ass += _ass("0:00:01.00", "0:00:03.00", "中文", "你好。")
    ass += _ass("0:00:05.50", "0:00:07.40", "中文", "这是一辆车。")
    ass += _ass("1:02:03.45", "1:02:05.10", "中文", "引擎轰鸣。")
    ass += _ass("0:00:09.00", "0:00:10.00", "注释", "（旁白）")
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(ass)
    return p


def _md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _run(args, cwd):
    return subprocess.run([sys.executable] + args, cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")


def _parse_srt_text(text):
    """不落盘地解析 SRT 文本（复用 parse_srt 的规则，写入临时文件）。"""
    tmp = tempfile.mkdtemp(prefix="derivesrt_parse_")
    try:
        p = os.path.join(tmp, "x.srt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return ap.parse_srt(p)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────

def t_d1_normal_derive(tmp):
    ass = make_ass(tmp)
    out = os.path.join(tmp, "derived", "ep.srt")
    n = ap.derive_srt_from_ass(ass, out)
    assert n == 3, f"英文轨 3 行应派生 3 块，实得 {n}"
    text = _read(out)
    assert "你好" not in text and "引擎轰鸣" not in text and "旁白" not in text, (
        "派生物混进了中文/注释轨")
    blocks = _parse_srt_text(text)
    assert len(blocks) == 3, f"回读应得 3 块，实得 {len(blocks)}"
    assert blocks[0].text == "Hello there."
    assert blocks[1].text == "This is a car."
    assert blocks[2].text == "The engine revs."


def t_d2_time_and_index(tmp):
    ass = make_ass(tmp)
    out = os.path.join(tmp, "derived", "ep.srt")
    ap.derive_srt_from_ass(ass, out)
    text = _read(out)
    lines = text.split("\n")
    # 序号从 1 连续
    indices = [lines[i] for i in range(0, len(lines), 4)]
    assert indices == ["1", "2", "3"], f"序号应连续 1..3，实得 {indices}"
    # 时间格式 HH:MM:SS,CCC
    pat = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$")
    ts_lines = [lines[i] for i in range(1, len(lines), 4)]
    for ln in ts_lines:
        assert pat.match(ln), f"时间行格式不对: {ln}"
    assert ts_lines[0] == "00:00:01,000 --> 00:00:03,000"
    # ASS 0:00:05.50 -> 00:00:05,500；1:02:03.45 -> 01:02:03,450
    assert ts_lines[1] == "00:00:05,500 --> 00:00:07,400"
    assert ts_lines[2] == "01:02:03,450 --> 01:02:05,100"
    blocks = _parse_srt_text(text)
    assert abs(blocks[2].start - (3600 + 123.45)) < 0.001, (
        f"跨小时起点回读错误: {blocks[2].start}")


def t_d3_no_english_clear_error(tmp):
    ass = make_ass(tmp, name="zh_only.ass", with_english=False)
    out = os.path.join(tmp, "derived", "zh_only.srt")
    try:
        ap.derive_srt_from_ass(ass, out)
    except SystemExit as e:
        msg = str(e)
        assert "没有英文轨" in msg, f"函数报错未指明原因: {msg}"
    else:
        raise AssertionError("无英文轨竟然派生成功了")
    p = _run([os.path.join(SCRIPTS, "derive_srt.py"), ass], cwd=tmp)
    assert p.returncode != 0, f"CLI 无英文轨应失败，退出码={p.returncode}"
    combined = (p.stdout or "") + (p.stderr or "")
    assert "没有英文轨" in combined, f"CLI 报错不清晰: {combined}"


def t_d4_provided_srt_no_derive(tmp):
    ass = make_ass(tmp)
    # 用户提供一份手工 SRT
    srt = os.path.join(tmp, "ep.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n"
                "2\n00:00:05,500 --> 00:00:07,400\nThis is a car.\n\n"
                "3\n01:02:03,450 --> 01:02:05,100\nThe engine revs.\n\n")
    p = _run([os.path.join(SCRIPTS, "extract_slice.py"), ass, srt,
              "--out", ".subtitle-polish/slices"], cwd=tmp)
    assert p.returncode == 0, f"给了 srt 却失败: {p.stdout}\n{p.stderr}"
    derived = os.path.join(tmp, ".subtitle-polish", "derived")
    assert not os.path.exists(derived), (
        f"已提供 srt 却仍派生了：{os.listdir(derived) if os.path.exists(derived) else ''}")


def t_d5_pipeline_auto_derive(tmp):
    ass = make_ass(tmp)
    p = _run([os.path.join(SCRIPTS, "extract_slice.py"), ass,
              "--out", ".subtitle-polish/slices"], cwd=tmp)
    assert p.returncode == 0, f"自动派生切片失败: {p.stdout}\n{p.stderr}"
    out = os.path.join(tmp, ".subtitle-polish", "derived", "ep.srt")
    assert os.path.exists(out), "未生成 .subtitle-polish/derived/ep.srt"
    assert "派生 3 块" in p.stdout, f"stdout 未报派生块数: {p.stdout}"
    slices = os.path.join(tmp, ".subtitle-polish", "slices")
    assert os.path.isdir(slices), "切片目录未生成"
    assert [f for f in os.listdir(slices) if f.endswith(".txt")], "没有切片文件"


def t_d6_reproducible(tmp):
    ass = make_ass(tmp)
    a = os.path.join(tmp, "d1.srt")
    b = os.path.join(tmp, "d2.srt")
    ap.derive_srt_from_ass(ass, a)
    ap.derive_srt_from_ass(ass, b)
    assert _md5(a) == _md5(b), "同一 ASS 两次派生结果不一致"
    assert not _read(a).startswith("\ufeff"), "派生物不应带 BOM"


def t_d7_no_derive_switch(tmp):
    ass = make_ass(tmp)
    p = _run([os.path.join(SCRIPTS, "extract_slice.py"), ass,
              "--no-derive-srt", "--out", ".subtitle-polish/slices"], cwd=tmp)
    assert p.returncode != 0, f"--no-derive-srt 无 srt 应拒绝，实际成功: {p.stdout}"
    combined = (p.stdout or "") + (p.stderr or "")
    assert "--no-derive-srt" in combined and "未提供 SRT" in combined, (
        f"关闭派生的报错不清晰: {combined}")
    assert not os.path.exists(os.path.join(tmp, ".subtitle-polish", "derived"))


def t_d8_no_mutation_no_product(tmp):
    ass = make_ass(tmp)
    before = _md5(ass)
    out = os.path.join(tmp, ".subtitle-polish", "derived", "ep.srt")
    ap.derive_srt_from_ass(ass, out)
    assert _md5(ass) == before, "派生改动了 ASS 原文件"
    assert os.path.dirname(out).lower().replace("\\", "/").endswith(
        ".subtitle-polish/derived"), f"派生物不在工作目录: {out}"
    assert os.path.basename(out) == "ep.srt", "派生物命名应沿用 ASS stem"


# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("无独立 SRT 源：从 ASS 英文轨派生 SRT (issue #26)")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="derivesrt_")

    def case(name):
        """每个用例独立子目录，避免上一个用例的 .subtitle-polish 干扰下一个。"""
        p = os.path.join(tmp, name)
        os.makedirs(p, exist_ok=True)
        return p

    try:
        test("D1 正常派生：逐行对应且不含中英文混轨",
             lambda: t_d1_normal_derive(case("d1")))
        test("D2 时间格式 HH:MM:SS,CCC 与序号 1..N",
             lambda: t_d2_time_and_index(case("d2")))
        test("D3 无英文轨时报错清晰", lambda: t_d3_no_english_clear_error(case("d3")))
        test("D4 已提供 srt 时不重复派生", lambda: t_d4_provided_srt_no_derive(case("d4")))
        test("D5 extract_slice 省略 srt 时自动派生",
             lambda: t_d5_pipeline_auto_derive(case("d5")))
        test("D6 派生可复现（逐字节相同、无 BOM）", lambda: t_d6_reproducible(case("d6")))
        test("D7 --no-derive-srt 显式关闭派生", lambda: t_d7_no_derive_switch(case("d7")))
        test("D8 不改 ASS、派生物只在工作目录", lambda: t_d8_no_mutation_no_product(case("d8")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print(f"通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
