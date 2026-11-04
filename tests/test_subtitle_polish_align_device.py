# -*- coding: utf-8 -*-
"""回归测试：对齐设备硬门（批次 9 的 CPU 静默退回事故）。

事故：`align_audit.py --engine qwen` 在主环境 `C:\\.venv`（`torch 2.15.0+cpu`）
里跑，模型加载成功、产物照常落盘，只是全程 CPU——不报错、无告警。
一集 120 s 音频要 180 s，数字与 GPU 口径不可比。

要求（本次落地）：
  - `cuda.is_available() == False` → 默认硬失败，退出码非 0，提示含
    「已拒绝在 CPU 上跑」，并说明 `--allow-cpu` 才能放行；
  - `--allow-cpu` 才继续；
  - 解释器没有 torch / 没有 qwen_asr → 同样失败，并给出修复命令；
  - 产物记录 `device` / `torch_version` / 解释器路径，报告打印设备行。

跑法:
  cd <skill-forge>
  python tests/test_subtitle_polish_align_device.py
"""
from __future__ import annotations

import os
import subprocess
import sys

SKILL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "subtitle-polish")
)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from lib import align_device as ad          # noqa: E402

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


CPU_INFO = {
    "python": r"C:\.venv\Scripts\python.exe",
    "python_version": "3.13.5",
    "torch_version": "2.15.0+cpu",
    "cuda_version": None,
    "cuda_available": False,
    "device_name": None,
    "has_qwen_asr": True,
}
CUDA_INFO = {
    "python": r"C:\whisperX\python_embed\python.exe",
    "python_version": "3.10.11",
    "torch_version": "2.6.0+cu124",
    "cuda_version": "12.4",
    "cuda_available": True,
    "device_name": "NVIDIA GeForce RTX 4060 Laptop GPU",
    "has_qwen_asr": True,
}


# ---------------------------------------------------------------- 硬门

def t_cpu_is_refused():
    """无 CUDA 且未给 --allow-cpu -> 抛 DeviceError，消息可执行。"""
    try:
        ad.require_cuda(info=dict(CPU_INFO), purpose="qwen 强制对齐",
                        require_qwen=True)
    except ad.DeviceError as e:
        msg = str(e)
        assert "未检测到 CUDA" in msg, msg
        assert "已拒绝在 CPU 上跑" in msg, msg
        assert "--allow-cpu" in msg, msg
        assert "2.15.0+cpu" in msg, msg
    else:
        raise AssertionError("CPU 环境没有被拒绝")


def t_allow_cpu_lets_it_through():
    """显式 --allow-cpu 才继续，且设备行里明确是 cpu。"""
    info = ad.require_cuda(info=dict(CPU_INFO), allow_cpu=True,
                           purpose="qwen 强制对齐", require_qwen=True)
    line = ad.fmt_line(info)
    assert line.startswith("对齐设备：cpu"), line
    assert "2.15.0+cpu" in line, line


def t_cuda_passes_and_formats():
    info = ad.require_cuda(info=dict(CUDA_INFO), require_qwen=True)
    line = ad.fmt_line(info)
    assert "对齐设备：cuda" in line, line
    assert "2.6.0+cu124" in line, line
    assert "RTX 4060" in line, line
    rec = ad.record(info)
    assert rec["device"] == "cuda", rec
    assert rec["torch_version"] == "2.6.0+cu124", rec
    assert rec["python"].endswith("python.exe"), rec


def t_missing_torch_fails_even_with_allow_cpu():
    """没有 torch 不是「想用 CPU」，--allow-cpu 也不能放行。"""
    info = dict(CPU_INFO)
    info["torch_version"] = None
    info["torch_error"] = "ModuleNotFoundError: No module named 'torch'"
    try:
        ad.require_cuda(info=info, allow_cpu=True, require_qwen=True)
    except ad.DeviceError as e:
        msg = str(e)
        assert "没有可用的 torch" in msg, msg
        assert "download.pytorch.org/whl/cu124" in msg, msg
    else:
        raise AssertionError("缺 torch 被放行了")


def t_missing_qwen_fails():
    """有 CUDA 但没 qwen_asr -> 失败并给出安装命令。"""
    info = dict(CUDA_INFO)
    info["has_qwen_asr"] = False
    try:
        ad.require_cuda(info=info, require_qwen=True)
    except ad.DeviceError as e:
        msg = str(e)
        assert "没有 qwen_asr" in msg, msg
        assert "pip install qwen_asr" in msg, msg
    else:
        raise AssertionError("缺 qwen_asr 被放行了")


# ---------------------------------------------------------------- 真实解释器

def t_probe_real_interpreter():
    """probe() 能在真实解释器里跑通，并带回版本字段。"""
    info = ad.probe(sys.executable)
    assert info["python"], info
    assert info["python_version"], info
    assert "cuda_available" in info, info


def t_qwen_cli_exits_nonzero_on_cpu():
    """端到端：qwen_align.py 在 CPU 解释器上必须非零退出并说清原因。

    这个解释器就是本机主环境（torch 2.15.0+cpu）；若测试机本身有 CUDA，
    这条不适用（跳过断言的 CLI 部分）。
    """
    info = ad.probe(sys.executable)
    if info.get("cuda_available"):
        print("         （本机解释器有 CUDA，跳过 CLI 硬失败断言）")
        return
    p = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "qwen_align.py"),
         "--sub", "missing.srt", "--wav", "missing.wav",
         "--model", "missing-model", "--out", "missing.json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode != 0, p.stdout
    out = (p.stdout or "") + (p.stderr or "")
    assert "已拒绝在 CPU 上跑" in out, out[-500:]


def main():
    print("对齐设备硬门（批次 9 CPU 静默退回事故）")
    test("CPU 默认硬失败", t_cpu_is_refused)
    test("--allow-cpu 才放行", t_allow_cpu_lets_it_through)
    test("CUDA 通过并格式化设备行", t_cuda_passes_and_formats)
    test("缺 torch：--allow-cpu 也不放行", t_missing_torch_fails_even_with_allow_cpu)
    test("缺 qwen_asr：硬失败", t_missing_qwen_fails)
    test("probe 真实解释器", t_probe_real_interpreter)
    test("qwen_align CLI 在 CPU 上非零退出", t_qwen_cli_exits_nonzero_on_cpu)
    print("\n通过 %d / 失败 %d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
