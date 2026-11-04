# -*- coding: utf-8 -*-
"""whisperX 分窗对齐的纯函数测试（issue #46）。

整集单 segment 在 8 GB 卡上 OOM，改成分窗后有两件事必须锁住：
  W1 分窗不重不漏：每个字幕行只落进一个窗，窗按时间递增，最后一个行尾不被截断
  W2 显存自适应：按当前空闲显存估峰值挑窗长，不够就降档（不低于 30 s）
  W3 `--window 0` 仍等价于旧的整段单 segment（回退路径不能被改坏）

真实的 whisperx 调用不在单测里跑（需要独立 CUDA 环境），由实测覆盖。
"""
from __future__ import annotations

import os
import sys

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

import align_whisperx as W  # noqa: E402

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
        print("  [ok  ] " + name)


def rows(starts, dur=2.0):
    return [{"start": float(s), "end": float(s) + dur, "text": "line %d" % i}
            for i, s in enumerate(starts)]


def test_partition_no_duplicate():
    rs = rows([0, 1, 5, 10, 15, 21, 28])
    wins = W._plan_windows(rs, 0.0, 30.0, 10.0)
    got = [r for _lo, _hi, ch in wins for r in ch]
    assert len(got) == len(rs), "有行丢了或重复：%d/%d" % (len(got), len(rs))
    assert sorted(id(r) for r in got) == sorted(id(r) for r in rs), "窗外行被塞进来"
    windows = [(lo, hi) for lo, hi, _ in wins]
    assert windows == sorted(windows), "窗没有按时间递增"
    for lo, hi, _ in wins:
        assert hi > lo, "空窗"


def test_last_row_end_not_truncated():
    rs = rows([0, 55], dur=8.0)          # 第二行 55-63，跨过 60 s 网格
    wins = W._plan_windows(rs, 0.0, 63.0, 60.0)   # z 取最后一行的 end
    assert len(wins) == 1
    lo, hi, ch = wins[0]
    assert hi >= 63.0, "窗尾把最后一行截断到 %.1f" % hi
    assert len(ch) == 2


def test_boundary_row_goes_next_window():
    rs = rows([0, 9.9, 10.0])
    wins = W._plan_windows(rs, 0.0, 30.0, 10.0)
    assert len(wins[0][2]) == 2, "起点恰好 10.0 的行应归后一窗（左闭右开）"
    assert len(wins[1][2]) == 1


def test_auto_window_tiers():
    class FakeCuda:
        def __init__(self, total_gb, free_gb):
            self.total = total_gb
            self.free = free_gb

        def is_available(self):
            return True

        def get_device_properties(self, _i):
            class P:
                total_memory = 0
            P.total_memory = self.total * float(1 << 30)
            return P()

        def mem_get_info(self):
            return (self.free * float(1 << 30), self.total * float(1 << 30))

    class FakeTorch:
        def __init__(self, total_gb, free_gb):
            self.cuda = FakeCuda(total_gb, free_gb)

    # 实测口径：峰值 ≈ 1.8 GB 常驻 + 21 MiB/秒，且只占空闲显存一半。
    # 8 GB 卡上 120 s 窗峰值 4.29 GB，仍被桌面挤成 WDDM 溢出（5.5 s → 38 s），
    # 所以 8 GB / 空闲 7 GB 只给 60 s。
    assert W._auto_window("cuda", FakeTorch(4, 3.5)) == 30.0
    assert W._auto_window("cuda", FakeTorch(8, 7)) == 60.0
    assert W._auto_window("cuda", FakeTorch(8, 3.5)) == 30.0, "空闲减半要再降档"
    assert W._auto_window("cuda", FakeTorch(16, 14)) == 240.0
    assert W._auto_window("cuda", FakeTorch(24, 22)) == 300.0
    assert W._auto_window("cpu", FakeTorch(8, 7)) == 60.0


def test_window_zero_single_segment():
    wins = W._plan_windows(rows([0, 100, 200]), 0.0, 210.0, 210.0)
    assert len(wins) == 1, "窗长等于全长时应只有一个窗"


def test_find_model_cache_local():
    """issue #54：默认先找本地缓存；只有真权重到位才算命中。

    只看 `models--org--name` 目录存在是不够的：坏快照会留下目录但权重只有
    `*.incomplete`，离线加载会直接 `could not be found`。所以命中判据是
    「有 >= 1 MB 的完整权重文件」。
    """
    import shutil
    import tempfile

    root = tempfile.mkdtemp(prefix="sp-hf-")
    name = "jonatasgrosman/wav2vec2-large-xlsr-53-english"
    repo = os.path.join(root, "models--" + name.replace("/", "--"))
    orig = W._candidate_caches
    try:
        snap = os.path.join(repo, "snapshots", "rev1")
        os.makedirs(snap)
        # 模拟下载完成的权重（>1 MB）
        weight = os.path.join(snap, "model.safetensors")
        with open(weight, "wb") as f:
            f.write(b"\0" * (W._MIN_WEIGHT_BYTES + 1024))
        # 只测探测逻辑本身：把候选路径收窄到当前临时目录，避免本机其它
        # HF 缓存（可能正好有同名目录）干扰断言。
        W._candidate_caches = lambda: [root]
        assert W.find_model_cache(name) == os.path.abspath(root), "本地缓存没命中"

        # 坏快照：目录在，但只有 .incomplete，不能命中
        os.remove(weight)
        with open(weight + ".incomplete", "wb") as f:
            f.write(b"\0" * (W._MIN_WEIGHT_BYTES + 1024))
        assert W.find_model_cache(name) == "", "只有 .incomplete 的快照被误判成缓存"

        # 空壳目录不能命中
        empty = os.path.join(root, "empty")
        os.makedirs(empty)
        W._candidate_caches = lambda: [empty]
        assert W.find_model_cache(name) == "", "空目录被误判成缓存"
    finally:
        W._candidate_caches = orig
        shutil.rmtree(root, ignore_errors=True)


def main():
    print("== whisperX 分窗对齐（#46）==")
    test("W1a 分窗不重不漏", test_partition_no_duplicate)
    test("W1b 最后一行不被窗尾截断", test_last_row_end_not_truncated)
    test("W1c 边界行归后一窗", test_boundary_row_goes_next_window)
    test("W2 按空闲显存自适应窗长", test_auto_window_tiers)
    test("W3 窗长=全长等价单段", test_window_zero_single_segment)
    test("W4 本地模型缓存探测（#54）", test_find_model_cache_local)
    print("\n通过 %d / 失败 %d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
