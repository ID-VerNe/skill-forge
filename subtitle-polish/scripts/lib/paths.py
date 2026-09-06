# -*- coding: utf-8 -*-
"""路径解析工具：work_dir 归一化，供所有脚本共用，避免循环导入。"""
from __future__ import annotations

import os


DEFAULT_WORK_DIR = ".subtitle-polish"


def resolve_work_dir(work_dir: str = "") -> str:
    """确定 .subtitle-polish 工作目录的绝对路径。

    解析顺序：
    1. work_dir 非空：直接用（相对路径转绝对）
    2. 从 cwd 往上找含 .subtitle-polish 的目录
    3. 找不到则回退到 cwd/.subtitle-polish
    """
    if work_dir:
        return os.path.abspath(work_dir)
    d = os.getcwd()
    for _ in range(10):
        if os.path.isdir(os.path.join(d, ".subtitle-polish")):
            return os.path.join(d, ".subtitle-polish")
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.abspath(DEFAULT_WORK_DIR)


def report_path(work_dir: str, filename: str) -> str:
    """reports/ 下的文件绝对路径，自动建目录。"""
    p = os.path.join(resolve_work_dir(work_dir), "reports", filename)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p
