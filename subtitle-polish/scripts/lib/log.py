# -*- coding: utf-8 -*-
"""操作日志：log.jsonl 读写 + rollback 反向应用。

log.jsonl 一行一条 JSON，记录每次修改。不进 git。
rollback 三种粒度：batch_id / srt_id / before-timestamp。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import List, Optional


def log_path(work_dir: str) -> str:
    return os.path.join(work_dir, "log.jsonl")


def append_log(
    work_dir: str,
    batch_id: str,
    action: str,
    file: str,
    srt_id: int,
    track: str,
    old_text: str,
    new_text: str,
    category: str = "",
    reason: str = "",
) -> None:
    """追加一条操作记录。file 归一化为绝对路径存储，便于跨 cwd 比较。"""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "batch_id": batch_id,
        "action": action,
        "file": _norm_file(file),
        "srt_id": srt_id,
        "track": track,
        "old_text": old_text,
        "new_text": new_text,
        "category": category,
        "reason": reason,
    }
    path = log_path(work_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(work_dir: str) -> List[dict]:
    """读全部日志，按时间顺序。"""
    path = log_path(work_dir)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _norm_file(p: str) -> str:
    """路径归一化：绝对路径 + normpath，用于 log 比较时容忍相对/绝对/大小写差异。"""
    if not p:
        return ""
    try:
        return os.path.normpath(os.path.abspath(p))
    except Exception:
        return p


def filter_log(
    entries: List[dict],
    *,
    batch_id: Optional[str] = None,
    srt_id: Optional[int] = None,
    file: Optional[str] = None,
    before_ts: Optional[str] = None,
) -> List[dict]:
    """筛选符合条件的日志条目。

    file 比较用归一化绝对路径，容忍相对路径 / 斜杠方向差异。
    """
    target_file = _norm_file(file) if file else ""
    out = []
    for e in entries:
        if batch_id and e.get("batch_id") != batch_id:
            continue
        if srt_id is not None and e.get("srt_id") != srt_id:
            continue
        if target_file and _norm_file(e.get("file", "")) != target_file:
            continue
        if before_ts and e.get("ts", "") > before_ts:
            continue
        out.append(e)
    return out


def append_raw(work_dir: str, entry: dict) -> None:
    """追加一条自定义结构的记录（时间轴曲线这类文件级动作走这里）。

    为什么不复用 `append_log`：它的字段是「逐条 event」语义（srt_id + track +
    old_text/new_text），而曲线是**整批一次**的。硬塞会变成 N 条一模一样的
    记录，或者 srt_id=0 这种脏数据。
    """
    e = dict(entry)
    e.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    e["file"] = _norm_file(e.get("file", ""))
    path = log_path(work_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")


def append_curve_log(work_dir: str, batch_id: str, file: str, spec: dict,
                     max_shift: float, n_events: int, backup: str,
                     fit: Optional[dict] = None) -> None:
    """记一次 `align_patch` 的时间轴改动。

    `srt_id=0 / track="*"` 明确表示文件级动作；读取方（rollback / 报告 /
    verify）按 action 分流，不动老的 replace/delete/insert 路径。
    """
    append_raw(work_dir, {
        "batch_id": batch_id,
        "action": "retime_curve",
        "file": file,
        "srt_id": 0,
        "track": "*",
        "old_text": "",
        "new_text": "",
        "spec": spec,
        "max_shift": round(float(max_shift), 4),
        "n_events": int(n_events),
        "backup": _norm_file(backup),
        "fit": fit or {},
        "category": "时间轴",
        "reason": "align_patch",
    })


def last_curve_entry(work_dir: str, file: Optional[str] = None) -> Optional[dict]:
    """最近一条 retime_curve（可限定文件），供 --revert 用。"""
    target = _norm_file(file) if file else ""
    hit = None
    for e in read_log(work_dir):
        if e.get("action") != "retime_curve":
            continue
        if target and _norm_file(e.get("file", "")) != target:
            continue
        hit = e
    return hit


def backup_index_path(work_dir: str) -> str:
    return os.path.join(work_dir, "backups.jsonl")


def record_backup(work_dir: str, path: str, backup: str, batch_id: str,
                  action: str) -> None:
    """记一条备份索引。

    解决的是「8 集批量后 16~24 个 .bak 混在目录里、哪个对应哪次操作只能
    猜时间戳」——.bak 不进 git，误删就没了，至少要能枚举出来。
    """
    try:
        sha = hashlib.sha1(open(path, "rb").read()).hexdigest() if os.path.exists(path) else ""
    except OSError:
        sha = ""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "batch_id": batch_id,
        "action": action,
        "path": _norm_file(path),
        "backup": _norm_file(backup),
        "sha1": sha,
    }
    p = backup_index_path(work_dir)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def make_batch_id() -> str:
    """生成 batch_id（时间戳串）。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")
