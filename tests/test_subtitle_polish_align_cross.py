# -*- coding: utf-8 -*-
"""双对齐器时间戳互证（issue #30 建议 3 / C 部分）。

锁五件事：
  1. 同一份文本、两个对齐器给出接近的时间戳 → `corroborated`；
  2. 时间戳/偏移结论明显偏离 → `divergent`，且报告明确提示；
  3. 只有一路可用 → `single_source`，**不冒充双证**；
  4. 互证不改变时间轴 `stats` / `verdict` / `pairs` / `curve`，也不改 ASS/SRT 文件；
  5. 比的是**时间戳**不是文本：文本不同但时间戳一致，仍应 corroborated。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_align_cross.py
"""
from __future__ import annotations

import hashlib
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

from lib import align_cross as xc  # noqa: E402
from lib import credential as cred  # noqa: E402
from lib import verdict as V  # noqa: E402
import round_orchestrator as ro  # noqa: E402

PASS = FAIL = 0


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


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def _rows(n=12):
    return [(i * 2, i * 2 + 2, "word%02d here" % (i + 1)) for i in range(n)]


def _tokens(n=12, shift=0.1, text_fn=None):
    out = []
    for i in range(n):
        text = text_fn(i) if text_fn else "word%02d" % (i + 1)
        out.append([i * 2 + shift, i * 2 + shift + 0.8, text])
        out.append([i * 2 + shift + 0.9, i * 2 + 1.9, "here"])
    return out


def _write_srt(path, n=12):
    lines = []
    for i in range(n):
        s, e = i * 2, i * 2 + 2
        lines.append("%d\n00:00:%02d,000 --> 00:00:%02d,000\nword%02d here\n"
                     % (i + 1, s, e, i + 1))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_ass(path, n=12):
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for i in range(n):
        ev.append("Dialogue: 0,0:00:%02d.00,0:00:%02d.00,英文,,0,0,0,,word%02d here"
                  % (i * 2, i * 2 + 2, i + 1))
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")


def t_corroborated():
    rows = _rows()
    a, b = _tokens(shift=0.1), _tokens(shift=0.2)
    r = xc.compare(rows, a, b, label_a="qwen", label_b="whisperx")
    assert r["status"] == "corroborated", r
    assert r["n_compared"] == 12, r
    assert r["timestamp_delta"]["median"] <= xc.THRESHOLDS["ts_median_s"], r
    assert r["verdict_agree"] is True, r
    text = "\n".join(xc.render_section(r))
    assert "corroborated" in text, text


def t_divergent_and_report():
    rows = _rows()
    a = _tokens(shift=0.1)
    b = _tokens(shift=2.6)          # 整体晚 2.5 s：结论明显不同
    r = xc.compare(rows, a, b, label_a="qwen", label_b="whisperx")
    assert r["status"] == "divergent", r
    assert r["offset_diff"] > xc.THRESHOLDS["offset_diff_s"], r
    assert r["timestamp_delta"]["median"] > xc.THRESHOLDS["ts_median_s"], r
    text = "\n".join(xc.render_section(r))
    assert "divergent" in text, text
    assert "未获双对齐器印证" in xc.confidence_label(r), xc.confidence_label(r)
    assert "单源 PASS 不能直接放行" in text, text


def t_single_source_not_claiming():
    rows = _rows()
    a = _tokens(shift=0.1)
    b = _tokens(n=3, shift=0.2)     # 第二路只有 3 个锚点
    r = xc.compare(rows, a, b, label_a="qwen", label_b="whisperx")
    assert r["status"] == "single_source", r
    assert "不冒充双证" in r["reason"], r["reason"]
    assert xc.confidence_label(r).startswith("单路对齐"), xc.confidence_label(r)


def t_no_data():
    rows = _rows()
    r = xc.compare(rows, _tokens(n=3), [], label_a="qwen", label_b="whisperx")
    assert r["status"] == "no_data", r


def t_sanitize():
    toks = [[0, 0, "SPEAKER02"], [0, 24.0, "This"],
            [1.0, 1.2, "ok"], [1.4, 1.1, "bad"]]
    kept, st = xc.sanitize(toks)
    assert [t[2] for t in kept] == ["ok"], kept
    assert st["n_speaker"] == 1 and st["n_span_out"] == 1 and st["n_negative"] == 1, st


def t_row_start_uses_token_start():
    """跨行超长 token 不能把下一行起点拖到自己身上。"""
    rows = [(0, 5, "a"), (10, 13, "b")]
    toks = [(4.9, 10.5, "a"), (10.6, 12.0, "b")]
    starts = xc.row_starts(rows, toks)
    assert starts[0] == 4.9, starts
    assert starts[1] == 10.6, starts


def t_text_not_primary():
    rows = _rows()
    a = _tokens(shift=0.1)
    b = _tokens(shift=0.2, text_fn=lambda i: "wordZZ%02d" % (i + 1))
    # 两路的单源结论显式给出且一致；文本全不一致时仍应按**时间戳**互证
    sa = {"n_pairs": 12, "median": 0.1, "slope": 0.0, "window_span": 0.0,
          "verdict": "PASS", "ok": True}
    sb = {"n_pairs": 12, "median": 0.2, "slope": 0.0, "window_span": 0.0,
          "verdict": "PASS", "ok": True}
    r = xc.compare(rows, a, b, stats_a=sa, stats_b=sb)
    assert r["text_sanity"]["n_diff"] == 12, r["text_sanity"]
    assert r["status"] == "corroborated", r


def t_stats_dicts_untouched():
    rows = _rows()
    a, b = _tokens(shift=0.1), _tokens(shift=2.6)
    sa, sb = {"n_pairs": 12, "median": 0.1, "slope": 0.0, "window_span": 0.0,
              "verdict": "PASS", "ok": True}, \
             {"n_pairs": 12, "median": 2.6, "slope": 0.0, "window_span": 0.0,
              "verdict": "PASS", "ok": True}
    before_a, before_b = dict(sa), dict(sb)
    xc.compare(rows, a, b, stats_a=sa, stats_b=sb)
    assert sa == before_a and sb == before_b, "互证改动了调用方的 stats"


def t_align_audit_verdict_unchanged():
    """同一份词级缓存，加不加第二路，stats/verdict/pairs/curve 必须完全一致。"""
    root = tempfile.mkdtemp(prefix="sp-dual-")
    try:
        srt = os.path.join(root, "e01.srt")
        a = os.path.join(root, "a.json")
        b = os.path.join(root, "b.json")
        out1 = os.path.join(root, "out1.json")
        out2 = os.path.join(root, "out2.json")
        rep = os.path.join(root, "out2.md")
        dup = os.path.join(root, "dual.json")
        _write_srt(srt)
        with open(a, "w", encoding="utf-8") as f:
            json.dump(_tokens(shift=0.1), f)
        with open(b, "w", encoding="utf-8") as f:
            json.dump(_tokens(shift=2.6), f)

        script = os.path.join(SCRIPTS, "align_audit.py")
        base = [sys.executable, script, "--sub", srt, "--asr-words", a,
                "--json", out1, "--no-strict"]
        p1 = subprocess.run(base, capture_output=True, text=True, encoding="utf-8")
        assert p1.returncode == 0, p1.stderr + p1.stdout
        p2 = subprocess.run([sys.executable, script, "--sub", srt,
                            "--asr-words", a, "--asr-words-b", b,
                            "--json", out2, "--report", rep,
                            "--dual-aligner-json", dup, "--no-strict"],
                            capture_output=True, text=True, encoding="utf-8")
        assert p2.returncode == 0, p2.stderr + p2.stdout

        with open(out1, encoding="utf-8") as f:
            j1 = json.load(f)
        with open(out2, encoding="utf-8") as f:
            j2 = json.load(f)
        for key in ("stats", "pairs", "verdict", "reject", "curve", "curve_base"):
            assert j1[key] == j2[key], f"{key} 被双对齐器互证改动了"
        assert j1["dual_aligner"] is None, j1["dual_aligner"]
        assert j2["dual_aligner"]["status"] == "divergent", j2["dual_aligner"]
        assert j2["dual_aligner"]["not_transcription"] is True, j2["dual_aligner"]
        with open(rep, encoding="utf-8") as f:
            md = f.read()
        assert "双对齐器时间戳互证" in md, md[-3000:]
        assert "divergent" in md, md[-3000:]
        assert "不参与 PASS/FAIL" in md, md[-3000:]
        with open(dup, encoding="utf-8") as f:
            dj = json.load(f)
        assert dj["status"] == "divergent", dj
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_ass_hash_unchanged():
    root = tempfile.mkdtemp(prefix="sp-dual-ass-")
    try:
        ass = os.path.join(root, "e01.ass")
        a = os.path.join(root, "a.json")
        b = os.path.join(root, "b.json")
        out = os.path.join(root, "out.json")
        _write_ass(ass)
        with open(a, "w", encoding="utf-8") as f:
            json.dump(_tokens(shift=0.1), f)
        with open(b, "w", encoding="utf-8") as f:
            json.dump(_tokens(shift=0.2), f)
        before = sha(ass)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "align_audit.py"),
                            "--sub", ass, "--asr-words", a, "--asr-words-b", b,
                            "--json", out, "--no-strict"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr + p.stdout
        assert sha(ass) == before, "双对齐器互证改了 ASS 文件"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_credential_and_round_wiring():
    root = tempfile.mkdtemp(prefix="sp-dual-cred-")
    try:
        srt = os.path.join(root, "e01.srt")
        _write_srt(srt)
        stats = {"n_pairs": 12, "mad": 0.0, "drift": 0.0, "window_span": 0.0,
                 "tol": 0.3, "verdict": "PASS", "ok": True}
        dual = xc.compare(_rows(), _tokens(shift=0.1), _tokens(shift=2.6))
        data = cred.build(srt, stats, "qwen3-forced-aligner", dual=dual)
        assert data["axis"]["confidence"]["status"] == "divergent", data["axis"]
        cred.save(srt, data)
        res = cred.check(srt)
        assert res["verdict"] == V.PASS, res
        assert res["detail"]["axis_confidence"]["status"] == "divergent", res
        suffix = ro._confidence_suffix({"status": "divergent", "reason": "r"})
        assert "未获双对齐器印证" in suffix, suffix
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    print("双对齐器时间戳互证（合成 fixture）")
    test("两路一致 → corroborated", t_corroborated)
    test("两路偏离 → divergent + 报告提示", t_divergent_and_report)
    test("单路 → single_source 不冒充双证", t_single_source_not_claiming)
    test("两路都不足 → no_data", t_no_data)
    test("token 清洗：说话人/超长/反向", t_sanitize)
    test("行起点按 token 起点归行", t_row_start_uses_token_start)
    test("文本不同但时间戳一致仍互证", t_text_not_primary)
    test("互证不改调用方 stats", t_stats_dicts_untouched)
    test("时间轴判定不被双对齐器改动", t_align_audit_verdict_unchanged)
    test("不改 ASS 文件", t_ass_hash_unchanged)
    test("凭据与总账接线", t_credential_and_round_wiring)
    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
