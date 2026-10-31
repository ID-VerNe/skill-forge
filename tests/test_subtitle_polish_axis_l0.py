# -*- coding: utf-8 -*-
"""回归测试：轴归属判定 + L0 结构哨兵 —— issue #11 / #12。

#11 旧实现是 `min(mad)`。排序问题永远有答案，于是四条流全是 0.62 时它照样
宣布「最贴合的是 s1.us」，0.220 vs 0.240 也判得出赢家（whisper 的 MAD 噪声带
就是 0.15~0.25）。拿错轴的后果不是「没修好」，是**把对的改坏**。

#12 任何时间检查都要模型（whisper 分钟级 / qwen 十几分钟），而最致命的错
往往是结构性、秒级就能看出来的。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_axis_l0.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from lib import axis as ax                   # noqa: E402
from lib import verdict as V                 # noqa: E402
import precheck_timeline as pt               # noqa: E402

PASS = 0
FAIL = 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
    except AssertionError as e:
        FAIL += 1
        print("  [FAIL] %s\n         %s" % (name, e))
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print("  [ERR ] %s\n         %s: %s" % (name, type(e).__name__, e))
    else:
        PASS += 1
        print("  [ ok ] %s" % name)


def cand(label, mad, ok=True, n=700):
    return {"label": label, "mad": mad, "ok": ok, "n_pairs": n}


# ---------------------------------------------------------------- A 判定

def test_resolved():
    r = ax.adjudicate([cand("s0.uk", 0.22), cand("s1.us", 0.62)])
    assert r["verdict"] == "RESOLVED", r
    assert r["chosen"] == "s0.uk"
    assert r["code"] == V.PASS
    assert r["margin"] >= r["margin_need"], r


def test_ambiguous_by_absolute_margin():
    """0.22 vs 0.24 在 whisper 噪声带内，不该判出赢家。"""
    r = ax.adjudicate([cand("a", 0.22), cand("b", 0.245, n=690)])
    assert r["verdict"] == "AMBIGUOUS", r
    assert r["chosen"] is None, "AMBIGUOUS 不许给 chosen，给了就会被照着用"
    assert r["code"] == V.AMBIGUOUS


def test_ambiguous_by_relative_margin():
    """0.60 vs 0.72：绝对差 0.12 过得了 0.10，但相对只差 20%，不该算判出来。"""
    r = ax.adjudicate([cand("a", 0.60), cand("b", 0.72, n=690)])
    assert r["verdict"] == "AMBIGUOUS", r


def test_no_candidate():
    """四条全错 —— min() 会挑一个，判定必须说「没有」。"""
    r = ax.adjudicate([cand("a", 0.62, ok=False), cand("b", 0.66, ok=False)])
    assert r["verdict"] == "NO_CANDIDATE", r
    assert r["chosen"] is None
    assert r["code"] == V.FAIL


def test_single_pass():
    r = ax.adjudicate([cand("only", 0.18)])
    assert r["verdict"] == "SINGLE_PASS", r
    assert r["cross_checked"] is False, "单候选必须标明没过交叉验证"
    assert r["code"] == V.PASS


def test_family_merge():
    """s0.uk 与 s2.uk.sdh 的 MAD、锚点数逐位相同 —— 它们不是两个选项。"""
    r = ax.adjudicate([cand("s0.uk", 0.22), cand("s2.uk.sdh", 0.221),
                       cand("s1.us", 0.62), cand("s3.us.sdh", 0.62)])
    assert len(r["families"]) == 2, r["families"]
    assert sorted(r["families"][0]) == ["s0.uk", "s2.uk.sdh"], r["families"]
    assert r["verdict"] == "RESOLVED" and r["chosen"] == "s0.uk", r


def test_family_not_merged_when_counts_differ():
    """MAD 接近但锚点数差很多，说明不是同一条轴的两个变体。"""
    r = ax.adjudicate([cand("a", 0.22, n=700), cand("b", 0.225, n=420)])
    assert len(r["families"]) == 2, r["families"]


def test_parse_stream_tag():
    t = ax.parse_stream_tag("S06E01.s2.uk.sdh.srt")
    assert t["index"] == 2 and t["family"] == "UK" and t["sdh"] is True, t
    t2 = ax.parse_stream_tag("S06E01.s1.us.srt")
    assert t2["index"] == 1 and t2["family"] == "US", t2
    t3 = ax.parse_stream_tag("S06E01.ass")
    assert t3["family"] == "unknown" and t3["index"] is None, t3


# ---------------------------------------------------------------- B 端到端

def _ts(sec):
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return "%02d:%02d:%06.3f" % (h, m, s)


def _write_srt(path, n=300, span=2700.0, shift=0.0):
    lines = []
    step = span / (n - 1)
    for i in range(n):
        t = i * step
        d = shift(i, t) if callable(shift) else shift
        lines.append("%d\n%s --> %s\nw%dx y%d z%d\n"
                     % (i + 1, _ts(t + d), _ts(t + d + step * 0.8), i, i, i))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def _run(script, args):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + args,
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _step_shift(base=0.15, every=600.0, jump=0.45):
    """分段阶跃：与 E01 的 US 流同形（每 10 分钟 +0.45s），不是常数偏移。

    常数偏移的 delta 是平的，分时段极差判据看不出——这是判据的设计（只看
    平坦度），所以构造「错轴」样本必须用阶跃，不能用平移。
    """
    def f(i, t):
        return base + jump * int(t // every)
    return f


def test_axis_end_to_end():
    d = tempfile.mkdtemp()
    try:
        a = _write_srt(os.path.join(d, "S06E01.s0.uk.srt"), shift=0.15)
        b = _write_srt(os.path.join(d, "S06E01.s1.us.srt"), shift=_step_shift())
        c = _write_srt(os.path.join(d, "S06E01.s2.uk.sdh.srt"), shift=0.15)
        d2 = _write_srt(os.path.join(d, "S06E01.s3.us.sdh.srt"), shift=_step_shift())
        # 词时间戳取自「真相」：行起点 +0.15
        from lib import align_core as ac
        rows = ac.load_rows(a, None)
        words = []
        for i, row in enumerate(rows):
            base = row[0] + 0.15
            for k, w in enumerate(("w%dx" % i, "y%d" % i, "z%d" % i)):
                words.append([round(base + k * 0.15, 3),
                              round(base + k * 0.15 + 0.12, 3), w])
        wp = os.path.join(d, "w.json")
        json.dump(words, open(wp, "w", encoding="utf-8"))

        jp = os.path.join(d, "out.json")
        code, out = _run("align_audit.py", [
            "--sub", a, "--asr-words", wp, "--json", jp,
            "--compare", b, "--compare", c, "--compare", d2,
            "--write-credential", "--credential-target", "chosen"])
        data = json.load(open(jp, encoding="utf-8"))
        res = data["axis"]
        assert res["verdict"] == "RESOLVED", (res, out[-800:])
        assert res["chosen"] == "S06E01.s0.uk.srt", res
        assert len(res["families"]) == 2, res["families"]
        assert code == 0, "RESOLVED 应 exit 0，实际 %s\n%s" % (code, out[-500:])

        # 凭据落在胜者旁边，source 自动反解
        cred_p = os.path.join(d, "S06E01.ts.json")
        assert os.path.exists(cred_p), os.listdir(d)
        cr = json.load(open(cred_p, encoding="utf-8"))
        assert cr["source"]["index"] == 0 and cr["source"]["family"] == "UK", cr["source"]
        assert cr["axis"]["cross_checked"] is True, cr["axis"]
    finally:
        shutil.rmtree(d)


def test_axis_wrong_primary_fails_but_points_to_right_one():
    """--sub 给错了那条：主文件自己 FAIL(2)，但输出必须指向该用的那条。"""
    d = tempfile.mkdtemp()
    try:
        a = _write_srt(os.path.join(d, "S06E01.s0.uk.srt"), shift=0.15)
        b = _write_srt(os.path.join(d, "S06E01.s1.us.srt"), shift=_step_shift())
        from lib import align_core as ac
        rows = ac.load_rows(a, None)
        words = []
        for i, row in enumerate(rows):
            base = row[0] + 0.15
            for k, w in enumerate(("w%dx" % i, "y%d" % i, "z%d" % i)):
                words.append([round(base + k * 0.15, 3),
                              round(base + k * 0.15 + 0.12, 3), w])
        wp = os.path.join(d, "w.json")
        json.dump(words, open(wp, "w", encoding="utf-8"))

        jp = os.path.join(d, "out.json")
        code, out = _run("align_audit.py", [
            "--sub", b, "--asr-words", wp, "--json", jp, "--compare", a])
        assert code == 2, "主文件错轴应 exit 2，实际 %s" % code
        assert "应当使用" in out, out[-600:]
        assert json.load(open(jp, encoding="utf-8"))["axis"]["chosen"] == "S06E01.s0.uk.srt"
    finally:
        shutil.rmtree(d)


# ---------------------------------------------------------------- C L0

def _rows(n=760, span=2700.0, start=1.0, end_pad=0.0):
    step = span / (n - 1)
    return [(start + i * step, start + i * step + step * 0.8 - end_pad, "x")
            for i in range(n)]


def test_l0_normal():
    r = pt.analyse(_rows(), duration=2712.4, baseline=16.9, tail=False)
    assert r["verdict"] == "PASS", r["items"]


def test_l0_last_beyond_duration():
    rows = _rows()
    rows[-1] = (rows[-1][0] + 200, rows[-1][1] + 200, "x")
    r = pt.analyse(rows, duration=2712.4)
    assert r["verdict"] == "SUSPECT", r["items"]
    assert any("超出片长" in m for _t, m, _s in r["items"]), r["items"]


def test_l0_negative_first():
    rows = _rows()
    rows[0] = (-3.0, 1.0, "x")
    r = pt.analyse(rows, duration=2712.4)
    assert r["verdict"] == "SUSPECT", r["items"]
    assert any("负" in m for _t, m, _s in r["items"]), r["items"]


def test_l0_tail_gap_needs_voice():
    """尾部缺口只有在「那段还有对白」时才算问题。

    这条是本 issue 里最要紧的一个反例：用「末条/片长」反解 fps 的做法在
    正常片子上也会命中（实测 0.9688 vs 0.9590，落在容差内），而真按它乘
    1.0427，整片会被推 110 秒。改成可验证的判据后，静音片尾不再误报。
    """
    rows = _rows(span=2400.0)          # 末条 2401，片长 2712 → 缺口 311s
    r_bad = pt.analyse(rows, duration=2712.4, tail=True)
    assert r_bad["verdict"] == "SUSPECT", r_bad["items"]
    assert any("片尾仍有对白" in m for _t, m, _s in r_bad["items"]), r_bad["items"]

    r_ok = pt.analyse(rows, duration=2712.4, tail=False)
    assert r_ok["verdict"] == "PASS", r_ok["items"]

    r_unknown = pt.analyse(rows, duration=2712.4, tail=None)
    assert r_unknown["verdict"] == "PASS", "没验片尾时不该阻断"
    assert any("给 --media" in m for _t, m, _s in r_unknown["items"]), r_unknown["items"]


def test_l0_no_duration_is_unverified():
    r = pt.analyse(_rows(), duration=None)
    assert r["verdict"] == "UNVERIFIED", r
    assert r["code"] == V.UNVERIFIED


def test_l0_density_anomaly():
    r = pt.analyse(_rows(n=40, span=2600.0), duration=2712.4,
                   baseline=16.9, tail=False)
    assert r["verdict"] == "SUSPECT", r["items"]
    assert any(t == "密度" and "基线" in m and _s == "SUSPECT"
               for t, m, _s in r["items"]), r["items"]


def test_l0_cli_exit():
    d = tempfile.mkdtemp()
    try:
        p = _write_srt(os.path.join(d, "E01.srt"), n=300)
        code, out = _run("precheck_timeline.py", [p, "--duration", "2712.4"])
        assert code == 0, out[-500:]
        code, out = _run("precheck_timeline.py", [p])
        assert code == 3, "无片长应 UNVERIFIED(3)，实际 %s\n%s" % (code, out[-400:])
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("轴归属判定 + L0 结构哨兵 回归测试 (issue #11 / #12)")
    print("=" * 70)
    test("A1 明显赢家 -> RESOLVED", test_resolved)
    test("A2 绝对裕度不足 -> AMBIGUOUS", test_ambiguous_by_absolute_margin)
    test("A3 相对裕度不足 -> AMBIGUOUS", test_ambiguous_by_relative_margin)
    test("A4 全错 -> NO_CANDIDATE", test_no_candidate)
    test("A5 单候选 -> SINGLE_PASS(cross_checked=false)", test_single_pass)
    test("A6 同族合并", test_family_merge)
    test("A7 锚点数不同不合并", test_family_not_merged_when_counts_differ)
    test("A8 文件名反解流信息", test_parse_stream_tag)
    test("B1 端到端判轴 + 凭据落点", test_axis_end_to_end)
    test("B2 --sub 给错也指得对", test_axis_wrong_primary_fails_but_points_to_right_one)
    test("C1 L0 正常样本", test_l0_normal)
    test("C2 末条超出片长", test_l0_last_beyond_duration)
    test("C3 首条为负", test_l0_negative_first)
    test("C4 尾部缺口要看有没有对白", test_l0_tail_gap_needs_voice)
    test("C5 无片长 -> UNVERIFIED", test_l0_no_duration_is_unverified)
    test("C6 密度异常", test_l0_density_anomaly)
    test("C7 L0 CLI 退出码", test_l0_cli_exit)
    print()
    print("  通过 %d / 失败 %d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)
