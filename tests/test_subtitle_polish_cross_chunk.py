# -*- coding: utf-8 -*-
"""回归测试：跨分块复核 —— 判定不能取决于一个任意的自由参数。

背景：`window_span` 对 qwen 的分块长度敏感，而分块长度是随手填的。
E01 在 60/75/90/105/120/135 上给出

    0.340  0.250  0.250  0.290  0.360  0.310

均值 0.300、标准差 0.046，而 qwen 的阈值正好是 0.300。旧逻辑按小数点后
第三位判 PASS / FAIL，于是同一条字幕：

    chunk=90  -> 0.250 PASS
    chunk=120 -> 0.360 FAIL

连跑两次同一配置结果完全相同——**这不是随机噪声，是随参数确定性变化的
系统偏差**，重跑永远发现不了它。

E05 更糟：0.260 / 0.340 / 0.440 三个值跨在阈值两侧。

本测试锁新规则：两档分块一致才算数，不一致报 AMBIGUOUS。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_cross_chunk.py
"""
from __future__ import annotations

import os
import sys

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import align_audit as aa          # noqa: E402
from lib import credential as cred  # noqa: E402
from lib import verdict as V        # noqa: E402

PASSED, FAILED = 0, 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        print("  FAIL %s  %s" % (name, detail))


def main():
    print("\n== A. 实测的两个翻转case ==")
    v, why = aa.combine_verdict([0.250, 0.360], 0.3)
    check("E01 0.250/0.360 -> AMBIGUOUS", v == "AMBIGUOUS", v)
    check("理由里两个值都写出来了", "0.250" in why and "0.360" in why, why)
    v, why = aa.combine_verdict([0.260, 0.440], 0.3)
    check("E05 0.260/0.440 -> AMBIGUOUS", v == "AMBIGUOUS", v)

    print("\n== B. 一致时照常判 ==")
    v, _ = aa.combine_verdict([0.180, 0.180], 0.3)
    check("两档都 0.180 -> PASS", v == "PASS", v)
    v, why = aa.combine_verdict([0.560, 0.560], 0.3)
    check("两档都 0.560 -> FAIL", v == "FAIL", v)
    check("FAIL 理由写了各分块都超", "都超过" in why, why)
    v, _ = aa.combine_verdict([0.195, 0.240], 0.3)
    check("0.195/0.240 都在线下 -> PASS", v == "PASS", v)
    v, _ = aa.combine_verdict([0.340, 0.410], 0.3)
    check("0.340/0.410 都在线上 -> FAIL", v == "FAIL", v)

    print("\n== C. 边界 ==")
    v, _ = aa.combine_verdict([0.299, 0.300], 0.3)
    check("0.299/0.300 都在线下 -> PASS", v == "PASS", v)
    v, _ = aa.combine_verdict([0.300, 0.300], 0.3)
    check("两档都恰好 0.300 -> PASS（<=）", v == "PASS", v)
    v, _ = aa.combine_verdict([0.1 + 0.2, 0.1 + 0.2], 0.3)
    check("浮点表示误差（0.1+0.2）不许顶成 FAIL", v == "PASS", v)
    v, _ = aa.combine_verdict([0.3001, 0.3001], 0.3)
    check("刚过线一点点 -> FAIL", v == "FAIL", v)
    v, _ = aa.combine_verdict([0.301, 0.299], 0.3)
    check("0.301/0.299 跨线 -> AMBIGUOUS", v == "AMBIGUOUS", v)

    print("\n== D. 退化输入 ==")
    v, _ = aa.combine_verdict([0.290], 0.3)
    check("单值 0.290 -> PASS（whisper 路径不变）", v == "PASS", v)
    v, _ = aa.combine_verdict([0.310], 0.3)
    check("单值 0.310 -> FAIL", v == "FAIL", v)
    v, why = aa.combine_verdict([], 0.3)
    check("空输入 -> UNVERIFIED 而不是 PASS", v == "UNVERIFIED", v)
    v, _ = aa.combine_verdict([0.2, None, 0.2], 0.3)
    check("None 被跳过", v == "PASS", v)

    print("\n== E. 分块配对 ==")
    c1, c2, why = aa.plan_chunks(7106)
    check("空闲 7106 -> 主 120 / 副 90", (c1, c2) == (120, 90), (c1, c2))
    c1, c2, _ = aa.plan_chunks(100)
    check("显存极少 -> 主 30 / 副 None（已在最小档）", (c1, c2) == (30, None), (c1, c2))
    check("副档一定比主档短", all(
        (lambda r: r[1] is None or r[1] < r[0])(aa.plan_chunks(f))
        for f in (0, 3000, 4000, 6000, 9000)))

    print("\n== F. 钉子：AMBIGUOUS 不许被压成 FAIL ==")
    # 曾经写成 `"PASS" if stats.get("ok") else "FAIL"`，四态被压成二态。
    data = cred.build(
        os.path.join(SKILL_ROOT, "scripts", "align_audit.py"),   # 存在的文件即可
        {"n_pairs": 700, "mad": 0.15, "drift": 0.02, "window_span": 0.25,
         "window_spans": [0.25, 0.36], "chunks": [120, 90],
         "tol": 0.3, "verdict": "AMBIGUOUS", "ok": False,
         "verdict_reason": "阈值落在两者之间"},
        "qwen3-forced-aligner")
    check("凭据里保留 AMBIGUOUS", data["axis"]["verdict"] == "AMBIGUOUS",
          data["axis"]["verdict"])
    check("跨分块数据进了凭据",
          data["axis"]["window_spans"] == [0.25, 0.36] and data["axis"]["chunks"] == [120, 90],
          data["axis"].get("window_spans"))
    check("AMBIGUOUS 映射到退出码 4",
          V.from_verdict(data["axis"]["verdict"]) == V.AMBIGUOUS)
    check("AMBIGUOUS 不许结案", not V.can_close(V.AMBIGUOUS))
    # 没有 verdict 字段时退回 ok 判定（旧凭据仍能读）
    d2 = cred.build(os.path.join(SKILL_ROOT, "scripts", "align_audit.py"),
                    {"ok": True, "window_span": 0.1, "tol": 0.3}, "whisper")
    check("缺 verdict 时按 ok 回退", d2["axis"]["verdict"] == "PASS",
          d2["axis"]["verdict"])

    print("\n%s  (%d passed, %d failed)" % ("FAILED" if FAILED else "ALL OK",
                                            PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
