"""双源交叉校验（issue #30 建议 2 C 部分）。

锁四件事：
  1. 两源逐行不一致 → `dual_source_mismatch`（只提示）；一致 → 计入 high-confidence。
  2. 单源缺覆盖不算冲突，单列计数。
  3. 双源校验不改变时间轴 `stats` / `verdict` / `pairs`，也不改 ASS/SRT 文件。
  4. 当前环境的真实边界：qwen 是强制对齐器，不能独立转录；测试用合成 fixture
     注入两源，不冒充「真实双引擎端到端验证」。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_asr_cross.py
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

from lib import asr_cross as xc  # noqa: E402

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


def _srt(path, n=12):
    lines = []
    for i in range(n):
        s, e = i * 2, i * 2 + 2
        lines.append("%d\n00:00:%02d,000 --> 00:00:%02d,000\nword%02d here\n"
                     % (i + 1, s, e, i + 1))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _tokens(n=12, bad_row=None, bad_text="wordXX"):
    out = []
    for i in range(n):
        text = "word%02d" % (i + 1)
        if bad_row is not None and i == bad_row:
            text = bad_text
        out.append([i * 2 + 0.1, i * 2 + 0.9, text])
        out.append([i * 2 + 0.95, i * 2 + 1.9, "here"])
    return out


def t_mismatch_only_hint():
    rows = [(i * 2, i * 2 + 2, "word%02d here" % (i + 1)) for i in range(12)]
    r = xc.compare(rows, _tokens(), _tokens(bad_row=2, bad_text="wordZZ"),
                   label_a="a", label_b="b")
    assert r["n_agree"] == 11, r
    assert r["n_mismatch"] == 1, r
    m = r["mismatches"][0]
    assert m["srt_id"] == 3, m
    assert m["text_a"] == "word03 here", m
    assert m["text_b"] == "wordZZ here", m
    assert r["real_dual_engine"] is False, "不许把接线说成真实双引擎"
    assert "不自动改写" in r["note"], r["note"]


def t_uncovered_not_conflict():
    rows = [(0, 2, "alpha"), (2, 4, "beta")]
    # 源 B 只有第一行的词，第二行没覆盖 → 不算 mismatch。
    r = xc.compare(rows, [[0.1, 1.9, "alpha"], [2.1, 3.9, "beta"]],
                   [[0.1, 1.9, "alpha"]], label_a="a", label_b="b")
    assert r["n_agree"] == 1, r
    assert r["n_mismatch"] == 0, r
    assert r["n_uncovered"] == 1, r


def t_render_says_only_hint():
    rows = [(0, 2, "alpha")]
    r = xc.compare(rows, [[0.1, 1.9, "alpha"]], [[0.1, 1.9, "omega"]],
                   label_a="a", label_b="b")
    text = "\n".join(xc.render_section(r))
    assert "仅提示，不参与 PASS/FAIL" in text, text
    assert "不自动改写英文轨" in text, text
    assert "真实双引擎" in text or "未做真实双引擎" in text, text


def t_align_audit_verdict_unchanged():
    """同一份词级缓存，加不加第二源，stats/verdict/pairs 必须完全一致。"""
    root = tempfile.mkdtemp(prefix="sp-cross-")
    try:
        srt = os.path.join(root, "e01.srt")
        a = os.path.join(root, "a.json")
        b = os.path.join(root, "b.json")
        out1 = os.path.join(root, "out1.json")
        out2 = os.path.join(root, "out2.json")
        rep = os.path.join(root, "out2.md")
        _srt(srt)
        with open(a, "w", encoding="utf-8") as f:
            json.dump(_tokens(), f)
        with open(b, "w", encoding="utf-8") as f:
            json.dump(_tokens(bad_row=2, bad_text="wordZZ"), f)

        script = os.path.join(SCRIPTS, "align_audit.py")
        base = [sys.executable, script, "--sub", srt, "--asr-words", a,
                "--json", out1, "--no-strict"]
        p1 = subprocess.run(base, capture_output=True, text=True, encoding="utf-8")
        assert p1.returncode == 0, p1.stderr + p1.stdout
        p2 = subprocess.run([sys.executable, script, "--sub", srt,
                            "--asr-words", a, "--asr-words-b", b,
                            "--json", out2, "--report", rep, "--no-strict"],
                            capture_output=True, text=True, encoding="utf-8")
        assert p2.returncode == 0, p2.stderr + p2.stdout

        with open(out1, encoding="utf-8") as f:
            j1 = json.load(f)
        with open(out2, encoding="utf-8") as f:
            j2 = json.load(f)
        for key in ("stats", "pairs", "verdict", "reject", "curve", "curve_base"):
            assert j1[key] == j2[key], f"{key} 被双源校验改动了"
        assert j1["dual_source"] is None, j1["dual_source"]
        assert j2["dual_source"]["n_mismatch"] == 1, j2["dual_source"]
        with open(rep, encoding="utf-8") as f:
            md = f.read()
        assert "双源交叉校验（仅提示" in md, md[-3000:]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_does_not_touch_subtitles():
    root = tempfile.mkdtemp(prefix="sp-cross-hash-")
    try:
        srt = os.path.join(root, "e01.srt")
        a = os.path.join(root, "a.json")
        b = os.path.join(root, "b.json")
        out = os.path.join(root, "out.json")
        _srt(srt)
        with open(a, "w", encoding="utf-8") as f:
            json.dump(_tokens(), f)
        with open(b, "w", encoding="utf-8") as f:
            json.dump(_tokens(bad_row=2, bad_text="wordZZ"), f)
        before = sha(srt)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "align_audit.py"),
                            "--sub", srt, "--asr-words", a, "--asr-words-b", b,
                            "--json", out, "--no-strict"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr + p.stdout
        assert sha(srt) == before, "双源校验改了字幕文件"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_round_seed_consumer_wired():
    tmpl = os.path.join(SKILL_ROOT, "prompts", "audit.tmpl")
    with open(tmpl, encoding="utf-8") as f:
        text = f.read()
    assert "{spelling_seeds}" in text, "第 6 类轮次没有英文侧提示段"
    assert "dual_source_mismatch" in text, "双源不一致没接到第 6 类轮次"
    assert "不得据此自动改写英文轨" in text, "模板没写明只提示不改写"


if __name__ == "__main__":
    print("双源交叉校验（合成 fixture，不代表真实双引擎验证）")
    test("两源不一致只标提示", t_mismatch_only_hint)
    test("单源缺覆盖不算冲突", t_uncovered_not_conflict)
    test("报告写明仅提示", t_render_says_only_hint)
    test("时间轴判定不被双源改动", t_align_audit_verdict_unchanged)
    test("不改字幕文件", t_does_not_touch_subtitles)
    test("第 6 类轮次已接线", t_round_seed_consumer_wired)
    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
