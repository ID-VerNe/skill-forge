# -*- coding: utf-8 -*-
"""回归测试：时间轴改动的记账 / 回滚 / 拟合健壮性 —— issue #13 / #14。

#13 `align_patch` 改时间轴完全不进 `log.jsonl`，只有一份 `.bak`。后果：
    `--rollback batch=` 回滚后文本回去了、时间还错着，**回滚本身变成新的错误**；
    `verify_fixes` 报「0 失败」，而它压根没把时间轴算进校验对象。

#14 曲线拟合假设「单调分段常数」。形态不匹配时它照样输出一条看起来合理的
    曲线——照它施加比不改更糟（v1.4.0 那次的 +1.26s 反转就是这么来的）。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_curve_fit.py
"""
from __future__ import annotations

import json
import math
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
from lib import credential as cred        # noqa: E402

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


def _run(script, args, cwd=None):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + args,
                       capture_output=True, text=True, cwd=cwd)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _pairs(n=400, span=2700.0, fn=None):
    step = span / (n - 1)
    out = []
    for i in range(n):
        t = i * step
        out.append((t, fn(t) if fn else 0.0))
    return out


# ---------------------------------------------------------------- A 拟合

def test_descending_staircase():
    """E03 形态：三处阶跃、整体递减（字幕被推晚）。"""
    def fn(t):
        return 0.15 - 0.45 * int(t // 600)
    spec, base, diag = ac.spec_from_pairs(_pairs(fn=fn))
    assert diag["verdict"] == "FIT_OK", diag
    assert diag["direction"] == -1, "方向应为负（递减），实际 %s" % diag["direction"]
    assert spec is not None and len(spec["segments"]) >= 2, spec
    vals = [s[1] for s in spec["segments"]]
    assert vals[0] == 0.0, "首段必须归零，实际 %s" % vals
    for a, b in zip(vals, vals[1:]):
        assert b <= a + 1e-9, "递减样本拟合出递增段：%s" % vals
    assert vals[-1] < -1.0, "末端应累积到 -1.8 左右，实际 %s" % vals[-1]


def test_ascending_staircase():
    def fn(t):
        return -0.2 + 0.4 * int(t // 700)
    spec, _base, diag = ac.spec_from_pairs(_pairs(fn=fn))
    assert diag["direction"] == 1, diag
    vals = [s[1] for s in spec["segments"]]
    for a, b in zip(vals, vals[1:]):
        assert b >= a - 1e-9, vals


def test_direction_not_fooled_by_tail_outliers():
    """末段几个离群点不该翻向 —— 首末两点法就是死在这里。"""
    pts = _pairs(fn=lambda t: 0.1 - 0.0006 * t)
    for i in range(len(pts) - 3, len(pts)):
        pts[i] = (pts[i][0], pts[i][1] + 6.0)
    spec, _b, diag = ac.spec_from_pairs(pts)
    assert diag["direction"] == -1, "方向被末段离群点带偏了：%s" % diag
    if spec:
        vals = [s[1] for s in spec["segments"]]
        assert max(vals) <= 0.01, "不该出现正向放大：%s" % vals


def test_reject_non_staircase():
    """正弦注入：不是分段常数形态，必须拒，而不是硬给一条曲线。"""
    spec, _b, diag = ac.spec_from_pairs(
        _pairs(fn=lambda t: 0.8 * math.sin(t / 180.0)))
    assert diag["verdict"] == "FIT_REJECTED", (
        "应判 FIT_REJECTED，实际 %s（P90=%s）" % (diag["verdict"], diag["p90"]))
    assert spec is None, "被拒时不该给 spec"


def test_diag_fields():
    spec, _b, diag = ac.spec_from_pairs(_pairs(fn=lambda t: 0.1))
    for k in ("p90", "r2", "segs", "direction", "breaks",
              "hit_max_seg", "hit_min_pts", "verdict"):
        assert k in diag, "diag 缺字段 %s" % k
    assert diag["verdict"] == "FIT_OK", diag
    assert diag["p90"] is not None and diag["p90"] < 0.4, diag


def test_non_monotonic_break_recorded():
    """先降后升：夹平是擅自决定，标出来让人判。"""
    def fn(t):
        return -0.5 * int(t // 600) if t < 1500 else -1.0 + 1.2
    _spec, _b, diag = ac.spec_from_pairs(_pairs(fn=fn))
    assert isinstance(diag["breaks"], list)
    # 有反向就必须记下来；没有反向则应为空
    assert diag["breaks"] == [] or diag["breaks"][0]["back"] > 0.15, diag["breaks"]


# ---------------------------------------------------------------- B 记账

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _fixture(d):
    ass = os.path.join(d, "E01.ass")
    srt = os.path.join(d, "E01.srt")
    body = []
    blocks = []
    for i in range(6):
        m, sec = divmod(i * 20, 60)
        st = "0:%02d:%02d.000" % (m, sec)
        en = "0:%02d:%02d.500" % (m, sec + 15)
        body.append("Dialogue: 0,%s,%s,英文,,0,0,0,,{\\be3}line %d english\n" % (st, en, i))
        body.append("Dialogue: 0,%s,%s,中文,,0,0,0,,{\\be3}第 %d 行\n" % (st, en, i))
        blocks.append("%d\n%s --> %s\nline %d english\n"
                      % (i + 1, st.replace(",", "."), en.replace(",", "."), i))
    with open(ass, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER + "".join(body))
    with open(srt, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    return ass, srt


def test_patch_writes_log_and_backup():
    d = tempfile.mkdtemp()
    try:
        ass, _srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        code, out = _run("align_patch.py", [
            "--sub", ass, "--slope", "0.01", "--origin", "0",
            "--write", "--work-dir", wd, "--batch-id", "b1"])
        assert code == 0, out[-800:]

        lp = os.path.join(wd, "log.jsonl")
        assert os.path.exists(lp), "没写 log.jsonl"
        ents = [json.loads(x) for x in open(lp, encoding="utf-8") if x.strip()]
        cur = [e for e in ents if e["action"] == "retime_curve"]
        assert len(cur) == 1, ents
        e = cur[0]
        assert e["srt_id"] == 0 and e["track"] == "*", e
        assert e["spec"] and e["spec"]["kind"] in ("curve", "linear"), e["spec"]
        assert e["n_events"] == 12, e
        assert e["max_shift"] > 0.5, e
        assert os.path.exists(e["backup"]), e["backup"]

        bp = os.path.join(wd, "backups.jsonl")
        assert os.path.exists(bp), "没写 backups.jsonl"
        b = json.loads(open(bp, encoding="utf-8").read().strip())
        assert b["path"].endswith("E01.ass") and b["sha1"], b
    finally:
        shutil.rmtree(d)


def test_patch_invalidates_credential():
    d = tempfile.mkdtemp()
    try:
        ass, _srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        cred.save(ass, cred.build(ass, {"n_pairs": 6, "mad": 0.1, "drift": 0.0,
                                        "window_span": 0.1, "tol": 0.3, "ok": True},
                                  "qwen"))
        assert cred.check(ass)["verdict"] == 0
        _run("align_patch.py", ["--sub", ass, "--slope", "0.0002", "--origin", "0",
                                "--write", "--work-dir", wd])
        res = cred.check(ass)
        assert res["verdict"] == 3, res
        assert any("改过时间轴但未复测" in r for r in res["reasons"]), res["reasons"]
        assert not any("内容已变" in r for r in res["reasons"]), \
            "touch_patch 应同步 sha1，否则会报错原因"
    finally:
        shutil.rmtree(d)


def test_revert_restores_bytes():
    d = tempfile.mkdtemp()
    try:
        ass, _srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        before = open(ass, "rb").read()
        _run("align_patch.py", ["--sub", ass, "--slope", "0.0002", "--origin", "0",
                                "--write", "--work-dir", wd])
        assert open(ass, "rb").read() != before, "patch 没生效"
        code, out = _run("align_patch.py", ["--sub", ass, "--revert",
                                            "--work-dir", wd])
        assert code == 0, out[-500:]
        assert open(ass, "rb").read() == before, "revert 未逐字节还原"

        lp = os.path.join(wd, "log.jsonl")
        acts = [json.loads(x)["action"] for x in open(lp, encoding="utf-8") if x.strip()]
        assert "revert_curve" in acts, acts
    finally:
        shutil.rmtree(d)


def test_fit_rejected_blocks_patch():
    """审计判 FIT_REJECTED 时，align_patch 必须拒写。"""
    d = tempfile.mkdtemp()
    try:
        ass, _srt = _fixture(d)
        jp = os.path.join(d, "audit.json")
        json.dump({"sub": ass, "verdict": "FAIL", "curve": None,
                   "curve_applicable": False,
                   "fit": {"verdict": "FIT_REJECTED", "p90": 0.71,
                           "reason": "残差 P90 0.71s > 0.40s"}},
                  open(jp, "w", encoding="utf-8"))
        before = open(ass, "rb").read()
        code, out = _run("align_patch.py", ["--sub", ass, "--spec", jp,
                                            "--write", "--work-dir", d])
        assert code != 0, out[-400:]
        assert "拟合被拒" in out, out[-400:]
        assert open(ass, "rb").read() == before, "被拒时不该动文件"
    finally:
        shutil.rmtree(d)


def test_dry_run_lists_top20():
    d = tempfile.mkdtemp()
    try:
        ass, _srt = _fixture(d)
        code, out = _run("align_patch.py", ["--sub", ass, "--slope", "0.0002",
                                            "--origin", "0"])
        assert code == 0, out[-400:]
        assert "改动最大的 20 条" in out, out[-800:]
    finally:
        shutil.rmtree(d)


def test_verify_marks_pending_not_fail():
    d = tempfile.mkdtemp()
    try:
        ass, srt = _fixture(d)
        wd = os.path.join(d, ".subtitle-polish")
        _run("align_patch.py", ["--sub", ass, "--slope", "0.0002", "--origin", "0",
                                "--write", "--work-dir", wd])
        code, out = _run("verify_fixes.py", ["--all", "--work-dir", wd])
        assert code == 0, "时间轴改动不该算失败：\n%s" % out[-600:]
        rep = os.path.join(wd, "reports", "verify-fixes.md")
        assert os.path.exists(rep), os.listdir(os.path.join(wd, "reports"))
        md = open(rep, encoding="utf-8").read()
        assert "待复测" in md, md[-800:]
        assert "retime_curve" in md, md[-800:]
        assert "重跑 `align_audit`" in md, md[-800:]
        assert "失败 0" not in md or "通过 0 / 失败 0" in md, md[-400:]
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("拟合健壮性 + 时间轴记账 回归测试 (issue #13 / #14)")
    print("=" * 70)
    test("A1 递减阶梯：方向为负、末段不反转", test_descending_staircase)
    test("A2 递增阶梯：方向为正", test_ascending_staircase)
    test("A3 末段离群不翻向", test_direction_not_fooled_by_tail_outliers)
    test("A4 非分段常数 -> FIT_REJECTED", test_reject_non_staircase)
    test("A5 diag 字段齐全", test_diag_fields)
    test("A6 非单调冲突被记录", test_non_monotonic_break_recorded)
    test("B1 施加后写 retime_curve + backups", test_patch_writes_log_and_backup)
    test("B2 施加后凭据立即失效", test_patch_invalidates_credential)
    test("B3 --revert 逐字节还原", test_revert_restores_bytes)
    test("B4 FIT_REJECTED 拒写", test_fit_rejected_blocks_patch)
    test("B5 dry-run 列 Top20", test_dry_run_lists_top20)
    test("B6 verify 报「待复测」而非失败", test_verify_marks_pending_not_fail)
    print()
    print("  通过 %d / 失败 %d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)
