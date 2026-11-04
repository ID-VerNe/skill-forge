# -*- coding: utf-8 -*-
"""回归测试：时间轴凭据绑定「时间轴事实」，而不是整份文件 sha1。

背景（R2–R3 实测）：文本轮每天在改文案，凭据却按整文件 sha1 绑定，于是
「只改几个中文字」也会让对齐证据作废，门禁每一轮都 UNVERIFIED。这不是
「验出来轴有问题」，而是把「文本改了」误当成「轴变了」。

本测试分两组：

  A. 放宽（文本轮不该失效）
     - 改中文文本、时间不动        -> PASS，detail/notes 写明「文本已改 N 条，时间轴证据沿用」
     - 只写 patched_at 元数据      -> PASS
     - 只改样式名                  -> PASS（样式不影响「什么时候出现」）
     - 只重写序列化（表头）        -> PASS

  B. 反向（真改了轴必须失效）
     - 改 start                    -> UNVERIFIED，理由指出第几条
     - 改 end                      -> UNVERIFIED
     - 加一行                      -> UNVERIFIED（行数变了）
     - 删一行                      -> UNVERIFIED
     - 调序（事件的起止顺序变了）  -> UNVERIFIED
     - 改 layer（ASS 叠层）        -> UNVERIFIED
     - 旧凭据没有轴指纹            -> 退回 sha1 口径，文本变仍失效

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_timeline_fingerprint.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

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

OK = {"n_pairs": 60, "mad": 0.1, "drift": 0.0, "window_span": 0.1,
      "tol": 0.3, "ok": True}


def _sec(ms):
    h = ms // 3600000
    m = ms % 3600000 // 60000
    s = ms % 60000 // 1000
    r = ms % 1000
    return "%02d:%02d:%02d.%03d" % (h, m, s, r)


def _write_srt(path, rows):
    """rows: [(start_ms, end_ms, text)]，按顺序写。"""
    out = []
    for i, (a, b, text) in enumerate(rows):
        out.append("%d\n%s --> %s\n%s\n" % (i + 1, _sec(a), _sec(b), text))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def _line(n, text=None, step=2000):
    return (n * step, n * step + 1600, text if text is not None else "line%d" % n)


def _ass_ts(ms):
    h = ms // 3600000
    m = ms % 3600000 // 60000
    s = ms % 60000 // 1000
    cs = ms % 1000 // 10
    return "%d:%02d:%02d.%02d" % (h, m, s, cs)


def _write_ass(path, rows, style="Default"):
    """rows: [(layer, start_ms, end_ms, text)]。"""
    body = ["[Script Info]", "ScriptType: v4.00+", "", "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1",
            "Style: Alt,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1",
            "", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text"]
    for layer, a, b, text in rows:
        body.append("Dialogue: %d,%s,%s,%s,,0,0,0,,%s"
                    % (layer, _ass_ts(a), _ass_ts(b), style, text))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")


def _fresh(path):
    cred.save(path, cred.build(path, OK, "qwen"))


def _text_notes(res):
    return [n for n in (res.get("notes") or []) if "文本已改" in n]


# ---------------------------------------------------------------- A 放宽

def test_text_edit_keeps_pass():
    """文本轮：改中文、时间不动 —— 必须保持 PASS，并写明「证据沿用」。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E04.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)
        assert cred.check(srt)["verdict"] == V.PASS

        rows[2] = (rows[2][0], rows[2][1], "改成中文的一行")
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.PASS, res
        notes = _text_notes(res)
        assert notes and "文本已改（1 条），时间轴证据沿用" in notes[0], notes
    finally:
        shutil.rmtree(d)


def test_many_text_edits_keep_pass():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E05.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)
        for i in range(8):
            rows[i * 5] = (rows[i * 5][0], rows[i * 5][1], "改写%d" % i)
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.PASS, res
        assert "文本已改（8 条）" in "".join(_text_notes(res)), res.get("notes")
    finally:
        shutil.rmtree(d)


def test_style_edit_keeps_pass():
    """样式/轨归属不属于「什么时候出现」：改 Style（即换轨）不该失效。

    对应 references/timeline-credential.md「为什么 track 不参与指纹」：指纹只取
    (start, end, layer)。这里把整轨从 Default 换到 Alt、时间一字不改，必须 PASS。
    """
    d = tempfile.mkdtemp()
    try:
        ass = os.path.join(d, "S06E06.eng.ass")
        rows = [(0, i * 2000, i * 2000 + 1600, "line%d" % i) for i in range(30)]
        _write_ass(ass, rows, style="Default")
        _fresh(ass)
        assert cred.check(ass)["verdict"] == V.PASS

        _write_ass(ass, rows, style="Alt")
        res = cred.check(ass)
        assert res["verdict"] == V.PASS, res
        # 只换轨、文本没动：不该误报「文本已改 N 条」
        assert not _text_notes(res), res.get("notes")
    finally:
        shutil.rmtree(d)


def test_metadata_only_patch_keeps_pass():
    """patched_at 只是元数据；轴没变就不该影响判定。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E07.eng.srt")
        _write_srt(srt, [_line(i) for i in range(30)])
        _fresh(srt)
        cred.touch_patch(srt, max_shift=0.0, n_events=0)
        assert cred.check(srt)["verdict"] == V.PASS
    finally:
        shutil.rmtree(d)


def test_header_rewrite_keeps_pass():
    """只重写序列化/表头（pysubs2 重存）→ 事件事实不变，仍 PASS。"""
    d = tempfile.mkdtemp()
    try:
        ass = os.path.join(d, "S06E08.eng.ass")
        rows = [(0, i * 2000, i * 2000 + 1600, "line%d" % i) for i in range(30)]
        _write_ass(ass, rows)
        _fresh(ass)
        import pysubs2
        subs = pysubs2.load(ass)
        subs.info["Comment"] = "rewritten by pysubs2"
        subs.save(ass)
        res = cred.check(ass)
        assert res["verdict"] == V.PASS, res
    finally:
        shutil.rmtree(d)


# ---------------------------------------------------------------- B 反向

def test_start_changed_fails_with_row():
    """改 start 必须失效，且理由指出是第几条。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E09.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)

        rows[11] = (rows[11][0] + 500, rows[11][1], rows[11][2])
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        why = "".join(res["reasons"])
        assert "时间轴已变" in why, res["reasons"]
        assert "第 12 条" in why, res["reasons"]
        assert "起点" in why, res["reasons"]
    finally:
        shutil.rmtree(d)


def test_end_changed_fails():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E10.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)

        rows[4] = (rows[4][0], rows[4][1] + 300, rows[4][2])
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        why = "".join(res["reasons"])
        assert "第 5 条" in why and "终点" in why, res["reasons"]
    finally:
        shutil.rmtree(d)


def test_append_row_fails():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E11.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)
        rows.append((61 * 2000, 61 * 2000 + 1600, "extra"))
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("行数已变" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_delete_row_fails():
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E12.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)
        rows.pop(20)
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("行数已变" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_reorder_fails():
    """调序（事件起止顺序变了）必须失效——字幕和语音的对应关系变了。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E13.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)
        rows[3], rows[4] = rows[4], rows[3]     # 两行整体换位（各带自己的时间）
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("时间轴已变" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_layer_changed_fails():
    """ASS 层决定谁盖住谁：层变了等于观众看到的字幕换了。"""
    d = tempfile.mkdtemp()
    try:
        ass = os.path.join(d, "S06E14.eng.ass")
        rows = [(0, i * 2000, i * 2000 + 1600, "line%d" % i) for i in range(30)]
        _write_ass(ass, rows)
        _fresh(ass)
        assert cred.check(ass)["verdict"] == V.PASS

        rows[7] = (1, rows[7][1], rows[7][2], rows[7][3])
        _write_ass(ass, rows)
        res = cred.check(ass)
        assert res["verdict"] == V.UNVERIFIED, res
        why = "".join(res["reasons"])
        assert "第 8 条" in why and "层" in why, res["reasons"]
    finally:
        shutil.rmtree(d)


def test_legacy_credential_still_strict():
    """旧凭据没有轴指纹：退回整文件口径，文本改动仍然失效（保守兜底）。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E15.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        data = cred.build(srt, OK, "qwen")
        data["files"][0].pop("timeline", None)
        cred.save(srt, data)
        assert cred.check(srt)["verdict"] == V.PASS

        rows[0] = (rows[0][0], rows[0][1], "改文本")
        _write_srt(srt, rows)
        res = cred.check(srt)
        assert res["verdict"] == V.UNVERIFIED, res
        assert any("旧凭据无轴指纹" in r for r in res["reasons"]), res["reasons"]
    finally:
        shutil.rmtree(d)


def test_rebuild_after_reaudit_restores_pass():
    """改轴 → 失效；重跑审计（重建凭据）后恢复 PASS。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E16.eng.srt")
        rows = [_line(i) for i in range(60)]
        _write_srt(srt, rows)
        _fresh(srt)
        rows = [(a + 500, b + 500, t) for a, b, t in rows]   # 全片平移
        _write_srt(srt, rows)
        assert cred.check(srt)["verdict"] == V.UNVERIFIED
        _fresh(srt)          # 复测后重建凭据（写新指纹）
        assert cred.check(srt)["verdict"] == V.PASS
    finally:
        shutil.rmtree(d)


def test_render_shows_text_note():
    """render() 要把「文本已改、证据沿用」显示出来，而不是只在详情里。"""
    d = tempfile.mkdtemp()
    try:
        srt = os.path.join(d, "S06E17.eng.srt")
        rows = [_line(i) for i in range(10)]
        _write_srt(srt, rows)
        _fresh(srt)
        rows[0] = (rows[0][0], rows[0][1], "中文")
        _write_srt(srt, rows)
        text = cred.render(cred.check(srt))
        assert "文本已改（1 条），时间轴证据沿用" in text, text
        assert "PASS" in text, text
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    print("=" * 70)
    print("时间轴指纹（轴事实绑定）回归测试")
    print("=" * 70)
    test("A1 改中文 -> PASS + 证据沿用", test_text_edit_keeps_pass)
    test("A2 改 8 条文本 -> PASS + 计数 8", test_many_text_edits_keep_pass)
    test("A3 改样式 -> PASS", test_style_edit_keeps_pass)
    test("A4 仅写 patched_at -> PASS", test_metadata_only_patch_keeps_pass)
    test("A5 重写表头 -> PASS", test_header_rewrite_keeps_pass)
    test("B1 改 start -> UNVERIFIED 且指出第 12 条", test_start_changed_fails_with_row)
    test("B2 改 end -> UNVERIFIED 且指出第 5 条", test_end_changed_fails)
    test("B3 加行 -> UNVERIFIED", test_append_row_fails)
    test("B4 删行 -> UNVERIFIED", test_delete_row_fails)
    test("B5 调序 -> UNVERIFIED", test_reorder_fails)
    test("B6 改 layer -> UNVERIFIED", test_layer_changed_fails)
    test("B7 旧凭据兜底 -> 文本变仍失效", test_legacy_credential_still_strict)
    test("B8 复测重建 -> 恢复 PASS", test_rebuild_after_reaudit_restores_pass)
    test("C1 render 输出沿用说明", test_render_shows_text_note)
    print()
    print("  通过 %d / 失败 %d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)
