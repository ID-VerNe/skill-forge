# -*- coding: utf-8 -*-
"""第 8 类（性别中立/敏感词）：白名单不误改 + 分层 + 清单同源。

为什么这个测试非写不可：第 8 类最大的风险不是漏改，是**误改**。
`母头`/`公头` 是螺接端子的行业标准词，`处女座` 是星座名，`夫妻肺片` 是菜名。
一旦被"为避免挑刺"的直觉改掉，行业观众看不懂、星座成了错、菜名没了。
这类错误不会触发 verify（字确实写进去了），只能靠白名单在源头拦住。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_inclusive.py
"""
from __future__ import annotations

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

import scan_inclusive as si

PY = sys.executable
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
        import traceback
        traceback.print_exc()
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        FAIL += 1
    else:
        print(f"  [PASS] {name}")
        PASS += 1


ASS_HEADER = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# 前 4 块是白名单（绝不改），后 2 块该改（L1 / L2）
ASS_BODY = """Dialogue: 0,0:00:00.00,0:00:02.00,英文,,0,0,0,,Plug the female connector in.
Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,把这个母头插上
Dialogue: 0,0:00:02.00,0:00:04.00,英文,,0,0,0,,I'm a Virgo.
Dialogue: 0,0:00:02.00,0:00:04.00,中文,,0,0,0,,我是处女座
Dialogue: 0,0:00:04.00,0:00:06.00,英文,,0,0,0,,Order the husband-and-wife beef.
Dialogue: 0,0:00:04.00,0:00:06.00,中文,,0,0,0,,来盘夫妻肺片
Dialogue: 0,0:00:06.00,0:00:08.00,英文,,0,0,0,,Her maiden voyage.
Dialogue: 0,0:00:06.00,0:00:08.00,中文,,0,0,0,,她的处女航
Dialogue: 0,0:00:08.00,0:00:10.00,英文,,0,0,0,,My God, this thing is fast.
Dialogue: 0,0:00:08.00,0:00:10.00,中文,,0,0,0,,天啊 这车太快了
Dialogue: 0,0:00:10.00,0:00:12.00,英文,,0,0,0,,The male thread is stripped.
Dialogue: 0,0:00:10.00,0:00:12.00,中文,,0,0,0,,公螺纹滑丝了
"""

SRT = """1
00:00:00,000 --> 00:00:02,000
Plug the female connector in.

2
00:00:02,000 --> 00:00:04,000
I'm a Virgo.

3
00:00:04,000 --> 00:00:06,000
Order the husband-and-wife beef.

4
00:00:06,000 --> 00:00:08,000
Her maiden voyage.

5
00:00:08,000 --> 00:00:10,000
My God, this thing is fast.

6
00:00:10,000 --> 00:00:12,000
The male thread is stripped.
"""


class Fixture:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="sp-incl-")
        self.ass = os.path.join(self.dir, "e05.ass")
        self.srt = os.path.join(self.dir, "e05.srt")
        with open(self.ass, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER + ASS_BODY)
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write(SRT)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════
# 1. 白名单优先（本测试的核心）
# ══════════════════════════════════════════════════════════════════

def t_whitelist_never_hits():
    """母头/公头/处女座/夫妻肺片 → 只进 whitelisted，不进 hits。"""
    for text, term in (("把这个母头插上", "母头"),
                       ("换个公头试试", "公头"),
                       ("我是处女座", "处女座"),
                       ("来盘夫妻肺片", "夫妻肺片"),
                       ("公螺纹滑丝了", "公螺纹"),
                       ("处女星号出发了", "处女星号")):
        r = si.classify(text)
        assert not r["hits"], f"{term!r} 不该进 hits，实际 {r['hits']}（文本 {text!r}）"
        assert any(w["term"] == term for w in r["whitelisted"]), \
            f"{term!r} 没进白名单，实际 {r['whitelisted']}"


def t_whitelist_beats_l1():
    """白名单优先于 L1：含 `处女` 的白名单词不能被当 L1 命中。"""
    r = si.classify("处女星号")
    assert not r["hits"], f"处女星号 被当成问题：{r['hits']}"
    # 同一段里既有白名单也有真问题，真问题仍要报
    r2 = si.classify("处女星号的首航？不 是处女航")
    terms = [h["term"] for h in r2["hits"]]
    assert "处女航" in terms, f"真问题没报出来：{r2['hits']}"
    assert "处女星号" not in terms, f"白名单词混进 hits：{terms}"


def t_l1_replace():
    r = si.classify("这是她的处女航")
    assert len(r["hits"]) == 1, r
    h = r["hits"][0]
    assert h["layer"] == "L1" and h["term"] == "处女航" and h["suggestion"] == "首航", h


def t_l2_has_suggestion():
    r = si.classify("天啊 这车太快了")
    assert len(r["hits"]) == 1, r
    h = r["hits"][0]
    assert h["layer"] == "L2" and h["suggestion"] == "天呐", h


def t_l3_no_suggestion():
    """L3（原文即贬义）只标注，不给替换建议——字幕不替角色洗白。"""
    r = si.classify("别像个女人一样")
    assert r["hits"], "L3 没命中"
    assert all(h["layer"] == "L3" and h["suggestion"] == "" for h in r["hits"]), r["hits"]


def t_layer_filter():
    r = si.scan_text("处女航 天啊 像个女人", layers=("L1",))
    assert [h["layer"] for h in r["hits"]] == ["L1"], r["hits"]


def t_ass_tags_ignored():
    """ASS 覆盖标签里的字不能被当成内容。"""
    r = si.classify("{\\i1}处女航{\\i0}")
    assert [h["term"] for h in r["hits"]] == ["处女航"], r


# ══════════════════════════════════════════════════════════════════
# 2. 清单与文档同源
# ══════════════════════════════════════════════════════════════════

def t_list_in_sync_with_md():
    """脚本内置清单里的每个词，必须在 references/inclusive-language.md 出现。

    为什么锁这个：内置清单是运行时唯一依据，md 是给人读的说明。
    两边漂移的话，人改 md 以为生效了，实际脚本不认——静默失效，最难发现。
    """
    md = os.path.join(SKILL_ROOT, "references", "inclusive-language.md")
    assert os.path.exists(md), f"缺清单文档：{md}"
    with open(md, "r", encoding="utf-8") as f:
        text = f.read()
    missing = [t for t in list(si.L1) + list(si.L2) + list(si.L3) + list(si.WHITELIST)
               if t not in text]
    assert not missing, f"这些词在脚本里有、md 里没有：{missing}"


def t_no_overlap_l1_whitelist():
    """白名单与 L1/L2 不能有交集——同一个词两层都有，处置就矛盾了。"""
    a = set(si.L1) | set(si.L2) | set(si.L3)
    b = set(si.WHITELIST)
    assert not (a & b), f"清单自相矛盾：{a & b}"


# ══════════════════════════════════════════════════════════════════
# 3. 端到端：扫 ASS
# ══════════════════════════════════════════════════════════════════

def t_scan_ass_hits_and_whitelist():
    fx = Fixture()
    try:
        r = si.scan_ass(fx.ass, fx.srt)
        hit_terms = {h["term"] for h in r["hits"]}
        wl_terms = {h["term"] for h in r["whitelisted"]}
        assert hit_terms == {"处女航", "天啊"}, f"候选不对：{hit_terms}"
        assert wl_terms == {"母头", "处女座", "夫妻肺片", "公螺纹"}, \
            f"白名单不对：{wl_terms}"
        # 上下文带上英文，L2 判语境要用
        hit2 = next(h for h in r["hits"] if h["term"] == "天啊")
        assert "My God" in hit2["en"], f"没带上英文上下文：{hit2['en']!r}"
    finally:
        fx.close()


def t_cli_exit_code():
    """有候选 → 1，无候选 → 0。这是「可操作信号」，不是错误。"""
    fx = Fixture()
    try:
        p = subprocess.run([PY, os.path.join(SCRIPTS, "scan_inclusive.py"), fx.ass],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 1, f"有候选应返回 1，实际 {p.returncode}\n{p.stderr}"

        clean = os.path.join(fx.dir, "clean.ass")
        with open(clean, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER.replace("英文,Arial", "英文,Arial")
                    + 'Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,把这个母头插上\n')
        p2 = subprocess.run([PY, os.path.join(SCRIPTS, "scan_inclusive.py"), clean],
                            capture_output=True, text=True, encoding="utf-8")
        assert p2.returncode == 0, f"只有白名单应返回 0，实际 {p2.returncode}\n{p2.stderr}"
    finally:
        fx.close()


def t_cli_json_shape():
    import json as _json
    fx = Fixture()
    try:
        out = os.path.join(fx.dir, "incl.json")
        subprocess.run([PY, os.path.join(SCRIPTS, "scan_inclusive.py"), fx.ass,
                        "--json", out], capture_output=True, text=True, encoding="utf-8")
        with open(out, "r", encoding="utf-8") as f:
            d = _json.load(f)
        assert d["hits"] and d["whitelisted"], d
        for h in d["hits"]:
            assert h["layer"] in ("L1", "L2", "L3"), h
            assert "suggestion" in h and "text" in h, h
        for w in d["whitelisted"]:
            assert w["suggestion"] == "", f"白名单不该给建议：{w}"
    finally:
        fx.close()


def t_english_track_not_scanned():
    """英文轨不扫：那是源片台词，不是译文。"""
    fx = Fixture()
    try:
        extra = os.path.join(fx.dir, "en.ass")
        with open(extra, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER
                    + 'Dialogue: 0,0:00:00.00,0:00:02.00,英文,,0,0,0,,处女航\n')
        r = si.scan_ass(extra)
        assert not r["hits"] and not r["whitelisted"], r
    finally:
        fx.close()


# ══════════════════════════════════════════════════════════════════
# 2. 两种「返回 0 条」必须能区分：干净 vs 漏检
#
# 这两个用例锁的是同一类失效模式——**静默漏检**。第 8 类扫描输出 0 条候选
# 时，人只会理解为「这集干净」。如果实际是一句没扫（样式名认不出、或被收了
# 三次又恰好去重掉了），那就是最坏的结果：报告说干净，其实没干活。
# ══════════════════════════════════════════════════════════════════

#: 样式名一律叫 Default（大量老工程、转码工具、人工拼的 ASS 都长这样）。
#: `style_to_track` 认不出它，原样返回 "Default"，于是每个事件都被 continue。
ASS_HEADER_DEFAULT = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ASS_BODY_DEFAULT = """Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,这是我们的处女航，穿越水库很顺利。
Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,Plug the female connector in.
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,这个母头跟这个插头完美契合。
"""


def t_ass_style_unrecognized_falls_back():
    """样式名全认不出时必须兜底判中文轨，不能返回「候选 0 条」了事。

    没有这个兜底，症状是「扫描完成，无候选」——和真的干净长得一模一样。
    所以要同时锁两件事：hits 真的出来了 + track_fallback 这个标志位为真
    （下游报告靠它打降级警示，标志位丢了警示也就没了）。
    """
    fx = Fixture()
    try:
        p = os.path.join(fx.dir, "e01.ass")
        with open(p, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER_DEFAULT + ASS_BODY_DEFAULT)

        r = si.scan_ass(p)
        assert r["track_fallback"] is True, \
            f"样式名全不可识别时应置 track_fallback=True，实际 {r['track_fallback']}"
        terms = [h["term"] for h in r["hits"]]
        assert "处女航" in terms, f"兜底后仍没扫到处女航，hits={r['hits']}"
        # 兜底是按「含汉字」判的，英文行不该被当成中文轨收进来
        assert all(h["track"] == "中文" for h in r["hits"]), \
            f"兜底轨道应记为中文，实际 {[h['track'] for h in r['hits']]}"
        # 白名单照样生效：兜底不是「全放过」
        assert any(w["term"] == "母头" for w in r["whitelisted"]), r["whitelisted"]
    finally:
        fx.close()


def t_style_recognized_no_fallback_flag():
    """样式名正常时 track_fallback 必须是 False——否则警示会天天误报。

    降级提示只在真降级时出现才有人看；如果正常文件也挂个「判不出轨道」，
    三天之后所有人都会无视这条提示，等于没有。
    """
    fx = Fixture()
    try:
        r = si.scan_ass(fx.ass)
        assert r["track_fallback"] is False, \
            f"样式名可识别时不该置降级标志，实际 {r['track_fallback']}"
        assert r["hits"], "正常文件也该有候选"
    finally:
        fx.close()


def t_single_file_not_collected_thrice():
    """CLI 传单个 .ass 时只能收一次。

    历史缺陷：`_collect(target, ext)` 在目标是单文件时无视 ext，于是 main 按
    `.ass`/`.ssa`/`.srt` 三轮各收一次同一个文件 → 「扫描对象 3 个文件」、
    候选三份重复。后果不只是难看：fixes.json 会跟着写三条同样的修改，
    apply 时同一行被改三次，verify 直接红。
    """
    fx = Fixture()
    try:
        out = os.path.join(fx.dir, "one.md")
        p = subprocess.run([PY, os.path.join(SCRIPTS, "scan_inclusive.py"),
                            fx.ass, "--md", out],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode in (0, 1), f"异常退出 {p.returncode}\n{p.stderr}"
        with open(out, "r", encoding="utf-8") as f:
            md = f.read()
        assert "扫描对象：1 个文件" in md, f"单个文件被重复收集：\n{md[:800]}"
        # 候选表里 `处女航` 只该有一行（同一行内会因「命中词 + 现译文本」出现两次，
        # 所以按行数而不是按字符串次数算）
        rows = [ln for ln in md.splitlines()
                if ln.startswith("| L1 |") and "处女航" in ln]
        assert len(rows) == 1, f"处女航 候选行出现 {len(rows)} 行，疑似重复：\n{rows}"
        wl_rows = [ln for ln in md.splitlines()
                   if ln.startswith("| `母头`")]
        assert len(wl_rows) == 1, f"白名单 母头 出现 {len(wl_rows)} 行：\n{wl_rows}"
    finally:
        fx.close()


def t_collect_respects_ext():
    """`_collect` 单文件时按扩展名过滤；目录时按扩展名筛选。"""
    fx = Fixture()
    try:
        assert si._collect(fx.ass, ".ass") == [fx.ass], "单 .ass 应被收"
        assert si._collect(fx.ass, ".srt") == [], "单 .ass 在 .srt 轮不该被收"
        assert si._collect(fx.ass, ".ssa") == [], "单 .ass 在 .ssa 轮不该被收"
        got = si._collect(fx.dir, ".ass")
        assert got == [fx.ass], f"目录收 .ass 应只有 1 个，实际 {got}"
    finally:
        fx.close()


# ══════════════════════════════════════════════════════════════════
# 5. 四子域（A 性别 / B 宗教 / C 政治 / D 法律）
# ══════════════════════════════════════════════════════════════════

def t_hit_has_domain_and_action():
    """每条 hit 必须带子域与 action——下游按 action 决定能不能进 fixes.json，
    缺字段会让 C 子域的 flag 被当成 fix 落盘。"""
    r = si.classify("处女航 天啊 中港台 死翘翘")
    assert r["hits"], r
    for h in r["hits"]:
        assert h["domain"] in si.DOMAIN_NAMES, h
        assert h["action"] in ("fix", "flag"), h
    doms = {h["domain"] for h in r["hits"]}
    assert doms == {"A", "B", "C", "D"}, f"四子域未全覆盖：{doms}"


def t_political_never_fix_by_default():
    """C 子域默认只 flag、不给建议——政治是判断问题，不是词语问题。"""
    r = si.classify("这次是大陆两个厂家合作。")
    c = [h for h in r["hits"] if h["domain"] == "C"]
    assert c, f"C 子域没扫到：{r['hits']}"
    assert all(h["action"] == "flag" and h["suggestion"] == "" for h in c), c


def t_politics_flag_only_unlocks_l1():
    """--politics 只放开 L1（`中港台`），L2（`大陆`）仍只标注。"""
    r = si.classify("中港台三地同步 这次是大陆两个厂家", allow_politics=True)
    by = {h["term"]: h for h in r["hits"] if h["domain"] == "C"}
    assert by["中港台"]["suggestion"], by
    assert by["中港台"]["action"] == "fix", by
    assert by["大陆"]["suggestion"] == "", by
    assert by["大陆"]["action"] == "flag", by


def t_political_whitelist_geo_terms():
    """`大陆架`/`台湾地区` 等正常用法不能被当成主权表述——这是本子域最危险的误报：
    把「大陆架」改成「中国内地架」比漏改更丢人。"""
    r = si.classify("大陆架式进气口 台湾地区 台湾卤肉饭")
    assert not [h for h in r["hits"] if h["domain"] == "C"], r["hits"]
    wl = {h["term"] for h in r["whitelisted"]}
    assert {"大陆架", "台湾地区", "台湾卤肉饭"} <= wl, wl


def t_domain_filter():
    r = si.scan_text("处女航 天啊 中港台", domains=("C",))
    assert r["hits"] and all(h["domain"] == "C" for h in r["hits"]), r["hits"]


def t_cli_md_sections():
    """CLI 报告必须按子域分段，且 C 段说明「只标注不改」。"""
    fx = Fixture()
    try:
        extra = os.path.join(fx.dir, "p.ass")
        with open(extra, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER
                    + 'Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,这次是大陆两个厂家\n')
        out = os.path.join(fx.dir, "p.md")
        subprocess.run([PY, os.path.join(SCRIPTS, "scan_inclusive.py"), extra,
                        "--md", out], capture_output=True)
        md = open(out, encoding="utf-8").read()
        assert "## C 政治与主权" in md, md[:600]
        assert "只标注" in md and "不改" in md, md[:600]
        assert "本 skill 不承担时政立场判定" in md, md[:900]
    finally:
        fx.close()


if __name__ == "__main__":
    print("第 8 类：白名单 / 分层 / 清单同源")
    for n, fn in (
        ("白名单永不进 hits", t_whitelist_never_hits),
        ("白名单优先于 L1", t_whitelist_beats_l1),
        ("L1 硬替换建议", t_l1_replace),
        ("L2 语境建议", t_l2_has_suggestion),
        ("L3 只标注不给建议", t_l3_no_suggestion),
        ("--layer 过滤", t_layer_filter),
        ("ASS 标签不参与匹配", t_ass_tags_ignored),
        ("清单与 md 同源", t_list_in_sync_with_md),
        ("L1/L2 与白名单无交集", t_no_overlap_l1_whitelist),
        ("扫 ASS：候选 + 白名单", t_scan_ass_hits_and_whitelist),
        ("CLI 退出码 0/1", t_cli_exit_code),
        ("CLI JSON 结构", t_cli_json_shape),
        ("英文轨不扫", t_english_track_not_scanned),
        ("样式名认不出：兜底判中文轨", t_ass_style_unrecognized_falls_back),
        ("样式名正常：不挂降级标志", t_style_recognized_no_fallback_flag),
        ("单文件不被收三次", t_single_file_not_collected_thrice),
        ("_collect 按扩展名过滤", t_collect_respects_ext),
        ("hit 带子域与 action", t_hit_has_domain_and_action),
        ("C 子域默认不 fix", t_political_never_fix_by_default),
        ("--politics 只放开 L1", t_politics_flag_only_unlocks_l1),
        ("C 子域白名单：地理术语", t_political_whitelist_geo_terms),
        ("--domain 过滤", t_domain_filter),
        ("报告按子域分段", t_cli_md_sections),
    ):
        test(n, fn)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
