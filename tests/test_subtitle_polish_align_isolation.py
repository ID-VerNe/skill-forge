# -*- coding: utf-8 -*-
"""回归测试：align_audit 离群点的孤立/连续判别 —— issue #29。

#29 的背景：forced-aligner 在单字锚定时偶发把词锚到别处，产出孤立单行的
巨大假 delta（实测 −15.25 s）。离群剔除本身是对的，但报告只给数字，用户
很容易当成「字幕严重错轴」去逐条返修，反而把对的改坏。

要求（本次落地）：
  - 孤立离群标 `isolation=isolated` / `outlier_kind=aligner_noise_candidate`，
    只给「可能为对齐器单字噪声、建议抽查音频」的提示；
  - 连续多行离群标 `clustered` / `real_step_candidate`，更像真实阶跃；
  - 判别不参与剔除，keep 集合与 PASS/FAIL 必须和旧口径一致。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_align_isolation.py
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

from lib import align_core as ac          # noqa: E402

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


def _pairs(n=300, span=2691.0, base=0.15):
    step = span / (n - 1)
    return [(i * step, base, i) for i in range(n)]


def _with_outliers(pairs, rows, delta):
    out = list(pairs)
    for r in rows:
        t, _d, idx = out[r]
        out[r] = (t, delta, idx)
    return out


# ---------------------------------------------------------------- 判别

def test_isolated_outlier_is_noise_candidate():
    """孤立单行大 delta -> isolated / aligner_noise_candidate。"""
    pairs = _with_outliers(_pairs(), [70], -15.10)
    _keep, info = ac.robust_reject(pairs)
    assert info["dropped"] == 1, info["dropped"]
    r = info["rejected"][0]
    assert r["isolation"] == "isolated", r
    assert r["outlier_kind"] == ac.OUTLIER_NOISE, r
    assert info["isolation_counts"]["isolated"] == 1, info["isolation_counts"]
    assert info["kind_counts"][ac.OUTLIER_NOISE] == 1, info["kind_counts"]


def test_consecutive_outliers_are_real_step():
    """连续 6 行离群 -> clustered / real_step_candidate。"""
    pairs = _with_outliers(_pairs(), range(100, 106), -3.0)
    _keep, info = ac.robust_reject(pairs)
    assert info["dropped"] == 6, info["dropped"]
    assert all(r["isolation"] == "clustered" for r in info["rejected"]), info["rejected"]
    assert all(r["outlier_kind"] == ac.OUTLIER_STEP for r in info["rejected"]), \
        info["rejected"]
    assert info["isolation_counts"]["clustered"] == 6, info["isolation_counts"]
    assert info["kind_counts"][ac.OUTLIER_STEP] == 6, info["kind_counts"]


def test_edge_outlier_unclassified():
    """首/末锚点缺一侧邻点 -> edge / unclassified，不硬判。"""
    pairs = _with_outliers(_pairs(), [0], -15.10)
    _keep, info = ac.robust_reject(pairs)
    r = info["rejected"][0]
    assert r["isolation"] == "edge", r
    assert r["outlier_kind"] == ac.OUTLIER_UNKNOWN, r


# ---------------------------------------------------------------- 判定不变

def test_single_outlier_does_not_change_verdict():
    """单条离群被剔除后，极差与 PASS 结论与干净数据完全一致。"""
    clean = _pairs()
    dirty = _with_outliers(clean, [70], -15.10)
    s_clean = ac.summarize(clean, window=180.0, tol=0.5)
    s_dirty = ac.summarize(dirty, window=180.0, tol=0.5)
    assert s_clean["verdict"] == "PASS", s_clean["verdict"]
    assert s_dirty["verdict"] == "PASS", s_dirty
    assert s_dirty["reject"]["dropped"] == 1, s_dirty["reject"]["dropped"]
    assert abs(s_dirty["window_span"] - s_clean["window_span"]) < 1e-9, \
        (s_clean["window_span"], s_dirty["window_span"])
    # 干净数据无离群；脏数据只少掉那一条，其余锚点全部保留
    assert s_clean["reject"]["dropped"] == 0, s_clean["reject"]["dropped"]
    assert s_dirty["n_keep"] == s_clean["n_keep"] - 1, \
        (s_clean["n_keep"], s_dirty["n_keep"])


def test_table_has_hint_and_kind():
    """终端表要带字段与提示，且明说「不自动重转写」。"""
    pairs = _with_outliers(_pairs(), [70], -15.10)
    _keep, info = ac.robust_reject(pairs)
    lines = ac.format_reject_table(info)
    text = "\n".join(lines)
    assert "isolated" in text, text
    assert ac.OUTLIER_NOISE in text, text
    assert "建议抽查对应音频确认" in text, text
    assert "不自动执行" in text, text
    assert "一定是错轴" in text, "提示里必须明确否定「一定是错轴」的结论"


# ---------------------------------------------------------------- 端到端

def _srt_ts(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return ("%02d:%02d:%06.3f" % (h, m, s)).replace(".", ",")


def _write_fixture(d):
    """300 行 SRT + 词级时间戳：第 70 行 delta = −15.10 s。"""
    n = 300
    step = 2691.0 / (n - 1)
    blocks, toks = [], []
    for i in range(n):
        st = i * step
        en = st + 4.5
        blocks.append("%d\n%s --> %s\nline %d\n" % (i + 1, _srt_ts(st), _srt_ts(en), i))
        delta = -15.10 if i == 70 else 0.15
        toks.append([round(st + delta, 3), round(st + delta + 0.4, 3), "line %d" % i])
    sub = os.path.join(d, "E01.srt")
    with open(sub, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    words = os.path.join(d, "words.json")
    with open(words, "w", encoding="utf-8") as f:
        json.dump(toks, f)
    return sub, words


def test_cli_json_and_report_fields():
    d = tempfile.mkdtemp()
    try:
        sub, words = _write_fixture(d)
        jp = os.path.join(d, "audit.json")
        rp = os.path.join(d, "report.md")
        p = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "align_audit.py"),
             "--sub", sub, "--asr-words", words,
             "--json", jp, "--report", rp, "--no-strict"],
            capture_output=True, text=True)
        out = (p.stdout or "") + (p.stderr or "")
        assert p.returncode == 0, out[-800:]
        payload = json.load(open(jp, encoding="utf-8"))
        rej = payload["stats"]["reject"]
        assert rej["dropped"] == 1, rej
        r = rej["rejected"][0]
        assert r["isolation"] == "isolated", r
        assert r["outlier_kind"] == ac.OUTLIER_NOISE, r
        assert rej["isolation_counts"]["isolated"] == 1, rej["isolation_counts"]
        # 判定口径不受提示影响
        assert payload["verdict"] == "PASS", payload["verdict"]
        assert payload["curve"] is None, payload["curve"]
        # 报告里也要能直接引用字段
        md = open(rp, encoding="utf-8").read()
        assert "outlier_kind" in md, md[-1200:]
        assert ac.OUTLIER_NOISE in md, md[-1200:]
        assert "建议抽查对应音频确认" in md, md[-1200:]
        assert "PASS" in md, md[-1200:]
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("align_audit 离群点孤立/连续判别 回归测试 (issue #29)")
    print("=" * 70)
    test("I1 孤立离群 -> noise 候选", test_isolated_outlier_is_noise_candidate)
    test("I2 连续多行离群 -> real 阶跃", test_consecutive_outliers_are_real_step)
    test("I3 首/末离群 -> edge/unclassified", test_edge_outlier_unclassified)
    test("I4 单条离群不改变总判定", test_single_outlier_does_not_change_verdict)
    test("I5 终端表带字段与提示语义", test_table_has_hint_and_kind)
    test("I6 CLI JSON/报告字段端到端", test_cli_json_and_report_fields)
    print()
    print("  通过 %d / 失败 %d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)
