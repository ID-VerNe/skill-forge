# -*- coding: utf-8 -*-
"""对齐设备硬门：没有 CUDA 就**拒绝**在 CPU 上跑强制对齐。

## 为什么需要它

2026-11-04 批次 9 的真实事故：`align_audit.py --engine qwen` 跑在主环境
`C:\\.venv`（`torch 2.15.0+cpu`），模型加载成功、结果照常落盘，只是全程在
CPU 上算——**没有任何报错**。一集 120 s 音频要 180 s，4 集要 12 分钟，而且
数字与 GPU 口径不可比。事后只能靠 `nvidia-smi` / 进程工作集才发现。

所以这里把「设备」变成**入口处的硬门**，而不是产物的一个字段：

- `probe()` 在目标解释器里读 `torch.__version__` / `cuda.is_available()` /
  解释器路径 / 是否有 `qwen_asr`；
- `require_cuda()` 在 `cuda_available is False` 时抛出 `DeviceError`，
  默认**直接失败**；只有显式 `--allow-cpu` 才放行；
- 解释器本身都跑不起来（路径错、没有 torch）同样硬失败，并给出修复命令。

主环境 `C:\\.venv` 是 CPU-only，这是**已知事实**，不是偶发环境问题：
只要子进程走到它，就一定是 CPU。默认解释器解析（`find_qwen_python()`）
因此优先找带 CUDA 的那个环境，而不是 `sys.executable`。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

#: 在目标解释器里执行的最小探针。只读，不加载模型。
_PROBE = r"""
import json, sys
out = {"python": sys.executable, "python_version": sys.version.split()[0]}
try:
    import torch
    out["torch_version"] = torch.__version__
    out["cuda_version"] = torch.version.cuda
    out["cuda_available"] = bool(torch.cuda.is_available())
    out["device_name"] = (torch.cuda.get_device_name(0)
                          if out["cuda_available"] else None)
except Exception as e:
    out["torch_version"] = None
    out["cuda_version"] = None
    out["cuda_available"] = False
    out["torch_error"] = "%s: %s" % (type(e).__name__, e)
try:
    import importlib.util as u
    out["has_qwen_asr"] = bool(u.find_spec("qwen_asr"))
except Exception:
    out["has_qwen_asr"] = False
print(json.dumps(out, ensure_ascii=False))
"""


class DeviceError(RuntimeError):
    """设备不满足硬门要求（无 CUDA、torch 缺失、解释器不可用）。"""


def probe(python_exe: str | None = None, timeout: float = 120.0) -> dict:
    """在 `python_exe`（默认当前解释器）里探测 torch / CUDA / qwen_asr。"""
    exe = python_exe or sys.executable
    if not os.path.isfile(exe):
        raise DeviceError("对齐解释器不存在：%s" % exe)
    env = os.environ.copy()
    env.setdefault("PYTHONWARNINGS", "ignore")
    try:
        p = subprocess.run([exe, "-X", "utf8", "-c", _PROBE],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise DeviceError("探测解释器超时（%.0fs）：%s" % (timeout, exe))
    if p.returncode != 0 or not p.stdout.strip():
        raise DeviceError("解释器不可用：%s（退出码 %d）\n%s"
                          % (exe, p.returncode, (p.stderr or "")[-500:]))
    try:
        info = json.loads(p.stdout.strip().splitlines()[-1])
    except ValueError:
        raise DeviceError("探测输出不是 JSON：%s\n%s" % (exe, p.stdout[-300:]))
    info.setdefault("python", exe)
    return info


def require_cuda(python_exe: str | None = None, *, allow_cpu: bool = False,
                 purpose: str = "强制对齐", require_qwen: bool = False,
                 info: dict | None = None) -> dict:
    """探测并强制要求 CUDA。返回设备信息；不满足时抛 `DeviceError`。

    `info` 只供测试注入；生产调用一律走 `probe()`。

    `allow_cpu=True` 只放行「没有 CUDA」这一种情况；解释器不存在 / 没有
    torch / 缺 qwen_asr 仍然失败——那是装错了，不是「想用 CPU」。
    """
    if info is None:
        info = probe(python_exe)
    if info.get("torch_version") is None:
        raise DeviceError(
            "解释器 %s 里没有可用的 torch（%s）。\n"
            "修复：& %s -m pip install torch --index-url "
            "https://download.pytorch.org/whl/cu124"
            % (info.get("python"), info.get("torch_error", "import torch 失败"),
               info.get("python")))
    if require_qwen and not info.get("has_qwen_asr"):
        raise DeviceError(
            "解释器 %s 没有 qwen_asr（torch %s）。\n"
            "修复：& %s -m pip install qwen_asr==0.0.6"
            % (info.get("python"), info.get("torch_version"),
               info.get("python")))
    if not info.get("cuda_available") and not allow_cpu:
        raise DeviceError(
            "未检测到 CUDA，已拒绝在 CPU 上跑%s；解释器 %s（torch %s）。\n"
            "如确需 CPU 请显式 --allow-cpu；否则改用带 CUDA 的解释器，"
            "例如 whisperX 的 python_embed（torch 2.6.0+cu124）。"
            % (purpose, info.get("python"), info.get("torch_version")))
    return info


def fmt_line(info: dict) -> str:
    """报告里的一行设备信息，一眼能看出是不是 GPU。"""
    dev = "cuda" if info.get("cuda_available") else "cpu"
    ver = info.get("torch_version") or "无 torch"
    extra = ("（%s）" % info["device_name"]) if info.get("device_name") else ""
    return "对齐设备：%s%s（torch %s，解释器 %s）" % (
        dev, extra, ver, info.get("python"))


def find_qwen_python(cli: str | None = None) -> str:
    """qwen 解释器的默认解析顺序；返回空串表示退回当前解释器。

    1. `--qwen-python`
    2. 环境变量 `QWEN_PYTHON`
    3. 环境变量 `WHISPERX_PYTHON`
    4. `WHISPERX_HOME\\python_embed\\python.exe`
    5. 用户目录下的约定位置（本机视频库的实际布局）

    不做「先跑当前解释器再看看」——主环境是 CPU-only，那样必然静默退回 CPU。
    """
    for cand in (cli, os.environ.get("QWEN_PYTHON"),
                 os.environ.get("WHISPERX_PYTHON")):
        if cand and os.path.isfile(cand):
            return cand
    home = os.environ.get("WHISPERX_HOME")
    if home:
        p = os.path.join(home, "python_embed", "python.exe")
        if os.path.isfile(p):
            return p
    p = os.path.join(os.path.expanduser("~"), "Downloads", "Documents",
                     "whisperX", "python_embed", "python.exe")
    if os.path.isfile(p):
        return p
    return ""


def record(info: dict) -> dict:
    """写进产物 JSON 的稳定字段（不含 torch_error 这类诊断噪声）。"""
    return {
        "device": "cuda" if info.get("cuda_available") else "cpu",
        "device_name": info.get("device_name"),
        "torch_version": info.get("torch_version"),
        "cuda_version": info.get("cuda_version"),
        "python": info.get("python"),
        "python_version": info.get("python_version"),
    }
