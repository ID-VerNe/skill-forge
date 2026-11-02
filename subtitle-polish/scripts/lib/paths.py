# -*- coding: utf-8 -*-
"""路径解析工具：work_dir 归一化，供所有脚本共用，避免循环导入。"""
from __future__ import annotations

import os


DEFAULT_WORK_DIR = ".subtitle-polish"


class WorkDirError(SystemExit):
    """work_dir 不合法。继承 SystemExit 是为了让 CLI 直接退出、不抛 traceback。"""


def resolve_work_dir(work_dir: str = "") -> str:
    """确定 .subtitle-polish 工作目录的绝对路径。

    解析顺序：
    1. work_dir 非空：必须等于默认值 `.subtitle-polish`（只允许改基准目录，
       不允许换名字）。传 `.`、绝对路径、别的名字一律报错退出。
    2. 从 cwd 往上找含 .subtitle-polish 的目录
    3. 找不到则回退到 cwd/.subtitle-polish

    **为什么收敛**（issue #24 的 M1）：以前传什么都接受，导致同一次审校里
    出现 `<项目>/.subtitle-polish/log.jsonl` 与 `<项目>/log.jsonl` 两本台账
    并存——报告读 A、脚本写 B，74 条改动在报告里只剩 2 条。
    work_dir 是**唯一约定**，不是自由参数。
    """
    if work_dir:
        norm = os.path.normpath(work_dir)
        if os.path.isabs(norm):
            # 绝对路径只允许指向一个名为 .subtitle-polish 的目录
            if os.path.basename(norm) != DEFAULT_WORK_DIR:
                raise WorkDirError(
                    f"[!] --work-dir 只接受 `{DEFAULT_WORK_DIR}`（或省略），"
                    f"收到绝对路径：{work_dir}\n"
                    f"    约定是「工作目录名固定，基准目录由 cwd 决定」。"
                    f"请在项目根目录下运行，或 cd 到目标基准目录。")
            return norm
        if norm != DEFAULT_WORK_DIR:
            raise WorkDirError(
                f"[!] --work-dir 只接受 `{DEFAULT_WORK_DIR}`（或省略），收到：{work_dir}\n"
                f"    以前接受任意路径，导致同一份工作里两本 log.jsonl 并存、"
                f"报告与脚本读写不同的台账。\n"
                f"    若已有孤儿台账，先运行：\n"
                f"      python <skill>/scripts/round_orchestrator.py --adopt\n"
                f"    把它并回 {DEFAULT_WORK_DIR}/log.jsonl。")

    d = os.getcwd()
    for _ in range(10):
        if os.path.isdir(os.path.join(d, DEFAULT_WORK_DIR)):
            return os.path.join(d, DEFAULT_WORK_DIR)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.abspath(DEFAULT_WORK_DIR)


def orphan_logs(work_dir: str = "") -> list:
    """找出与规范台账并存的孤儿 log.jsonl（M1 的残留）。

    规范位置：`<基准>/.subtitle-polish/log.jsonl`。
    孤儿：`<基准>/log.jsonl`（历史 bug 的产物，脚本从 cwd 写出来的）。
    只探测最近 3 层向上，避免在大目录树上乱扫。
    """
    wd = os.path.abspath(resolve_work_dir(work_dir))
    canon = os.path.normcase(os.path.join(wd, "log.jsonl"))
    out = []
    d = os.path.dirname(wd)          # 基准目录
    for _ in range(3):
        p = os.path.join(d, "log.jsonl")
        if os.path.exists(p) and os.path.normcase(os.path.abspath(p)) != canon:
            out.append(os.path.abspath(p))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return out


def assert_no_orphan_log(work_dir: str = "") -> None:
    """两本台账并存时 abort。宁可停下，也不要在两本账上继续记账。"""
    orp = orphan_logs(work_dir)
    if not orp:
        return
    wd = resolve_work_dir(work_dir)
    raise WorkDirError(
        "[!] 检测到孤儿 log.jsonl，拒绝继续（否则改动会记到另一本账上）：\n"
        + "\n".join(f"      {p}" for p in orp)
        + f"\n    规范台账应为：{os.path.join(wd, 'log.jsonl')}\n"
        + "    先合并：python <skill>/scripts/round_orchestrator.py --adopt")


def report_path(work_dir: str, filename: str) -> str:
    """reports/ 下的文件绝对路径，自动建目录。"""
    p = os.path.join(resolve_work_dir(work_dir), "reports", filename)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def assert_report_location(path: str, work_dir: str = "") -> str:
    """报告落点必须是 `<wd>/reports/` 下的文件（D4 / M8）。

    **为什么这条要写成硬校验**：M8 的根源是两份报告并存且互相矛盾——
    `.subtitle-polish/reports/校对报告.md`（人手写的）和脚本出的
    `audit-report.md` 摆在同一层，谁新谁旧、谁算数，读的人看不出来。
    报告是**唯一口径的产物**，不是随手一写的东西：多一个落点，就多一次
    「我看的是哪一份」的歧义。

    允许的唯一例外：`<wd>/runs/<stamp>/final-report.md`——那是**某一次跑测自己的
    结论快照**，天然属于那次 run，不该被搬到公共 reports/ 里（搬了之后
    「这份结论是哪次跑出来的」就丢了）。所以它不是"第二个落点"，
    而是"这次跑测记录的一部分"。

    返回规范化后的绝对路径；不合规则抛 `WorkDirError`（继承 SystemExit）。
    """
    wd = resolve_work_dir(work_dir)
    ap = os.path.normcase(os.path.abspath(path))
    rep = os.path.normcase(os.path.abspath(os.path.join(wd, "reports")))
    runs = os.path.normcase(os.path.abspath(os.path.join(wd, "runs")))

    if ap.startswith(rep + os.sep):
        return os.path.abspath(path)
    if ap.startswith(runs + os.sep) and os.path.basename(ap) == "final-report.md":
        return os.path.abspath(path)
    raise WorkDirError(
        f"[!] 报告落点不合规：{os.path.abspath(path)}\n"
        f"    报告只许落在两个位置：\n"
        f"      {os.path.join(wd, 'reports')}/<名字>.md   （通用报告）\n"
        f"      {os.path.join(wd, 'runs')}/<stamp>/final-report.md（单次跑测的结论）\n"
        f"    为什么不许散落：两份报告并存时，读的人分不清哪份算数——"
        f"这是 M8 的根因。\n"
        f"    要人工写说明，写进 reports/ 下的文件，不要另开一个落点。")
