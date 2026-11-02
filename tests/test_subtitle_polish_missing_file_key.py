# -*- coding: utf-8 -*-
"""回归测试:缺 `file` 字段不许崩成 `KeyError`,要给出能照着改的报错。

## 背景(第十七轮测试 agent 报告 bug #12)

现场表现很有欺骗性:

    第 1 次  python apply_fixes.py fixes.json --dry-run
             → 语义守卫中止（8 个 requires_confirm），退出码 1
    第 2 次  python apply_fixes.py fixes.json --dry-run --confirm
             → KeyError: 'file'

于是人被引向「`--confirm` 有问题」。实际上 `--confirm` 什么都没做错——它只是让流程
**走得更远**，越过了原本拦路的护栏，走到下游 `by_file.setdefault(fx["file"], ...)`
那一行才崩。

## 两个都算 bug

  1. **崩在 `setdefault` 上是坏报错**：栈里只写 `KeyError: 'file'`，看不出是第几条
     fix、也看不出该补什么。fixes.json 有 33 条时，人得一条条看。
  2. **顺序是坏的**：结构校验必须**全部前置**到护栏之前。护栏不读 `file`，
     让它先跑，就必然产出「先过护栏、再加 --confirm 才崩」这种误导性序列。

## 本文件锁住的四件事

  F1 缺 file 且无 --file → SystemExit，消息里带**出问题的 fix id** 和两种补救方式
  F2 缺 file 但给了 --file → 补齐后照常继续（单文件批次的正常形态）
  F3 `--file` 只补**缺失**的，不覆盖已写的（多文件批次混着单文件不能被打乱）
  F4 补齐发生在护栏之前 —— 用「缺 file + 有 requires_confirm」的组合验：
     不带 --confirm 时应报护栏（而非 KeyError），带 --confirm 时应能走到下游

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_missing_file_key.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

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
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        FAIL += 1
    else:
        print(f"  [PASS] {name}")
        PASS += 1


# ─────────────────────────────────────────────────────────────
# F1 缺 file 又没 --file：要报得能照着改
# ─────────────────────────────────────────────────────────────

def t_f1_missing_file_raises_clear_systemexit():
    """缺 `file` 且没有兜底 → SystemExit，且消息要点名是哪条、怎么补。

    只写「缺 file」不够:33 条 fixes 里人还得自己找。所以要求消息里出现该条
    的 id。同时两种补救方式都要写出来（补字段 / 给命令行 --file），
    否则人只能猜。
    """
    import apply_fixes as af
    fixes = [
        {"id": "e02#10", "srt_id": 10, "track": "中文", "current": "旧", "final_new": "新"},
        {"id": "e02#11", "srt_id": 11, "track": "中文", "current": "旧2", "final_new": "新2"},
    ]
    try:
        af._resolve_file_key(fixes, "")
    except SystemExit as e:
        msg = str(e)
        assert "e02#10" in msg, f"没点名是哪条 fix:{msg}"
        assert "--file" in msg, f"没给出命令行补救方式:{msg}"
        assert "file" in msg, f"没点出缺的是哪个字段:{msg}"
    else:
        raise AssertionError("缺 file 却没报错 —— 下游 setdefault 会崩成 KeyError")


# ─────────────────────────────────────────────────────────────
# F2 --file 兜底
# ─────────────────────────────────────────────────────────────

def t_f2_cli_file_fills_missing():
    """给了 --file 就补齐，且不抛异常（单文件批次的正常形态）。"""
    import apply_fixes as af
    fixes = [
        {"id": "e02#10", "srt_id": 10, "track": "中文"},
        {"id": "e02#11", "srt_id": 11, "track": "中文"},
    ]
    af._resolve_file_key(fixes, "C:/work/e02.ass")
    assert all(f["file"] == "C:/work/e02.ass" for f in fixes), (
        f"没补齐:{[f.get('file') for f in fixes]}")


def t_f3_cli_file_does_not_override_existing():
    """`--file` 只补缺失的，不许覆盖已写的。

    多文件批次里有些条目自带 file、有些漏写时，若 --file 覆盖全部，
    会把指向 e03 的条目一起改指到 e02 —— 改错文件比崩掉严重得多。
    """
    import apply_fixes as af
    fixes = [
        {"id": "e02#10", "file": "C:/work/e02.ass"},
        {"id": "e03#20", "file": "C:/work/e03.ass"},
        {"id": "e03#21"},                                  # 只有这一条该被补
    ]
    af._resolve_file_key(fixes, "C:/work/e02.ass")
    assert fixes[0]["file"] == "C:/work/e02.ass", "自带 file 被改了"
    assert fixes[1]["file"] == "C:/work/e03.ass", (
        f"e03#20 被 --file 覆盖成 {fixes[1]['file']!r} —— 会改错文件")
    assert fixes[2]["file"] == "C:/work/e02.ass", "缺失的那条没补上"


def t_f3b_empty_string_counts_as_missing():
    """`file: ""` 也算缺 —— 空串会让 by_file 分组出一个叫 "" 的假文件组。"""
    import apply_fixes as af
    fixes = [{"id": "x#1", "file": "   "}]
    af._resolve_file_key(fixes, "C:/work/e02.ass")
    assert fixes[0]["file"] == "C:/work/e02.ass", (
        f"空白 file 没被当缺失处理:{fixes[0]['file']!r}")


# ─────────────────────────────────────────────────────────────
# F4 顺序：补齐必须在护栏之前
# ─────────────────────────────────────────────────────────────

ASS_BODY = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: 中文,Arial,16,&H00FFFFFF,&H000000FF,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,中文,,0,0,0,,我不用去
"""

SRT_BODY = """1
00:00:01,000 --> 00:00:03,000
我不用去

"""


def _setup_case(tmp):
    ass = os.path.join(tmp, "e02.ass")
    srt = os.path.join(tmp, "e02.srt")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(ASS_BODY)
    with open(srt, "w", encoding="utf-8") as f:
        f.write(SRT_BODY)
    import json
    # 「不用」->「用」会命中否定词护栏，因此这条 requires_confirm。
    # 故意**不写 file**：这是 bug #12 的现场。
    fixes = [{
        "id": "e02#1", "srt_id": 1, "track": "中文",
        "current": "我不用去", "final_new": "我用去",
        "srt_path": srt,
    }]
    fp = os.path.join(tmp, "fixes.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(fixes, f, ensure_ascii=False)
    return ass, srt, fp


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "apply_fixes.py")] + args,
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def t_f4_confirm_path_no_keyerror(tmp):
    """缺 file + 有 requires_confirm：带 --confirm 时不许崩 KeyError。

    这条是 bug #12 的正面复现。修复前：不带 --confirm 报护栏，带了就 KeyError。
    修复后：带了 --confirm 应当正常跑完 dry-run（或者因为别的原因明确失败，
    但**不能**是 KeyError: 'file'）。
    """
    ass, srt, fp = _setup_case(tmp)
    wd = os.path.join(tmp, ".subtitle-polish")
    os.makedirs(wd, exist_ok=True)

    # ① 不带 --confirm、也不给 --file：
    #    修复后应先报「缺 file」（结构问题比语义确认更基础），而不是报护栏。
    #    修 bug 前这里会先报护栏 —— 于是人加了 --confirm，下一步才崩，被误导。
    r1 = _run([fp, "--dry-run", "--work-dir", wd], tmp)
    assert r1.returncode != 0, "缺 file 却返回成功"
    assert "缺 `file`" in (r1.stderr or ""), (
        f"没有先报缺 file:{r1.stderr[:300]}")
    assert "KeyError" not in (r1.stderr or ""), "结构校验阶段就撞 KeyError"

    # ② 带 --confirm + --file：必须过 KeyError 这一关
    r2 = _run([fp, "--dry-run", "--confirm", "--file", ass,
               "--work-dir", wd], tmp)
    assert "KeyError" not in (r2.stderr or ""), (
        f"带 --confirm 崩了 KeyError: 'file' —— 没过 file 补齐关\n{r2.stderr[:500]}")
    assert "KeyError" not in (r2.stdout or ""), (
        f"stdout 里有 KeyError\n{r2.stdout[:500]}")


def t_f4b_without_file_flag_errors_before_guard(tmp):
    """缺 file 且没给 --file：应报「缺 file」，而不是先报护栏。

    这是顺序的另一半:结构问题比语义确认更基础，必须先说。否则人按提示加了
    --confirm，还是会崩。
    """
    ass, srt, fp = _setup_case(tmp)
    wd = os.path.join(tmp, ".subtitle-polish")
    os.makedirs(wd, exist_ok=True)
    r = _run([fp, "--dry-run", "--confirm", "--work-dir", wd], tmp)
    assert "KeyError" not in (r.stdout or r.stderr or ""), (
        f"崩成 KeyError 了，没走明确报错分支\n{(r.stderr or '')[:500]}")
    assert r.returncode != 0, "缺 file 却返回成功"


# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("== 缺 file 字段 ==")
    tmp_ = tempfile.mkdtemp(prefix="no-file-key-")

    test("F1  缺 file 报错要点名条目与补法", t_f1_missing_file_raises_clear_systemexit)
    test("F2  --file 补齐缺失", t_f2_cli_file_fills_missing)
    test("F3  --file 不覆盖已写的", t_f3_cli_file_does_not_override_existing)
    test("F3b 空白 file 算缺失", t_f3b_empty_string_counts_as_missing)
    test("F4  --confirm 不再崩 KeyError",
         lambda: t_f4_confirm_path_no_keyerror(tmp_))
    test("F4b 缺 file 先于护栏报错",
         lambda: t_f4b_without_file_flag_errors_before_guard(tmp_))

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
