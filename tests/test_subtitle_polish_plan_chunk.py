# -*- coding: utf-8 -*-
"""回归测试：qwen 分块按空闲显存自动规划 —— 显存溢出会静默产出错值。

背景：`tokens_qwen` 原先写死 `chunk=240`。在 8GB 卡上 240s 一次要 7.9GB
峰值，顶到 WDDM 预算后驱动把一部分搬去系统内存——不报错，只变慢（单块
1.3s -> 91.7s），**并且结果是错的**：

    E08 同一集 / 同一字幕 / 同一模型
      240s -> 极差 0.300 (PASS)
      60s  -> 0.520
      90s  -> 0.560
      120s -> 0.560
      180s -> 0.560

90s 及以上逐时段数字收敛到厘秒，240s 是溢出后的坏值。这个坏值曾让 E08
看起来是「whisper FAIL / qwen PASS 的双引擎分歧」，实际两边都是 0.560。

因此 `plan_chunk()` 是**判据正确性的一部分**，不是性能优化。本测试锁三件事：

  A. 阶梯按空闲显存下降，边界值精确
  B. 读不到显存时走保守方向（60s 而不是 120s）
  C. 永远不会规划出 >120s 的分块（钉子：240 不许回来）

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_plan_chunk.py
"""
from __future__ import annotations

import inspect
import os
import sys

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import align_audit as aa  # noqa: E402

PASSED, FAILED = 0, 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        print("  FAIL %s  %s" % (name, detail))


def need(c):
    return aa.QWEN_PEAK_MIB[c] + aa.QWEN_VRAM_HEADROOM_MIB


def main():
    print("\n== A. 阶梯与边界 ==")
    check("阶梯降序", list(aa.QWEN_CHUNK_LADDER) ==
          sorted(aa.QWEN_CHUNK_LADDER, reverse=True),
          aa.QWEN_CHUNK_LADDER)
    check("阶梯每档都有实测峰值",
          all(c in aa.QWEN_PEAK_MIB for c in aa.QWEN_CHUNK_LADDER),
          [c for c in aa.QWEN_CHUNK_LADDER if c not in aa.QWEN_PEAK_MIB])

    for c in aa.QWEN_CHUNK_LADDER[:-1]:
        got, why = aa.plan_chunk(need(c))
        check("空闲恰好够 %ds -> %d" % (c, c), got == c, "得到 %d（%s）" % (got, why))
        got, why = aa.plan_chunk(need(c) - 1)
        check("差 1 MiB 不够 %ds -> 降一档" % c, got != c,
              "得到 %d（%s）" % (got, why))

    got, why = aa.plan_chunk(10 ** 6)
    check("显存很多 -> 最大档（不越界）", got == aa.QWEN_CHUNK_LADDER[0],
          "得到 %d" % got)

    print("\n== B. 读不到显存时走保守方向 ==")
    got, why = aa.plan_chunk(0)
    check("free=0 -> 最小档（读不到就最保守）",
          got == aa.QWEN_CHUNK_LADDER[-1], "得到 %d" % got)
    check("理由里说明了读不到", "读不到" in why, why)
    got, why = aa.plan_chunk(100)
    check("显存极少 -> 最小档", got == aa.QWEN_CHUNK_LADDER[-1], "得到 %d" % got)
    check("理由里给了可操作建议", "关闭" in why or "关掉" in why, why)

    print("\n== C. 钉子：不许规划出 >120s ==")
    check("阶梯里没有 240", 240 not in aa.QWEN_CHUNK_LADDER)
    worst = max(aa.plan_chunk(f)[0] for f in
                (0, 100, 1000, 3000, 3900, 5500, 8000, 10 ** 6))
    check("任何输入下最大分块 <= 120", worst <= 120, "最大 %d" % worst)
    check("默认 chunk 为 None（走规划，不写死）",
          inspect.signature(aa.tokens_qwen).parameters["chunk"].default is None)

    print("\n== D. 单调性 ==")
    seq = [aa.plan_chunk(f)[0] for f in range(0, 9000, 250)]
    check("空闲显存增加时，分块不下降",
          all(b >= a for a, b in zip(seq, seq[1:])), seq)

    print("\n== E. 探针与 whisperX 项目同义 ==")
    check("free_vram_mib 返回 int >= 0",
          isinstance(aa.free_vram_mib(), int) and aa.free_vram_mib() >= 0)
    check("余量与 whisperX 的 VRAM_HEADROOM_MIB 同值",
          aa.QWEN_VRAM_HEADROOM_MIB == 600, aa.QWEN_VRAM_HEADROOM_MIB)

    print("\n%s  (%d passed, %d failed)" % ("FAILED" if FAILED else "ALL OK",
                                            PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
