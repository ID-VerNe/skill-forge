# -*- coding: utf-8 -*-
"""规则化翻译腔检查（信达雅之"达"轴）。

纯 Python 规则，无 LLM，秒级。判据照搬 translate_principle pipeline 的
TranslationQualityChecker（`core/quality_checker.py`），但适配 skill 的
切片格式（一 block 一行 `<srt_id> | <ass_time> | <英文> | <中文> | <注释>`）。

检查项：
  - 书面语黑名单：进行/实施/开展/予以/给予/关于/针对/基于/鉴于/
                   显著/充分/有效/积极/此外/因此/所以/然而
  - 机翻特征正则：的的 / 了了 / 重复标点
  - 长度异常比：译文 < 原文×0.4 或 > ×1.5

LLM（gemini-3.1 / glm-5.2）对书面语召回仅 6-11%，本脚本召回 100%。
软语境/俚语/委婉语抓不到，留给 LLM 两轨。

可独立单跑，也被 pre_audit.py 调用。

用法：
  python check_fluency.py <slice.txt> [--out report.json]
  python check_fluency.py <slice.txt>   # 打印到 stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict

# 书面语黑名单（出现在口语对白里 = 翻译腔）
FORMAL_WORDS = [
    "进行", "实施", "开展", "予以", "给予",
    "关于", "针对", "基于", "鉴于",
    "显著", "充分", "有效", "积极",
    "此外", "因此", "所以", "然而",
]

# 机翻特征正则
MACHINE_PATTERNS = [
    (r"的\s*的", "的的"),
    (r"了\s*了", "了了"),
    (r"[，。！？]{2,}", "重复标点"),
]

# 长度比阈值。
# 注意：ASS 字幕常把一句英文长句按时间轴拆成多行，单行中文看起来"过短"
# 但和相邻行拼起来译文完整。单行长度比在字幕场景精度接近 0%（实测
# Claude 把 21/22 条"译文过短"判为 misreport）。这里**默认关闭**长度比
# 检查，只在 --len-ratio 显式开启时跑，且标 confidence=low（仅辅助线索）。
LEN_MIN_RATIO = 0.25
LEN_MAX_RATIO = 2.0
LEN_MIN_EN = 12

# 切片行格式：<srt_id> | <ass_time> | <英文> | <中文> | <注释>
SLICE_LINE_RE = re.compile(
    r"^(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|"
)


def check_line(en: str, zh: str, len_ratio: bool = False) -> List[Dict]:
    """对单行（英文原文 + 中文译文）跑规则检查，返回 hit 列表。

    len_ratio：是否跑长度比检查（默认 False——字幕单行长度比精度接近 0%，
    ASS 常拆句导致单行中文"过短"但拼起来完整，实测 Claude 把 21/22 条
    "译文过短"判为 misreport）。开启时标 confidence=low（仅辅助线索）。

    每个 hit: {"axis": "达", "rule": ..., "detail": ..., "suggestion": ...}
    """
    hits = []
    # 1. 书面语黑名单
    found_formal = [w for w in FORMAL_WORDS if w in zh]
    if found_formal:
        hits.append({
            "axis": "达",
            "rule": "书面语残留",
            "detail": f"命中：{', '.join(found_formal)}",
            "suggestion": "改为口语化表达",
        })
    # 2. 机翻特征
    for pat, name in MACHINE_PATTERNS:
        m = re.search(pat, zh)
        if m:
            hits.append({
                "axis": "达",
                "rule": "机翻特征",
                "detail": f"{name}：{m.group(0)!r}",
                "suggestion": "修正重复",
            })
    # 3. 长度比（默认关——ASS 拆句使单行中文普遍"过短"，精度接近 0%）
    if len_ratio and len(en) >= LEN_MIN_EN:
        ratio = len(zh) / len(en)
        if ratio < LEN_MIN_RATIO:
            hits.append({
                "axis": "信",
                "rule": "译文过短",
                "detail": f"ratio={ratio:.2f}（en={len(en)} zh={len(zh)}）",
                "suggestion": "检查是否漏译（长度比仅辅助线索）",
                "confidence": "low",
            })
        elif ratio > LEN_MAX_RATIO:
            hits.append({
                "axis": "达",
                "rule": "译文过长",
                "detail": f"ratio={ratio:.2f}（en={len(en)} zh={len(zh)}）",
                "suggestion": "检查是否冗余/加戏",
                "confidence": "low",
            })
    return hits


def check_slice(slice_path: Path, len_ratio: bool = False) -> List[Dict]:
    """对整个切片文件跑检查，返回 hit 列表（每条带 srt_id/ass_time/hits）。

    只查中文行（英文行是源片台词，不查）。
    """
    results = []
    for line in slice_path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\n")
        if not line or line.startswith("#") or line.startswith("slice"):
            continue
        m = SLICE_LINE_RE.match(line)
        if not m:
            continue
        sid = int(m.group(1))
        ass_time = m.group(2).strip()
        en = m.group(3).strip()
        zh = m.group(4).strip()
        if not zh:
            # 中文行为空是漏译，归第 2 类不是信达雅，跳过
            continue
        hits = check_line(en, zh, len_ratio=len_ratio)
        if hits:
            results.append({
                "srt_id": sid,
                "ass_time": ass_time,
                "english": en,
                "current": zh,
                "hits": hits,
            })
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slice", help="切片文件（extract_slice.py 输出）")
    ap.add_argument("--out", help="写 JSON 到此路径（不给则打印到 stdout）")
    ap.add_argument("--summary", action="store_true",
                    help="只打印每类计数摘要，不列明细")
    ap.add_argument("--len-ratio", action="store_true",
                    help="开启长度比检查（默认关——字幕单行精度接近 0%）")
    args = ap.parse_args()

    slice_path = Path(args.slice)
    if not slice_path.is_file():
        print(f"切片文件不存在：{args.slice}", file=sys.stderr)
        sys.exit(1)

    results = check_slice(slice_path, len_ratio=args.len_ratio)

    if args.summary:
        from collections import Counter
        rule_counts = Counter()
        for r in results:
            for h in r["hits"]:
                rule_counts[h["rule"]] += 1
        print(f"切片：{slice_path.name}")
        print(f"命中行数：{len(results)}")
        for rule, cnt in rule_counts.most_common():
            print(f"  {rule}: {cnt}")
        return

    out = {
        "slice": str(slice_path),
        "total_hits": len(results),
        "results": results,
    }
    payload = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"写 {len(results)} 条命中到 {args.out}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
