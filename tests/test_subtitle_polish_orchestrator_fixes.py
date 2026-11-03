"""三个 open issue 的回归测试：

  #27  round_orchestrator 等脚本捕获子进程输出时按 UTF-8 解码，不再用 locale 编码
  #28  最终报告的时间轴结论读 sidecar 凭据，不再只看 init 时冻结的 media
  #30  无独立 SRT（whisper 转录）时，「本次未覆盖」提示 ASR 听写错误风险

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_orchestrator_fixes.py
"""
from __future__ import annotations

import hashlib
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

import round_orchestrator as ro
from lib import credential as cred

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

ASS_BODY = """Dialogue: 0,0:00:00.00,0:00:02.00,英文,,0,0,0,,This is Phil's bag.
Dialogue: 0,0:00:00.00,0:00:02.00,中文,,0,0,0,,这就是菲尔的地盘
Dialogue: 0,0:00:02.00,0:00:04.00,英文,,0,0,0,,Right, walk me through this.
Dialogue: 0,0:00:02.00,0:00:04.00,中文,,0,0,0,,好了 再讲一遍
"""


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


class Run:
    """临时工作区：<tmp>/.subtitle-polish + ASS/SRT/片源占位文件。"""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="sp-fixes-")
        self.wd = os.path.join(self.root, ".subtitle-polish")
        os.makedirs(self.wd, exist_ok=True)
        self.ass = os.path.join(self.root, "e04.ass")
        self.srt = os.path.join(self.root, "e04.srt")
        self.media = os.path.join(self.root, "e04.mkv")
        with open(self.ass, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER + ASS_BODY)
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:02,000\nThis is Phil's bag.\n\n"
                    "2\n00:00:02,000 --> 00:00:04,000\nRight, walk me through this.\n")
        with open(self.media, "wb") as f:
            f.write(b"not-a-real-video")

    def init(self, srt=None, media="", plan=None, stamp="T1",
             asr_transcribed=False):
        plan = plan or ro.build_plan()
        srt = self.srt if srt is None else srt
        return ro.init_run(self.wd, self.ass, srt, plan, media=media, stamp=stamp,
                           asr_transcribed=asr_transcribed)

    def write_cred(self, media=None, ok=True, verdict=None):
        stats = {"n_pairs": 10, "mad": 0.1, "drift": 0.0,
                 "window_span": 0.2 if ok else 3.0, "tol": 1.0, "ok": ok}
        if verdict:
            stats["verdict"] = verdict
        cred.save(self.ass, cred.build(self.ass, stats, "qwen",
                                       media=self.media if media is None else media))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════
# #27 子进程捕获编码
# ══════════════════════════════════════════════════════════════════

def t_gate_decodes_utf8_under_cp936_locale():
    """模拟中文 Windows：父进程按 cp936 取默认编码，子进程仍输出 UTF-8。

    旧代码 `text=True` 会把「结构正常」解成乱码；显式 encoding='utf-8' 后必须可读。
    """
    r = Run()
    try:
        code = (
            "import locale, sys\n"
            "locale.getencoding = lambda: 'cp936'\n"
            f"sys.path.insert(0, {SCRIPTS!r})\n"
            "import round_orchestrator as ro\n"
            f"ro._structure_gate({r.ass!r})\n"
        )
        env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="utf-8")
        p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=120)
        assert p.returncode == 0, p.stderr
        assert "结构正常" in p.stdout, \
            "子进程中文输出被按 GBK 解码成乱码：%r" % p.stdout
        assert "缁撴瀯" not in p.stdout, "乱码仍在：%r" % p.stdout
    finally:
        r.close()


# ══════════════════════════════════════════════════════════════════
# #28 报告时间轴判定
# ══════════════════════════════════════════════════════════════════

def _top(md):
    return md.split("## 本次未覆盖")[0]


def t_no_media_but_credential_is_pass():
    """init 没带 --media，事后写凭据 → 报告必须写 PASS，不能写 UNVERIFIED。"""
    r = Run()
    try:
        stamp = r.init(media="")
        r.write_cred(ok=True)
        md = ro.render_report(r.wd, stamp)
        assert "时间轴 PASS（凭据已验）" in _top(md), _top(md)
        assert "UNVERIFIED（无片源）" not in _top(md), _top(md)
    finally:
        r.close()


def t_no_media_but_credential_is_fail():
    """凭据判 FAIL 时报告同样按凭据写，而不是降级成 UNVERIFIED。"""
    r = Run()
    try:
        stamp = r.init(media="")
        r.write_cred(ok=False)
        md = ro.render_report(r.wd, stamp)
        assert "时间轴 FAIL（凭据判轴有问题）" in _top(md), _top(md)
        assert "UNVERIFIED" not in _top(md), _top(md)
    finally:
        r.close()


def t_no_media_no_credential_stays_unverified():
    r = Run()
    try:
        stamp = r.init(media="")
        md = ro.render_report(r.wd, stamp)
        assert "时间轴 UNVERIFIED（无片源）" in _top(md), _top(md)
        assert "时间轴 —— 无片源" in md, md
    finally:
        r.close()


def t_media_without_credential_is_not_pass():
    """只有片源、没有凭据 = 没验过轴；不能因为 media 非空就当作通过。"""
    r = Run()
    try:
        stamp = r.init(media=r.media)
        md = ro.render_report(r.wd, stamp)
        assert "时间轴 UNVERIFIED（有片源但未验轴）" in _top(md), _top(md)
        assert "时间轴 PASS" not in _top(md), _top(md)
    finally:
        r.close()


def t_stale_credential_says_reason():
    """凭据写完后 ASS 又被改 → 报告写 UNVERIFIED 并给出失效原因。"""
    r = Run()
    try:
        stamp = r.init(media="")
        r.write_cred(ok=True)
        with open(r.ass, "a", encoding="utf-8") as f:
            f.write("Dialogue: 0,9:59:00.00,9:59:02.00,中文,,0,0,0,,外挂改过\n")
        md = ro.render_report(r.wd, stamp)
        assert "时间轴 UNVERIFIED（凭据失效：" in _top(md), _top(md)
        assert "文件内容已变" in md, md
    finally:
        r.close()


def t_cross_run_table_uses_credential():
    """合并报告的表头/单元格也要按凭据写，而不是 media 有/无。"""
    r = Run()
    try:
        s1 = r.init(media="", stamp="A")
        r.write_cred(ok=True)
        # 第二个 run 用另一份 ASS，没有凭据，才能同时出现 PASS 与 UNVERIFIED
        ass2 = os.path.join(r.root, "e05.ass")
        shutil.copy(r.ass, ass2)
        s2 = ro.init_run(r.wd, ass2, r.srt, ro.build_plan(), stamp="B")
        md = ro.render_report(r.wd, "B", extra_stamps="A")
        table = md.split("## 本次合并了")[1]
        assert "| 时间轴 |" in table, table
        assert "PASS" in table, table          # A 读了凭据
        assert "UNVERIFIED" in table, table    # B 没有凭据
        assert "| 有 |" not in table, table     # 不再用 media 的有/无冒充结论
        assert s1 in md and s2 in md, md
    finally:
        r.close()


# ══════════════════════════════════════════════════════════════════
# #30 whisper 转录的「未覆盖」提示
# ══════════════════════════════════════════════════════════════════

def t_whisper_hint_when_no_srt():
    r = Run()
    try:
        stamp = r.init(srt="")
        md = ro.render_report(r.wd, stamp)
        gaps = md.split("## 本次未覆盖")[1]
        assert "whisper 转录" in gaps, gaps
        assert "ASR 听写错误" in gaps, gaps
        assert "--with-spelling" in gaps, gaps
    finally:
        r.close()


def t_no_whisper_hint_with_independent_srt():
    r = Run()
    try:
        stamp = r.init(srt=r.srt)
        md = ro.render_report(r.wd, stamp)
        assert "whisper 转录" not in md, md
    finally:
        r.close()


def t_whisper_hint_with_asr_flag():
    """派生 SRT 路径非空，但 init 标了 --asr-transcribed → 同样要提示。"""
    r = Run()
    try:
        stamp = r.init(srt=r.srt, asr_transcribed=True)
        md = ro.render_report(r.wd, stamp)
        gaps = md.split("## 本次未覆盖")[1]
        assert "whisper 转录" in gaps, gaps
    finally:
        r.close()


def t_no_whisper_hint_when_spelling_enabled():
    r = Run()
    try:
        stamp = r.init(srt="", plan=ro.build_plan(with_spelling=True))
        md = ro.render_report(r.wd, stamp)
        assert "whisper 转录" not in md, md
    finally:
        r.close()


# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("subtitle-polish 编排修复（#27 / #28 / #30）")
    test("#27 门禁在 cp936 locale 下仍正确解码 UTF-8",
         t_gate_decodes_utf8_under_cp936_locale)
    test("#28 无 media 但有 PASS 凭据", t_no_media_but_credential_is_pass)
    test("#28 无 media 但有 FAIL 凭据", t_no_media_but_credential_is_fail)
    test("#28 无 media 无凭据仍 UNVERIFIED", t_no_media_no_credential_stays_unverified)
    test("#28 有 media 无凭据不算通过", t_media_without_credential_is_not_pass)
    test("#28 凭据失效写明原因", t_stale_credential_says_reason)
    test("#28 合并报告按凭据写时间轴", t_cross_run_table_uses_credential)
    test("#30 whisper 素材给出未覆盖提示", t_whisper_hint_when_no_srt)
    test("#30 有独立 SRT 不提示 whisper", t_no_whisper_hint_with_independent_srt)
    test("#30 派生 SRT + --asr-transcribed 仍提示", t_whisper_hint_with_asr_flag)
    test("#30 开了拼写类不再提示 whisper", t_no_whisper_hint_when_spelling_enabled)
    print(f"\n通过 {PASS} / 失败 {FAIL}")
    sys.exit(0 if FAIL == 0 else 1)
