"""英文侧锚点 + 在线检索试水（issue #30 建议 2 D 部分）。

锁四件事：
  1. 英文侧能产出带行号的候选：专名 / 同文档形近变体 / 同音词双现。
  2. 在线检索默认关闭；失败降级为「未检索」，不影响退出码；结果只带来源 URL，不给替换词。
  3. 锚点能进含第 6 类的轮次（audit.tmpl `{spelling_seeds}` + auto-flow 接线）。
  4. 锚点不参与时间轴：输出没有 verdict/stats，输入文件哈希不变。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_en_seeds.py
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

import scan_seed as ss  # noqa: E402
from lib import web_lookup as wl  # noqa: E402

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


def _rows(*texts):
    return [{"srt_id": i + 1, "ass_time": "%d-%d" % (i * 2, i * 2 + 2),
             "en": t, "zh": "", "raw": t} for i, t in enumerate(texts)]


def _slice(path, *texts):
    with open(path, "w", encoding="utf-8") as f:
        for i, t in enumerate(texts, 1):
            f.write("%d | %d-%d | %s |\n" % (i, i * 2, i * 2 + 2, t))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def t_proper_noun_anchor():
    seed = ss.build_seeds(_rows("The British Leyland story"), en=True)
    forms = [(a["srt_id"], a["form"], a["term"]) for a in seed["en_anchors"]]
    assert (1, "en_proper_noun", "British") in forms, forms
    assert (1, "en_proper_noun", "Leyland") in forms, forms
    assert "不参与时间轴" in seed["en_instruction"], seed["en_instruction"]


def t_near_variant_anchor():
    seed = ss.build_seeds(_rows("British Leyland is here", "British Layland again"),
                          en=True)
    near = [a for a in seed["en_anchors"] if a["form"] == "en_near_variant"]
    assert any(a["term"] == "Layland" and "Leyland" in a["note"] for a in near), near


def t_homophone_requires_both():
    one = ss.build_seeds(_rows("The brake works"), en=True)
    assert not [a for a in one["en_anchors"] if a["form"] == "en_homophone"], \
        one["en_anchors"]
    both = ss.build_seeds(_rows("The brake works", "Give me a break"), en=True)
    forms = [a["term"].lower() for a in both["en_anchors"]
             if a["form"] == "en_homophone"]
    assert "brake" in forms and "break" in forms, forms


def t_web_verify_default_off():
    assert wl.verify_term("Leyland")["status"] == "disabled", "默认必须关闭"
    seed = ss.build_seeds(_rows("British Leyland"), en=True)  # 不传 lookup
    assert all(a["verify"] is None or a["verify"]["status"] == "disabled"
               for a in seed["en_anchors"]), "默认不应发起检索"
    a = next(a for a in seed["en_anchors"] if a["term"] == "Leyland")
    assert a["verify"]["status"] == "disabled", a


def t_web_verify_found_has_url():
    def fake(term):
        return {"status": "found", "query": term, "title": term,
                "source_url": "https://example.org/wiki/" + term}

    seed = ss.build_seeds(_rows("British Leyland"), en=True, lookup=fake)
    a = next(a for a in seed["en_anchors"] if a["term"] == "Leyland")
    assert a["verify"]["status"] == "found", a
    assert a["verify"]["source_url"].startswith("https://"), a
    # 只带来源，不给「应该改成什么」
    assert "suggestion" not in a["verify"] and "replacement" not in a["verify"], a


def t_web_verify_failure_degrades():
    def boom(term):
        return {"status": "unavailable", "query": term,
                "source_url": "https://example.org/search?q=" + term,
                "note": "URLError: timed out"}

    seed = ss.build_seeds(_rows("British Leyland"), en=True, lookup=boom)
    a = next(a for a in seed["en_anchors"] if a["term"] == "Leyland")
    assert a["verify"]["status"] == "unavailable", a
    assert "Leyland" in a["term"], "检索失败不应丢掉锚点"


def t_web_verify_network_error_real():
    """真实失败路径（不依赖外网）：opener 抛异常必须降级，不抛出。"""
    class Bad:
        def __call__(self, *a, **k):
            raise OSError("network down")

    r = wl.verify_term("Leyland", enabled=True, opener=Bad())
    assert r["status"] == "unavailable", r
    assert r["source_url"].startswith("https://"), r


def t_srt_refused_by_default_allowed_with_en():
    root = tempfile.mkdtemp(prefix="sp-en-")
    try:
        srt = os.path.join(root, "e01.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:02,000\nBritish Leyland\n"
                    "\n2\n00:00:02,000 --> 00:00:04,000\nBritish Layland\n")
        script = os.path.join(SCRIPTS, "scan_seed.py")
        p = subprocess.run([sys.executable, script, srt],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 2, (p.returncode, p.stderr)
        p = subprocess.run([sys.executable, script, srt, "--en-anchors"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, (p.returncode, p.stderr)
        seed = json.loads(p.stdout)
        assert any(a["form"] == "en_near_variant" for a in seed["en_anchors"]), \
            seed["en_anchors"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_ass_english_pairing():
    root = tempfile.mkdtemp(prefix="sp-en-ass-")
    try:
        ass = os.path.join(root, "e01.ass")
        with open(ass, "w", encoding="utf-8") as f:
            f.write("""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: EN,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: ZH,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.00,EN,,0,0,0,,The British Leyland story
Dialogue: 0,0:00:00.00,0:00:02.00,ZH,,0,0,0,,英国利兰的故事
""")
        rows = ss.read_ass(ass, with_en=True)
        assert len(rows) == 1, rows
        assert rows[0]["en"] == "The British Leyland story", rows[0]
        seed = ss.build_seeds(rows, en=True)
        assert any(a["term"] == "Leyland" for a in seed["en_anchors"]), seed
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_cli_en_hint_and_no_timeline_keys():
    root = tempfile.mkdtemp(prefix="sp-en-cli-")
    try:
        sl = os.path.join(root, "p1.txt")
        _slice(sl, "The British Leyland story", "British Layland again")
        before = _sha(sl)
        out = os.path.join(root, "spelling.json")
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scan_seed.py"),
                            sl, "--en-anchors", "--out", out],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr
        assert _sha(sl) == before, "scan_seed 改了输入切片"
        with open(out, encoding="utf-8") as f:
            seed = json.load(f)
        assert "en_hint_text" in seed and "{spelling_seeds}" not in seed["en_hint_text"], seed
        assert "verdict" not in seed and "stats" not in seed and "pairs" not in seed, \
            "锚点输出不应包含时间轴判定字段"
        assert len(seed["en_anchors"]) >= 1, seed
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_web_verify_requires_en_anchors():
    root = tempfile.mkdtemp(prefix="sp-en-flag-")
    try:
        sl = os.path.join(root, "p1.txt")
        _slice(sl, "The British Leyland story")
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scan_seed.py"),
                            sl, "--web-verify"],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 2, (p.returncode, p.stderr)
        assert "--en-anchors" in p.stderr, p.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_round_seed_consumer_wired():
    with open(os.path.join(SKILL_ROOT, "prompts", "audit.tmpl"),
              encoding="utf-8") as f:
        tmpl = f.read()
    with open(os.path.join(SKILL_ROOT, "references", "auto-flow.md"),
              encoding="utf-8") as f:
        flow = f.read()
    assert "{spelling_seeds}" in tmpl, "第 6 类轮次拿不到英文侧锚点"
    assert "--en-anchors" in flow, "auto-flow 没接线 --en-anchors"
    assert "不参与时间轴" in tmpl, "模板没写明锚点不参与时间轴"


def t_align_core_not_imported():
    assert not hasattr(ss, "align_core"), "scan_seed 不应引入时间轴模块"


# ── issue #47：收紧专名口径（旧口径一集 650 候选里 57% 是句首噪声） ──────────

def t_initial_greetings_dropped():
    seed = ss.build_seeds(_rows("Yeah, that's right", "Okay then", "Nice one"),
                          en=True)
    pro = [a for a in seed["en_anchors"] if a["form"] == "en_proper_noun"]
    assert not pro, pro
    st = seed["en_anchor_stats"]
    assert st["kept"] == 0 and st["dropped"] > 0, st


def t_contractions_not_names():
    seed = ss.build_seeds(_rows("I'm here", "Let's go", "He's late"), en=True)
    assert not [a for a in seed["en_anchors"]
                if a["form"] == "en_proper_noun"], seed["en_anchors"]


def t_mid_sentence_kept_initial_flagged():
    seed = ss.build_seeds(_rows("We met John yesterday", "John was here"), en=True)
    pros = [a for a in seed["en_anchors"] if a["form"] == "en_proper_noun"]
    assert len(pros) == 2, pros
    by_row = {a["srt_id"]: a for a in pros}
    assert by_row[1]["note"] == "", by_row[1]
    assert "弱证据" in by_row[2]["note"], by_row[2]


def t_strong_form_kept_even_initial():
    seed = ss.build_seeds(_rows("McLaren is fast", "F1 season starts"), en=True)
    terms = [a["term"] for a in seed["en_anchors"]
             if a["form"] == "en_proper_noun"]
    assert "McLaren" in terms, terms
    assert "F1" in terms, terms


def t_elided_apostrophe_not_name():
    seed = ss.build_seeds(_rows("'Cause they'll change", "Mr Smith arrived"),
                          en=True)
    terms = [a["term"] for a in seed["en_anchors"]
             if a["form"] == "en_proper_noun"]
    assert "Cause" not in terms, terms
    assert "Smith" in terms, terms


def t_stats_reported_in_md():
    seed = ss.build_seeds(_rows("Yeah, that's right", "We met John yesterday"),
                          en=True)
    st = seed["en_anchor_stats"]
    assert st["candidates"] == st["kept"] + st["dropped"], st
    md = ss.render_md_seed(seed)
    assert "大写开头候选" in md and "丢弃（只在句首出现）" in md, md
    assert "%.1f%%" % st["dropped_pct"] in md, (st, md)


if __name__ == "__main__":
    print("英文侧锚点 + 在线检索（只提示，不参与时间轴）")
    test("英文专名候选", t_proper_noun_anchor)
    test("同文档形近变体", t_near_variant_anchor)
    test("同音词需双现", t_homophone_requires_both)
    test("在线检索默认关闭", t_web_verify_default_off)
    test("检索命中带来源 URL", t_web_verify_found_has_url)
    test("检索失败降级", t_web_verify_failure_degrades)
    test("真实网络失败降级", t_web_verify_network_error_real)
    test("SRT 默认拒绝 / --en-anchors 放行",
         t_srt_refused_by_default_allowed_with_en)
    test("ASS 英中配对", t_ass_english_pairing)
    test("CLI 产出 en_hint 且无时间轴字段", t_cli_en_hint_and_no_timeline_keys)
    test("--web-verify 需要 --en-anchors", t_web_verify_requires_en_anchors)
    test("第 6 类轮次已接线", t_round_seed_consumer_wired)
    test("不引入时间轴模块", t_align_core_not_imported)
    test("句首问候语不报专名", t_initial_greetings_dropped)
    test("缩写不算专名", t_contractions_not_names)
    test("句中出现才留、句首只标弱证据", t_mid_sentence_kept_initial_flagged)
    test("强形（内部大写/带数字）即使句首也留", t_strong_form_kept_even_initial)
    test("撇号缩写不算专名", t_elided_apostrophe_not_name)
    test("报告带候选/丢弃占比", t_stats_reported_in_md)
    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
