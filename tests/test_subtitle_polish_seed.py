# -*- coding: utf-8 -*-
"""scan_seed.py（第 8 类线索器）：它只定位，不判断。

为什么这个测试非写不可：
`scan_seed` 的整个存在价值是「**不能**被当成判据」。如果哪天有人给它加了
「有候选就返回 1」的退出码、或者把白名单候选直接从输出里丢掉、或者把
`instruction`（「这是线索不是待办清单」）删掉——它还照样跑、照样出 JSON，
但整个审计流程会悄悄退回「词表没命中 = 干净」的老路，而**没有任何报错**。

所以这里锁的是它的**边界**，不是它的准确率：
  （a）退出码恒 0，不给「有无问题」的信号
  （b）五类形态都能出锚点（含词表外的形态）
  （c）白名单候选**保留**在 whitelist_hits 里，不被丢弃、也不混进 lexicon
  （d）instruction 非空且明确写着「线索不是结论」
  （e）切片正文里的 `|` 不把字段切错
  （f）读不出行时返回 2，而不是 0（「没扫到」不许伪装成「干净」）
  （g）上下文段：相邻锚点归并，前后各带 _CTX_LINES 行

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_seed.py
"""
from __future__ import annotations

import io
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

import scan_seed as ss

PY = sys.executable
PASS = 0
FAIL = 0

TMP = tempfile.mkdtemp(prefix="seedtest_")


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


def _write(name, text):
    p = os.path.join(TMP, name)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def _run(args, **kw):
    return subprocess.run([PY, os.path.join(SCRIPTS, "scan_seed.py")] + args,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


# ── 夹具 ────────────────────────────────────────────────────────────────────
# 切片行格式：<srt_id> | <ass_time> | <英文> | <中文> | <注释>
# 覆盖五种形态各至少一处；第 8 行中文里带一个 `|`，用来验证字段切分。

SLICE = """# slice e05 p1
1 | 0:00:01.00-0:00:03.00 | This is her maiden voyage. | 这是她的处女航
2 | 0:00:03.00-0:00:05.00 | Plug the female connector in. | 把这个母头插上
3 | 0:00:05.00-0:00:07.00 | I'm a Virgo. | 我是处女座
4 | 0:00:07.00-0:00:09.00 | Nothing special here. | 这里没什么特别的
5 | 0:00:09.00-0:00:11.00 | Nothing special either. | 这也没什么
6 | 0:00:11.00-0:00:13.00 | Bloody hell, that was close. | 天啊 好险
7 | 0:00:13.00-0:00:15.00 | He's a real mother hen. | 他像个娘们似的
8 | 0:00:15.00-0:00:17.00 | We ship it from the mainland. | 我们从大陆发货 | 注:另一段
9 | 0:00:17.00-0:00:19.00 | It rained all week. | 下了一整周的雨
10 | 0:00:19.00-0:00:21.00 | The boat sank near the Virgin Islands. | 船在处女群岛附近沉了
"""

# 干净切片：一个锚点都没有。用来验证「0 锚点 ≠ 退出码非 0」。
CLEAN_SLICE = """1 | 0:00:01.00-0:00:03.00 | The chassis is stiff. | 底盘很硬
2 | 0:00:03.00-0:00:05.00 | Brakes are fine. | 刹车没问题
"""

ASS_HEADER = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 英文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ASS_BODY = """Dialogue: 0,0:00:01.00,0:00:03.00,英文,,0,0,0,,This is her maiden voyage.
Dialogue: 0,0:00:01.00,0:00:03.00,中文,,0,0,0,,这是她的处女航
Dialogue: 0,0:00:03.00,0:00:05.00,英文,,0,0,0,,Plug the female connector in.
Dialogue: 0,0:00:03.00,0:00:05.00,中文,,0,0,0,,把这个母头插上
Dialogue: 0,0:00:05.00,0:00:07.00,英文,,0,0,0,,{\\an8}My God, this thing is fast.
Dialogue: 0,0:00:05.00,0:00:07.00,中文,,0,0,0,,{\\an8}天啊 这车太快了
"""


# ── (a) 退出码恒 0，不给「有无问题」的信号 ──────────────────────────────────

def t_exit_zero_with_anchors():
    p = _write("s_hit.txt", SLICE)
    r = _run([p])
    assert r.returncode == 0, f"有锚点时退出码应为 0，实际 {r.returncode}"


def t_exit_zero_without_anchors():
    """这是整个设计的核心：干净不等于「通过」，有料也不等于「失败」。"""
    p = _write("s_clean.txt", CLEAN_SLICE)
    r = _run([p])
    assert r.returncode == 0, \
        f"0 锚点时退出码也必须是 0（否则调用方会把它当门禁），实际 {r.returncode}"
    seed = json.loads(r.stdout)
    assert seed["anchors"] == [], f"期望 0 锚点，实际 {seed['anchors']}"
    assert seed["n_rows"] == 2


def t_exit_codes_indistinguishable():
    """把两种情况的返回值并排比：不许出现「能区分有没有问题」的信号。"""
    a = _run([_write("s_cmp_a.txt", SLICE)])
    b = _run([_write("s_cmp_b.txt", CLEAN_SLICE)])
    assert a.returncode == b.returncode == 0, \
        f"两种输入的退出码必须相同（都是 0），实际 {a.returncode} vs {b.returncode}"


# ── (b) 五类形态都能出锚点 ──────────────────────────────────────────────────

def t_all_five_forms_present():
    seed = ss.build_seeds(ss.read_slice(_write("s_forms.txt", SLICE)))
    forms = {a["form"] for a in seed["anchors"]}
    expect = {"lexicon", "whitelist_hits", "interjection",
              "derogatory", "geo_political"}
    missing = expect - forms
    assert not missing, f"缺形态：{missing}（实际 {sorted(forms)}）"


def t_forms_have_required_fields():
    seed = ss.build_seeds(ss.read_slice(_write("s_fields.txt", SLICE)))
    assert seed["anchors"], "夹具应当出锚点"
    for a in seed["anchors"]:
        for k in ("srt_id", "ass_time", "form", "term", "zh", "en", "row_index"):
            assert k in a, f"锚点缺字段 {k}: {a}"


def t_beyond_lexicon_caught():
    """词表外的形态必须能被锚到——这正是加这层正则的全部理由。"""
    rows = ss.read_slice(_write("s_beyond.txt", SLICE))
    by_id = {a["srt_id"]: a for a in ss.build_seeds(rows)["anchors"]}

    # `Bloody hell` 不在第 8 类词表里，但属感叹起誓形态
    assert 6 in by_id and by_id[6]["form"] == "interjection", \
        f"第 6 行 Bloody hell 应以 interjection 锚出，实际 {by_id.get(6)}"
    # `像...娘们` 是贬义称谓形态
    assert 7 in by_id and by_id[7]["form"] == "derogatory", \
        f"第 7 行应以 derogatory 锚出，实际 {by_id.get(7)}"
    # `mainland` 属主权地域形态（词表故意不收 mainland 这个词）
    assert 8 in by_id and by_id[8]["form"] == "geo_political", \
        f"第 8 行 mainland 应以 geo_political 锚出，实际 {by_id.get(8)}"


# ── (c) 白名单候选保留，不丢弃、不混层 ──────────────────────────────────────

def t_whitelist_kept_not_dropped():
    """白名单是「默认判不是问题」，不是「从输出里消失」。"""
    rows = ss.read_slice(_write("s_wl.txt", SLICE))
    seed = ss.build_seeds(rows)
    wl = [a for a in seed["anchors"] if a["form"] == "whitelist_hits"]
    assert wl, "`母头` / `处女座` 应以 whitelist_hits 出现，不能被静默丢弃"
    terms = {a["term"] for a in wl}
    assert terms & {"母头", "处女座"}, f"白名单候选里应含母头/处女座，实际 {terms}"


def t_whitelist_not_in_lexicon():
    """同一行不许既算白名单又算词表命中——否则 subagent 会收到矛盾指令。"""
    rows = ss.read_slice(_write("s_wl2.txt", SLICE))
    seed = ss.build_seeds(rows)
    per_row = {}
    for a in seed["anchors"]:
        per_row.setdefault(a["row_index"], set()).add(a["form"])
    for idx, forms in per_row.items():
        assert not ({"lexicon", "whitelist_hits"} <= forms), \
            f"第 {idx} 行同时出现在 lexicon 与 whitelist_hits：{forms}"


def t_whitelist_forms_survive_md():
    """md 输出里也必须能看见白名单候选（人读版不许把它藏起来）。"""
    seed = ss.build_seeds(ss.read_slice(_write("s_wl3.txt", SLICE)))
    md = ss.render_md_seed(seed)
    assert "白名单候选" in md, "md 输出应标注白名单候选行"


# ── (d) instruction：必须原样带着「线索不是结论」 ───────────────────────────

def t_instruction_nonempty_and_warns():
    seed = ss.build_seeds(ss.read_slice(_write("s_instr.txt", SLICE)))
    ins = seed["instruction"]
    assert ins and len(ins) > 80, f"instruction 太短或为空：{ins!r}"
    assert "线索" in ins and "不是待办清单" in ins, \
        f"instruction 必须写明「线索不是待办清单」，实际：{ins[:80]}"
    assert "整片读完" in ins, "instruction 必须要求整片读完，不许只看锚点行"


def t_instruction_in_both_formats():
    """json 与 md 两条路都得带上 instruction，缺一路等于白写。"""
    seed = ss.build_seeds(ss.read_slice(_write("s_instr2.txt", SLICE)))
    js = json.dumps(seed, ensure_ascii=False)
    md = ss.render_md_seed(seed)
    assert "不是待办清单" in js, "json 输出丢了 instruction"
    assert "不是待办清单" in md, "md 输出丢了 instruction"


def t_instruction_forbids_whitelist_rewrite():
    """白名单行只许写 L3 给理由，不许自己造替换词。"""
    ins = ss.build_seeds(ss.read_slice(_write("s_instr3.txt", SLICE)))["instruction"]
    assert "whitelist_hits" in ins, "instruction 应指出白名单对应的 form 名"
    assert "L3" in ins, "instruction 应说明白名单行只能写 L3"


def t_empty_seed_still_has_instruction():
    """0 锚点时 instruction 也不能省——省了 subagent 就以为这块不用读。"""
    seed = ss.build_seeds(ss.read_slice(_write("s_instr4.txt", CLEAN_SLICE)))
    assert seed["instruction"], "0 锚点时 instruction 仍必须存在"
    md = ss.render_md_seed(seed)
    assert "不等于" in md, "0 锚点的 md 必须写明「这不等于没有敏感问题」"


# ── (e) 切片正文里的 `|` 不把字段切错 ───────────────────────────────────────

def t_pipe_inside_text_not_split():
    rows = ss.read_slice(_write("s_pipe.txt", SLICE))
    r8 = [r for r in rows if r["srt_id"] == 8]
    assert r8, "第 8 行没读出来"
    assert "大陆" in r8[0]["zh"], f"中文字段被 `|` 切坏了：{r8[0]['zh']!r}"
    assert r8[0]["zh"].startswith("我们从大陆发货"), \
        f"中文只该取到第一个 `|` 之前，实际：{r8[0]['zh']!r}"


def t_pipe_row_still_anchored():
    """被 `|` 干扰的行照样要能出锚点，不能因为切歪了而静默漏掉。"""
    rows = ss.read_slice(_write("s_pipe2.txt", SLICE))
    ids = {a["srt_id"] for a in ss.build_seeds(rows)["anchors"]}
    assert 8 in ids, "第 8 行（含 `|`）应仍被锚出"


def t_comments_and_blanks_skipped():
    rows = ss.read_slice(_write("s_cmt.txt", SLICE))
    assert len(rows) == 10, f"注释行应跳过、只留 10 行，实际 {len(rows)}"


# ── (f) 读不出行 → 2，不许伪装成「干净」 ────────────────────────────────────

def t_unreadable_slice_returns_2():
    p = _write("s_bad.txt", "这不是切片格式\n随便什么内容\n")
    r = _run([p])
    assert r.returncode == 2, f"读不出行时应返回 2，实际 {r.returncode}"
    assert "没扫到" in (r.stderr or ""), \
        f"报错文案必须点明「这不是干净，是没扫到」，实际：{r.stderr!r}"


def t_missing_file_returns_2():
    r = _run([os.path.join(TMP, "no_such_file.txt")])
    assert r.returncode == 2, f"文件不存在应返回 2，实际 {r.returncode}"


def t_srt_input_refused():
    """SRT 是英文源，扫它没有意义——必须拒绝而不是返回 0。"""
    p = _write("s_refuse.srt", "1\n00:00:01,000 --> 00:00:02,000\nhello\n")
    r = _run([p])
    assert r.returncode == 2, f"SRT 输入应被拒绝（2），实际 {r.returncode}"
    assert "没有意义" in (r.stderr or ""), f"应说明拒绝理由，实际：{r.stderr!r}"


def t_unknown_ext_returns_2():
    p = _write("s_unknown.xyz", "1 | 0:00:01.00 | a | b\n")
    r = _run([p])
    assert r.returncode == 2, f"认不出的扩展名应返回 2，实际 {r.returncode}"


# ── (g) 归并段与上下文 ──────────────────────────────────────────────────────

def t_adjacent_anchors_merged():
    """相距 ≤ _CTX_LINES 的锚点合成一段：subagent 按段读，不按锚点读。"""
    seed = ss.build_seeds(ss.read_slice(_write("s_merge.txt", SLICE)))
    segs = seed["segments"]
    assert segs, "应当有归并段"
    # 夹具里 1/2/3 连续命中、6/7/8 连续命中 → 段数远少于锚点数
    assert len(segs) < len(seed["anchors"]), \
        f"锚点 {len(seed['anchors'])} 条应归并成更少的段，实际 {len(segs)} 段"


def t_context_padding():
    rows = ss.read_slice(_write("s_ctx.txt", SLICE))
    seed = ss.build_seeds(rows)
    for seg in seed["segments"]:
        span_hit = seg["srt_id_to"] - seg["srt_id_from"]
        span_ctx = seg["context_to"] - seg["context_from"]
        assert span_ctx > span_hit or seg["context_from"] == rows[0]["srt_id"], \
            f"段上下文没有外扩：命中 {seg['srt_id_from']}–{seg['srt_id_to']}，" \
            f"上下文 {seg['context_from']}–{seg['context_to']}"


def t_context_never_out_of_bounds():
    rows = ss.read_slice(_write("s_ctx2.txt", SLICE))
    seed = ss.build_seeds(rows)
    lo, hi = rows[0]["srt_id"], rows[-1]["srt_id"]
    for seg in seed["segments"]:
        assert lo <= seg["context_from"] <= hi, f"上下文越界：{seg['context_from']}"
        assert lo <= seg["context_to"] <= hi, f"上下文越界：{seg['context_to']}"
        assert seg["context"], "段里必须有上下文行，否则 agent 判不出语境"


def t_segment_anchors_included_in_context_index():
    """段里列出的锚点，其行必须落在该段的上下文范围内。"""
    seed = ss.build_seeds(ss.read_slice(_write("s_ctx3.txt", SLICE)))
    for seg in seed["segments"]:
        for a in seg["anchors"]:
            assert seg["context_from"] <= a["srt_id"] <= seg["context_to"], \
                f"锚点 {a['srt_id']} 不在上下文 " \
                f"{seg['context_from']}–{seg['context_to']} 内"


# ── ASS 直读路径 ────────────────────────────────────────────────────────────

def t_read_ass_zh_only():
    p = _write("s_a.ass", ASS_HEADER + ASS_BODY)
    rows = ss.read_ass(p)
    assert len(rows) == 3, f"中文轨应 3 行，实际 {len(rows)}"
    assert all(r["zh"] for r in rows), "每行都应有中文正文"


def t_ass_tags_do_not_break_anchor():
    """`{\\an8}` 这类标签不能干扰锚定，也不能残留在 zh 里。"""
    p = _write("s_tags.ass", ASS_HEADER + ASS_BODY)
    rows = ss.read_ass(p)
    joined = "".join(r["zh"] for r in rows)
    assert "\\an8" not in joined, f"ASS 标签没被清掉：{joined!r}"
    # 注意 srt_id 是 **事件序号**（含英文轨），不是中文轨的第几条：
    # ASS_BODY 里 `天啊` 是第 6 个事件。拿它当「第 5 行中文」会判错。
    by_term = {(a["form"], a["term"]): a for a in ss.build_seeds(rows)["anchors"]}
    hit = by_term.get(("interjection", "天啊"))
    assert hit, f"带标签的那行（天啊）应仍被锚出，实际 {sorted(by_term)}"
    assert hit["srt_id"] == 6, f"天啊所在事件序号应为 6，实际 {hit['srt_id']}"
    assert "\\an8" not in hit["zh"], f"锚点里残留了标签：{hit['zh']!r}"


def t_cli_ass_input_works():
    p = _write("s_cli.ass", ASS_HEADER + ASS_BODY)
    r = _run([p])
    assert r.returncode == 0, f"ASS 输入应正常，实际 {r.returncode}: {r.stderr}"
    seed = json.loads(r.stdout)
    assert seed["n_rows"] == 3 and seed["anchors"]


# ── 输出结构 ────────────────────────────────────────────────────────────────

def t_cli_json_shape():
    seed = json.loads(_run([_write("s_shape.txt", SLICE)]).stdout)
    for k in ("base", "n_rows", "anchors", "segments", "instruction"):
        assert k in seed, f"json 缺顶层字段 {k}"
    assert isinstance(seed["anchors"], list)
    assert isinstance(seed["segments"], list)


def t_cli_out_file_written():
    out = os.path.join(TMP, "out", "seed.json")
    r = _run([_write("s_out.txt", SLICE), "--out", out])
    assert r.returncode == 0, r.stderr
    assert os.path.exists(out), "──out 没写文件"
    with io.open(out, encoding="utf-8") as f:
        assert "instruction" in f.read()


def t_cli_md_format():
    r = _run([_write("s_mdfmt.txt", SLICE), "--fmt", "md"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.lstrip().startswith("#"), "md 输出应以标题开头"
    assert "线索" in r.stdout and "锚点" in r.stdout


def t_stderr_summary_says_not_conclusion():
    """人看的那行统计也必须带「线索，非结论」，防止被当成绩单。"""
    r = _run([_write("s_stderr.txt", SLICE)])
    assert "非结论" in (r.stderr or ""), f"stderr 应带「线索，非结论」，实际：{r.stderr!r}"


def t_base_recorded():
    p = _write("s_base.txt", SLICE)
    seed = json.loads(_run([p]).stdout)
    assert seed["base"] == p, f"base 应记录来源，实际 {seed['base']!r}"


# ── 入口 ────────────────────────────────────────────────────────────────────

def main():
    try:
        print("scan_seed.py —— 只定位，不判断")
        for n, fn in (
            ("(a) 有锚点退出码 0", t_exit_zero_with_anchors),
            ("(a) 0 锚点退出码也是 0", t_exit_zero_without_anchors),
            ("(a) 两种输入退出码不可区分", t_exit_codes_indistinguishable),
            ("(b) 五类形态齐全", t_all_five_forms_present),
            ("(b) 锚点字段完整", t_forms_have_required_fields),
            ("(b) 词表外形也能锚到", t_beyond_lexicon_caught),
            ("(c) 白名单候选保留不丢", t_whitelist_kept_not_dropped),
            ("(c) 白名单不混进 lexicon", t_whitelist_not_in_lexicon),
            ("(c) md 里看得见白名单候选", t_whitelist_forms_survive_md),
            ("(d) instruction 非空且警示", t_instruction_nonempty_and_warns),
            ("(d) 两种格式都带 instruction", t_instruction_in_both_formats),
            ("(d) instruction 禁止绕白名单改写", t_instruction_forbids_whitelist_rewrite),
            ("(d) 0 锚点也有 instruction", t_empty_seed_still_has_instruction),
            ("(e) 正文 `|` 不切坏字段", t_pipe_inside_text_not_split),
            ("(e) 含 `|` 的行仍被锚出", t_pipe_row_still_anchored),
            ("(e) 注释/空行跳过", t_comments_and_blanks_skipped),
            ("(f) 读不出行返回 2 且报『没扫到』", t_unreadable_slice_returns_2),
            ("(f) 文件不存在返回 2", t_missing_file_returns_2),
            ("(f) SRT 输入被拒", t_srt_input_refused),
            ("(f) 未知扩展名返回 2", t_unknown_ext_returns_2),
            ("(g) 相邻锚点归并成段", t_adjacent_anchors_merged),
            ("(g) 上下文外扩", t_context_padding),
            ("(g) 上下文不越界", t_context_never_out_of_bounds),
            ("(g) 段锚点落在上下文内", t_segment_anchors_included_in_context_index),
            ("ASS 只读中文轨", t_read_ass_zh_only),
            ("ASS 标签不干扰锚定", t_ass_tags_do_not_break_anchor),
            ("ASS 走 CLI 正常", t_cli_ass_input_works),
            ("输出 json 结构", t_cli_json_shape),
            ("--out 写文件", t_cli_out_file_written),
            ("--fmt md", t_cli_md_format),
            ("stderr 带「非结论」", t_stderr_summary_says_not_conclusion),
            ("base 记录来源", t_base_recorded),
        ):
            test(n, fn)

        print(f"\n通过 {PASS} / 失败 {FAIL}")
        return 0 if FAIL == 0 else 1
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
