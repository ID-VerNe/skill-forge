# -*- coding: utf-8 -*-
"""回归测试:跨轮次回归检测(issue #5 #6)+ 规则表结构性约束(issue #7)。

背景(issue #6)——三轮改了三次、每轮都"通过":

    R6  「这正是菲尔的强项」→「这就是菲尔的地盘」   （改错）
    R7  「这就是菲尔的地盘」→「这正是菲尔的强项」   （改回来）
    R8  「这正是菲尔的强项」→「这就是菲尔的地盘」   （又改回去）

三轮 `verify_fixes` 都是 0 失败、`cross_check` 都是 0 预警——**没有任何信号
能发现这个来回**。原因是审计 agent 每轮只看到"当前盘面 + 英文源",不知道
这一行上周刚被改过。

修法:`lib/regress.py` 只用字符串判据(不需要模型)给出四条线索——
连续改动 / 疑似反向 / 已收敛 / 疑似回归。

背景(issue #7)——`FORMAL_WORDS` 里一个空串会让规则静默变味:

    if en_pat and re.search(en_pat, en, re.I):   # "" → 假, 跳过查源
    confidence = "medium" if en_pat is None else "high"   # "" is None → 假 → high

空串既"没查来源"又"标了 high",等于把没验过的当成验过的。修法是启动自检
直接报错,并提供 `--audit-rules` 让人看清每条规则落在哪一组。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_regression.py
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

from lib import regress as rg

PASS = 0
FAIL = 0

PY = sys.executable


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


# ══════════════════════════════════════════════════════════════════
# 夹具
# ══════════════════════════════════════════════════════════════════

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

# 3 块，中文分别是「菲尔的地盘」/「随便一句」/「无关」
ASS_BODY = """Dialogue: 0,0:00:00.00,0:00:02.00,英文,,0,0,0,,This is Phil's bag.
Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,这就是菲尔的地盘
Dialogue: 0,0:00:02.00,0:00:04.00,英文,,0,0,0,,Right, walk me through this.
Dialogue: 0,0:00:02.00,0:00:04.00,中文,,0,0,0,,好了 再讲一遍
Dialogue: 0,0:00:04.00,0:00:06.00,英文,,0,0,0,,MX-5, yes.
Dialogue: 0,0:00:04.00,0:00:06.00,中文,,0,0,0,,MX-5 是的
"""

SRT = """1
00:00:00,000 --> 00:00:02,000
This is Phil's bag.

2
00:00:02,000 --> 00:00:04,000
Right, walk me through this.

3
00:00:04,000 --> 00:00:06,000
MX-5, yes.
"""


def _entry(batch, sid, old, new, track="中文", action="replace",
           file="F.ass", ts="", reason="", category="第4类"):
    return {
        "ts": ts, "batch_id": batch, "action": action, "file": file,
        "srt_id": sid, "track": track, "old_text": old, "new_text": new,
        "category": category, "reason": reason,
    }


def flipflop_trail():
    """issue #6 的原始轨迹:改错 → 改回来 → 又改错。"""
    return [
        _entry("R6", 1, "这正是菲尔的强项", "这就是菲尔的地盘", ts="2026-10-01T10:00:00"),
        _entry("R7", 1, "这就是菲尔的地盘", "这正是菲尔的强项", ts="2026-10-01T11:00:00"),
        _entry("R8", 1, "这正是菲尔的强项", "这就是菲尔的地盘", ts="2026-10-01T12:00:00"),
    ]


class WorkDir:
    """临时 .subtitle-polish 工作目录 + 一个可配的 log.jsonl。"""

    def __init__(self, entries=None):
        self.dir = tempfile.mkdtemp(prefix="sp-regress-")
        self.ass = os.path.join(self.dir, "e04.ass")
        self.srt = os.path.join(self.dir, "e04.srt")
        with open(self.ass, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER + ASS_BODY)
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write(SRT)
        if entries:
            self.write_log(entries)

    def write_log(self, entries):
        with open(os.path.join(self.dir, "log.jsonl"), "w", encoding="utf-8") as f:
            for e in entries:
                e = dict(e)
                e["file"] = self.ass  # 归一化路径：cross_check 用它当 ass_path
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _run(script, args, cwd=None):
    return subprocess.run([PY, os.path.join(SCRIPTS, script)] + args,
                          capture_output=True, text=True, encoding="utf-8",
                          cwd=cwd or SKILL_ROOT)


# ══════════════════════════════════════════════════════════════════
# 1. lib/regress.py 单元
# ══════════════════════════════════════════════════════════════════

def test_clean_strips_tags_and_ws():
    assert rg.clean("{\\be3}这就是 菲尔 的 地盘") == "这就是菲尔的地盘"
    assert rg.clean("") == ""
    assert rg.clean("   ") == ""


def test_history_keys_and_order():
    entries = flipflop_trail()
    h = rg.history(entries)
    assert len(h) == 1, f"同一 (file,sid,track) 应聚成一条，实际 {list(h)}"
    key = next(iter(h))
    assert key[1] == 1 and key[2] == "中文", key
    assert [x["batch"] for x in h[key]] == ["R6", "R7", "R8"], h[key]


def test_history_excludes_retime():
    entries = flipflop_trail() + [
        _entry("R8", 1, "", "", action="retime", ts="2026-10-01T12:30:00"),
        _entry("R8", 0, "", "", action="retime_curve", ts="2026-10-01T12:31:00"),
    ]
    h = rg.history(entries)
    got = [x["batch"] for x in next(iter(h.values()))]
    assert got == ["R6", "R7", "R8"], f"retime 不算文本改动，实际 {got}"


def test_conflicts_counts_rounds_not_entries():
    entries = flipflop_trail() + [
        _entry("R8", 1, "x", "y", ts="2026-10-01T12:40:00"),
    ]
    c = rg.conflicts(rg.history(entries))
    assert len(c) == 1, c
    assert c[0]["n_rounds"] == 3, f"R8 有两条也只能算一轮，实际 {c[0]['n_rounds']}"


def test_reversals_detects_flipback():
    # R8 又把文本改回 R6 的样子 → 与 R6 的相似度高于与 R7 的
    trail = rg.history(flipflop_trail())[("F.ass", 1, "中文")]
    rev = rg.reversals(trail)
    assert len(rev) == 1, f"应判 1 处疑似反向，实际 {rev}"
    assert rev[0]["round"] == "R8" and rev[0]["earlier_round"] == "R6", rev[0]
    assert rev[0]["sim_earlier"] > rev[0]["sim_prev"], rev[0]


def test_reversals_silent_on_monotone_drift():
    # 一路往同一个方向改，不该被判反向
    trail = [{"batch": "R6", "new": "这是菲尔的地盘啊"},
             {"batch": "R7", "new": "这是菲尔的地盘"},
             {"batch": "R8", "new": "这是菲尔的地盘呀"}]
    assert rg.reversals(trail) == [], "渐进改动不是反向"


def test_converged_is_impossible_on_consistent_log():
    """「连续两轮给出相同 new_text」在一致的日志里永远为假。

    这是设计缺陷，不是一个待修的 bug：trail 里相邻两条满足
    `old[i] == new[i-1]`，若再有 `new[i] == new[i-1]`，则 `old[i] == new[i]`
    —— 那是一条空改动，会被 _is_text_change 滤掉。

    所以 converged() 已删掉，换成可观测的 settled() / churn()。
    这条测试盯住「不要再把它加回来」。
    """
    assert not hasattr(rg, "converged"), \
        "converged() 在一致的日志里永远为假，不该存在；用 settled()/churn()"


def test_settled_excludes_recent_rounds():
    entries = flipflop_trail() + [
        _entry("R9", 500, "甲", "乙", ts="2026-10-01T13:00:00"),
    ]
    h = rg.history(entries)
    # 最近 1 轮 = R9 → #1 的最后改动是 R8，算「沉住」；#500 刚改，不算
    s = rg.settled(h, {"R9"})
    keys = [x["key"][1] for x in s]
    assert keys == [1], s
    assert s[0]["n_rounds"] == 3 and s[0]["last"]["batch"] == "R8", s[0]
    # 最近 5 轮覆盖全部 → 没有沉住的
    assert rg.settled(h, {"R1", "R6", "R7", "R8", "R9"}) == []


def test_churn_counts_overturned_rows():
    """批次沉住度：这一批改的行，后来又被改过的比例。"""
    entries = flipflop_trail()  # R6 改 #1、R7 再改 #1、R8 再改 #1
    rows = rg.churn(rg.history(entries))
    by = {r["batch"]: r for r in rows}
    assert [r["batch"] for r in rows] == ["R6", "R7", "R8"], rows
    assert by["R6"]["n"] == 1 and by["R6"]["again"] == 1, by["R6"]   # 后来被 R7 推翻
    assert by["R7"]["n"] == 1 and by["R7"]["again"] == 1, by["R7"]   # 后来被 R8 推翻
    assert by["R8"]["n"] == 1 and by["R8"]["again"] == 0, by["R8"]   # 最后一次，没人动它
    assert by["R8"]["rate"] == 0.0, by["R8"]


def test_history_excludes_noop_text_change():
    """old_text == new_text 的记录不算文本改动。

    真实来源：`retime` 在 `--manual-log` 里没有时间戳字段可用（issue #3），
    只能以 `replace` 补记，old 与 new 完全相同。S06E04 的真实 log 里因此
    把 #390 算成「3 轮改过」、英文轨算成「2 轮已收敛」——实际分别是 2 轮和
    1 轮，而 1 轮根本不该出现在「连续改动」里。
    """
    noop = _entry("R6_retime", 390,
                  "但是嗯那就好了如果你们能少做点影响生产力的事",
                  "但是嗯那就好了如果你们能少做点影响生产力的事",
                  ts="2026-10-01T10:30:00", category="时间轴", reason="纯 retime")
    real = _entry("R6_merge", 390, "但是嗯那就太好了",
                  "但是嗯那就好了如果你们能少做点影响生产力的事",
                  ts="2026-10-01T10:00:00")
    later = _entry("R10", 390, "但是嗯那就好了如果你们能少做点影响生产力的事",
                   "不过嗯你们要是能少干点影响生产力的活儿那就太好了",
                   ts="2026-10-01T11:00:00")
    h = rg.history([real, noop, later])
    trail = h[("F.ass", 390, "中文")]
    assert len(trail) == 2, f"空改动不该算一轮，实际 {[x['batch'] for x in trail]}"
    assert [x["batch"] for x in trail] == ["R6_merge", "R10"], trail

    # 只有一条真实改动的行，不该出现在「连续改动」里
    h2 = rg.history([real, noop])
    assert rg.conflicts(h2) == [], "1 轮改动不是连续改动"


def test_find_regressions_skips_noop_current():
    """本轮记录本身 old == new，谈不上「改掉了历史修好的译文」。"""
    cur = [_entry("R8", 1, "这正是菲尔的强项", "这正是菲尔的强项")]
    past = [_entry("R7", 1, "这就是菲尔的地盘", "这正是菲尔的强项")]
    assert rg.find_regressions(cur, past) == [], "文本没变就不该报疑似回归"


def test_find_regressions_exact():
    cur = [_entry("R8", 1, "这正是菲尔的强项", "这就是菲尔的地盘")]
    past = [_entry("R7", 1, "这就是菲尔的地盘", "这正是菲尔的强项")]
    r = rg.find_regressions(cur, past)
    assert len(r) == 1, f"应命中 1 条，实际 {r}"
    assert r[0]["kind"] == "exact" and r[0]["sim"] == 1.0, r[0]
    assert r[0]["hist"]["batch_id"] == "R7", r[0]


def test_find_regressions_near():
    cur = [_entry("R8", 1, "这正是菲尔的强项啊", "这就是菲尔的地盘")]
    past = [_entry("R7", 1, "这就是菲尔的地盘", "这正是菲尔强项")]
    r = rg.find_regressions(cur, past)
    assert len(r) == 1 and r[0]["kind"] == "near", r
    assert 0.55 <= r[0]["sim"] < 1.0, r[0]


def test_find_regressions_ignores_unrelated():
    cur = [_entry("R8", 1, "好了 再讲一遍", "从头说一遍")]
    past = [_entry("R7", 1, "这就是菲尔的地盘", "这正是菲尔的强项")]
    assert rg.find_regressions(cur, past) == [], "旧文本和历史上任何一版都不像，不该报"


def test_find_regressions_ignores_same_batch():
    cur = [_entry("R8", 1, "甲", "乙")]
    past = [_entry("R8", 1, "乙", "甲")]
    assert rg.find_regressions(cur, past) == [], "自己跟同一批比不算回归"


def test_find_regressions_skips_retime_and_blank_old():
    past = [_entry("R7", 1, "甲", "乙")]
    assert rg.find_regressions(
        [_entry("R8", 1, "", "", action="retime")], past) == [], "retime 不动文本"
    assert rg.find_regressions(
        [_entry("R8", 1, "  ", "乙")], past) == [], "old 为空没法判"


def test_find_regressions_respects_track():
    cur = [_entry("R8", 1, "甲", "乙", track="英文")]
    past = [_entry("R7", 1, "乙", "甲", track="中文")]
    assert rg.find_regressions(cur, past) == [], "轨道不同不该互相比"


def test_ledger_window():
    entries = flipflop_trail()
    h = rg.history(entries)
    assert len(rg.ledger(h, window=0)) == 3
    rows = rg.ledger(h, window=2)
    assert [r["batch"] for r in rows] == ["R7", "R8"], rows
    assert rows[0]["srt_id"] == 1 and rows[0]["track"] == "中文", rows[0]


# ══════════════════════════════════════════════════════════════════
# 2. regression_check.py 端到端
# ══════════════════════════════════════════════════════════════════

def test_regression_check_conflicts():
    wd = WorkDir(flipflop_trail())
    try:
        p = _run("regression_check.py", ["--work-dir", wd.dir, "--conflicts"])
        assert p.returncode == 0, p.stderr
        assert "连续改动 1 行" in p.stdout, p.stdout
        md = open(os.path.join(wd.dir, "reports", "regression.md"),
                  encoding="utf-8").read()
        assert "#1" in md, md[:600]
        assert "被 3 轮改过" in md, md
        assert "疑似反向" in md, md
        assert "没有「已收敛」标记" in md, "报告里要写清为什么没有「已收敛」"
    finally:
        wd.close()


def test_regression_check_settled():
    """--settled：改过、但最近 N 轮没再被动。

    #1 最后改于 R8，#500 最后改于 R9；最近 1 轮是 R9 → 只有 #1 沉住了。
    """
    rows = flipflop_trail() + [
        _entry("R9", 500, "甲", "乙", ts="2026-10-01T13:00:00"),
    ]
    wd = WorkDir(rows)
    try:
        p = _run("regression_check.py", ["--work-dir", wd.dir,
                                         "--settled", "--window", "1"])
        assert p.returncode == 0, p.stderr
        md = open(os.path.join(wd.dir, "reports", "regression.md"),
                  encoding="utf-8").read()
        assert "## 沉住的" in md and "| 1 | 中文 | 3 | R8 |" in md, md
        assert "| 500 |" not in md, "--settled 不该列最近一轮刚改的 #500"
        # --settled 是选段开关：不该顺带输出台账
        assert "## 台账" not in md, md
    finally:
        wd.close()


def test_regression_check_window_zero_lists_everything_settled():
    wd = WorkDir(flipflop_trail())
    try:
        p = _run("regression_check.py", ["--work-dir", wd.dir,
                                         "--settled", "--window", "0"])
        assert p.returncode == 0, p.stderr
        md = open(os.path.join(wd.dir, "reports", "regression.md"),
                  encoding="utf-8").read()
        assert "## 沉住的（最近 全部 轮没再被动）" in md, md
        assert "没有。", "window=0 时所有改动过的行都算沉住"
    finally:
        wd.close()


def test_regression_check_ledger_prints_rows():
    wd = WorkDir(flipflop_trail())
    try:
        p = _run("regression_check.py", ["--work-dir", wd.dir, "--ledger"])
        assert p.returncode == 0, p.stderr
        assert "#1" in p.stdout and "R8" in p.stdout, p.stdout
        md = open(os.path.join(wd.dir, "reports", "regression.md"),
                  encoding="utf-8").read()
        assert "## 台账" in md and "当时那条理由错在哪" in md, md
    finally:
        wd.close()


def test_regression_check_json_shape():
    wd = WorkDir(flipflop_trail())
    try:
        out = os.path.join(wd.dir, "r.json")
        p = _run("regression_check.py", ["--work-dir", wd.dir, "--all", "--json", out])
        assert p.returncode == 0, p.stderr
        data = json.load(open(out, encoding="utf-8"))
        assert data["window"] == 3, data
        assert len(data["conflicts"]) == 1, data["conflicts"]
        c = data["conflicts"][0]
        assert c["srt_id"] == 1, c
        assert "converged" not in c, "converged 已废，json 里不该再有这个键"
        assert isinstance(data["churn"], list) and data["churn"], data["churn"]
        assert data["churn"][-1]["again"] == 0, "最后一批没人再动"
        assert len(c["reversals"]) == 1, c["reversals"]
        assert len(c["trail"]) == 3, c["trail"]
    finally:
        wd.close()


def test_regression_check_section_selectors():
    """--ledger / --conflicts 是选段开关：点名哪段只出哪段。

    以前 --conflicts 是装饰性的——默认本来就输出全部，所以它什么也不做。
    这类「开关不起作用」比没有开关更糟：读代码的人以为能控制输出。
    """
    wd = WorkDir(flipflop_trail())
    try:
        md_path = os.path.join(wd.dir, "reports", "regression.md")

        p = _run("regression_check.py", ["--work-dir", wd.dir, "--ledger"])
        assert p.returncode == 0, p.stderr
        md = open(md_path, encoding="utf-8").read()
        assert "## 台账" in md, md
        assert "## 连续改动" not in md, f"--ledger 不该输出连续改动段：{md}"

        p = _run("regression_check.py", ["--work-dir", wd.dir, "--conflicts"])
        assert p.returncode == 0, p.stderr
        md = open(md_path, encoding="utf-8").read()
        assert "## 连续改动" in md, md
        assert "## 台账" not in md, f"--conflicts 不该输出台账段：{md}"

        p = _run("regression_check.py", ["--work-dir", wd.dir])
        assert p.returncode == 0, p.stderr
        md = open(md_path, encoding="utf-8").read()
        assert "## 台账" in md and "## 连续改动" in md, "默认两段都出"
    finally:
        wd.close()


def test_regression_check_empty_log():
    wd = WorkDir()
    try:
        p = _run("regression_check.py", ["--work-dir", wd.dir])
        assert p.returncode == 1, f"没 log 应返回 1，实际 {p.returncode}"
        assert "不存在或为空" in p.stdout, p.stdout
    finally:
        wd.close()


# ══════════════════════════════════════════════════════════════════
# 3. cross_check --regression-window
# ══════════════════════════════════════════════════════════════════

def _cross_check_regs(window):
    # R6 改错、R7 改回，R8 又改错 → 从 R8 的角度看，old_text 命中了 R6 之后
    # 又被 R7 写成的那一版
    rows = flipflop_trail()
    wd = WorkDir(rows)
    try:
        p = _run("cross_check.py", ["--work-dir", wd.dir, "--batch-id", "R8",
                                    "--ass", wd.ass, "--srt-path", wd.srt,
                                    "--regression-window", str(window)])
        assert p.returncode == 0, p.stderr + p.stdout
        md = open(os.path.join(wd.dir, "reports", "cross-check.md"),
                  encoding="utf-8").read()
        return p.stdout, md
    finally:
        wd.close()


def test_cross_check_reports_regression_by_default():
    stdout, md = _cross_check_regs(3)
    assert "疑似回归 1 条" in stdout, stdout
    assert "## 疑似回归" in md, md
    assert "exact" in md, md
    assert "只报不阻断" in md, md


def test_cross_check_regression_window_zero_disables():
    stdout, md = _cross_check_regs(0)
    assert "疑似回归 0 条" in stdout, stdout
    assert "## 疑似回归" not in md, f"--regression-window 0 应完全关闭，实际报告里还有：{md[-400:]}"


# ══════════════════════════════════════════════════════════════════
# 4. issue #7：规则表结构性约束
# ══════════════════════════════════════════════════════════════════

def test_shipped_rules_are_valid():
    import check_fluency as cf
    problems = cf.validate_rules()
    assert problems == [], f"仓库里的规则表应自检通过，实际：{problems}"


def test_empty_string_rule_is_rejected():
    import check_fluency as cf
    problems = cf.validate_rules({"测试词": ""})
    assert len(problems) == 1, problems
    assert "测试词" in problems[0], problems[0]
    assert "空串" in problems[0], problems[0]


def test_whitespace_rule_is_rejected():
    import check_fluency as cf
    problems = cf.validate_rules({"空白词": "   "})
    assert len(problems) == 1 and "空白词" in problems[0], problems


def test_bad_regex_is_rejected():
    import check_fluency as cf
    problems = cf.validate_rules({"坏正则": r"\b(so"})
    assert len(problems) == 1 and "编译失败" in problems[0], problems


def test_non_string_rule_is_rejected():
    import check_fluency as cf
    problems = cf.validate_rules({"列表词": ["so"]})
    assert len(problems) == 1 and "list" in problems[0], problems


def test_none_rule_is_accepted():
    import check_fluency as cf
    assert cf.validate_rules({"空动词": None}) == [], "None 是合法值（显式声明无来源）"


def test_check_line_raises_on_broken_rules():
    """运行中有人把规则改坏，check_line 必须当场炸，不能带着假 high 继续跑。"""
    import check_fluency as cf
    saved = dict(cf.FORMAL_WORDS)
    try:
        cf.FORMAL_WORDS["测试词"] = ""
        try:
            cf.check_line("But it is so.", "然而就是这样")
        except ValueError as e:
            assert "测试词" in str(e), str(e)
        else:
            raise AssertionError("规则表有空串时 check_line 应抛 ValueError")
        # pre_audit 走的是 check_slice，那条路径也要炸
        tmp = tempfile.mkdtemp(prefix="sp-slice-")
        try:
            p = os.path.join(tmp, "s.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("1 | 0:00:00.00 | But it is so. | 然而就是这样 |\n")
            try:
                cf.check_slice(__import__("pathlib").Path(p))
            except ValueError:
                pass
            else:
                raise AssertionError("check_slice 也应抛 ValueError")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        cf.FORMAL_WORDS.clear()
        cf.FORMAL_WORDS.update(saved)


def test_audit_rules_counts():
    import check_fluency as cf
    a = cf.audit_rules()
    assert a["total"] == len(cf.FORMAL_WORDS), a
    assert len(a["sourced"]) + len(a["bare"]) == a["total"], a
    assert sorted(a["sourced"] + a["bare"]) == sorted(cf.FORMAL_WORDS), a
    # 「进行」是空动词，英文不会有字面对应物 → 必须落在 bare 组
    assert "进行" in a["bare"], a["bare"]
    # 「所以」有 So 来源 → 必须落在 sourced 组
    assert "所以" in a["sourced"], a["sourced"]


def test_audit_rules_cli():
    p = _run("check_fluency.py", ["--audit-rules"])
    assert p.returncode == 0, p.stderr
    assert "规则自检通过" in p.stdout, p.stdout
    assert "无英文字面对应物" in p.stdout, p.stdout
    assert "进行" in p.stdout and "所以" in p.stdout, p.stdout
    assert "不要当 high 报" in p.stdout, p.stdout


def test_cli_requires_slice_without_audit():
    p = _run("check_fluency.py", [])
    assert p.returncode != 0, "既没切片也没 --audit-rules 应报错退出"
    assert "--audit-rules" in (p.stderr + p.stdout), p.stderr


def test_cli_broken_rules_exit_2():
    """子进程里注入空串 → main() 启动自检 sys.exit(2)，且指出是哪个词。"""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import check_fluency as cf\n"
        "cf.FORMAL_WORDS['手滑词'] = ''\n"
        "sys.argv = ['check_fluency.py', '--audit-rules']\n"
        "cf.main()\n" % SCRIPTS
    )
    p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", cwd=SKILL_ROOT)
    assert p.returncode == 2, f"应 exit 2，实际 {p.returncode}\n{p.stdout}\n{p.stderr}"
    assert "手滑词" in p.stderr, p.stderr
    assert "规则自检失败" in p.stderr, p.stderr


# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("跨轮次回归检测 + 规则表结构性约束 (issue #5 #6 #7)")
    print("=" * 70)

    print("\n-- 1. lib/regress 单元 --")
    test("G1 clean 去标签与空白", test_clean_strips_tags_and_ws)
    test("G2 history 按 (file,sid,track) 聚合并按时间序", test_history_keys_and_order)
    test("G3 history 排除 retime/retime_curve", test_history_excludes_retime)
    test("G4 conflicts 数轮次不数条目", test_conflicts_counts_rounds_not_entries)
    test("G5 reversals 抓到改回去", test_reversals_detects_flipback)
    test("G6 reversals 不误报渐进改动", test_reversals_silent_on_monotone_drift)
    test("G7 converged 是不可观测的（已删）", test_converged_is_impossible_on_consistent_log)
    test("G8 settled 排除最近轮次", test_settled_excludes_recent_rounds)
    test("G8b churn 统计被推翻的行", test_churn_counts_overturned_rows)
    test("G9 空改动不算一轮", test_history_excludes_noop_text_change)
    test("G9b 空改动不报疑似回归", test_find_regressions_skips_noop_current)
    test("G10 疑似回归 exact", test_find_regressions_exact)
    test("G11 疑似回归 near", test_find_regressions_near)
    test("G12 无关改动不报", test_find_regressions_ignores_unrelated)
    test("G13 同批不自比", test_find_regressions_ignores_same_batch)
    test("G14 retime 与空 old 跳过", test_find_regressions_skips_retime_and_blank_old)
    test("G15 轨道不同不比", test_find_regressions_respects_track)
    test("G16 ledger 窗口", test_ledger_window)

    print("\n-- 2. regression_check 端到端 --")
    test("G17 --conflicts 报告三处痕迹", test_regression_check_conflicts)
    test("G18 --settled 过滤", test_regression_check_settled)
    test("G18b window=0 全部沉住", test_regression_check_window_zero_lists_everything_settled)
    test("G19 --ledger 打印台账", test_regression_check_ledger_prints_rows)
    test("G20 --json 结构", test_regression_check_json_shape)
    test("G21 选段开关真的起作用", test_regression_check_section_selectors)
    test("G22 空 log 退出 1", test_regression_check_empty_log)

    print("\n-- 3. cross_check --regression-window --")
    test("G23 默认窗口报疑似回归", test_cross_check_reports_regression_by_default)
    test("G24 window=0 完全关闭", test_cross_check_regression_window_zero_disables)

    print("\n-- 4. 规则表结构性约束 (issue #7) --")
    test("G25 仓库规则表自检通过", test_shipped_rules_are_valid)
    test("G26 空串被拒", test_empty_string_rule_is_rejected)
    test("G27 空白串被拒", test_whitespace_rule_is_rejected)
    test("G28 坏正则被拒", test_bad_regex_is_rejected)
    test("G29 非字符串被拒", test_non_string_rule_is_rejected)
    test("G30 None 合法", test_none_rule_is_accepted)
    test("G31 规则坏了 check_line/check_slice 当场炸", test_check_line_raises_on_broken_rules)
    test("G32 audit_rules 分组计数", test_audit_rules_counts)
    test("G33 --audit-rules 输出", test_audit_rules_cli)
    test("G34 缺参数报错", test_cli_requires_slice_without_audit)
    test("G35 坏规则启动 exit 2", test_cli_broken_rules_exit_2)

    print()
    print(f"  通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
