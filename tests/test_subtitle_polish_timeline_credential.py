# -*- coding: utf-8 -*-
"""回归测试：时间轴凭据（sidecar）与三态判定 —— issue #9 / #10。

背景：8 集双语字幕走完全流程，verify_fixes 0 失败、cross_check 全绿，交付后
被反馈「所有集都对不上轴」。回头对音频测，E01/E07/E08 偏 +2.44/+2.79/+2.91 秒。
根因不是某个检查写错了，而是「时间轴对不对」这个状态**从未进入流程**。

本测试覆盖两块：

  A. 凭据本身（lib/credential.py）
     - 无凭据 -> UNVERIFIED
     - 片源 sha1 变 -> UNVERIFIED
     - 成品文件内容变 -> UNVERIFIED
     - patched_at > computed_at -> UNVERIFIED（改过没复测）
     - 凭据绑定片源但本次没给 --media -> UNVERIFIED（不能假装验过）
     - fresh PASS -> PASS；fresh FAIL -> FAIL
     - 陈旧性必须排在 verdict 前面（一份写了 PASS 但过期的凭据不能放行）

  B. 脚本退出码
     - align_audit: PASS->0 / FAIL->2 / 无音频->3
     - timeline_gate: 各状态透传，批量取最坏

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_timeline_credential.py
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

from lib import credential as cred          # noqa: E402
from lib import verdict as V                # noqa: E402

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


# ---------------------------------------------------------------- 夹具

def _srt(path, n=60, span=2700.0, shift=None):
    """写一份 n 条的字幕；shift(i, t) 可以是常数或函数。"""
    lines = []
    step = span / (n - 1)
    for i in range(n):
        t = i * step
        d = shift(i, t) if callable(shift) else (shift or 0.0)
        a, b = t + d, t + d + step * 0.8
        lines.append("%d\n%s --> %s\nw%dx y%d z%d\n"
                     % (i + 1, _ts(a), _ts(b), i, i, i))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _ts(sec):
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return "%02d:%02d:%06.3f" % (h, m, s)


def _words(path, rows, shift):
    """词级时间戳：每行 3 个词，首词时间 = 行起点 + delta。"""
    out = []
    for i, row in enumerate(rows):
        st = row[0]
        d = shift(i, st) if callable(shift) else (shift or 0.0)
        base = st + d
        for k, w in enumerate(("w%dx" % i, "y%d" % i, "z%d" % i)):
            out.append([round(base + k * 0.15, 3), round(base + k * 0.15 + 0.12, 3), w])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return path


def _rows(srt):
    from lib import align_core as ac
    return ac.load_rows(srt, None)


def _run(script, args, cwd=None):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + args,
                       capture_output=True, text=True, cwd=cwd)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------- A 凭据

def test_no_credential():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S01E01.srt")
        _srt(srt)
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("无凭据" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_fresh_pass_and_fail():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S01E02.srt")
        _srt(srt)
        ok = {"n_pairs": 60, "mad": 0.10, "drift": 0.02, "window_span": 0.12,
              "tol": 0.3, "ok": True}
        cred.save(srt, cred.build(srt, ok, "qwen"))
        assert cred.check(srt)["verdict"] == V.PASS, cred.check(srt)

        bad = dict(ok, window_span=1.4, ok=False)
        cred.save(srt, cred.build(srt, bad, "qwen"))
        res = cred.check(srt)
        assert res["verdict"] == V.FAIL, res
        assert any("FAIL" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_media_sha_changed():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S01E03.srt")
        media = os.path.join(d, "S01E03.mkv")
        _srt(srt)
        with open(media, "wb") as f:
            f.write(b"A" * 4096)
        ok = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
              "tol": 0.3, "ok": True}
        cred.save(srt, cred.build(srt, ok, "qwen", media=media))
        assert cred.check(srt, media=media)["verdict"] == V.PASS

        with open(media, "wb") as f:      # 换片源
            f.write(b"B" * 4096)
        res = cred.check(srt, media=media)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("片源已换" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_media_declared_but_not_given():
    """凭据绑定了片源，本次却没给 --media —— 不能假装验过。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S01E04.srt")
        media = os.path.join(d, "S01E04.mkv")
        _srt(srt)
        with open(media, "wb") as f:
            f.write(b"A" * 1024)
        ok = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
              "tol": 0.3, "ok": True}
        cred.save(srt, cred.build(srt, ok, "qwen", media=media))
        res = cred.check(srt, media=None)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("未提供 --media" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_file_content_changed():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S01E05.srt")
        _srt(srt)
        ok = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
              "tol": 0.3, "ok": True}
        cred.save(srt, cred.build(srt, ok, "qwen"))
        assert cred.check(srt)["verdict"] == V.PASS
        with open(srt, "a", encoding="utf-8") as f:
            f.write("\n61\n00:45:01.000 --> 00:45:03.000\nzz\n")
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("内容已变" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_patched_without_reaudit():
    """改过时间轴、没复测 —— 这是本次实测里最容易犯的一条。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S01E06.srt")
        _srt(srt)
        ok = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
              "tol": 0.3, "ok": True}
        cred.save(srt, cred.build(srt, ok, "qwen"))
        assert cred.check(srt)["verdict"] == V.PASS

        with open(srt, "a", encoding="utf-8") as f:   # 模拟 align_patch 改盘
            f.write("\n61\n00:45:01.000 --> 00:45:03.000\nzz\n")
        assert cred.touch_patch(srt, max_shift=-1.94, n_events=763) is not None

        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("改过时间轴但未复测" in r for r in res["reasons"]), res["reasons"]
        # sha1 已被 touch_patch 同步，不该再报「内容已变」
        assert not any("内容已变" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_stale_beats_verdict():
    """顺序检查：一份写着 PASS 但已过期的凭据，必须判 UNVERIFIED 而不是放行。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S01E07.srt")
        media = os.path.join(d, "S01E07.mkv")
        _srt(srt)
        with open(media, "wb") as f:
            f.write(b"A" * 512)
        ok = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
              "tol": 0.3, "ok": True}
        data = cred.build(srt, ok, "qwen", media=media)
        cred.save(srt, data)
        assert cred.check(srt, media=media)["verdict"] == V.PASS

        with open(media, "wb") as f:   # 片源换了，但凭据里仍写着 PASS
            f.write(b"C" * 512)
        res = cred.check(srt, media=media)
        assert res["verdict"] == V.UNVERIFIED, (
            "陈旧性必须优先于 verdict，实际 %s" % V.label(res["verdict"]))
    finally:
        shutil.rmtree(d)


def test_roundtrip_json():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E01.eng.srt")
        _srt(srt)
        ok = {"n_pairs": 60, "mad": 0.18, "drift": -0.11, "window_span": 0.23,
              "tol": 0.3, "ok": True}
        p = cred.save(srt, cred.build(srt, ok, "qwen3-forced-aligner",
                                      source={"kind": "embedded_stream", "index": 2,
                                              "title": "UK", "family": "UK"},
                                      cross_checked=True))
        assert p.endswith("S06E01.ts.json"), p   # 取首个点之前做 stem
        back = cred.load(srt)
        assert back["axis"]["mad"] == 0.18
        assert back["source"]["family"] == "UK"
        assert isinstance(back["files"], list) and back["files"][0]["patches"] == 0
    finally:
        shutil.rmtree(d)


# ---------------------------------------------------------------- B 退出码

def test_audit_exit_codes():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S02E01.srt")
        _srt(srt, n=300, shift=0.15)             # 恒定 0.15s：平坦
        rows = _rows(srt)
        w = _words(os.path.join(d, "w_ok.json"), rows, 0.15)
        code, out = _run("align_audit.py", ["--sub", srt, "--asr-words", w])
        assert code == 0, "PASS 应为 0，实际 %s\n%s" % (code, out[-800:])

        w2 = _words(os.path.join(d, "w_bad.json"), rows,
                    lambda i, t: 1.5 * (t / 2700.0))   # 线性漂移到 1.5s
        code, out = _run("align_audit.py", ["--sub", srt, "--asr-words", w2])
        assert code == 2, "FAIL 应为 2，实际 %s\n%s" % (code, out[-800:])
        assert "FAIL" in out, out[-400:]
    finally:
        shutil.rmtree(d)


def test_audit_unverified_without_audio():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S02E02.srt")
        _srt(srt, n=300, shift=0.1)
        code, out = _run("align_audit.py", ["--sub", srt])
        assert code == 3, "无音频应为 UNVERIFIED(3)，实际 %s\n%s" % (code, out[-500:])
    finally:
        shutil.rmtree(d)


def test_audit_writes_credential_both_ways():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S02E03.srt")
        _srt(srt, n=300, shift=0.15)
        rows = _rows(srt)
        w = _words(os.path.join(d, "w.json"), rows, 0.15)
        code, out = _run("align_audit.py",
                         ["--sub", srt, "--asr-words", w, "--write-credential"])
        assert code == 0, out[-600:]
        assert cred.load(srt)["axis"]["verdict"] == "PASS", cred.load(srt)

        # FAIL 也必须写，否则 gate 分不出「验过不对」和「没验」
        w2 = _words(os.path.join(d, "w2.json"), rows,
                    lambda i, t: 1.5 * (t / 2700.0))
        code, _ = _run("align_audit.py",
                       ["--sub", srt, "--asr-words", w2, "--write-credential"])
        assert code == 2
        d2 = cred.load(srt)
        assert d2["axis"]["verdict"] == "FAIL", d2["axis"]
    finally:
        shutil.rmtree(d)


def test_gate_passthrough():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S03E01.srt")
        _srt(srt)
        ok = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
              "tol": 0.3, "ok": True}
        cred.save(srt, cred.build(srt, ok, "qwen"))
        code, out = _run("timeline_gate.py", [srt])
        assert code == 0, out[-500:]
        assert "PASS" in out

        bad = dict(ok, window_span=1.4, ok=False)
        cred.save(srt, cred.build(srt, bad, "qwen"))
        code, out = _run("timeline_gate.py", [srt])
        assert code == 2, out[-500:]

        os.remove(cred.sidecar_path(srt))
        code, out = _run("timeline_gate.py", [srt])
        assert code == 3, out[-500:]
        assert "align_audit" in out, "无凭据时要给出下一步命令\n" + out[-400:]
    finally:
        shutil.rmtree(d)


def test_sparse_is_unverified():
    """字幕密度不足以凑出任何合格时段时，不能因为 window_span 默认 0 就判 PASS。

    这是 #10 的同源漏洞：`win_span = max(meds) - min(meds) if meds else 0.0`，
    meds 为空时得 0，于是「最该报警」的情况反而全绿。
    """
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S02E09.srt")
        _srt(srt, n=12, span=2700.0)          # 12 条 / 45min：每窗不足 5 条
        rows = _rows(srt)
        w = _words(os.path.join(d, "w.json"), rows, 0.15)
        code, out = _run("align_audit.py", ["--sub", srt, "--asr-words", w])
        assert code == 3, "样本不足应为 UNVERIFIED(3)，实际 %s\n%s" % (code, out[-600:])
        assert "UNVERIFIED" in out, out[-400:]
        # 没有曲线可施加
        jp = os.path.join(d, "o.json")
        _run("align_audit.py", ["--sub", srt, "--asr-words", w, "--json", jp])
        data = json.load(open(jp, encoding="utf-8"))
        assert data["curve"] is None and data["curve_applicable"] is False, data["curve_applicable"]
    finally:
        shutil.rmtree(d)


def test_gate_batch_worst_wins():
    d = tempfile.mkdtemp()
    try:
        ok = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
              "tol": 0.3, "ok": True}
        bad = dict(ok, window_span=1.4, ok=False)
        a = os.path.join(d, "E01.srt")
        b = os.path.join(d, "E02.srt")
        c = os.path.join(d, "E03.srt")
        for p in (a, b, c):
            _srt(p)
        cred.save(a, cred.build(a, ok, "qwen"))
        cred.save(b, cred.build(b, bad, "qwen"))
        # c 无凭据
        code, out = _run("timeline_gate.py", [d])
        assert code == 2, "有 FAIL 时应整体 2，实际 %s\n%s" % (code, out[-800:])
        assert "3 集，2 集不可用" in out or "2 集不可用" in out, out[-500:]
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("时间轴凭据 + 三态判定 回归测试 (issue #9 / #10)")
    print("=" * 70)
    test("A1 无凭据 -> UNVERIFIED", test_no_credential)
    test("A2 fresh PASS/FAIL", test_fresh_pass_and_fail)
    test("A3 片源 sha1 变 -> UNVERIFIED", test_media_sha_changed)
    test("A4 绑定片源但没给 --media -> UNVERIFIED", test_media_declared_but_not_given)
    test("A5 文件内容变 -> UNVERIFIED", test_file_content_changed)
    test("A6 改过时间轴未复测 -> UNVERIFIED", test_patched_without_reaudit)
    test("A7 陈旧性优先于 verdict", test_stale_beats_verdict)
    test("A8 凭据 json 往返一致", test_roundtrip_json)
    test("B1 align_audit 退出码 0/2", test_audit_exit_codes)
    test("B2 无音频 -> 3 而不是崩溃", test_audit_unverified_without_audio)
    test("B3 PASS/FAIL 都写凭据", test_audit_writes_credential_both_ways)
    test("B4 gate 三态透传", test_gate_passthrough)
    test("B5 批量取最坏", test_gate_batch_worst_wins)
    test("B6 字幕过稀 -> UNVERIFIED 而不是空判 PASS", test_sparse_is_unverified)
    print()
    print("  通过 %d / 失败 %d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)
